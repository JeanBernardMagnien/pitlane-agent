import yaml
import json
import jwt as pyjwt
import threading
import os
import psutil as _psutil
from pathlib import Path
from flask import Flask, jsonify, request, abort
from server_manager import (
    start_instance, stop_instance, restart_instance,
    get_instance_status, get_last_config, list_configs, _running
)
from encode_config import encode_file
from flask_sock import Sock
from log_streamer import tail_log
from datetime import datetime, timezone

# ─── Chargement config ────────────────────────────────────────────────────────

CONFIG_PATH = Path('config.yml')

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def save_config(cfg: dict):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

CFG = load_config()
GAME_CFG  = CFG['game']
AUTH_CFG  = CFG['auth']
HTTP_CFG  = CFG['http']
INSTANCES = {inst['id']: inst for inst in CFG['instances']}

_config_lock = threading.Lock()
_config_mtime = CONFIG_PATH.stat().st_mtime

def _watch_config():
    """Thread de surveillance — recharge config.yml si modifié."""
    global CFG, GAME_CFG, AUTH_CFG, HTTP_CFG, INSTANCES, _config_mtime
    while True:
        threading.Event().wait(1)
        try:
            mtime = CONFIG_PATH.stat().st_mtime
            if mtime != _config_mtime:
                new_cfg = load_config()
                with _config_lock:
                    CFG        = new_cfg
                    GAME_CFG   = new_cfg['game']
                    AUTH_CFG   = new_cfg['auth']
                    HTTP_CFG   = new_cfg['http']
                    INSTANCES  = {inst['id']: inst for inst in new_cfg['instances']}
                    _config_mtime = mtime
                print(f"[config] Rechargé — {len(INSTANCES)} instance(s)")
        except Exception as e:
            print(f"[config] Erreur rechargement : {e}")

_watcher = threading.Thread(target=_watch_config, daemon=True)
_watcher.start()

# ─── Infos système ────────────────────────────────────────────────────────────

def get_system_info() -> dict:
    cpu_cores = _psutil.cpu_count(logical=False) or 1
    max_instances = cpu_cores // 2
    return {
        'cpu_cores': cpu_cores,
        'cpu_threads': _psutil.cpu_count(logical=True),
        'max_instances': max_instances,
        'current_instances': len(INSTANCES),
    }

# ─── Flask ────────────────────────────────────────────────────────────────────

app = Flask(__name__)
sock = Sock(app)

# ─── WebSocket Logs ───────────────────────────────────────────────────────────

@sock.route('/api/instances/<instance_id>/logs/stream')
def logs_stream(ws, instance_id):
    with _config_lock:
        known = instance_id in INSTANCES
    if not known:
        ws.send('{"error": "Instance introuvable"}')
        return
    log_file = CFG['logging']['log_file']
    max_lines = CFG['logging'].get('max_lines', 500)
    try:
        tail_log(ws, log_file, max_lines)
    except Exception:
        pass

# ─── Auth JWT ─────────────────────────────────────────────────────────────────

def require_jwt():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        abort(401, 'Token manquant')
    token = auth_header[7:]
    try:
        pyjwt.decode(
            token,
            AUTH_CFG['jwt_secret'],
            algorithms=[AUTH_CFG['jwt_algorithm']],
            leeway=30
        )
    except pyjwt.ExpiredSignatureError:
        abort(401, 'Token expiré')
    except pyjwt.InvalidTokenError:
        abort(401, 'Token invalide')

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_instance_or_404(instance_id: str) -> dict:
    with _config_lock:
        inst = INSTANCES.get(instance_id)
    if not inst:
        abort(404, f"Instance '{instance_id}' introuvable dans config.yml")
    return inst

def error(msg: str, code: int = 400):
    return jsonify({'error': msg}), code

def resolve_filename(instance_id: str, body: dict) -> str | None:
    filename = body.get('filename')
    if filename:
        return filename
    last = get_last_config(instance_id)
    return last.get('config')

# ─── Système ──────────────────────────────────────────────────────────────────

@app.route('/api/system', methods=['GET'])
def system_info():
    require_jwt()
    return jsonify(get_system_info())

# ─── Instances — CRUD ─────────────────────────────────────────────────────────

