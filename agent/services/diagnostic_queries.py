from datetime import datetime

from core import config_store
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
    samples = _downsample(samples, MAX_RESPONSE_POINTS)

    return {
        'schema_version': 1,
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
