from datetime import datetime

from core import config_store
from services.capacity_profiler_summary import percentile
from services.capacity_profiler_store import get_capacity_profiler_store
from services.technical_history import (
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SAMPLE_INTERVAL_SECONDS,
)

MAX_RESPONSE_POINTS = 120


class DiagnosticQueryError(ValueError):
    pass


def execute_diagnostic_query(query: str, params: dict | None = None) -> dict:
    query = str(query or '').strip()
    params = params if isinstance(params, dict) else {}

    if query != 'technical_history':
        raise DiagnosticQueryError('Requête diagnostique inconnue')

    since = _normalized_since(params.get('since'))
    limit = _bounded_limit(params.get('limit'))
    samples = get_capacity_profiler_store().list_technical_history(
        since=since,
        limit=limit,
    )
    summary = _summarize(samples)
    samples = _downsample(samples, MAX_RESPONSE_POINTS)

    return {
        'schema_version': 2,
        'query': query,
        'source': 'agent_sqlite',
        'sample_interval_seconds': _positive_number(
            config_store.CAPACITY_PROFILER_CFG.get('technical_history_interval_seconds'),
            DEFAULT_SAMPLE_INTERVAL_SECONDS,
        ),
        'retention_days': _positive_int(
            config_store.CAPACITY_PROFILER_CFG.get('technical_history_retention_days'),
            DEFAULT_RETENTION_DAYS,
        ),
        'returned_points': len(samples),
        'summary': summary,
        'samples': samples,
    }


def _normalized_since(value) -> str | None:
    if value is None or value == '':
        return None

    candidate = str(value).strip()
    if len(candidate) > 40:
        raise DiagnosticQueryError('Date de début invalide')

    try:
        datetime.fromisoformat(candidate.replace('Z', '+00:00'))
    except ValueError:
        raise DiagnosticQueryError('Date de début invalide') from None

    return candidate


def _bounded_limit(value) -> int:
    try:
        parsed = int(value if value is not None else 720)
    except (TypeError, ValueError):
        raise DiagnosticQueryError('Limite invalide') from None

    if parsed < 1 or parsed > 1440:
        raise DiagnosticQueryError('Limite hors bornes')

    return parsed


def _downsample(samples: list[dict], target: int) -> list[dict]:
    if len(samples) <= target:
        return samples
    if target <= 1:
        return [samples[-1]]

    last_index = len(samples) - 1
    indexes = {
        round(position * last_index / (target - 1))
        for position in range(target)
    }

    return [samples[index] for index in sorted(indexes)]


def _summarize(samples: list[dict]) -> dict:
    scalar_keys = (
        'cpu_total_percent',
        'cpu_core_max_percent',
        'ram_percent',
        'network_tx_mbps',
        'network_rx_mbps',
        'disk_read_kbps',
        'disk_write_kbps',
        'active_instances_count',
        'total_connected_drivers',
    )
    summary = {
        key: _distribution([
            value
            for sample in samples
            if (value := _numeric(sample.get(key))) is not None
        ])
        for key in scalar_keys
    }

    per_core = [
        sample.get('cpu_per_core')
        for sample in samples
        if isinstance(sample.get('cpu_per_core'), list)
    ]
    core_count = max((len(values) for values in per_core), default=0)
    summary['cpu_per_core'] = [
        {
            'core': index + 1,
            **(_distribution([
                value
                for values in per_core
                if index < len(values)
                and (value := _numeric(values[index])) is not None
            ]) or {}),
        }
        for index in range(core_count)
    ]

    return summary


def _distribution(values: list[float]) -> dict | None:
    if not values:
        return None

    return {
        'min': round(min(values), 2),
        'mean': round(sum(values) / len(values), 2),
        'p95': percentile(values, 95),
        'max': round(max(values), 2),
        'latest': round(values[-1], 2),
        'count': len(values),
    }


def _numeric(value) -> float | None:
    if isinstance(value, bool):
        return None

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None

    return parsed


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