@app.route('/api/instances', methods=['GET'])
def list_instances():
    require_jwt()
    with _config_lock:
        insts = list(INSTANCES.values())
    statuses = [get_instance_status(inst) for inst in insts]
    return jsonify(statuses)

@app.route('/api/instances', methods=['POST'])
def create_instance():
    require_jwt()
    body = request.get_json(silent=True) or {}

    # Validation
    required = ['id', 'name', 'tcp_port', 'udp_port', 'http_port']
    for field in required:
        if not body.get(field):
            return error(f"Champ '{field}' requis")

    info = get_system_info()
    if info['current_instances'] >= info['max_instances']:
        return error(
            f"Limite atteinte : {info['max_instances']} instance(s) max "
            f"pour {info['cpu_cores']} cœurs physiques", 403
        )

    instance_id = str(body['id']).strip()
    with _config_lock:
        if instance_id in INSTANCES:
            return error(f"Instance '{instance_id}' existe déjà")

    # Vérif unicité des ports
    new_ports = {int(body['tcp_port']), int(body['udp_port']), int(body['http_port'])}
    with _config_lock:
        for inst in INSTANCES.values():
            existing_ports = {inst.get('tcp_port'), inst.get('udp_port'), inst.get('http_port')}
            conflict = new_ports & existing_ports
            if conflict:
                return error(f"Port(s) déjà utilisé(s) : {', '.join(str(p) for p in conflict)}")

    new_inst = {
        'id':        instance_id,
        'name':      str(body['name']).strip(),
        'tcp_port':  int(body['tcp_port']),
        'udp_port':  int(body['udp_port']),
        'http_port': int(body['http_port']),
    }

    # Écriture dans config.yml → le watcher rechargera automatiquement
    cfg = load_config()
    cfg['instances'].append(new_inst)
    save_config(cfg)

    # Rechargement immédiat sans attendre le watcher
    global _config_mtime
    with _config_lock:
        INSTANCES[instance_id] = new_inst
        _config_mtime = CONFIG_PATH.stat().st_mtime

    return jsonify(new_inst), 201


@app.route('/api/instances/<instance_id>', methods=['DELETE'])
def delete_instance(instance_id):
    require_jwt()
    with _config_lock:
        if instance_id not in INSTANCES:
            return error(f"Instance '{instance_id}' introuvable", 404)

    # Impossible de supprimer une instance en cours
    if instance_id in _running and _running[instance_id]['process'].poll() is None:
        return error("Arrêtez l'instance avant de la supprimer", 409)

    cfg = load_config()
    cfg['instances'] = [i for i in cfg['instances'] if i['id'] != instance_id]
    save_config(cfg)

    global _config_mtime
    with _config_lock:
        INSTANCES.pop(instance_id, None)
        _config_mtime = CONFIG_PATH.stat().st_mtime

    return jsonify({'deleted': instance_id})

# ─── Instances — Actions ──────────────────────────────────────────────────────

@app.route('/api/instances/<instance_id>/status', methods=['GET'])
def instance_status(instance_id):
    require_jwt()
    inst = get_instance_or_404(instance_id)
    return jsonify(get_instance_status(inst))


