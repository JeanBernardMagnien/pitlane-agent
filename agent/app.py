import json
import os
import re
import subprocess
import threading
from pathlib import Path
from flask import Flask, jsonify, request
from flask_sock import Sock

import config_store
from auth import require_jwt
from encode_config import encode_file
from firewall import close_ports, open_ports
from http_helpers import error, get_instance_or_404, resolve_filename
from log_streamer import tail_log
from server_manager import (
    start_instance, stop_instance, restart_instance,
    get_instance_status, list_configs, _running
)
from system_info import get_system_info

# ─── Config watcher ──────────────────────────────────────────────────────────────────────────────

def _watch_config():
    while True:
        threading.Event().wait(1)
        try:
            if config_store.reload_if_changed():
                print(f"[config] Rechargé — {len(config_store.get_instances())} instance(s)")
        except Exception as e:
            print(f"[config] Erreur rechargement : {e}")


_watcher = threading.Thread(target=_watch_config, daemon=True)
_watcher.start()

# ─── Steam update process tracker ───────────────────────────────────────────────────────

_steam_process = None
_steam_process_lock = threading.Lock()

# ─── VDF helpers ──────────────────────────────────────────────────────────────────────────────

def _vdf_block(text: str, key: str, start: int = 0) -> str | None:
    """
    Extrait le contenu du premier bloc {…} associé à `key` dans du texte VDF,
    en comptant les accolades pour gérer les blocs imbriqués.
    Retourne le contenu sans les accolades externes, ou None si non trouvé.
    """
    m = re.search(rf'"{ re.escape(key) }"\s*\{{', text[start:])
    if not m:
        return None
    pos = start + m.end()
    depth = 1
    while pos < len(text) and depth:
        if text[pos] == '{':
            depth += 1
        elif text[pos] == '}':
            depth -= 1
        pos += 1
    return text[start + m.end(): pos - 1]

# ─── Flask ──────────────────────────────────────────────────────────────────────────────────

app = Flask(__name__)
sock = Sock(app)

# ─── WebSocket Logs ───────────────────────────────────────────────────────────────────────

@sock.route('/api/instances/<instance_id>/logs/stream')
def logs_stream(ws, instance_id):
    if not config_store.has_instance(instance_id):
        ws.send('{"error": "Instance introuvable"}')
        return

    logs_path = Path(config_store.LOGGING_CFG['logs_path'])
    max_lines = config_store.LOGGING_CFG.get('max_lines', 500)

    log_files = sorted(logs_path.glob(f"log_{instance_id}_*.log"), reverse=True)
    if not log_files:
        ws.send('{"error": "Aucun log disponible pour cette instance"}')
        return

    try:
        tail_log(ws, str(log_files[0]), max_lines)
    except Exception:
        pass

# ─── Système ─────────────────────────────────────────────────────────────────────────────────

@app.route('/api/system', methods=['GET'])
def system_info():
    require_jwt()
    return jsonify(get_system_info())

# ─── Instances — CRUD ───────────────────────────────────────────────────────────────────

@app.route('/api/instances', methods=['GET'])
def list_instances():
    require_jwt()
    statuses = [get_instance_status(inst) for inst in config_store.get_instances()]
    return jsonify(statuses)

@app.route('/api/instances', methods=['POST'])
def create_instance():
    require_jwt()
    body = request.get_json(silent=True) or {}

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
    if config_store.has_instance(instance_id):
        return error(f"Instance '{instance_id}' existe déjà")

    new_ports = {int(body['tcp_port']), int(body['udp_port']), int(body['http_port'])}
    for inst in config_store.get_instances():
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

    fw_errors = open_ports(
        instance_id,
        int(body['tcp_port']),
        int(body['udp_port']),
        int(body['http_port']),
    )

    cfg = config_store.load_config()
    cfg['instances'].append(new_inst)
    config_store.save_config(cfg)
    config_store.set_instance(instance_id, new_inst)
    config_store.mark_saved()

    response = {**new_inst}
    if fw_errors:
        response['fw_warnings'] = fw_errors
    return jsonify(response), 201

