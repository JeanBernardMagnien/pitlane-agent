import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

from services.agent_commands import execute_agent_command
from services.runtime_reporter import (
    _agent_token,
    _coerce_report_interval,
    _coerce_scan_interval,
    _enabled_hub_configs,
    build_runtime_report,
    runtime_report_signature,
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


def _build_runtime_report() -> dict:
    started = time.perf_counter()
    payload = build_runtime_report()
    payload['agent']['report_duration_ms'] = int((time.perf_counter() - started) * 1000)

    return payload


def _send_runtime_report(ws, send_lock: threading.Lock, payload: dict | None = None) -> str:
    payload = payload or _build_runtime_report()

    _send_json(ws, send_lock, {
        'type': 'runtime_report',
        'payload': payload,
    })

    return runtime_report_signature(payload)


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
        _send_runtime_report(ws, send_lock)
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


def _send_artifact_notifications(
    ws,
    send_lock: threading.Lock,
    hub_name: str,
    hub_base_url: str | None,
) -> None:
    try:
        from services.result_pipeline import get_result_pipeline

        candidates = get_result_pipeline().spool.notification_candidates(hub_name, hub_base_url)
        for artifact in candidates[:100]:
            _send_json(ws, send_lock, {
                'type': 'result_artifact_available',
                'payload': artifact,
            })
    except Exception as exc:
        logging.warning('[hub-ws] Notification résultats impossible pour "%s": %s', hub_name, exc)


def _handle_message(ws, send_lock: threading.Lock, hub_name: str, raw_message: str) -> None:
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
    elif message_type == 'result_artifact_available_ack':
        artifact_id = str(message.get('artifact_id') or '').strip()
        if artifact_id:
            from services.result_pipeline import get_result_pipeline
            get_result_pipeline().spool.mark_notified(artifact_id, hub_name)


def _find_hub_cfg(hub_name: str) -> dict | None:
    for hub_cfg in _enabled_hub_configs():
        if (hub_cfg.get('name') or 'hub') == hub_name:
            return hub_cfg
    return None


def _run_hub_client(hub_name: str) -> None:
    try:
        import websocket
    except ImportError:
        logging.warning('[hub-ws] Désactivé: dépendance websocket-client manquante')
        return

    send_lock = threading.Lock()
    backoff_seconds = 1
    last_ws_url = None
    was_waiting = False

    while not _stop_event.is_set():
        hub_cfg = _find_hub_cfg(hub_name)
        ws_url = _hub_ws_url(hub_cfg) if hub_cfg else None
        token = _agent_token(hub_cfg) if hub_cfg else None

        if hub_cfg is None or not ws_url or not token:
            if not was_waiting:
                if hub_cfg is None:
                    logging.info('[hub-ws] Hub "%s" désactivé/retiré de la config, en attente', hub_name)
                else:
                    logging.warning('[hub-ws] Hub "%s" ignoré: configuration WebSocket incomplète', hub_name)
                was_waiting = True
            _stop_event.wait(5)
            continue

        if was_waiting:
            logging.info('[hub-ws] Hub "%s" de nouveau disponible', hub_name)
            was_waiting = False

        interval = _coerce_report_interval(hub_cfg.get('runtime_report_interval'))
        scan_interval = _coerce_scan_interval(hub_cfg.get('runtime_scan_interval'))

        if ws_url != last_ws_url:
            logging.info('[hub-ws] Hub "%s": cible %s', hub_name, ws_url)
            last_ws_url = ws_url

        ws = None
        try:
            ws = websocket.create_connection(ws_url, timeout=10)
            ws.settimeout(min(scan_interval, 0.2))

            _send_json(ws, send_lock, {'type': 'hello', 'token': token})
            last_signature = _send_runtime_report(ws, send_lock)
            logging.info('[hub-ws] Connecté à "%s"', hub_name)

            backoff_seconds = 1
            next_scan_at = time.monotonic() + scan_interval
            next_report_at = time.monotonic() + interval
            next_config_check_at = time.monotonic() + 5
            next_artifact_notification_at = time.monotonic()

            while not _stop_event.is_set():
                now = time.monotonic()

                if now >= next_config_check_at:
                    next_config_check_at = now + 5
                    fresh_cfg = _find_hub_cfg(hub_name)
                    fresh_ws_url = _hub_ws_url(fresh_cfg) if fresh_cfg else None
                    fresh_token = _agent_token(fresh_cfg) if fresh_cfg else None
                    if fresh_cfg is None or fresh_ws_url != ws_url or fresh_token != token:
                        logging.info('[hub-ws] Config changée pour "%s", reconnexion', hub_name)
                        break

                if now >= next_scan_at or now >= next_report_at:
                    payload = _build_runtime_report()
                    signature = runtime_report_signature(payload)
                    heartbeat_due = now >= next_report_at

                    if heartbeat_due or signature != last_signature:
                        last_signature = _send_runtime_report(ws, send_lock, payload)
                        next_report_at = now + interval

                    next_scan_at = now + scan_interval

                if now >= next_artifact_notification_at:
                    _send_artifact_notifications(ws, send_lock, hub_name, hub_cfg.get('base_url'))
                    next_artifact_notification_at = now + 2

                try:
                    raw_message = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue

                if raw_message is None:
                    raise websocket.WebSocketConnectionClosedException()

                _handle_message(ws, send_lock, hub_name, raw_message)

        except Exception as exc:
            logging.warning('[hub-ws] Déconnecté de "%s" (%s): %s', hub_name, ws_url, exc)
            _stop_event.wait(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, 30)
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass



def _supervise_hub_client(hub_name: str) -> None:
    # _run_hub_client ne revient normalement que lorsque _stop_event est déclenché
    # (arrêt global) ; il gère lui-même la désactivation/réactivation du hub en interne.
    while not _stop_event.is_set():
        try:
            _run_hub_client(hub_name)
        except Exception as exc:
            logging.error('[hub-ws] Crash client "%s": %s', hub_name, exc.__class__.__name__)

        if not _stop_event.is_set():
            logging.info('[hub-ws] Redémarrage client "%s" dans 5s', hub_name)
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
        logging.info('[hub-ws] Désactivé: aucune configuration WebSocket')
        return

    _stop_event.clear()

    for hub_cfg in hub_configs:
        hub_name = hub_cfg.get('name') or 'hub'
        thread = threading.Thread(
            target=_supervise_hub_client,
            args=(hub_name,),
            daemon=True,
        )
        thread.start()
        _client_threads.append(thread)

    logging.info('[hub-ws] Activé vers %d hub(s)', len(hub_configs))
