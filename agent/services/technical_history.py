import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from core import config_store
from services.capacity_profiler_store import get_capacity_profiler_store


DEFAULT_SAMPLE_INTERVAL_SECONDS = 60.0
DEFAULT_RETENTION_DAYS = 30
MAINTENANCE_INTERVAL_SECONDS = 3600.0

_lock = threading.Lock()
_last_sample_monotonic = 0.0
_last_maintenance_monotonic = 0.0


def record_runtime_report(report: dict, now: float | None = None) -> bool:
    global _last_sample_monotonic, _last_maintenance_monotonic

    now = time.monotonic() if now is None else now
    interval = _positive_number(
        config_store.CAPACITY_PROFILER_CFG.get('technical_history_interval_seconds'),
        DEFAULT_SAMPLE_INTERVAL_SECONDS,
    )

    with _lock:
        if _last_sample_monotonic and now - _last_sample_monotonic < interval:
            return False

        snapshot = _snapshot_from_runtime_report(report)
        store = get_capacity_profiler_store()
        store.insert_technical_history_snapshot(snapshot)
        _last_sample_monotonic = now

        if (
            not _last_maintenance_monotonic
            or now - _last_maintenance_monotonic >= MAINTENANCE_INTERVAL_SECONDS
        ):
            retention_days = _positive_int(
                config_store.CAPACITY_PROFILER_CFG.get('technical_history_retention_days'),
                DEFAULT_RETENTION_DAYS,
            )
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            store.purge_technical_history(cutoff.isoformat().replace('+00:00', 'Z'))
            _last_maintenance_monotonic = now

    return True


def _snapshot_from_runtime_report(report: dict) -> dict:
    agent = report.get('agent') if isinstance(report.get('agent'), dict) else {}
    reported_instances = report.get('instances') if isinstance(report.get('instances'), list) else []
    instances = []

    for item in reported_instances:
        if not isinstance(item, dict):
            continue

        instance_id = str(item.get('id') or '').strip()
        if not instance_id:
            continue

        instances.append({
            'id': instance_id,
            'status': item.get('status'),
            'cpu_percent': item.get('cpu_percent'),
            'ram_mb': item.get('ram_mb'),
            'connected_drivers': item.get('connected_drivers'),
            'http_ok': item.get('http_ok'),
            'http_duration_ms': item.get('http_duration_ms'),
            'uptime_seconds': item.get('uptime_seconds'),
        })

    running = [
        item for item in instances
        if item.get('status') in ('running', 'online')
    ]

    return {
        'captured_at': agent.get('server_time') or _utc_now(),
        'cpu_total_percent': agent.get('cpu_percent'),
        'ram_used_mb': _gb_to_mb(agent.get('ram_used_gb')),
        'ram_total_mb': _gb_to_mb(agent.get('ram_total_gb')),
        'ram_percent': agent.get('ram_percent'),
        'active_instances_count': len(running),
        'total_connected_drivers': sum(
            int(item.get('connected_drivers') or 0) for item in running
        ),
        'instances': instances,
    }


def _gb_to_mb(value):
    try:
        return round(float(value) * 1024, 2)
    except (TypeError, ValueError):
        return None


def _positive_number(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default

    return parsed if parsed > 0 else default


def _positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    return parsed if parsed > 0 else default


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def safe_record_runtime_report(report: dict) -> None:
    try:
        record_runtime_report(report)
    except Exception as exc:
        logging.warning(
            '[technical-history] Échantillonnage impossible: %s',
            exc.__class__.__name__,
        )
