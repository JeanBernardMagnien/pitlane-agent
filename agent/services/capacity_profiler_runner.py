import logging
import platform
import sqlite3
import threading
import time
from datetime import datetime, timezone

import psutil

from core import config_store
from core.capacity_profiler_constants import classify
from services import capacity_profiler_sampler
from services import capacity_profiler_summary
from services.capacity_profiler_maintenance import (
    CapacityProfilerMaintenance,
    DEFAULT_CLEANUP_LIMIT,
    DEFAULT_RUN_RETENTION_DAYS,
    DEFAULT_SNAPSHOT_RETENTION_DAYS,
)
from services.capacity_profiler_store import get_capacity_profiler_store


DEFAULT_SAMPLE_INTERVAL_SECONDS = 8.0
DEFAULT_MAX_RUN_DURATION_SECONDS = 43200.0
JOIN_TIMEOUT_SECONDS = 10.0
MAINTENANCE_INTERVAL_SECONDS = 86400

_lock = threading.Lock()
_active = {'run_id': None, 'thread': None, 'stop_event': None}

_maintenance_lock = threading.Lock()
_last_maintenance_monotonic = 0.0

_watcher_thread = None
_watcher_stop_event = threading.Event()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _positive_number(value, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default

    return parsed if parsed > 0 else default


def _sample_interval_seconds() -> float:
    return _positive_number(
        config_store.CAPACITY_PROFILER_CFG.get('sample_interval_seconds'),
        DEFAULT_SAMPLE_INTERVAL_SECONDS,
    )


def _max_run_duration_seconds() -> float:
    return _positive_number(
        config_store.CAPACITY_PROFILER_CFG.get('max_run_duration_seconds'),
        DEFAULT_MAX_RUN_DURATION_SECONDS,
    )


def _store():
    return get_capacity_profiler_store()


def start_run(meta: dict, start_reason: str = 'manual') -> tuple[dict, int]:
    with _lock:
        if _active['run_id'] is not None or _store().active_run() is not None:
            return {'error': 'run_already_active'}, 409

        cpu_cores = psutil.cpu_count(logical=False) or 1
        cpu_threads = psutil.cpu_count(logical=True) or cpu_cores
        ram_total_mb = round(psutil.virtual_memory().total / 1024 / 1024)
        server_name = config_store.CAPACITY_PROFILER_CFG.get('server_name') or platform.node()

        run_meta = {
            'server_name': server_name,
            'cpu_model': capacity_profiler_sampler.cpu_model(),
            'cpu_cores': cpu_cores,
            'cpu_threads': cpu_threads,
            'ram_total_mb': ram_total_mb,
            'test_label': (meta or {}).get('test_label'),
            'track': (meta or {}).get('track'),
            'allowed_cars_mode': (meta or {}).get('allowed_cars_mode'),
            'server_profile_type': (meta or {}).get('server_profile_type'),
            'start_reason': start_reason,
        }

        try:
            run = _store().create_run(run_meta)
        except sqlite3.IntegrityError:
            return {'error': 'run_already_active'}, 409

        stop_event = threading.Event()
        thread = threading.Thread(target=_sampling_loop, args=(run['id'], stop_event), daemon=True)
        _active.update(run_id=run['id'], thread=thread, stop_event=stop_event)
        thread.start()

    _maybe_run_maintenance()
    return run, 201


def stop_run(run_id: int, stop_reason: str = 'manual') -> tuple[dict, int]:
    with _lock:
        if _active['run_id'] != run_id:
            return {'error': 'run_not_active'}, 404

        stop_event = _active['stop_event']
        thread = _active['thread']

    stop_event.set()
    thread.join(timeout=JOIN_TIMEOUT_SECONDS)

    return _finalize(run_id, 'completed', stop_reason), 200


def current_status() -> dict | None:
    _maybe_run_maintenance()

    run = _store().active_run()
    if run is None:
        return None

    recent = _store().list_snapshots(run['id'], limit=5000)[-12:]
    latest_snapshot = _store().latest_snapshot(run['id'])

    ram_total_mb = run.get('ram_total_mb')
    cpu_core_values = [s['cpu_core_max_percent'] for s in recent if s.get('cpu_core_max_percent') is not None]
    cpu_total_values = [s['cpu_total_percent'] for s in recent if s.get('cpu_total_percent') is not None]
    ram_values = [
        value for value in (capacity_profiler_summary.ram_available_percent(s, ram_total_mb) for s in recent)
        if value is not None
    ]

    live_risk_level, live_limiting_factor = classify(
        max(cpu_core_values) if cpu_core_values else None,
        max(cpu_total_values) if cpu_total_values else None,
        min(ram_values) if ram_values else None,
        int(run.get('crash_count') or 0),
    )

    return {
        'active': True,
        'run': run,
        'latest_snapshot': latest_snapshot,
        'live_risk_level': live_risk_level,
        'live_limiting_factor': live_limiting_factor,
    }


def list_runs(limit: int = 50, offset: int = 0) -> list[dict]:
    _maybe_run_maintenance()
    return _store().list_runs(limit, offset)


def get_run(run_id: int) -> dict | None:
    return _store().get_run(run_id)


def list_snapshots(run_id: int, since: str | None = None, limit: int = 500) -> list[dict]:
    return _store().list_snapshots(run_id, since, limit)


def get_settings() -> dict:
    return _store().get_settings()


def update_settings(patch: dict) -> dict:
    return _store().update_settings(patch or {})


def reconcile_at_boot() -> None:
    reconciled_ids = _store().reconcile_orphaned_runs()
    if reconciled_ids:
        logging.info(
            '[capacity-profiler] %d run(s) resté(s) actifs au précédent arrêt, finalisé(s) en interrupted',
            len(reconciled_ids),
        )
    _maybe_run_maintenance(force=True)


def _finalize(run_id: int, status: str, stop_reason: str) -> dict:
    store = _store()
    run = store.get_run(run_id)
    ended_at = _utc_now()
    snapshots = store.list_snapshots(run_id, limit=100000)
    summary_fields = capacity_profiler_summary.compute_summary(
        run, snapshots, ended_at=ended_at, sample_interval_seconds=_sample_interval_seconds(),
    )
    finalized = store.finalize_run(run_id, ended_at, status, stop_reason, summary_fields)

    with _lock:
        if _active['run_id'] == run_id:
            _active.update(run_id=None, thread=None, stop_event=None)

    return finalized


def _sampling_loop(run_id: int, stop_event: threading.Event) -> None:
    store = _store()
    interval = _sample_interval_seconds()
    max_duration = _max_run_duration_seconds()
    started = time.monotonic()
    previous_state = None

    while not stop_event.is_set():
        try:
            snapshot, previous_state, crash_events = capacity_profiler_sampler.build_snapshot(previous_state)
            store.insert_snapshot(run_id, snapshot)
            for _ in crash_events:
                store.increment_crash_count(run_id)
        except Exception:
            logging.exception('[capacity-profiler] Erreur pendant un tick d’échantillonnage')

        if time.monotonic() - started >= max_duration:
            _finalize(run_id, 'completed', 'timeout')
            return

        stop_event.wait(interval)


def start_capacity_profiler_watcher() -> None:
    global _watcher_thread

    if _watcher_thread and _watcher_thread.is_alive():
        return

    _watcher_stop_event.clear()
    _watcher_thread = threading.Thread(target=_watcher_loop, daemon=True)
    _watcher_thread.start()


def _watcher_loop() -> None:
    above_since = None
    below_since = None
    io_state = None

    while not _watcher_stop_event.is_set():
        try:
            above_since, below_since, io_state = _evaluate_auto_trigger(above_since, below_since, io_state)
        except Exception:
            logging.exception('[capacity-profiler] Erreur pendant l’évaluation du déclenchement automatique')

        _watcher_stop_event.wait(_sample_interval_seconds())


def _evaluate_auto_trigger(
    above_since: float | None,
    below_since: float | None,
    io_state: dict | None,
    now: float | None = None,
) -> tuple[float | None, float | None, dict | None]:
    now = now if now is not None else time.monotonic()
    store = _store()
    settings = store.get_settings()

    if not settings['auto_start_enabled']:
        return None, None, io_state

    active_run = store.active_run()

    if active_run is None:
        snapshot, io_state, _crash_events = capacity_profiler_sampler.build_snapshot(io_state)
        drivers = snapshot.get('total_connected_drivers') or 0

        if drivers >= settings['driver_threshold']:
            above_since = above_since if above_since is not None else now
            if now - above_since >= settings['start_grace_seconds']:
                start_run({}, start_reason='auto_threshold')
                above_since = None
        else:
            above_since = None

        return above_since, None, io_state

    if active_run.get('start_reason') != 'auto_threshold':
        # Run manuel : l'opérateur garde la main, le watcher ne l'arrête jamais.
        return None, None, io_state

    latest = store.latest_snapshot(active_run['id'])
    drivers = (latest.get('total_connected_drivers') if latest else None) or 0

    if drivers < settings['driver_threshold']:
        below_since = below_since if below_since is not None else now
        if now - below_since >= settings['stop_grace_seconds']:
            stop_run(active_run['id'], stop_reason='auto_threshold')
            below_since = None
    else:
        below_since = None

    return None, below_since, io_state


def _maybe_run_maintenance(force: bool = False) -> None:
    global _last_maintenance_monotonic

    now = time.monotonic()
    if not force and now - _last_maintenance_monotonic < MAINTENANCE_INTERVAL_SECONDS:
        return

    with _maintenance_lock:
        now = time.monotonic()
        if not force and now - _last_maintenance_monotonic < MAINTENANCE_INTERVAL_SECONDS:
            return

        _last_maintenance_monotonic = now

        try:
            store = _store()
            maintenance = CapacityProfilerMaintenance(store.path)
            snapshot_retention_days = int(_positive_number(
                config_store.CAPACITY_PROFILER_CFG.get('snapshot_retention_days'), DEFAULT_SNAPSHOT_RETENTION_DAYS,
            ))
            run_retention_days = int(_positive_number(
                config_store.CAPACITY_PROFILER_CFG.get('run_retention_days'), DEFAULT_RUN_RETENTION_DAYS,
            ))
            cleanup_limit = int(_positive_number(
                config_store.CAPACITY_PROFILER_CFG.get('cleanup_limit'), DEFAULT_CLEANUP_LIMIT,
            ))

            maintenance.purge_old_snapshots(retention_days=snapshot_retention_days, limit=cleanup_limit, execute=True)
            maintenance.purge_old_runs(retention_days=run_retention_days, limit=cleanup_limit, execute=True)
        except Exception as exc:
            logging.warning('[capacity-profiler] Nettoyage impossible: %s', exc)
