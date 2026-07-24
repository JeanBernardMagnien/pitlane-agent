import json
import math
from datetime import datetime, timezone

from core.capacity_profiler_constants import classify


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace('Z', '+00:00'))


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)

    rank = (len(ordered) - 1) * (p / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)

    if lower == upper:
        return round(ordered[int(rank)], 2)

    lower_value = ordered[int(lower)] * (upper - rank)
    upper_value = ordered[int(upper)] * (rank - lower)
    return round(lower_value + upper_value, 2)


def ram_available_percent(snapshot: dict, ram_total_mb: float | None) -> float | None:
    """RAM disponible en % — dérivée de ram_available_mb/ram_total_mb, avec repli sur
    (100 - ram_percent) si le total machine n'est pas connu. Réutilisée par le résumé
    de run et par l'indicateur de risque en direct (capacity_profiler_runner).
    """
    available_mb = snapshot.get('ram_available_mb')
    if available_mb is not None and ram_total_mb:
        return round((available_mb / ram_total_mb) * 100, 2)

    ram_percent = snapshot.get('ram_percent')
    if ram_percent is not None:
        return round(100 - ram_percent, 2)

    return None


def _numeric_values(snapshots: list[dict], key: str) -> list[float]:
    return [s[key] for s in snapshots if s.get(key) is not None]


def _distribution(values: list[float]) -> dict | None:
    if not values:
        return None

    return {
        'min': round(min(values), 2),
        'max': round(max(values), 2),
        'mean': round(sum(values) / len(values), 2),
        'count': len(values),
    }


def _duration_seconds(started_at: str | None, ended_at: str | None) -> int | None:
    if not started_at or not ended_at:
        return None

    try:
        start = _parse_iso(started_at)
        end = _parse_iso(ended_at)
    except (TypeError, ValueError):
        return None

    return max(0, int((end - start).total_seconds()))


def _sample_quality(
    snapshot_count: int,
    duration_seconds: int | None,
    sample_interval_seconds: float | None,
) -> float | None:
    if not duration_seconds or not sample_interval_seconds or sample_interval_seconds <= 0:
        return None

    expected = duration_seconds / sample_interval_seconds
    if expected <= 0:
        return None

    return round(min(1.0, snapshot_count / expected), 2)


def compute_summary(
    run_row: dict,
    snapshots: list[dict],
    ended_at: str | None = None,
    sample_interval_seconds: float | None = None,
) -> dict:
    ended_at = ended_at or _utc_now()
    duration_seconds = _duration_seconds(run_row.get('started_at'), ended_at)

    cpu_total_values = _numeric_values(snapshots, 'cpu_total_percent')
    cpu_core_values = _numeric_values(snapshots, 'cpu_core_max_percent')
    driver_values = _numeric_values(snapshots, 'total_connected_drivers')
    instance_values = _numeric_values(snapshots, 'active_instances_count')
    network_tx_values = _numeric_values(snapshots, 'network_tx_mbps')

    ram_total_mb = run_row.get('ram_total_mb')
    ram_available_values = [
        value for value in (ram_available_percent(s, ram_total_mb) for s in snapshots)
        if value is not None
    ]

    cpu_total_p95 = percentile(cpu_total_values, 95)
    cpu_core_max_p95 = percentile(cpu_core_values, 95)
    ram_available_min = min(ram_available_values) if ram_available_values else None
    network_tx_max = max(network_tx_values) if network_tx_values else None
    max_total_drivers = max(driver_values) if driver_values else None
    max_simultaneous_instances = max(instance_values) if instance_values else None

    sample_quality = _sample_quality(len(snapshots), duration_seconds, sample_interval_seconds)

    crash_count = int(run_row.get('crash_count') or 0)
    risk_level, limiting_factor = classify(cpu_core_max_p95, cpu_total_p95, ram_available_min, crash_count)

    summary_json = json.dumps({
        'snapshot_count': len(snapshots),
        'crash_count': crash_count,
        'first_captured_at': snapshots[0]['captured_at'] if snapshots else None,
        'last_captured_at': snapshots[-1]['captured_at'] if snapshots else None,
        'cpu_total_percent': _distribution(cpu_total_values),
        'cpu_core_max_percent': _distribution(cpu_core_values),
        'ram_available_percent': _distribution(ram_available_values),
        'network_tx_mbps': _distribution(network_tx_values),
        'total_connected_drivers': _distribution(driver_values),
    }, sort_keys=True)

    return {
        'duration_seconds': duration_seconds,
        'max_total_drivers': max_total_drivers,
        'max_simultaneous_instances': max_simultaneous_instances,
        'cpu_total_p95': cpu_total_p95,
        'cpu_core_max_p95': cpu_core_max_p95,
        'ram_available_min': ram_available_min,
        'network_tx_max': network_tx_max,
        'sample_quality': sample_quality,
        'risk_level': risk_level,
        'limiting_factor': limiting_factor,
        'summary_json': summary_json,
    }
