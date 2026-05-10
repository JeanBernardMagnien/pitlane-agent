import yaml
import json
import re
import jwt as pyjwt
import threading
import os
import subprocess
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

# ─── Chargement config ──────────────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path('config.yml')

def load_config():
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def save_config(cfg: dict):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

CFG         = load_config()
GAME_CFG    = CFG['game']
AUTH_CFG    = CFG['auth']
HTTP_CFG    = CFG['http']
LOGGING_CFG = CFG['logging']
INSTANCES   = {inst['id']: inst for inst in CFG['instances']}

_config_lock = threading.Lock()
_config_mtime = CONFIG_PATH.stat().st_mtime

def _watch_config():
    global CFG, GAME_CFG, AUTH_CFG, HTTP_CFG, LOGGING_CFG, INSTANCES, _config_mtime
    while True:
        threading.Event().wait(1)
        try:
            mtime = CONFIG_PATH.stat().st_mtime
            if mtime != _config_mtime:
                new_cfg = load_config()
                with _config_lock:
                    CFG         = new_cfg
                    GAME_CFG    = new_cfg['game']
                    AUTH_CFG    = new_cfg['auth']
                    HTTP_CFG    = new_cfg['http']
                    LOGGING_CFG = new_cfg['logging']
                    INSTANCES   = {inst['id']: inst for inst in new_cfg['instances']}
                    _config_mtime = mtime
                print(f"[config] Rechargé — {len(INSTANCES)} instance(s)")
        except Exception as e:
            print(f"[config] Erreur rechargement : {e}")

_watcher = threading.Thread(target=_watch_config, daemon=True)
_watcher.start()

# ─── Steam update process tracker ───────────────────────────────────────────────────────

_steam_process = None
_steam_process_lock = threading.Lock()

# ─── Infos système ──────────────────────────────────────────────────────────────────────────────

def get_system_info() -> dict:
    cpu_cores = _psutil.cpu_count(logical=False) or 1
    max_instances = cpu_cores // 2
    return {
        'cpu_cores': cpu_cores,
        'cpu_threads': _psutil.cpu_count(logical=True),
        'max_instances': max_instances,
        'current_instances': len(INSTANCES),
    }

# ─── Firewall helpers ───────────────────────────────────────────────────────────────────────────

def _fw_rule_name(instance_id: str, port: int, proto: str) -> str:
    return f"PitLane-{instance_id}-{proto}-{port}"

