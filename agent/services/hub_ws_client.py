import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

from services.agent_commands import execute_agent_command
from services.runtime_reporter import (
    _agent_token,
    _coerce_report_interval,
    _enabled_hub_configs,
    build_runtime_report,
)


DEFAULT_WEBSOCKET_ENDPOINT = '/api/agent/ws'


_client_threads: list[threading.Thread] = []
_stop_event = threading.Event()
_command_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='hub-ws-command')


def _hub_ws_url(hub_cfg: dict) -> str | None:
    explicit_url = hub_cfg.get('websocket_url') or hub_cfg.get('ws_url')
    if explicit_url:
        return str(explicit_url).strip()

    endpoint = hub_cfg.get('websocket_endpoint') or hub_cfg.get('ws_endpoint') or DEFAULT_WEBSOCKET_ENDPOINT
    base_url = str(hub_cfg.get('base_url') or '').strip()
    if not base_url:
        return None

    endpoint = str(endpoint)
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint

    parsed = urlparse(base_url)
    scheme = {'http': 'ws', 'https': 'wss'}.get(parsed.scheme, parsed.scheme)

    return urlunparse((scheme, parsed.netloc, endpoint, '', '', ''))


def _send_json(ws, send_lock: threading.Lock, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    with send_lock:
        ws.send(raw)


def _send_runtime_report(ws, send_lock: threading.Lock) -> None:
    started = time.perf_counter()
    payload = build_runtime_report()
    payload['agent']['report_duration_ms'] = int((time.perf_counter() - started) * 1000)

    _send_json(ws, send_lock, {
        'type': 'runtime_report',
        'payload': payload,
    })


def _send_command_result(ws, send_lock: threading.Lock, command_id, future) -> None:
    try:
        payload, status_code = future.result()
        ok = 200 <= int(status_code) < 300
    except Exception as exc:
        payload = {'error': f'Erreur commande : {exc}'}
        ok = False

    try:
        _send_json(ws, send_lock, {
            'type': 'command_result',
            'id': command_id,
            'ok': ok,
            'payload': payload,
        })
    except Exception:
        pass


def _handle_command(ws, send_lock: threading.Lock, message: dict) -> None:
    command_id = message.get('id')
    command = message.get('command')
    payload = message.get('payload') or {}

    if not command_id:
        _send_json(ws, send_lock, {
            'type': 'command_result',
            'id': None,
            'ok': False,
            'payload': {'error': 'id requis'},
        })
        return

    if not isinstance(command, str) or not command.strip():
        _send_json(ws, send_lock, {
            'type': 'command_result',
            'id': command_id,
            'ok': False,
            'payload': {'error': 'command requis'},
        })
        return

    future = _command_executor.submit(execute_agent_command, command, payload)
    future.add_done_callback(lambda completed: _send_command_result(
        ws,
        send_lock,
        command_id,
        completed,
    ))


def _handle_message(ws, send_lock: threading.Lock, raw_message: str) -> None:
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError:
        return

    if not isinstance(message, dict):
        return

    message_type = message.get('type')

    if message_type == 'command':
        _handle_command(ws, send_lock, message)
    elif message_type == 'ping':
        _send_json(ws, send_lock, {'type': 'pong'})


def _run_hub_client(hub_cfg: dict) -> None:
    try:
        import websocket
    except ImportError:
        print('[hub-ws] Désactivé: dépendance websocket-client manquante')
        return

    hub_name = hub_cfg.get('name') or 'hub'
    ws_url = _hub_ws_url(hub_cfg)
    token = _agent_token(hub_cfg)
    interval = _coerce_report_interval(hub_cfg.get('runtime_report_interval'))
    send_lock = threading.Lock()
    backoff_seconds = 1

    if not ws_url or not token:
        print(f'[hub-ws] Hub "{hub_name}" ignoré: configuration WebSocket incomplète')
        return

    while not _stop_event.is_set():
        ws = None
        try:
            ws = websocket.create_connection(ws_url, timeout=10)
            ws.settimeout(1)

            _send_json(ws, send_lock, {'type': 'hello', 'token': token})
            _send_runtime_report(ws, send_lock)
            print(f'[hub-ws] Connecté à "{hub_name}"')

            backoff_seconds = 1
            next_report_at = time.monotonic() + interval

            while not _stop_event.is_set():
                now = time.monotonic()
                if now >= next_report_at:
                    _send_runtime_report(ws, send_lock)
                    next_report_at = now + interval

                try:
                    raw_message = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue

                if raw_message is None:
                    raise websocket.WebSocketConnectionClosedException()

                _handle_message(ws, send_lock, raw_message)

        except Exception as exc:
            print(f'[hub-ws] Déconnecté de "{hub_name}": {exc.__class__.__name__}')
            _stop_event.wait(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 30)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass



def _supervise_hub_client(hub_cfg: dict) -> None:
    hub_name = hub_cfg.get('name') or 'hub'

    while not _stop_event.is_set():
        try:
            _run_hub_client(hub_cfg)
        except Exception as exc:
            print(f'[hub-ws] Crash client "{hub_name}": {exc.__class__.__name__}')

        if not _stop_event.is_set():
            print(f'[hub-ws] Redémarrage client "{hub_name}" dans 5s')
            _stop_event.wait(5)


def start_hub_ws_clients() -> None:
    if _client_threads:
        return

    hub_configs = [
        hub_cfg for hub_cfg in _enabled_hub_configs()
        if (
            hub_cfg.get('websocket_enabled', True) is not False
            and _hub_ws_url(hub_cfg)
            and _agent_token(hub_cfg)
        )
    ]

    if not hub_configs:
        print('[hub-ws] Désactivé: aucune configuration WebSocket')
        return

    _stop_event.clear()

    for hub_cfg in hub_configs:
        thread = threading.Thread(
            target=_supervise_hub_client,
            args=(hub_cfg,),
            daemon=True,
        )
        thread.start()
        _client_threads.append(thread)

    print(f'[hub-ws] Activé vers {len(hub_configs)} hub(s)')
