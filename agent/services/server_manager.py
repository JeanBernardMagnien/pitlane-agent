import subprocess
import psutil
import time
import threading
import urllib.request
import json as _json
from pathlib import Path
from datetime import datetime, timezone

from services.process_supervisor import process_supervisor
from services.server_process_command import build_process_args

# { instance_id → { process, instance, started_at, config, config_loaded_at, log_file } }
_running = process_supervisor.running

# Survit au stop/crash — garde la dernière config connue par instance
# { instance_id → { config, config_loaded_at } }
_last_config = {}
_instance_stop_locks: dict[str, threading.RLock] = {}
_instance_stop_locks_guard = threading.Lock()


def _instance_stop_lock(instance_id: str) -> threading.RLock:
    with _instance_stop_locks_guard:
        return _instance_stop_locks.setdefault(instance_id, threading.RLock())


def _get_connected_drivers(http_port: int) -> int | None:
    """
    Interroge l'API HTTP d'AC EVO pour compter les pilotes connectés.
    AC EVO expose GET / sur http_port et retourne {"clients": N, "version": X, "protocol": Y}.
    """
    try:
        url = f"http://127.0.0.1:{http_port}/"
        req = urllib.request.Request(url, headers={'User-Agent': 'PitLane/1.0'})
        with urllib.request.urlopen(req, timeout=1) as resp:
            data = _json.loads(resp.read())
            return data.get('clients', None)
    except Exception:
        return None


def _open_log_file(instance_id: str, logs_path: str):
    """Ouvre le fichier de log pour une instance avec un timestamp de démarrage."""
    logs_dir = Path(logs_path)
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = logs_dir / f"log_{instance_id}_{timestamp}.log"

    return open(log_path, 'a', encoding='utf-8')


def _save_runtime_state_safe(logging_cfg: dict):
    try:
        from services.runtime_state import save_runtime_state
        save_runtime_state(logging_cfg)
    except Exception as exc:
        print(f"[runtime-state] Erreur sauvegarde : {exc}")


def get_runtime_instances() -> list[dict]:
    """Retourne les instances connues en mémoire par l'agent runtime."""
    return [info['instance'] for info in _running.values() if info.get('instance')]


def already_executed_command(instance_id: str, command_id: str | None) -> dict | None:
    if not command_id:
        return None

    info = _running.get(instance_id)
    if (
        not info
        or info.get('command_id') != command_id
        or info['process'].poll() is not None
    ):
        return None

    return {
        'status': 'started',
        'pid': info['process'].pid,
        'already_executed': True,
    }


def _process_identity(process, exe_path: Path) -> tuple[float | None, str]:
    try:
        ps_process = psutil.Process(process.pid)
        return float(ps_process.create_time()), str(Path(ps_process.exe()).resolve())
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return None, str(exe_path.resolve())


def _observe_game_log(instance_id: str, info: dict, logging_cfg: dict | None) -> None:
    if not logging_cfg:
        return

    from services.player_count_observer import observe_player_count

    info['game_observation'] = observe_player_count(
        instance_id,
        info,
        logging_cfg.get('logs_path') or 'logs',
    )


def start_instance(
    instance_cfg,
    game_cfg,
    logging_cfg,
    serverconfig_b64,
    seasondefinition_b64,
    filename=None,
    command_id=None,
    runtime_policy=None,
):
    instance_id = instance_cfg['id']

    if instance_id in _running:
        if _running[instance_id]['process'].poll() is None:
            return {'error': f"Instance {instance_id} déjà en cours d'exécution"}

    exe_path = Path(game_cfg['install_path']) / game_cfg['executable_name']
    log_file = _open_log_file(instance_id, logging_cfg['logs_path'])
    args = build_process_args(exe_path, game_cfg, serverconfig_b64, seasondefinition_b64)

    process = subprocess.Popen(
        args,
        cwd=game_cfg['install_path'],
        stdout=log_file,
        stderr=log_file,
    )
    process_create_time, executable_path = _process_identity(process, exe_path)

    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    runtime_info = {
        'process': process,
        'instance': instance_cfg,
        'started_at': time.time(),
        'config': filename,
        'command_id': command_id,
        'config_loaded_at': now,
        'log_file': log_file,
        'log_path': log_file.name,
        'process_create_time': process_create_time,
        'executable_path': executable_path,
        'exit_code_available': True,
        'stop_requested_at': None,
        'stop_reason': None,
        'game_observation': {},
        'runtime_policy': dict(runtime_policy or {}),
    }
    process_supervisor.register(instance_id, runtime_info)
    if filename:
        _last_config[instance_id] = {
            'config': filename,
            'config_loaded_at': now,
        }

    _save_runtime_state_safe(logging_cfg)

    return {'status': 'started', 'pid': process.pid}


def stop_instance(
    instance_id: str,
    logging_cfg: dict | None = None,
    reason: str = 'manual_stop',
) -> dict:
    """Arrête proprement une instance. La dernière config reste dans _last_config."""
    with _instance_stop_lock(instance_id):
        return _stop_instance_locked(instance_id, logging_cfg, reason)


