import json
import time
from pathlib import Path

import psutil

from services.process_supervisor import process_supervisor


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


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
        'schema_version': 4,
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
            'command_id': info.get('command_id'),
            'config_loaded_at': info.get('config_loaded_at'),
            'log_path': info.get('log_path'),
            'process_create_time': info.get('process_create_time'),
            'executable_path': info.get('executable_path'),
            'stop_requested_at': info.get('stop_requested_at'),
            'stop_reason': info.get('stop_reason'),
            'game_observation': info.get('game_observation') or {},
            'runtime_policy': info.get('runtime_policy') or {},
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
            ps_process, process_missing = _inspect_process(pid, info, game_cfg)
            if ps_process is None:
                if process_missing:
                    process_supervisor.restore_terminated(
                        instance_id,
                        _missing_process_terminal(instance_id, info),
                    )
                continue

            process = RestoredProcess(pid)
            if process.poll() is not None:
                continue

            process_supervisor.restore_running(instance_id, {
                'process': process,
                'instance': info.get('instance') or {'id': instance_id},
                'started_at': float(info.get('started_at') or time.time()),
                'config': info.get('config'),
                'command_id': info.get('command_id'),
                'config_loaded_at': info.get('config_loaded_at'),
                'log_file': None,
                'log_path': info.get('log_path'),
                'process_create_time': float(ps_process.create_time()),
                'executable_path': _safe_executable_path(ps_process),
                'exit_code_available': False,
                'stop_requested_at': info.get('stop_requested_at'),
                'stop_reason': info.get('stop_reason'),
                'game_observation': info.get('game_observation') or {},
                'runtime_policy': info.get('runtime_policy') or {},
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
    process, _ = _inspect_process(pid, info, game_cfg)
    return process


def _inspect_process(
    pid: int,
    info: dict,
    game_cfg: dict | None,
) -> tuple[psutil.Process | None, bool]:
    """Retourne le processus validé et si sa disparition est certaine."""
    if not psutil.pid_exists(pid):
        return None, True

    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None, True

        saved_create_time = info.get('process_create_time')
        if saved_create_time is not None and abs(float(saved_create_time) - float(process.create_time())) > 1.0:
            return None, True

        expected_executable = str(info.get('executable_path') or '').strip()
        actual_executable = _safe_executable_path(process)
        if expected_executable and actual_executable:
            if Path(expected_executable).resolve() != Path(actual_executable).resolve():
                return None, True
        elif expected_executable:
            return None, False
        elif game_cfg:
            expected_name = str(game_cfg.get('executable_name') or '').strip().lower()
            if expected_name and process.name().strip().lower() != expected_name:
                return None, True
        else:
            return None, False

        return process, False
    except psutil.NoSuchProcess:
        return None, True
    except (psutil.AccessDenied, OSError, ValueError):
        return None, False


def _missing_process_terminal(instance_id: str, info: dict) -> dict:
    observed_at = _utc_now()
    stop_reason = info.get('stop_reason')
    observation = dict(info.get('game_observation') or {})
    if not stop_reason:
        observation['crash_detected_at'] = observation.get('crash_detected_at') or observed_at
        observation['crash_message'] = observation.get('crash_message') or (
            'Processus AC EVO suivi absent au redémarrage de l’agent.'
        )

    return {
        'instance': info.get('instance') or {'id': instance_id, 'name': instance_id},
        'started_at': info.get('started_at'),
        'config': info.get('config'),
        'config_loaded_at': info.get('config_loaded_at'),
        'log_path': info.get('log_path'),
        'process_create_time': info.get('process_create_time'),
        'executable_path': info.get('executable_path'),
        'stop_requested_at': info.get('stop_requested_at'),
        'stop_reason': stop_reason,
        'exit_code': None,
        'exit_observed_at': observed_at,
        'game_observation': observation,
    }


def _safe_executable_path(process: psutil.Process) -> str | None:
    try:
        return str(Path(process.exe()).resolve())
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None
