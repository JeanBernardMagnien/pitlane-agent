import time

import psutil


PROCESS_CPU_SAMPLE_INTERVAL_SECONDS = 0.9


_process_cpu_cache: dict[int, dict] = {}


def _safe_float(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def sample_cpu_percent(pid: int, process: psutil.Process) -> float | None:
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


def cached_process(pid: int) -> psutil.Process | None:
    cached = _process_cpu_cache.get(pid)
    return cached.get('process') if cached else None


def forget(pid: int) -> None:
    _process_cpu_cache.pop(pid, None)