def _open_ports(instance_id: str, tcp_port: int, udp_port: int, http_port: int):
    rules = [
        (tcp_port,  'TCP', 'jeu AC EVO TCP'),
        (udp_port,  'UDP', 'jeu AC EVO UDP'),
        (http_port, 'TCP', 'HTTP statut AC EVO'),
    ]
    errors = []
    for port, proto, desc in rules:
        name = _fw_rule_name(instance_id, port, proto)
        cmd = [
            'powershell', '-NonInteractive', '-Command',
            f'New-NetFirewallRule -DisplayName "{name}" '
            f'-Direction Inbound -Protocol {proto} '
            f'-LocalPort {port} -Action Allow -ErrorAction Stop'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append(f"{proto}/{port}: {result.stderr.strip()}")
    return errors

def _close_ports(instance_id: str, tcp_port: int, udp_port: int, http_port: int):
    rules = [
        (tcp_port,  'TCP'),
        (udp_port,  'UDP'),
        (http_port, 'TCP'),
    ]
    errors = []
    for port, proto in rules:
        name = _fw_rule_name(instance_id, port, proto)
        cmd = [
            'powershell', '-NonInteractive', '-Command',
            f'Remove-NetFirewallRule -DisplayName "{name}" -ErrorAction SilentlyContinue'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append(f"{proto}/{port}: {result.stderr.strip()}")
    return errors

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
    with _config_lock:
        known = instance_id in INSTANCES
    if not known:
        ws.send('{"error": "Instance introuvable"}')
        return

    logs_path = Path(LOGGING_CFG['logs_path'])
    max_lines = LOGGING_CFG.get('max_lines', 500)

    log_files = sorted(logs_path.glob(f"log_{instance_id}_*.log"), reverse=True)
    if not log_files:
        ws.send('{"error": "Aucun log disponible pour cette instance"}')
        return

    try:
        tail_log(ws, str(log_files[0]), max_lines)
    except Exception:
        pass

# ─── Auth JWT ─────────────────────────────────────────────────────────────────────────────

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

# ─── Helpers ────────────────────────────────────────────────────────────────────────────────

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

# ─── Système ─────────────────────────────────────────────────────────────────────────────────

@app.route('/api/system', methods=['GET'])
def system_info():
    require_jwt()
    return jsonify(get_system_info())

# ─── Instances — CRUD ───────────────────────────────────────────────────────────────────

@app.route('/api/instances', methods=['GET'])
def list_instances():
    require_jwt()
    with _config_lock:
        insts = list(INSTANCES.values())
    statuses = [get_instance_status(inst) for inst in insts]
    return jsonify(statuses)

@app.route('/api/instances', methods=['POST'])
def create_instance():
    global _config_mtime
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
    with _config_lock:
        if instance_id in INSTANCES:
            return error(f"Instance '{instance_id}' existe déjà")

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

    fw_errors = _open_ports(
        instance_id,
        int(body['tcp_port']),
        int(body['udp_port']),
        int(body['http_port']),
    )

    cfg = load_config()
    cfg['instances'].append(new_inst)
    save_config(cfg)

    with _config_lock:
        INSTANCES[instance_id] = new_inst
        _config_mtime = CONFIG_PATH.stat().st_mtime

    response = {**new_inst}
    if fw_errors:
        response['fw_warnings'] = fw_errors
    return jsonify(response), 201

@app.route('/api/instances/<instance_id>', methods=['PUT'])
def update_instance(instance_id):
    global _config_mtime
    require_jwt()

    with _config_lock:
        if instance_id not in INSTANCES:
            return error(f"Instance '{instance_id}' introuvable", 404)

    if instance_id in _running and _running[instance_id]['process'].poll() is None:
        return error("Arrêtez l'instance avant de la modifier", 409)

    body = request.get_json(silent=True) or {}

    with _config_lock:
        old_inst = INSTANCES[instance_id].copy()

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
        with _config_lock:
            for iid, inst in INSTANCES.items():
                if iid == instance_id:
                    continue
                existing_ports = {inst.get('tcp_port'), inst.get('udp_port'), inst.get('http_port')}
                conflict = new_ports & existing_ports
                if conflict:
                    return error(f"Port(s) déjà utilisé(s) : {', '.join(str(p) for p in conflict)}")

        _close_ports(instance_id, old_inst['tcp_port'], old_inst['udp_port'], old_inst['http_port'])
        fw_errors = _open_ports(instance_id, new_inst['tcp_port'], new_inst['udp_port'], new_inst['http_port'])
    else:
        fw_errors = []

    cfg = load_config()
    cfg['instances'] = [new_inst if i['id'] == instance_id else i for i in cfg['instances']]
    save_config(cfg)

    with _config_lock:
        INSTANCES[instance_id] = new_inst
        _config_mtime = CONFIG_PATH.stat().st_mtime

    response = {**new_inst}
    if fw_errors:
        response['fw_warnings'] = fw_errors
    return jsonify(response)


@app.route('/api/instances/<instance_id>', methods=['DELETE'])
def delete_instance(instance_id):
    global _config_mtime
    require_jwt()
    with _config_lock:
        if instance_id not in INSTANCES:
            return error(f"Instance '{instance_id}' introuvable", 404)

    if instance_id in _running and _running[instance_id]['process'].poll() is None:
        return error("Arrêtez l'instance avant de la supprimer", 409)

    with _config_lock:
        inst_data = INSTANCES.get(instance_id, {})

    cfg = load_config()
    cfg['instances'] = [i for i in cfg['instances'] if i['id'] != instance_id]
    save_config(cfg)

    with _config_lock:
        INSTANCES.pop(instance_id, None)
        _config_mtime = CONFIG_PATH.stat().st_mtime

    fw_errors = _close_ports(
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

    config_path = Path(GAME_CFG['configs_path']) / Path(filename).name
    if not config_path.exists():
        return error(f"Config '{filename}' introuvable", 404)

    try:
        serverconfig_b64, seasondefinition_b64 = encode_file(str(config_path))
    except Exception as e:
        return error(f"Erreur encodage config : {e}")

    result = start_instance(inst, GAME_CFG, LOGGING_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
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

    result = restart_instance(instance_id, inst, GAME_CFG, LOGGING_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
    return jsonify(result)

# ─── Configs ──────────────────────────────────────────────────────────────────────────────────

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

    result = restart_instance(instance_id, inst, GAME_CFG, LOGGING_CFG, serverconfig_b64, seasondefinition_b64, filename=filename)
    return jsonify({**result, 'loaded_config': filename})

# ─── Logs ────────────────────────────────────────────────────────────────────────────────────

@app.route('/api/instances/<instance_id>/logs', methods=['GET'])
def instance_logs(instance_id):
    require_jwt()
    get_instance_or_404(instance_id)

    logs_path = Path(LOGGING_CFG['logs_path'])
    max_lines = LOGGING_CFG.get('max_lines', 500)

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

    with _config_lock:
        steam_cfg = CFG.get('steam', {})
        logs_path = LOGGING_CFG['logs_path']
        install_path = GAME_CFG['install_path']

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

    cmd = [
        steamcmd_path,
        '+force_install_dir', install_path,
        '+login', username, password,
        '+app_update', app_id, 'validate',
        '+quit',
    ]

    with _steam_process_lock:
        log_file = open(str(log_path), 'w', encoding='utf-8')
        process = subprocess.Popen(cmd, stdout=log_file, stderr=log_file)
        _steam_process = {'process': process, 'log_file': log_file}

    return jsonify({'status': 'started', 'pid': process.pid}), 202


@app.route('/api/steam/update/logs', methods=['GET'])
def steam_update_logs():
    require_jwt()

    with _config_lock:
        logs_path = LOGGING_CFG['logs_path']

    log_path = Path(logs_path) / 'steam_update.log'
    if not log_path.exists():
        return jsonify({'lines': [], 'finished': True, 'success': False})

    lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()[-100:]

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

    with _config_lock:
        steam_cfg = CFG.get('steam', {})

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

    # Navigate branches > public using brace-counting to avoid matching
    # the "public" manifest blocks inside each depot's "manifests" section.
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
    print(f"PitLane Server Agent démarré sur {HTTP_CFG['host']}:{HTTP_CFG['port']}")
    serve(app, host=HTTP_CFG['host'], port=HTTP_CFG['port'])