@app.route('/api/instances/<instance_id>', methods=['PUT'])
def update_instance(instance_id):
    require_jwt()

    if not config_store.has_instance(instance_id):
        return error(f"Instance '{instance_id}' introuvable", 404)

    if instance_id in _running and _running[instance_id]['process'].poll() is None:
        return error("Arrêtez l'instance avant de la modifier", 409)

    body = request.get_json(silent=True) or {}
    old_inst = config_store.get_instance(instance_id).copy()

    new_inst = {
        'id':        instance_id,
        'name':      str(body.get('name', old_inst['name'])).strip(),
        'tcp_port':  int(body.get('tcp_port', old_inst['tcp_port'])),
        'udp_port':  int(body.get('udp_port', old_inst['udp_port'])),
        'http_port': int(body.get('http_port', old_inst['http_port'])),
    }

    new_ports = {new_inst['tcp_port'], new_inst['udp_port'], new_inst['http_port']}
    old_ports = {old_inst['tcp_port'], old_inst['udp_port'], old_inst['http_port']}

    if new_ports != old_ports:
        for iid, inst in config_store.INSTANCES.items():
            if iid == instance_id:
                continue
            existing_ports = {inst.get('tcp_port'), inst.get('udp_port'), inst.get('http_port')}
            conflict = new_ports & existing_ports
            if conflict:
                return error(f"Port(s) déjà utilisé(s) : {', '.join(str(p) for p in conflict)}")

        close_ports(instance_id, old_inst['tcp_port'], old_inst['udp_port'], old_inst['http_port'])
        fw_errors = open_ports(instance_id, new_inst['tcp_port'], new_inst['udp_port'], new_inst['http_port'])
    else:
        fw_errors = []

    cfg = config_store.load_config()
    cfg['instances'] = [new_inst if i['id'] == instance_id else i for i in cfg['instances']]
    config_store.save_config(cfg)
    config_store.set_instance(instance_id, new_inst)
    config_store.mark_saved()

    response = {**new_inst}
    if fw_errors:
        response['fw_warnings'] = fw_errors
    return jsonify(response)


@app.route('/api/instances/<instance_id>', methods=['DELETE'])
def delete_instance(instance_id):
    require_jwt()
    if not config_store.has_instance(instance_id):
        return error(f"Instance '{instance_id}' introuvable", 404)

    if instance_id in _running and _running[instance_id]['process'].poll() is None:
        return error("Arrêtez l'instance avant de la supprimer", 409)

    inst_data = config_store.get_instance(instance_id) or {}

    cfg = config_store.load_config()
    cfg['instances'] = [i for i in cfg['instances'] if i['id'] != instance_id]
    config_store.save_config(cfg)
    config_store.remove_instance(instance_id)
    config_store.mark_saved()

    fw_errors = close_ports(
        instance_id,
        inst_data.get('tcp_port', 0),
        inst_data.get('udp_port', 0),
        inst_data.get('http_port', 0),
    )

    response = {'deleted': instance_id}
    if fw_errors:
        response['fw_warnings'] = fw_errors
    return jsonify(response)

