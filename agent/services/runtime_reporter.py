import json
import logging
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import psutil

from core import config_store
from services.player_count_observer import observe_player_count, resolve_player_count
from services.process_supervisor import process_supervisor
from services.server_manager import terminal_process_payload


DEFAULT_REPORT_INTERVAL_SECONDS = 1
DEFAULT_SCAN_INTERVAL_SECONDS = 0.5
DEFAULT_HTTP_TIMEOUT_SECONDS = 0.5
DEFAULT_RUNTIME_REPORT_ENDPOINT = '/api/agent/runtime-report'
PROCESS_CPU_SAMPLE_INTERVAL_SECONDS = 0.9


_reporter_thread = None
_reporter_stop_event = threading.Event()
_process_cpu_cache: dict[int, dict] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _safe_float(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _coerce_report_interval(value) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = DEFAULT_REPORT_INTERVAL_SECONDS

    return max(1, interval)


def _coerce_scan_interval(value) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError):
        interval = DEFAULT_SCAN_INTERVAL_SECONDS

    return max(0.2, min(interval, 5.0))


def _coerce_http_timeout(value) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_HTTP_TIMEOUT_SECONDS

    return max(0.1, min(timeout, 5.0))


def _configured_hubs() -> list[dict]:
    hubs_cfg = config_store.CFG.get('hubs')

    if isinstance(hubs_cfg, list) and hubs_cfg:
        return hubs_cfg

    legacy_hub = config_store.CFG.get('hub')
    if isinstance(legacy_hub, dict) and legacy_hub.get('base_url'):
        return [{
            'name': legacy_hub.get('name') or 'production',
            'enabled': legacy_hub.get('enabled', True),
            'required': legacy_hub.get('required', True),
            'base_url': legacy_hub.get('base_url'),
            'runtime_report_endpoint': legacy_hub.get('runtime_report_endpoint') or legacy_hub.get('state_endpoint'),
            'runtime_report_interval': legacy_hub.get('runtime_report_interval') or legacy_hub.get('monitor_interval'),
            'runtime_scan_interval': legacy_hub.get('runtime_scan_interval') or legacy_hub.get('monitor_scan_interval'),
            'instance_http_timeout': legacy_hub.get('instance_http_timeout'),
            'agent_token': legacy_hub.get('agent_token') or legacy_hub.get('token'),
            'websocket_enabled': legacy_hub.get('websocket_enabled', legacy_hub.get('ws_enabled', True)),
            'websocket_url': legacy_hub.get('websocket_url') or legacy_hub.get('ws_url'),
            'websocket_endpoint': legacy_hub.get('websocket_endpoint') or legacy_hub.get('ws_endpoint'),
        }]

    return []


def _enabled_hub_configs() -> list[dict]:
    hubs_cfg = _configured_hubs()
    enabled_hubs = []

    for index, hub_cfg in enumerate(hubs_cfg):
        if not isinstance(hub_cfg, dict):
            continue

        if hub_cfg.get('enabled') is not True:
            continue

        enabled_hubs.append({
            'name': hub_cfg.get('name') or f'hub-{index + 1}',
            'enabled': True,
            'required': bool(hub_cfg.get('required', False)),
            'base_url': hub_cfg.get('base_url'),
            'runtime_report_endpoint': hub_cfg.get('runtime_report_endpoint', DEFAULT_RUNTIME_REPORT_ENDPOINT),
            'runtime_report_interval': _coerce_report_interval(hub_cfg.get('runtime_report_interval')),
            'runtime_scan_interval': _coerce_scan_interval(hub_cfg.get('runtime_scan_interval')),
            'instance_http_timeout': _coerce_http_timeout(hub_cfg.get('instance_http_timeout')),
            'agent_token': hub_cfg.get('agent_token', hub_cfg.get('token')),
            'websocket_enabled': hub_cfg.get('websocket_enabled', hub_cfg.get('ws_enabled', True)),
            'websocket_url': hub_cfg.get('websocket_url', hub_cfg.get('ws_url')),
            'websocket_endpoint': hub_cfg.get('websocket_endpoint', hub_cfg.get('ws_endpoint')),
        })

    return enabled_hubs