@app.route('/api/instances/<instance_id>/start', methods=['POST'])
def instance_start(instance_id):
    require_jwt()
    inst = get_instance_or_404(instance_id)

    body = request.get_json(silent=True) or {}
    filename = resolve_filename(instance_id, body)
    if not filename:
        return error("Aucune config disponible — chargez d'abord une config via \"Charger\"")

    config_path = Path(GAME_CFG['configs_path']) / Path(filename).name
    if not config_path.exists():
        return error(f"Config '{filename}' introuvable", 404)

    try:
        serverconfig_b64, seasondefinition_b64 = encode_file(str(config_path))
    except Exception as e:
        return error(f"Erreur encodage config : {e}")

    result = start_instance(inst, GAME_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
    if 'error' in result:
        return jsonify(result), 409
    return jsonify(result)


@app.route('/api/instances/<instance_id>/stop', methods=['POST'])
def instance_stop(instance_id):
    require_jwt()
    get_instance_or_404(instance_id)
    result = stop_instance(instance_id)
    if 'error' in result:
        return jsonify(result), 409
    return jsonify(result)


@app.route('/api/instances/<instance_id>/restart', methods=['POST'])
def instance_restart(instance_id):
    require_jwt()
    inst = get_instance_or_404(instance_id)

    body = request.get_json(silent=True) or {}
    filename = resolve_filename(instance_id, body)
    if not filename:
        return error("Aucune config disponible — chargez d'abord une config via \"Charger\"")

    config_path = Path(GAME_CFG['configs_path']) / Path(filename).name
    if not config_path.exists():
        return error(f"Config '{filename}' introuvable", 404)

    try:
        serverconfig_b64, seasondefinition_b64 = encode_file(str(config_path))
    except Exception as e:
        return error(f"Erreur encodage config : {e}")

    result = restart_instance(instance_id, inst, GAME_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
    return jsonify(result)

# ─── Configs ──────────────────────────────────────────────────────────────────

@app.route('/api/configs', methods=['GET'])
def configs_list():
    require_jwt()
    return jsonify(list_configs(GAME_CFG['configs_path']))


@app.route('/api/configs', methods=['POST'])
def config_create():
    require_jwt()
    body = request.get_json(silent=True)
    if not body or 'filename' not in body or 'content' not in body:
        return error('filename et content requis')

    filename = Path(body['filename']).name
    if not filename.endswith('.json'):
        return error('Le fichier doit être un .json')

    dest = Path(GAME_CFG['configs_path']) / filename
    if dest.exists():
        return error(f"'{filename}' existe déjà — utilisez PUT pour modifier")

    dest.write_text(json.dumps(body['content'], indent=2), encoding='utf-8')
    return jsonify({'created': filename}), 201


@app.route('/api/configs/<filename>', methods=['PUT'])
def config_update(filename):
    require_jwt()
    body = request.get_json(silent=True)
    if not body or 'content' not in body:
        return error('content requis')

    safe_name = Path(filename).name
    dest = Path(GAME_CFG['configs_path']) / safe_name
    if not dest.exists():
        return error(f"'{safe_name}' introuvable"), 404

    dest.write_text(json.dumps(body['content'], indent=2), encoding='utf-8')
    return jsonify({'updated': safe_name})


@app.route('/api/configs/<filename>', methods=['DELETE'])
def config_delete(filename):
    require_jwt()
    safe_name = Path(filename).name
    dest = Path(GAME_CFG['configs_path']) / safe_name
    if not dest.exists():
        return error(f"'{safe_name}' introuvable"), 404

    dest.unlink()
    return jsonify({'deleted': safe_name})


@app.route('/api/instances/<instance_id>/switch', methods=['POST'])
def instance_switch(instance_id):
    require_jwt()
    inst = get_instance_or_404(instance_id)

    body = request.get_json(silent=True) or {}
    filename = body.get('filename')
    if not filename:
        return error('filename requis')

    config_path = Path(GAME_CFG['configs_path']) / Path(filename).name
    if not config_path.exists():
        return error(f"Config '{filename}' introuvable", 404)

    try:
        serverconfig_b64, seasondefinition_b64 = encode_file(str(config_path))
    except Exception as e:
        return error(f"Erreur encodage config : {e}")

    result = restart_instance(instance_id, inst, GAME_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
    return jsonify({**result, 'loaded_config': filename})

# ─── Logs ─────────────────────────────────────────────────────────────────────

@app.route('/api/instances/<instance_id>/logs', methods=['GET'])
def instance_logs(instance_id):
    require_jwt()
    get_instance_or_404(instance_id)

    log_file = Path(CFG['logging']['log_file'])
    max_lines = CFG['logging'].get('max_lines', 500)

    if not log_file.exists():
        return jsonify({'lines': []})

    lines = log_file.read_text(encoding='utf-8', errors='replace').splitlines()
    return jsonify({'lines': lines[-max_lines:]})

# ─── Lancement ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    from waitress import serve
    print(f"PitLane Server Agent démarré sur {HTTP_CFG['host']}:{HTTP_CFG['port']}")
    serve(app, host=HTTP_CFG['host'], port=HTTP_CFG['port'])