# ─── Instances — Actions ───────────────────────────────────────────────────────────────────

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

    config_path = Path(config_store.GAME_CFG['configs_path']) / Path(filename).name
    if not config_path.exists():
        return error(f"Config '{filename}' introuvable", 404)

    try:
        serverconfig_b64, seasondefinition_b64 = encode_file(str(config_path))
    except Exception as e:
        return error(f"Erreur encodage config : {e}")

    result = start_instance(inst, config_store.GAME_CFG, config_store.LOGGING_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
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

    config_path = Path(config_store.GAME_CFG['configs_path']) / Path(filename).name
    if not config_path.exists():
        return error(f"Config '{filename}' introuvable", 404)

    try:
        serverconfig_b64, seasondefinition_b64 = encode_file(str(config_path))
    except Exception as e:
        return error(f"Erreur encodage config : {e}")

    result = restart_instance(instance_id, inst, config_store.GAME_CFG, config_store.LOGGING_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
    return jsonify(result)

# ─── Configs ──────────────────────────────────────────────────────────────────────────────────

@app.route('/api/configs', methods=['GET'])
def configs_list():
    require_jwt()
    return jsonify(list_configs(config_store.GAME_CFG['configs_path']))


@app.route('/api/configs', methods=['POST'])
def config_create():
    require_jwt()
    body = request.get_json(silent=True)
    if not body or 'filename' not in body or 'content' not in body:
        return error('filename et content requis')

    filename = Path(body['filename']).name
    if not filename.endswith('.json'):
        return error('Le fichier doit être un .json')

    dest = Path(config_store.GAME_CFG['configs_path']) / filename
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
    dest = Path(config_store.GAME_CFG['configs_path']) / safe_name
    if not dest.exists():
        return error(f"'{safe_name}' introuvable"), 404

    dest.write_text(json.dumps(body['content'], indent=2), encoding='utf-8')
    return jsonify({'updated': safe_name})


@app.route('/api/configs/<filename>', methods=['DELETE'])
def config_delete(filename):
    require_jwt()
    safe_name = Path(filename).name
    dest = Path(config_store.GAME_CFG['configs_path']) / safe_name
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

    config_path = Path(config_store.GAME_CFG['configs_path']) / Path(filename).name
    if not config_path.exists():
        return error(f"Config '{filename}' introuvable", 404)

    try:
        serverconfig_b64, seasondefinition_b64 = encode_file(str(config_path))
    except Exception as e:
        return error(f"Erreur encodage config : {e}")

    result = restart_instance(instance_id, inst, config_store.GAME_CFG, config_store.LOGGING_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
    return jsonify({**result, 'loaded_config': filename})

# ─── Logs ────────────────────────────────────────────────────────────────────────────────────

@app.route('/api/instances/<instance_id>/logs', methods=['GET'])
def instance_logs(instance_id):
    require_jwt()
    get_instance_or_404(instance_id)

    logs_path = Path(config_store.LOGGING_CFG['logs_path'])
    max_lines = config_store.LOGGING_CFG.get('max_lines', 500)

    log_files = sorted(logs_path.glob(f"log_{instance_id}_*.log"), reverse=True)
    if not log_files:
        return jsonify({'lines': []})

    lines = log_files[0].read_text(encoding='utf-8', errors='replace').splitlines()
    return jsonify({'lines': lines[-max_lines:]})

# ─── Steam ──────────────────────────────────────────────────────────────────────────────────

@app.route('/api/steam/update', methods=['POST'])
def steam_update():
    global _steam_process
    require_jwt()

    steam_cfg = config_store.CFG.get('steam', {})
    logs_path = config_store.LOGGING_CFG['logs_path']

    steamcmd_path = steam_cfg.get('steamcmd_path', '')
    if not steamcmd_path:
        return error('Mise à jour à distance non configurée', 503)

    running_instances = [
        iid for iid, info in _running.items()
        if info['process'].poll() is None
    ]
    if running_instances:
        return error('Arrêtez les instances avant de mettre à jour', 409)

    body = request.get_json(silent=True) or {}
    username = body.get('steam_username')
    password = body.get('steam_password')
    if not username or not password:
        return error('steam_username et steam_password requis', 400)

    app_id = str(steam_cfg.get('app_id', 4564210))

    logs_dir = Path(logs_path)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / 'steam_update.log'

    steamcmd_dir = str(Path(steamcmd_path).parent)
    cmd = [
        steamcmd_path,
        '+force_install_dir', steamcmd_dir,
        '+login', username, password,
        '+app_update', app_id, 'validate',
        '+quit',
    ]

    create_flags = 0x08000000 if os.name == 'nt' else 0  # CREATE_NO_WINDOW
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=create_flags,
    )

    def _drain(proc, path):
        with open(path, 'wb') as f:
            while True:
                chunk = proc.stdout.read(256)
                if not chunk:
                    break
                f.write(chunk)
                f.flush()

    threading.Thread(target=_drain, args=(process, str(log_path)), daemon=True).start()

    with _steam_process_lock:
        _steam_process = {'process': process}

    return jsonify({'status': 'started', 'pid': process.pid}), 202


@app.route('/api/steam/update/logs', methods=['GET'])
def steam_update_logs():
    require_jwt()

    log_path = Path(config_store.LOGGING_CFG['logs_path']) / 'steam_update.log'
    if not log_path.exists():
        return jsonify({'lines': [], 'finished': True, 'success': False})

    raw = log_path.read_bytes()
    text = raw.decode('utf-8', errors='replace')
    lines = [line.split('\r')[-1] for line in text.split('\n')][-100:]

    with _steam_process_lock:
        proc = _steam_process.get('process') if _steam_process else None
        exit_code = proc.poll() if proc is not None else None
        finished = proc is None or exit_code is not None

    return jsonify({'lines': lines, 'finished': finished, 'success': finished and exit_code == 0})


@app.route('/api/steam/update-check', methods=['POST'])
def steam_update_check():
    """
    Compare le build local (appmanifest) au build distant via steamcmd app_info_print.
    Nécessite des identifiants Steam valides.

    Le VDF de steamcmd contient plusieurs blocs "public" (un par dépôt dans "manifests").
    On navigue explicitement dans branches > public pour éviter les faux positifs.
    """
    require_jwt()

    steam_cfg = config_store.CFG.get('steam', {})

    steamcmd_path = steam_cfg.get('steamcmd_path', '')
    if not steamcmd_path:
        return error('steamcmd non configuré', 503)

    appmanifest_path = steam_cfg.get('appmanifest_path', '')
    if not appmanifest_path:
        return error('Chemin appmanifest non configuré', 503)

    body = request.get_json(silent=True) or {}
    username = body.get('steam_username', '').strip()
    password = body.get('steam_password', '').strip()
    if not username or not password:
        return error('steam_username et steam_password requis', 400)

    manifest_file = Path(appmanifest_path)
    if not manifest_file.exists():
        return error(f"appmanifest introuvable : {appmanifest_path}", 404)

    content = manifest_file.read_text(encoding='utf-8', errors='replace')
    local_match = re.search(r'"buildid"\s+"(\d+)"', content)
    if not local_match:
        return error('buildid introuvable dans appmanifest', 500)

    local_buildid = int(local_match.group(1))
    app_id = str(steam_cfg.get('app_id', 4564210))

    try:
        result = subprocess.run(
            [
                steamcmd_path,
                '+login', username, password,
                '+app_info_update', '1',
                '+app_info_print', app_id,
                '+quit',
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        output = result.stdout
    except subprocess.TimeoutExpired:
        return error('steamcmd timeout (90s)', 504)
    except Exception as e:
        return error(f"steamcmd erreur : {e}", 502)

    branches_block = _vdf_block(output, 'branches')
    if not branches_block:
        return error('Section "branches" introuvable dans la sortie steamcmd', 502)

    public_block = _vdf_block(branches_block, 'public')
    if not public_block:
        return error('Branche "public" introuvable dans steamcmd', 502)

    remote_match = re.search(r'"buildid"\s+"(\d+)"', public_block)
    if not remote_match:
        return error('buildid distant introuvable dans la branche public', 502)

    remote_buildid = int(remote_match.group(1))
    up_to_date = (local_buildid == remote_buildid)

    return jsonify({
        'up_to_date':       up_to_date,
        'local_build':      local_buildid,
        'remote_build':     remote_buildid,
        'update_available': not up_to_date,
    })

# ─── Lancement ────────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    from waitress import serve
    print(f"PitLane Server Agent démarré sur {config_store.HTTP_CFG['host']}:{config_store.HTTP_CFG['port']}")
    serve(app, host=config_store.HTTP_CFG['host'], port=config_store.HTTP_CFG['port'])
