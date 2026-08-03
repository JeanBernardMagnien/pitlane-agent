import threading
from datetime import datetime, timezone


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


class ProcessSupervisor:
    """Conserve l'identité et la dernière observation terminale de chaque processus."""

    def __init__(self):
        self.running: dict[str, dict] = {}
        self.terminated: dict[str, dict] = {}
        self._lock = threading.RLock()

    def register(self, instance_id: str, runtime_info: dict) -> None:
        with self._lock:
            self.terminated.pop(instance_id, None)
            self.running[instance_id] = runtime_info

    def restore_running(self, instance_id: str, runtime_info: dict) -> None:
        with self._lock:
            self.terminated.pop(instance_id, None)
            self.running[instance_id] = runtime_info

    def restore_terminated(self, instance_id: str, terminal_info: dict) -> None:
        with self._lock:
            if instance_id not in self.running:
                self.terminated[instance_id] = terminal_info

    def request_stop(self, instance_id: str, reason: str) -> dict | None:
        with self._lock:
            info = self.running.get(instance_id)
            if info is None:
                return None

            info['stop_requested_at'] = info.get('stop_requested_at') or _utc_now()
            info['stop_reason'] = reason

            return info

    def observe_exit(self, instance_id: str, exit_code: int | None = None) -> dict | None:
        with self._lock:
            info = self.running.get(instance_id)
            if info is None:
                return self.terminated.get(instance_id)

            process = info.get('process')
            if process is None:
                return None

            polled_exit_code = process.poll()
            if polled_exit_code is None:
                return None

            if exit_code is None and info.get('exit_code_available', True):
                try:
                    exit_code = int(polled_exit_code)
                except (TypeError, ValueError):
                    exit_code = None

            log_file = info.get('log_file')
            if log_file is not None and not getattr(log_file, 'closed', True):
                try:
                    log_file.close()
                except OSError:
                    pass

            terminal = {
                'instance': info.get('instance') or {'id': instance_id, 'name': instance_id},
                'started_at': info.get('started_at'),
                'config': info.get('config'),
                'config_loaded_at': info.get('config_loaded_at'),
                'log_path': info.get('log_path'),
                'process_create_time': info.get('process_create_time'),
                'executable_path': info.get('executable_path'),
                'stop_requested_at': info.get('stop_requested_at'),
                'stop_reason': info.get('stop_reason'),
                'exit_code': exit_code,
                'exit_observed_at': _utc_now(),
                'exit_origin': 'process_exit',
                'game_observation': dict(info.get('game_observation') or {}),
            }
            self.terminated[instance_id] = terminal
            self.running.pop(instance_id, None)

            return terminal

    def terminal(self, instance_id: str) -> dict | None:
        with self._lock:
            return self.terminated.get(instance_id)

    def forget(self, instance_id: str) -> bool:
        with self._lock:
            if instance_id in self.running:
                return False

            return self.terminated.pop(instance_id, None) is not None

    def snapshot_running(self) -> list[tuple[str, dict]]:
        with self._lock:
            return list(self.running.items())

    def snapshot_terminated(self) -> list[tuple[str, dict]]:
        with self._lock:
            return list(self.terminated.items())


process_supervisor = ProcessSupervisor()
