import yaml
import json
import jwt as pyjwt
from pathlib import Path
from flask import Flask, jsonify, request, abort
from server_manager import (
    start_instance, stop_instance, restart_instance,
    get_instance_status, list_configs
)
from encode_config import encode_file
from flask_sock import Sock
from log_streamer import tail_log
from datetime import datetime

# ─── Chargement config ────────────────────────────────────────────────────────

with open('config.yml', 'r', encoding='utf-8') as f:
    CFG = yaml.safe_load(f)

GAME_CFG  = CFG['game']
AUTH_CFG  = CFG['auth']
HTTP_CFG  = CFG['http']
INSTANCES = {inst['id']: inst for inst in CFG['instances']}

app = Flask(__name__)
sock = Sock(app)  

# ─── WebSocket Logs ───────────────────────────────────────────────────────────

@sock.route('/api/instances/<instance_id>/logs/stream')
def logs_stream(ws, instance_id):
    if instance_id not in INSTANCES:
        ws.send('{"error": "Instance introuvable"}')
        return

    log_file = CFG['logging']['log_file']
    max_lines = CFG['logging'].get('max_lines', 500)

    try:
        tail_log(ws, log_file, max_lines)
    except Exception:
        # Client déconnecté — on sort proprement
        pass


# ─── Auth JWT ─────────────────────────────────────────────────────────────────

def require_jwt():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        abort(401, 'Token manquant')
    token = auth_header[7:]
    try:
        pyjwt.decode(token, AUTH_CFG['jwt_secret'], algorithms=[AUTH_CFG['jwt_algorithm']])
    except pyjwt.ExpiredSignatureError:
        abort(401, 'Token expiré')
    except pyjwt.InvalidTokenError:
        abort(401, 'Token invalide')


# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_instance_or_404(instance_id: str) -> dict:
    if instance_id not in INSTANCES:
        abort(404, f"Instance '{instance_id}' introuvable dans config.yml")
    return INSTANCES[instance_id]


def error(msg: str, code: int = 400):
    return jsonify({'error': msg}), code


# ─── Instances ────────────────────────────────────────────────────────────────

@app.route('/api/instances', methods=['GET'])
def list_instances():
    require_jwt()
    statuses = [get_instance_status(inst) for inst in INSTANCES.values()]
    return jsonify(statuses)


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

    result = start_instance(inst, GAME_CFG, serverconfig_b64, seasondefinition_b64)
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

    result = restart_instance(instance_id, inst, GAME_CFG, serverconfig_b64, seasondefinition_b64)
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
    """Charge une nouvelle config sur une instance et la redémarre."""
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

    result = restart_instance(instance_id, inst, GAME_CFG, serverconfig_b64, seasondefinition_b64)

    # On enregistre la config active seulement si le restart a réussi
    if result.get('status') == 'online':
        _running[instance_id]['config'] = filename
        _running[instance_id]['config_loaded_at'] = datetime.utcnow().isoformat() + 'Z'

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