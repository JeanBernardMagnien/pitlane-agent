import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import psutil

from core import config_store
from services.server_manager import _running


DEFAULT_REPORT_INTERVAL_SECONDS = 10
DEFAULT_HTTP_TIMEOUT_SECONDS = 0.5
DEFAULT_RUNTIME_REPORT_ENDPOINT = '/api/agent/runtime-report'


_reporter_thread = None
_reporter_stop_event = threading.Event()
_process_cpu_cache: dict[int, psutil.Process] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _safe_float(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _hub_config() -> dict:
    return config_store.CFG.get('hub', {}) or {}


def _coerce_report_interval(value) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError):
        interval = DEFAULT_REPORT_INTERVAL_SECONDS

    return max(1, interval)


def _coerce_http_timeout(value) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        timeout = DEFAULT_HTTP_TIMEOUT_SECONDS

    return max(0.1, min(timeout, 5.0))


def _enabled_hub_configs() -> list[dict]:
    """Return enabled runtime report targets.

    Preferred config uses `hubs:`.
    Legacy `hub:` is still supported as a fallback for existing installs.
    """
    legacy_hub_cfg = _hub_config()
    hubs_cfg = config_store.CFG.get('hubs')

    if not hubs_cfg:
        return [
            {
                **legacy_hub_cfg,
                'name': legacy_hub_cfg.get('name') or 'hub',
                'enabled': True,
                'required': True,
                'runtime_report_endpoint': legacy_hub_cfg.get('runtime_report_endpoint', DEFAULT_RUNTIME_REPORT_ENDPOINT),
                'runtime_report_interval': _coerce_report_interval(
                    legacy_hub_cfg.get('runtime_report_interval', legacy_hub_cfg.get('monitor_interval'))
                ),
                'instance_http_timeout': _coerce_http_timeout(legacy_hub_cfg.get('instance_http_timeout')),
            }
        ] if legacy_hub_cfg else []

    global_token = legacy_hub_cfg.get('agent_token', legacy_hub_cfg.get('token'))
    global_endpoint = legacy_hub_cfg.get('runtime_report_endpoint', DEFAULT_RUNTIME_REPORT_ENDPOINT)
    global_interval = legacy_hub_cfg.get('runtime_report_interval', legacy_hub_cfg.get('monitor_interval'))
    global_timeout = legacy_hub_cfg.get('instance_http_timeout')
    enabled_hubs = []

    for index, hub_cfg in enumerate(hubs_cfg):
        if not isinstance(hub_cfg, dict):
            continue

        if hub_cfg.get('enabled', True) is False:
            continue

        merged_cfg = {
            'name': hub_cfg.get('name') or f'hub-{index + 1}',
            'enabled': True,
            'required': bool(hub_cfg.get('required', False)),
            'base_url': hub_cfg.get('base_url'),
            'runtime_report_endpoint': hub_cfg.get('runtime_report_endpoint', global_endpoint),
            'runtime_report_interval': _coerce_report_interval(
                hub_cfg.get('runtime_report_interval', global_interval)
            ),
            'instance_http_timeout': _coerce_http_timeout(
                hub_cfg.get('instance_http_timeout', global_timeout)
            ),
            'agent_token': hub_cfg.get('agent_token', hub_cfg.get('token', global_token)),
        }
        enabled_hubs.append(merged_cfg)

    return enabled_hubs


def _report_interval() -> int:
    intervals = [hub_cfg['runtime_report_interval'] for hub_cfg in _enabled_hub_configs()]
    return min(intervals) if intervals else DEFAULT_REPORT_INTERVAL_SECONDS


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