def _http_report_hub_configs() -> list[dict]:
    return [
        hub_cfg for hub_cfg in _enabled_hub_configs()
        if hub_cfg.get('websocket_enabled', True) is False
    ]


def _report_interval() -> int:
    intervals = [hub_cfg['runtime_report_interval'] for hub_cfg in _enabled_hub_configs()]
    return min(intervals) if intervals else DEFAULT_REPORT_INTERVAL_SECONDS


def _scan_interval() -> float:
    intervals = [hub_cfg['runtime_scan_interval'] for hub_cfg in _enabled_hub_configs()]
    return min(intervals) if intervals else DEFAULT_SCAN_INTERVAL_SECONDS


def _http_timeout() -> float:
    timeouts = [hub_cfg['instance_http_timeout'] for hub_cfg in _enabled_hub_configs()]
    return min(timeouts) if timeouts else DEFAULT_HTTP_TIMEOUT_SECONDS


def _runtime_report_url(hub_cfg: dict) -> str | None:
    base_url = str(hub_cfg.get('base_url') or '').rstrip('/')
    endpoint = str(hub_cfg.get('runtime_report_endpoint') or DEFAULT_RUNTIME_REPORT_ENDPOINT)

    if not base_url:
        return None

    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint

    return base_url + endpoint


def _agent_token(hub_cfg: dict) -> str | None:
    value = hub_cfg.get('agent_token', hub_cfg.get('token')) or config_store.AUTH_CFG.get('jwt_secret')
    return str(value).strip() if value not in (None, '') else None


def _read_connected_drivers(http_port: int, timeout: float) -> dict:
    started = time.perf_counter()

    try:
        req = urllib.request.Request(
            f'http://127.0.0.1:{http_port}/',
            headers={'User-Agent': 'PitLane-Agent/1.0'},
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        duration_ms = int((time.perf_counter() - started) * 1000)
        clients = data.get('clients')

        return {
            'http_connected_drivers': int(clients) if isinstance(clients, int) else None,
            'http_drivers_seen_at': _utc_now() if isinstance(clients, int) else None,
            'http_ok': True,
            'http_checked_at': _utc_now(),
            'http_duration_ms': duration_ms,
            'http_error': None,
        }
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            'http_connected_drivers': None,
            'http_drivers_seen_at': None,
            'http_ok': False,
            'http_checked_at': _utc_now(),
            'http_duration_ms': duration_ms,
            'http_error': exc.__class__.__name__,
        }


def _process_cpu_percent(pid: int, process: psutil.Process) -> float | None:
    try:
        now = time.monotonic()
        cached = _process_cpu_cache.get(pid)

        if cached:
            process = cached.get('process') or process
            sampled_at = float(cached.get('sampled_at') or 0)

            if now - sampled_at < PROCESS_CPU_SAMPLE_INTERVAL_SECONDS:
                return cached.get('value')
        else:
            process.cpu_percent(interval=None)
            _process_cpu_cache[pid] = {
                'process': process,
                'sampled_at': now,
                'value': None,
            }
            return None

        value = _safe_float(process.cpu_percent(interval=None))
        _process_cpu_cache[pid] = {
            'process': process,
            'sampled_at': now,
            'value': value,
        }

        return value
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        _process_cpu_cache.pop(pid, None)
        return None


