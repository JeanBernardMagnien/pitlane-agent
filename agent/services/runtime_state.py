import json
import time
from pathlib import Path

import psutil

from services.server_manager import _running


class RestoredProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self._process = psutil.Process(pid)

    def poll(self):
        try:
            return None if self._process.is_running() and self._process.status() != psutil.STATUS_ZOMBIE else 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 1

    def terminate(self):
        self._process.terminate()

    def wait(self, timeout=None):
        return self._process.wait(timeout=timeout)

    def kill(self):
        self._process.kill()


def runtime_state_path(logging_cfg: dict) -> Path:
    logs_path = Path(logging_cfg.get('logs_path') or 'logs')
    logs_path.mkdir(parents=True, exist_ok=True)
    return logs_path / 'runtime_state.json'


def save_runtime_state(logging_cfg: dict) -> None:
    path = runtime_state_path(logging_cfg)
    payload = {}

    for instance_id, info in list(_running.items()):
        proc = info.get('process')
        instance = info.get('instance') or {}

        if not proc or proc.poll() is not None:
            continue

        payload[instance_id] = {
            'pid': proc.pid,
            'instance': instance,
            'started_at': info.get('started_at') or time.time(),
            'config': info.get('config'),
            'config_loaded_at': info.get('config_loaded_at'),
            'log_path': info.get('log_path'),
        }

    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def restore_runtime_state(logging_cfg: dict) -> int:
    path = runtime_state_path(logging_cfg)

    if not path.exists():
        return 0

    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return 0

    restored = 0

    for instance_id, info in payload.items():
        try:
            pid = int(info.get('pid'))
            if not psutil.pid_exists(pid):
                continue

            process = RestoredProcess(pid)
            if process.poll() is not None:
                continue

            _running[instance_id] = {
                'process': process,
                'instance': info.get('instance') or {'id': instance_id},
                'started_at': float(info.get('started_at') or time.time()),
                'config': info.get('config'),
                'config_loaded_at': info.get('config_loaded_at'),
                'log_file': None,
                'log_path': info.get('log_path'),
            }
            restored += 1
        except Exception:
            continue

    save_runtime_state(logging_cfg)
    return restored
