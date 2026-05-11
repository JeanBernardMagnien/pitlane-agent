import psutil

from core import config_store


def get_system_info() -> dict:
    cpu_cores = psutil.cpu_count(logical=False) or 1
    max_instances = cpu_cores // 2
    return {
        'cpu_cores': cpu_cores,
        'cpu_threads': psutil.cpu_count(logical=True),
        'max_instances': max_instances,
        'current_instances': len(config_store.get_instances()),
    }
