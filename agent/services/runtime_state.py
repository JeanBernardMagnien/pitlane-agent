import json
import time
from pathlib import Path

import psutil

from services.process_supervisor import process_supervisor


class RestoredProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self._process = psutil.Process(pid)

    def poll(self):
        try:
            return None if self._process.is_running() and self._process.status() != psutil.STATUS_ZOMBIE else -1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return -1

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
    payload = {
        'schema_version': 2,
        'running': {},
        'terminated': {},
    }

    for instance_id, info in process_supervisor.snapshot_running():
        proc = info.get('process')
        instance = info.get('instance') or {}

        if not proc or proc.poll() is not None:
            continue

        payload['running'][instance_id] = {
            'pid': proc.pid,
            'instance': instance,
            'started_at': info.get('started_at') or time.time(),
            'config': info.get('config'),
            'config_loaded_at': info.get('config_loaded_at'),
            'log_path': info.get('log_path'),
            'process_create_time': info.get('process_create_time'),
            'executable_path': info.get('executable_path'),
            'stop_requested_at': info.get('stop_requested_at'),
            'stop_reason': info.get('stop_reason'),
            'game_observation': info.get('game_observation') or {},
        }

    for instance_id, terminal in process_supervisor.snapshot_terminated():
        payload['terminated'][instance_id] = terminal

    temporary_path = path.with_suffix(path.suffix + '.tmp')
    temporary_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    temporary_path.replace(path)


def restore_runtime_state(logging_cfg: dict, game_cfg: dict | None = None) -> int:
    path = runtime_state_path(logging_cfg)

    if not path.exists():
        return 0

    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return 0

    if not isinstance(payload, dict):
        return 0

    if int(payload.get('schema_version') or 1) >= 2:
        running_payload = payload.get('running') if isinstance(payload.get('running'), dict) else {}
        terminated_payload = payload.get('terminated') if isinstance(payload.get('terminated'), dict) else {}
    else:
        running_payload = payload
        terminated_payload = {}

    restored = 0

    for instance_id, info in running_payload.items():
        try:
            pid = int(info.get('pid'))
            ps_process = _validated_process(pid, info, game_cfg)
            if ps_process is None:
                continue

            process = RestoredProcess(pid)
            if process.poll() is not None:
                continue

            process_supervisor.restore_running(instance_id, {
                'process': process,
                'instance': info.get('instance') or {'id': instance_id},
                'started_at': float(info.get('started_at') or time.time()),
                'config': info.get('config'),
                'config_loaded_at': info.get('config_loaded_at'),
                'log_file': None,
                'log_path': info.get('log_path'),
                'process_create_time': float(ps_process.create_time()),
                'executable_path': _safe_executable_path(ps_process),
                'exit_code_available': False,
                'stop_requested_at': info.get('stop_requested_at'),
                'stop_reason': info.get('stop_reason'),
                'game_observation': info.get('game_observation') or {},
            })
            restored += 1
        except Exception:
            continue

    for instance_id, terminal in terminated_payload.items():
        if isinstance(terminal, dict):
            process_supervisor.restore_terminated(instance_id, terminal)

    save_runtime_state(logging_cfg)
    return restored


def _validated_process(pid: int, info: dict, game_cfg: dict | None) -> psutil.Process | None:
    if not psutil.pid_exists(pid):
        return None

    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None

        saved_create_time = info.get('process_create_time')
        if saved_create_time is not None and abs(float(saved_create_time) - float(process.create_time())) > 1.0:
            return None

        expected_executable = str(info.get('executable_path') or '').strip()
        actual_executable = _safe_executable_path(process)
        if expected_executable and actual_executable:
            if Path(expected_executable).resolve() != Path(actual_executable).resolve():
                return None
        elif game_cfg:
            expected_name = str(game_cfg.get('executable_name') or '').strip().lower()
            if expected_name and process.name().strip().lower() != expected_name:
                return None
        else:
            return None

        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, ValueError):
        return None


def _safe_executable_path(process: psutil.Process) -> str | None:
    try:
        return str(Path(process.exe()).resolve())
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None
