import psutil


def get_system_info() -> dict:
    cpu_cores = psutil.cpu_count(logical=False) or 1
    cpu_threads = psutil.cpu_count(logical=True) or cpu_cores
    max_instances = max(1, cpu_cores // 2)

    memory = psutil.virtual_memory()

    try:
        from services.server_manager import _running
        current_instances = sum(
            1 for info in _running.values()
            if info.get('process') and info['process'].poll() is None
        )
    except Exception:
        current_instances = 0

    return {
        'cpu_cores': cpu_cores,
        'cpu_threads': cpu_threads,
        'cpu_percent': psutil.cpu_percent(interval=None),
        'max_instances': max_instances,
        'current_instances': current_instances,
        'ram_total_gb': round(memory.total / 1024 / 1024 / 1024, 2),
        'ram_used_gb': round(memory.used / 1024 / 1024 / 1024, 2),
        'ram_percent': memory.percent,
    }
