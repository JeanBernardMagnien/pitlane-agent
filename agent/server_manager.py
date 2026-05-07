import subprocess
import psutil
import time
import urllib.request
import urllib.error
import json as _json
from pathlib import Path
from datetime import datetime, timezone

# { instance_id → { process, started_at, config, config_loaded_at, log_file } }
_running = {}

# Survit au stop/crash — garde la dernière config connue par instance
# { instance_id → { config, config_loaded_at } }
_last_config = {}


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


def start_instance(instance_cfg, game_cfg, logging_cfg, serverconfig_b64, seasondefinition_b64, filename=None):
    instance_id = instance_cfg['id']

    if instance_id in _running:
        if _running[instance_id]['process'].poll() is None:
            return {'error': f"Instance {instance_id} déjà en cours d'exécution"}

    exe_path = Path(game_cfg['install_path']) / game_cfg['executable_name']
    log_file = _open_log_file(instance_id, logging_cfg['logs_path'])

    args = [
        str(exe_path),
        '-serverconfig', serverconfig_b64,
        '-seasondefinition', seasondefinition_b64,
    ]

    process = subprocess.Popen(
        args,
        cwd=game_cfg['install_path'],
        stdout=log_file,
        stderr=log_file,
    )

    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    _running[instance_id] = {
        'process': process,
        'started_at': time.time(),
        'config': filename,
        'config_loaded_at': now,
        'log_file': log_file,
    }
    if filename:
        _last_config[instance_id] = {
            'config': filename,
            'config_loaded_at': now,
        }

    return {'status': 'started', 'pid': process.pid}


def stop_instance(instance_id: str) -> dict:
    """Arrête proprement une instance. La dernière config reste dans _last_config."""
    if instance_id not in _running:
        return {'error': f"Instance {instance_id} non trouvée"}

    info = _running[instance_id]
    if info.get('config'):
        _last_config[instance_id] = {
            'config': info['config'],
            'config_loaded_at': info.get('config_loaded_at'),
        }

    proc = info['process']
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    if info.get('log_file'):
        info['log_file'].close()

    del _running[instance_id]
    return {'status': 'stopped'}


def restart_instance(instance_id: str, instance_cfg: dict, game_cfg: dict,
                     logging_cfg: dict, serverconfig_b64: str,
                     seasondefinition_b64: str, filename: str | None = None) -> dict:
    """Stop + Start en conservant le filename."""
    stop_instance(instance_id)
    time.sleep(2)
    return start_instance(instance_cfg, game_cfg, logging_cfg, serverconfig_b64, seasondefinition_b64, filename=filename)


def get_last_config(instance_id: str) -> dict:
    """Retourne la dernière config connue pour une instance (même après stop)."""
    return _last_config.get(instance_id, {})


def get_instance_status(instance_cfg: dict) -> dict:
    """Retourne le statut complet d'une instance."""
    instance_id = instance_cfg['id']
    info = _running.get(instance_id)
    http_port = instance_cfg.get('http_port')

    if not info or info['process'].poll() is not None:
        if instance_id in _running:
            dead_info = _running.pop(instance_id)
            if dead_info.get('log_file'):
                dead_info['log_file'].close()
            if dead_info.get('config'):
                _last_config[instance_id] = {
                    'config': dead_info['config'],
                    'config_loaded_at': dead_info.get('config_loaded_at'),
                }

        last = _last_config.get(instance_id, {})
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
        }

    pid = info['process'].pid
    uptime = int(time.time() - info['started_at'])

    try:
        ps_proc = psutil.Process(pid)
        ram_mb = round(ps_proc.memory_info().wset / 1024 / 1024, 1)
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
