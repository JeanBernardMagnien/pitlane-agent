import platform
import time
from datetime import datetime, timezone
from functools import lru_cache

import psutil

from core import config_store
from services import process_cpu_sampler
from services.player_count_observer import observe_player_count, resolve_player_count
from services.process_supervisor import process_supervisor
from services.runtime_reporter import DEFAULT_HTTP_TIMEOUT_SECONDS, read_connected_drivers


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _safe_round(value, digits: int = 2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def cpu_model() -> str | None:
    """Best-effort : sous Windows, platform.processor() renvoie souvent une chaîne
    générique (ex: 'Intel64 Family 6 Model 158...') plutôt qu'un nom marketing.
    Limitation connue V1, pas de lecture registre dédiée pour l'instant."""
    value = (platform.processor() or '').strip()
    return value or None


def _num_handles(ps_proc: psutil.Process) -> int | None:
    getter = getattr(ps_proc, 'num_handles', None)
    if getter is None:
        return None

    try:
        return getter()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _instance_snapshot(instance_id: str, info: dict, logs_path: str, http_timeout: float) -> dict | None:
    proc = info.get('process')
    if not proc or proc.poll() is not None:
        # Sortie de process déjà survenue ou en cours d'observation par runtime_reporter,
        # qui reste seul responsable de la bascule running -> terminated.
        return None

    pid = proc.pid
    instance_cfg = info.get('instance') or {}
    started_ts = info.get('started_at')
    uptime_seconds = max(0, int(time.time() - started_ts)) if started_ts else None

    log_observation = observe_player_count(instance_id, info, logs_path)

    try:
        ps_proc = process_cpu_sampler.cached_process(pid) or psutil.Process(pid)
        process_cpu_percent = process_cpu_sampler.sample_cpu_percent(pid, ps_proc)
        process_ram_mb = round(ps_proc.memory_info().private / 1024 / 1024, 1)
        threads = ps_proc.num_threads()
        handles = _num_handles(ps_proc)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        process_cpu_sampler.forget(pid)
        return None

    http_port = instance_cfg.get('http_port')
    http_observation = read_connected_drivers(int(http_port), http_timeout) if http_port else {
        'http_connected_drivers': None,
        'http_drivers_seen_at': None,
        'http_ok': None,
        'http_checked_at': None,
        'http_duration_ms': None,
        'http_error': None,
    }
    process_identity = f"{pid}:{started_ts or ''}"
    resolved = resolve_player_count(instance_id, process_identity, http_observation, log_observation)

    return {
        'id': instance_id,
        'status': 'running',
        'pid': pid,
        'connected_drivers': resolved.get('connected_drivers'),
        'session_phase': log_observation.get('session_phase'),
        'race_started_at': log_observation.get('race_started_at'),
        'process_cpu_percent': process_cpu_percent,
        'process_ram_mb': process_ram_mb,
        'threads': threads,
        'handles': handles,
        'uptime_seconds': uptime_seconds,
        'crash_detected_at': log_observation.get('crash_detected_at'),
    }


def _detect_crash_events(previous_seen_exits: dict) -> tuple[list[dict], dict]:
    crash_events = []
    new_seen_exits = dict(previous_seen_exits)

    for instance_id, terminal in process_supervisor.snapshot_terminated():
        exit_observed_at = terminal.get('exit_observed_at')
        if not exit_observed_at or previous_seen_exits.get(instance_id) == exit_observed_at:
            continue

        new_seen_exits[instance_id] = exit_observed_at
        if terminal.get('stop_requested_at') is None:
            crash_events.append({'instance_id': instance_id, 'exit_observed_at': exit_observed_at})

    return crash_events, new_seen_exits


def _delta_rate(current: float | None, previous: float | None, elapsed: float, divisor: float) -> float | None:
    if current is None or previous is None:
        return None

    delta = current - previous
    if delta < 0:
        # Compteur système réinitialisé (ex: redémarrage OS) : pas de taux fiable ce tick.
        return None

    return round((delta / divisor) / elapsed, 2)


def _io_rates(previous_io: dict | None) -> tuple[dict, dict]:
    now = time.monotonic()
    net = psutil.net_io_counters()
    disk = psutil.disk_io_counters()

    current_io = {
        'bytes_sent': net.bytes_sent if net else None,
        'bytes_recv': net.bytes_recv if net else None,
        'read_bytes': disk.read_bytes if disk else None,
        'write_bytes': disk.write_bytes if disk else None,
        'at': now,
    }

    empty_rates = {
        'network_tx_mbps': None,
        'network_rx_mbps': None,
        'disk_read_kbps': None,
        'disk_write_kbps': None,
    }

    if not previous_io:
        return empty_rates, current_io

    elapsed = now - previous_io.get('at', now)
    if elapsed <= 0:
        return empty_rates, current_io

    rates = {
        'network_tx_mbps': _delta_rate(current_io['bytes_sent'], previous_io.get('bytes_sent'), elapsed, 1_000_000),
        'network_rx_mbps': _delta_rate(current_io['bytes_recv'], previous_io.get('bytes_recv'), elapsed, 1_000_000),
        'disk_read_kbps': _delta_rate(current_io['read_bytes'], previous_io.get('read_bytes'), elapsed, 1024),
        'disk_write_kbps': _delta_rate(current_io['write_bytes'], previous_io.get('write_bytes'), elapsed, 1024),
    }
    return rates, current_io


def build_snapshot(previous_state: dict | None = None) -> tuple[dict, dict, list[dict]]:
    """Compose un snapshot machine + instances, sans dupliquer la logique déjà
    fournie par process_cpu_sampler / player_count_observer / process_supervisor.

    Retourne (snapshot, new_state, crash_events) : new_state doit être repassé au tick
    suivant (compteurs réseau/disque cumulatifs, dédoublonnage des sorties de process).
    """
    previous_state = previous_state or {}
    logs_path = config_store.LOGGING_CFG.get('logs_path') or 'logs'

    cpu_total_percent = _safe_round(psutil.cpu_percent(interval=None))
    per_core = [round(float(v), 2) for v in psutil.cpu_percent(interval=None, percpu=True)]
    cpu_core_max_percent = max(per_core) if per_core else None

    memory = psutil.virtual_memory()

    instances = []
    for instance_id, info in process_supervisor.snapshot_running():
        instance_snapshot = _instance_snapshot(instance_id, info, logs_path, DEFAULT_HTTP_TIMEOUT_SECONDS)
        if instance_snapshot is not None:
            instances.append(instance_snapshot)

    crash_events, new_seen_exits = _detect_crash_events(previous_state.get('seen_exits') or {})
    io_rates, new_io = _io_rates(previous_state.get('io'))

    total_connected_drivers = (
        sum((item.get('connected_drivers') or 0) for item in instances) if instances else None
    )
    instances_with_players_count = sum(
        1 for item in instances if (item.get('connected_drivers') or 0) > 0
    )

    snapshot = {
        'captured_at': _utc_now(),
        'total_connected_drivers': total_connected_drivers,
        'active_instances_count': len(instances),
        'instances_with_players_count': instances_with_players_count,
        'cpu_total_percent': cpu_total_percent,
        'cpu_core_max_percent': cpu_core_max_percent,
        'cpu_per_core': per_core,
        'ram_used_mb': round(memory.used / 1024 / 1024, 1),
        'ram_available_mb': round(memory.available / 1024 / 1024, 1),
        'ram_percent': _safe_round(memory.percent),
        'instances': instances,
        **io_rates,
    }

    new_state = {'io': new_io, 'seen_exits': new_seen_exits}

    return snapshot, new_state, crash_events
