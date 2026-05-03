import subprocess
import psutil
import time
from pathlib import Path
import os

# Dictionnaire en mémoire : { instance_id → { process, started_at, config } }
_running = {}

def start_instance(instance_cfg: dict, game_cfg: dict, serverconfig_b64: str, seasondefinition_b64: str) -> dict:
    instance_id = instance_cfg['id']

    if instance_id in _running:
        if _running[instance_id]['process'].poll() is None:
            return {'error': f"Instance {instance_id} déjà en cours d'exécution"}

    exe_path = Path(game_cfg['install_path']) / game_cfg['executable_name']
    log_path = Path(game_cfg['install_path']) / f"debug_{instance_id}.txt"

    args = [
        str(exe_path),
        '-serverconfig', serverconfig_b64,
        '-seasondefinition', seasondefinition_b64,
    ]

    with open(log_path, 'w') as log_file:
        process = subprocess.Popen(
            args,
            cwd=game_cfg['install_path'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    _running[instance_id] = {
        'process': process,
        'started_at': time.time(),
        'config': None,
    }

    return {'status': 'started', 'pid': process.pid}


def stop_instance(instance_id: str) -> dict:
    """Arrête proprement une instance."""
    if instance_id not in _running:
        return {'error': f"Instance {instance_id} non trouvée"}

    proc = _running[instance_id]['process']

    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    del _running[instance_id]
    return {'status': 'stopped'}


def restart_instance(instance_id: str, instance_cfg: dict, game_cfg: dict, serverconfig_b64: str, seasondefinition_b64: str) -> dict:
    """Stop + Start."""
    stop_instance(instance_id)
    time.sleep(2)
    return start_instance(instance_cfg, game_cfg, serverconfig_b64, seasondefinition_b64)


def get_instance_status(instance_cfg: dict) -> dict:
    """Retourne le statut complet d'une instance."""
    instance_id = instance_cfg['id']
    info = _running.get(instance_id)

    if not info or info['process'].poll() is not None:
        if instance_id in _running:
            del _running[instance_id]
        return {
            'id': instance_id,
            'name': instance_cfg['name'],
            'status': 'offline',
            'pid': None,
            'uptime_seconds': None,
            'ram_mb': None,
            'active_config': None,
        }

    pid = info['process'].pid
    uptime = int(time.time() - info['started_at'])

    try:
        ps_proc = psutil.Process(pid)
        ram_mb = round(ps_proc.memory_info().rss / 1024 / 1024, 1)
    except psutil.NoSuchProcess:
        ram_mb = None

    return {
        'id': instance_id,
        'name': instance_cfg['name'],
        'status': 'online',
        'pid': pid,
        'uptime_seconds': uptime,
        'ram_mb': ram_mb,
        'active_config': info.get('config'),
    }


def list_configs(configs_path: str) -> list:
    """Liste les fichiers .json dans le dossier configs."""
    path = Path(configs_path)
    if not path.exists():
        return []
    return [f.name for f in path.glob('*.json')]