def _agent_token(hub_cfg: dict | None = None) -> str | None:
    hub_cfg = hub_cfg or _hub_config()
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
            'connected_drivers': int(clients) if isinstance(clients, int) else None,
            'drivers_seen_at': _utc_now() if isinstance(clients, int) else None,
            'http_ok': True,
            'http_checked_at': _utc_now(),
            'http_duration_ms': duration_ms,
            'http_error': None,
        }
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            'connected_drivers': None,
            'drivers_seen_at': None,
            'http_ok': False,
            'http_checked_at': _utc_now(),
            'http_duration_ms': duration_ms,
            'http_error': exc.__class__.__name__,
        }


def _process_cpu_percent(process: psutil.Process) -> float | None:
    try:
        return _safe_float(process.cpu_percent(interval=None))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _running_instance_reports() -> list[dict]:
    reports = []
    timeout = _http_timeout()

    for instance_id, info in list(_running.items()):
        proc = info.get('process')
        instance = info.get('instance') or {}

        if not proc:
            continue

        poll = proc.poll()
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
                ps_proc = _process_cpu_cache.get(pid)
                if not ps_proc:
                    ps_proc = psutil.Process(pid)
                    ps_proc.cpu_percent(interval=None)
                    _process_cpu_cache[pid] = ps_proc

                cpu_percent = _process_cpu_percent(ps_proc)
                ram_mb = round(ps_proc.memory_info().rss / 1024 / 1024, 1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
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
        if status == 'running' and http_port:
            report.update(_read_connected_drivers(int(http_port), timeout))

        reports.append(report)

    return reports


def build_runtime_report() -> dict:
    memory = psutil.virtual_memory()

    return {
        'agent': {
            'version': '0.2.0',
            'server_time': _utc_now(),
            'report_interval_seconds': _report_interval(),
            'cpu_percent': _safe_float(psutil.cpu_percent(interval=None)),
            'ram_total_gb': round(memory.total / 1024 / 1024 / 1024, 2),
            'ram_used_gb': round(memory.used / 1024 / 1024 / 1024, 2),
            'ram_percent': _safe_float(memory.percent),
        },
        'instances': _running_instance_reports(),
    }


def _send_runtime_report_to_hub(hub_cfg: dict, payload: dict) -> bool:
    url = _runtime_report_url(hub_cfg)
    token = _agent_token(hub_cfg)
    hub_name = hub_cfg.get('name') or 'hub'
    required = bool(hub_cfg.get('required', False))

    if not url or not token:
        if required:
            print(f'[runtime-report] Hub requis "{hub_name}" ignoré: configuration incomplète')
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            ok = 200 <= resp.status < 300
            if not ok:
                print(f'[runtime-report] Hub "{hub_name}" a répondu HTTP {resp.status}')
            return ok
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        level = 'ERROR' if required else 'WARN'
        print(f'[runtime-report] {level} hub "{hub_name}": {exc.__class__.__name__}')
        return False


def send_runtime_report() -> bool:
    hub_configs = _enabled_hub_configs()

    if not hub_configs:
        return False

    started = time.perf_counter()
    payload = build_runtime_report()
    payload['agent']['report_duration_ms'] = int((time.perf_counter() - started) * 1000)

    results = [_send_runtime_report_to_hub(hub_cfg, payload) for hub_cfg in hub_configs]
    return any(results)


def _report_loop():
    while not _reporter_stop_event.is_set():
        try:
            send_runtime_report()
        except Exception as exc:
            print(f'[runtime-report] Erreur: {exc}')

        _reporter_stop_event.wait(_report_interval())


def start_runtime_reporter():
    global _reporter_thread

    if _reporter_thread and _reporter_thread.is_alive():
        return

    hub_configs = _enabled_hub_configs()
    if not any(_runtime_report_url(hub_cfg) and _agent_token(hub_cfg) for hub_cfg in hub_configs):
        print('[runtime-report] Désactivé: configuration hub incomplète')
        return

    _reporter_stop_event.clear()
    _reporter_thread = threading.Thread(target=_report_loop, daemon=True)
    _reporter_thread.start()
    print(f'[runtime-report] Activé toutes les {_report_interval()}s vers {len(hub_configs)} hub(s)')