def _stop_instance_locked(
    instance_id: str,
    logging_cfg: dict | None,
    reason: str,
) -> dict:
    if instance_id not in _running:
        terminal = process_supervisor.terminal(instance_id)
        # Stop est une commande idempotente : si le premier accusé s'est perdu après la
        # disparition du processus, le retry du hub doit pouvoir converger vers le même état.
        return {
            'status': 'stopped',
            'already_stopped': True,
            **terminal_process_payload(terminal),
        }

    info = _running[instance_id]
    if info.get('config'):
        _last_config[instance_id] = {
            'config': info['config'],
            'config_loaded_at': info.get('config_loaded_at'),
        }

    proc = info['process']
    _observe_game_log(instance_id, info, logging_cfg)
    process_supervisor.request_stop(instance_id, reason)
    if logging_cfg:
        _save_runtime_state_safe(logging_cfg)

    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)

    _observe_game_log(instance_id, info, logging_cfg)
    terminal = process_supervisor.observe_exit(instance_id)

    from services.player_count_observer import forget_player_count
    forget_player_count(instance_id)

    if logging_cfg:
        _save_runtime_state_safe(logging_cfg)

    return {
        'status': 'stopped',
        **terminal_process_payload(terminal),
    }


def restart_instance(instance_id: str, instance_cfg: dict, game_cfg: dict,
                     logging_cfg: dict, serverconfig_b64: str,
                     seasondefinition_b64: str, filename: str | None = None,
                     before_start=None, command_id: str | None = None,
                     runtime_policy: dict | None = None) -> dict:
    """Stop + Start en conservant le filename."""
    stop_instance(instance_id, logging_cfg, reason='preempted')
    if before_start:
        before_start()
    time.sleep(2)
    return start_instance(
        instance_cfg,
        game_cfg,
        logging_cfg,
        serverconfig_b64,
        seasondefinition_b64,
        filename=filename,
        command_id=command_id,
        runtime_policy=runtime_policy,
    )


def get_last_config(instance_id: str) -> dict:
    """Retourne la dernière config connue pour une instance (même après stop)."""
    if instance_id in _last_config:
        return _last_config[instance_id]

    terminal = process_supervisor.terminal(instance_id) or {}
    if terminal.get('config'):
        return {
            'config': terminal.get('config'),
            'config_loaded_at': terminal.get('config_loaded_at'),
        }

    return {}


def forget_instance_runtime(instance_id: str, logging_cfg: dict | None = None) -> bool:
    info = _running.get(instance_id)
    if info is not None:
        if info['process'].poll() is None:
            return False
        process_supervisor.observe_exit(instance_id)

    _last_config.pop(instance_id, None)
    process_supervisor.forget(instance_id)

    from services.player_count_observer import forget_player_count
    forget_player_count(instance_id)

    if logging_cfg:
        _save_runtime_state_safe(logging_cfg)

    return True


def get_instance_status(instance_cfg: dict) -> dict:
    """Retourne le statut complet d'une instance."""
    instance_id = instance_cfg['id']
    info = _running.get(instance_id)
    http_port = instance_cfg.get('http_port')

    if not info or info['process'].poll() is not None:
        if info:
            _observe_game_log(instance_id, info, None)
            if info.get('config'):
                _last_config[instance_id] = {
                    'config': info['config'],
                    'config_loaded_at': info.get('config_loaded_at'),
                }
            process_supervisor.observe_exit(instance_id)

        last = get_last_config(instance_id)
        return {
            'id': instance_id,
            'name': instance_cfg['name'],
            'status': 'offline',
            'pid': None,
            'uptime_seconds': None,
            'started_at': None,
            'ram_mb': None,
            'connected_drivers': None,
            'active_config': last.get('config'),
            'active_config_loaded_at': last.get('config_loaded_at'),
            'tcp_port': instance_cfg.get('tcp_port'),
            'http_port': instance_cfg.get('http_port'),
            **terminal_process_payload(process_supervisor.terminal(instance_id)),
        }

    pid = info['process'].pid
    uptime = int(time.time() - info['started_at'])

    try:
        ps_proc = psutil.Process(pid)
        ram_mb = round(ps_proc.memory_info().private / 1024 / 1024, 1)
    except psutil.NoSuchProcess:
        ram_mb = None

    connected_drivers = _get_connected_drivers(http_port) if http_port else None

    return {
        'id': instance_id,
        'name': instance_cfg['name'],
        'status': 'online',
        'pid': pid,
        'uptime_seconds': uptime,
        'started_at': datetime.fromtimestamp(info['started_at'], tz=timezone.utc).isoformat().replace('+00:00', 'Z'),
        'ram_mb': ram_mb,
        'connected_drivers': connected_drivers,
        'active_config': info.get('config'),
        'active_config_loaded_at': info.get('config_loaded_at'),
        'tcp_port': instance_cfg.get('tcp_port'),
        'http_port': instance_cfg.get('http_port'),
    }


def list_configs(configs_path: str) -> list:
    """Liste les fichiers .json dans le dossier configs."""
    path = Path(configs_path)
    if not path.exists():
        return []
    return [f.name for f in path.glob('*.json')]


def terminal_process_payload(terminal: dict | None) -> dict:
    if not terminal:
        return {}

    observation = terminal.get('game_observation') or {}

    return {
        'exit_code': terminal.get('exit_code'),
        'exit_observed_at': terminal.get('exit_observed_at'),
        'exit_origin': terminal.get('exit_origin'),
        'stop_requested_at': terminal.get('stop_requested_at'),
        'stop_reason': terminal.get('stop_reason'),
        'crash_detected_at': observation.get('crash_detected_at'),
        'crash_message': observation.get('crash_message'),
        'session_phase': observation.get('session_phase'),
        'session_observed_at': observation.get('session_observed_at'),
        'sport_started_at': observation.get('sport_started_at'),
        'race_started_at': observation.get('race_started_at'),
        'season_restart_count': int(observation.get('season_restart_count') or 0),
        'season_restart_observed_at': observation.get('season_restart_observed_at'),
        'first_driver_seen_at': observation.get('first_driver_seen_at'),
        'log_observed_from_start': bool(observation.get('log_observed_from_start')),
    }
