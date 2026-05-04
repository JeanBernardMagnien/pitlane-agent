import subprocess
import psutil
import time
import urllib.request
import urllib.error
import json as _json
from pathlib import Path
from datetime import datetime, timezone

# { instance_id → { process, started_at, config, config_loaded_at } }
_running = {}

# Survit au stop/crash — garde la dernière config connue par instance
# { instance_id → { config, config_loaded_at } }
_last_config = {}


def _get_connected_drivers(http_port: int) -> int | None:
    """Interroge l'API HTTP d'AC EVO pour compter les pilotes connectés."""
    try:
        url = f"http://127.0.0.1:{http_port}/api/details"
        with urllib.request.urlopen(url, timeout=1) as resp:
            data = _json.loads(resp.read())
            cars = data.get('cars', [])
            return sum(1 for c in cars if c.get('isConnected', False))
    except Exception:
        return None


def start_instance(instance_cfg, game_cfg, serverconfig_b64, seasondefinition_b64, filename=None):
    instance_id = instance_cfg['id']

    if instance_id in _running:
        if _running[instance_id]['process'].poll() is None:
            return {'error': f"Instance {instance_id} déjà en cours d'exécution"}

    exe_path = Path(game_cfg['install_path']) / game_cfg['executable_name']

    args = [
        str(exe_path),
        '-serverconfig', serverconfig_b64,
        '-seasondefinition', seasondefinition_b64,
    ]

    process = subprocess.Popen(
        args,
        cwd=game_cfg['install_path'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    _running[instance_id] = {
        'process': process,
        'started_at': time.time(),
        'config': filename,
        'config_loaded_at': now,
    }
    # Mémorise aussi dans _last_config si on a un filename
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

    # Sauvegarde la config avant suppression
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

    del _running[instance_id]
    return {'status': 'stopped'}


def restart_instance(instance_id: str, instance_cfg: dict, game_cfg: dict,
                     serverconfig_b64: str, seasondefinition_b64: str,
                     filename: str | None = None) -> dict:
    """Stop + Start en conservant le filename."""
    stop_instance(instance_id)
    time.sleep(2)
    return start_instance(instance_cfg, game_cfg, serverconfig_b64, seasondefinition_b64, filename=filename)


def get_last_config(instance_id: str) -> dict:
    """Retourne la dernière config connue pour une instance (même après stop)."""
    return _last_config.get(instance_id, {})


def get_instance_status(instance_cfg: dict) -> dict:
    """Retourne le statut complet d'une instance."""
    instance_id = instance_cfg['id']
    info = _running.get(instance_id)
    http_port = instance_cfg.get('http_port')

    if not info or info['process'].poll() is not None:
        # Nettoyage si le process est mort
        if instance_id in _running:
            dead_info = _running.pop(instance_id)
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
    }


def list_configs(configs_path: str) -> list:
    """Liste les fichiers .json dans le dossier configs."""
    path = Path(configs_path)
    if not path.exists():
        return []
    return [f.name for f in path.glob('*.json')]