def _running_instance_reports() -> list[dict]:
    reports = []
    timeout = _http_timeout()
    process_exit_observed = False

    for instance_id, info in process_supervisor.snapshot_running():
        proc = info.get('process')
        instance = info.get('instance') or {}

        if not proc:
            continue

        log_observation = observe_player_count(
            instance_id,
            info,
            config_store.LOGGING_CFG['logs_path'],
        )
        info['game_observation'] = log_observation

        poll = proc.poll()
        if poll is not None:
            process_supervisor.observe_exit(instance_id)
            process_exit_observed = True
            continue

        status = 'running' if poll is None else 'stopped'
        pid = proc.pid if poll is None else None
        started_at = None
        uptime_seconds = None
        cpu_percent = None
        ram_mb = None

        if poll is None and pid:
            started_ts = info.get('started_at')
            if started_ts:
                started_at = datetime.fromtimestamp(started_ts, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
                uptime_seconds = max(0, int(time.time() - started_ts))

            try:
                cached = _process_cpu_cache.get(pid)
                ps_proc = cached.get('process') if cached else psutil.Process(pid)

                cpu_percent = _process_cpu_percent(pid, ps_proc)
                ram_mb = round(ps_proc.memory_info().private / 1024 / 1024, 1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                _process_cpu_cache.pop(pid, None)
                status = 'stopped'
                pid = None

        report = {
            'id': instance_id,
            'status': status,
            'pid': pid,
            'started_at': started_at,
            'uptime_seconds': uptime_seconds,
            'cpu_percent': cpu_percent,
            'ram_mb': ram_mb,
        }

        http_port = instance.get('http_port')
        if status == 'running':
            http_observation = _read_connected_drivers(int(http_port), timeout) if http_port else {
                'http_connected_drivers': None,
                'http_drivers_seen_at': None,
                'http_ok': None,
                'http_checked_at': None,
                'http_duration_ms': None,
                'http_error': None,
            }
            process_identity = f"{pid or ''}:{info.get('started_at') or ''}"
            report.update(resolve_player_count(instance_id, process_identity, http_observation, log_observation))
            report.update(_game_observation_payload(log_observation))

        reports.append(report)

    if process_exit_observed:
        try:
            from services.runtime_state import save_runtime_state
            save_runtime_state(config_store.LOGGING_CFG)
        except Exception as exc:
            logging.warning('[runtime-state] Impossible de persister une sortie process: %s', exc)

    for instance_id, terminal in process_supervisor.snapshot_terminated():
        instance = terminal.get('instance') or {}
        reports.append({
            'id': instance_id,
            'status': 'stopped',
            'pid': None,
            'started_at': None,
            'uptime_seconds': None,
            'cpu_percent': None,
            'ram_mb': None,
            **terminal_process_payload(terminal),
        })

    return reports


def _game_observation_payload(observation: dict) -> dict:
    return {
        'session_phase': observation.get('session_phase'),
        'session_observed_at': observation.get('session_observed_at'),
        'sport_started_at': observation.get('sport_started_at'),
        'race_started_at': observation.get('race_started_at'),
        'first_driver_seen_at': observation.get('first_driver_seen_at'),
        'log_observed_from_start': bool(observation.get('log_observed_from_start')),
        'crash_detected_at': observation.get('crash_detected_at'),
    }


def build_runtime_report() -> dict:
    memory = psutil.virtual_memory()
    cpu_cores = psutil.cpu_count(logical=False) or 1
    cpu_threads = psutil.cpu_count(logical=True) or cpu_cores

    try:
        from services.result_pipeline import result_spool_usage
        spool_usage = result_spool_usage()
    except Exception as exc:
        spool_usage = {
            'status': 'unknown',
            'reasons': [f'metrics_unavailable:{exc.__class__.__name__}'],
        }

    return {
        'agent': {
            'version': '0.3.3',
            'server_time': _utc_now(),
            'report_interval_seconds': _report_interval(),
            'cpu_cores': cpu_cores,
            'cpu_threads': cpu_threads,
            'cpu_percent': _safe_float(psutil.cpu_percent(interval=None)),
            'ram_total_gb': round(memory.total / 1024 / 1024 / 1024, 2),
            'ram_used_gb': round(memory.used / 1024 / 1024 / 1024, 2),
            'ram_percent': _safe_float(memory.percent),
            'result_spool': spool_usage,
        },
        'instances': _running_instance_reports(),
    }


def runtime_report_signature(payload: dict) -> str:
    instances = payload.get('instances') if isinstance(payload, dict) else []
    comparable_instances = []

    if isinstance(instances, list):
        for item in instances:
            if not isinstance(item, dict):
                continue

            comparable_instances.append({
                'id': str(item.get('id') or ''),
                'status': item.get('status'),
                'pid': item.get('pid'),
                'started_at': item.get('started_at'),
                'connected_drivers': item.get('connected_drivers'),
                'drivers_source': item.get('drivers_source'),
                'drivers_conflict': item.get('drivers_conflict'),
                'drivers_zero_confirmed': item.get('drivers_zero_confirmed'),
                'log_connected_drivers': item.get('log_connected_drivers'),
                'http_connected_drivers': item.get('http_connected_drivers'),
                'http_ok': item.get('http_ok'),
                'http_error': item.get('http_error'),
                'session_phase': item.get('session_phase'),
                'session_observed_at': item.get('session_observed_at'),
                'sport_started_at': item.get('sport_started_at'),
                'race_started_at': item.get('race_started_at'),
                'first_driver_seen_at': item.get('first_driver_seen_at'),
                'log_observed_from_start': item.get('log_observed_from_start'),
                'exit_code': item.get('exit_code'),
                'exit_observed_at': item.get('exit_observed_at'),
                'stop_requested_at': item.get('stop_requested_at'),
                'stop_reason': item.get('stop_reason'),
                'crash_detected_at': item.get('crash_detected_at'),
            })

    comparable_instances.sort(key=lambda item: item['id'])

    agent = payload.get('agent') if isinstance(payload, dict) else {}
    result_spool = agent.get('result_spool') if isinstance(agent, dict) else None
    comparable_spool = None
    if isinstance(result_spool, dict):
        comparable_spool = {
            'status': result_spool.get('status'),
            'reasons': result_spool.get('reasons'),
            'file_count': result_spool.get('file_count'),
            'stored_bytes': result_spool.get('stored_bytes'),
            'artifacts': result_spool.get('artifacts'),
        }

    return json.dumps({
        'instances': comparable_instances,
        'result_spool': comparable_spool,
    }, sort_keys=True, separators=(',', ':'))


def _send_runtime_report_to_hub(hub_cfg: dict, payload: dict) -> bool:
    url = _runtime_report_url(hub_cfg)
    token = _agent_token(hub_cfg)
    hub_name = hub_cfg.get('name') or 'hub'
    required = bool(hub_cfg.get('required', False))
    timeout = _coerce_http_timeout(hub_cfg.get('instance_http_timeout'))

    if not url or not token:
        if required:
            logging.warning('[runtime-report] Hub requis "%s" ignoré: configuration incomplète', hub_name)
        return False

    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'Content-Type': 'application/json',
            'X-Pitlane-Agent-Token': token,
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                logging.warning('[runtime-report] Hub "%s" a répondu HTTP %s', hub_name, resp.status)
            return ok
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        log_fn = logging.error if required else logging.warning
        log_fn('[runtime-report] hub "%s": %s', hub_name, exc.__class__.__name__)
        return False


def send_runtime_report() -> bool:
    hub_configs = _http_report_hub_configs()

    if not hub_configs:
        return False

    started = time.perf_counter()
    payload = build_runtime_report()
    payload['agent']['report_duration_ms'] = int((time.perf_counter() - started) * 1000)

    max_workers = min(len(hub_configs), 8)
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_send_runtime_report_to_hub, hub_cfg, payload) for hub_cfg in hub_configs]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                logging.error('[runtime-report] Erreur push parallèle: %s', exc)
                results.append(False)

    return any(results)


def _report_loop():
    while not _reporter_stop_event.is_set():
        try:
            send_runtime_report()
        except Exception as exc:
            logging.error('[runtime-report] Erreur: %s', exc)

        _reporter_stop_event.wait(_report_interval())


def start_runtime_reporter():
    global _reporter_thread

    if _reporter_thread and _reporter_thread.is_alive():
        return

    hub_configs = _http_report_hub_configs()
    if not any(_runtime_report_url(hub_cfg) and _agent_token(hub_cfg) for hub_cfg in hub_configs):
        logging.info('[runtime-report] Désactivé: WebSocket actif ou configuration HTTP incomplète')
        return

    _reporter_stop_event.clear()
    _reporter_thread = threading.Thread(target=_report_loop, daemon=True)
    _reporter_thread.start()
    logging.info('[runtime-report] HTTP fallback activé toutes les %ss vers %d hub(s)', _report_interval(), len(hub_configs))
