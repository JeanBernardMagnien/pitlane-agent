import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urlunparse

from services.agent_commands import execute_agent_command
from services.agent_command_journal import (
    AgentCommandConflict,
    AgentCommandContractError,
    StaleAgentCommand,
    get_agent_command_journal,
)
from services.durable_command_executor import DurableCommandCoordinator
from services.runtime_reporter import (
    _agent_token,
    _coerce_report_interval,
    _coerce_scan_interval,
    _enabled_hub_configs,
    build_runtime_report,
    runtime_report_signature,
)
from services.websocket_inbox import drain_available_messages
from services.websocket_authentication import ReconnectBackoff, await_hello_acknowledgement


DEFAULT_WEBSOCKET_ENDPOINT = '/api/agent/ws'
MAX_INBOUND_MESSAGES_PER_CYCLE = 100


_client_threads: list[threading.Thread] = []
_stop_event = threading.Event()
_command_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='hub-ws-command')
_durable_coordinator = None
_durable_coordinator_lock = threading.Lock()


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


def _handle_legacy_command(ws, send_lock: threading.Lock, message: dict) -> None:
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


def _send_command_ack(
    ws,
    send_lock: threading.Lock,
    record: dict,
    response: dict | None = None,
) -> None:
    status = str(record.get('status') or '')
    occurred_at = (
        record.get('completed_at')
        if status in ('succeeded', 'failed')
        else record.get('executing_at')
        if status == 'executing'
        else record.get('received_at')
    )
    payload = {
        'type': 'command_ack',
        'schema_version': 1,
        'id': record.get('command_id'),
        'status': status,
        'occurred_at': occurred_at,
    }

    if status in ('succeeded', 'failed'):
        journal = get_agent_command_journal()
        payload['payload'] = response if response is not None else journal.response(record)
        if record.get('error_code'):
            payload['code'] = record['error_code']
        if record.get('error_message'):
            payload['error'] = record['error_message']

    _send_json(ws, send_lock, payload)


def _get_durable_coordinator() -> DurableCommandCoordinator:
    global _durable_coordinator

    if _durable_coordinator is not None:
        return _durable_coordinator

    with _durable_coordinator_lock:
        if _durable_coordinator is None:
            _durable_coordinator = DurableCommandCoordinator(
                get_agent_command_journal(),
                execute_agent_command,
            )

    return _durable_coordinator


def _handle_durable_command(
    ws,
    send_lock: threading.Lock,
    hub_name: str,
    message: dict,
) -> None:
    command_id = str(message.get('id') or '').strip()

    try:
        _get_durable_coordinator().receive(
            hub_name,
            message,
            lambda record, response: _send_command_ack(ws, send_lock, record, response),
            lambda: _send_runtime_report(ws, send_lock),
        )
    except StaleAgentCommand as exc:
        _send_json(ws, send_lock, {
            'type': 'command_ack',
            'schema_version': 1,
            'id': command_id or None,
            'status': 'failed',
            'code': 'stale_fence',
            'error': str(exc),
            'payload': {'code': 'stale_fence', 'error': str(exc)},
        })
        return
    except AgentCommandConflict as exc:
        _send_json(ws, send_lock, {
            'type': 'command_ack',
            'schema_version': 1,
            'id': command_id or None,
            'status': 'failed',
            'code': 'idempotency_conflict',
            'error': str(exc),
            'payload': {'code': 'idempotency_conflict', 'error': str(exc)},
        })
        return
    except AgentCommandContractError as exc:
        _send_json(ws, send_lock, {
            'type': 'command_ack',
            'schema_version': 1,
            'id': command_id or None,
            'status': 'failed',
            'code': 'invalid_command',
            'error': str(exc),
            'payload': {'code': 'invalid_command', 'error': str(exc)},
        })
        return


def _confirm_command_ack(hub_name: str, message: dict) -> None:
    command_id = str(message.get('id') or '').strip()
    status = str(message.get('status') or '').strip()
    if not command_id or not status:
        return

    try:
        _get_durable_coordinator().confirm(hub_name, command_id, status)
    except AgentCommandContractError:
        return


def _send_pending_command_acknowledgements(
    ws,
    send_lock: threading.Lock,
    hub_name: str,
) -> None:
    try:
        _get_durable_coordinator().replay_pending(
            hub_name,
            lambda record, response: _send_command_ack(ws, send_lock, record, response),
            lambda: _send_runtime_report(ws, send_lock),
            limit=100,
        )
    except Exception as exc:
        logging.warning(
            '[hub-ws] Resynchronisation commandes impossible pour "%s": %s',
            hub_name,
            exc.__class__.__name__,
        )


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
        if int(message.get('schema_version') or 1) >= 2:
            _handle_durable_command(ws, send_lock, hub_name, message)
        else:
            _handle_legacy_command(ws, send_lock, message)
    elif message_type == 'command_ack_confirmed':
        _confirm_command_ack(hub_name, message)
    elif message_type == 'ping':
        _send_json(ws, send_lock, {'type': 'pong'})
    elif message_type == 'result_artifact_available_ack':
        artifact_id = str(message.get('artifact_id') or '').strip()
        if artifact_id:
            from services.result_pipeline import get_result_pipeline
            get_result_pipeline().spool.mark_notified(artifact_id, hub_name)


def _receive_available_messages(
    ws,
    send_lock: threading.Lock,
    hub_name: str,
    limit: int = MAX_INBOUND_MESSAGES_PER_CYCLE,
) -> int:
    """Drain a bounded batch so runtime acknowledgements cannot starve commands."""
    import websocket

    return drain_available_messages(
        ws,
        lambda raw_message: _handle_message(ws, send_lock, hub_name, raw_message),
        websocket.WebSocketTimeoutException,
        websocket.WebSocketConnectionClosedException,
        limit,
    )


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
    reconnect_backoff = ReconnectBackoff()
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
            _send_json(ws, send_lock, {'type': 'hello', 'token': token})
            await_hello_acknowledgement(ws)
            ws.settimeout(min(scan_interval, 0.2))
            last_signature = _send_runtime_report(ws, send_lock)
            logging.info('[hub-ws] Connecté à "%s"', hub_name)

            # Une ouverture TCP/WebSocket suivie d'un refus d'authentification
            # n'est pas une reconnexion réussie et ne doit pas réinitialiser le
            # backoff. Seul hello_ack rend la connexion exploitable.
            reconnect_backoff.reset_after_authentication()
            next_scan_at = time.monotonic() + scan_interval
            next_report_at = time.monotonic() + interval
            next_config_check_at = time.monotonic() + 5
            next_artifact_notification_at = time.monotonic()
            next_command_ack_replay_at = time.monotonic()

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

                if now >= next_command_ack_replay_at:
                    _send_pending_command_acknowledgements(ws, send_lock, hub_name)
                    next_command_ack_replay_at = now + 2

                _receive_available_messages(ws, send_lock, hub_name)

        except Exception as exc:
            logging.warning('[hub-ws] Déconnecté de "%s" (%s): %s', hub_name, ws_url, exc)
            _stop_event.wait(reconnect_backoff.next_failure_delay())
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
