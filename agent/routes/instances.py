from pathlib import Path

from flask import jsonify, request

from core import config_store
from core.auth import require_jwt
from core.firewall import close_ports, open_ports
from core.http_helpers import error, get_instance_or_404, resolve_filename
from core.system_info import get_system_info
from services.encode_config import encode_file, encode_payload
from services.runtime_config_compiler import compile_event_config
from services.server_manager import (
    _running,
    get_instance_status,
    restart_instance,
    start_instance,
    stop_instance,
)


def register_instance_routes(app):
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

    @app.route('/api/instances/<instance_id>/start-event', methods=['POST'])
    def instance_start_event(instance_id):
        require_jwt()
        inst = get_instance_or_404(instance_id)

        body = request.get_json(silent=True) or {}
        event_config = body.get('event_config')

        if not isinstance(event_config, dict):
            return error('event_config requis')

        try:
            runtime_config = compile_event_config(event_config, inst)
            serverconfig_b64, seasondefinition_b64 = encode_payload(runtime_config)
        except Exception as e:
            return error(f"Erreur compilation config event : {e}")

        runtime_name = body.get('event_config_name') or body.get('event_config_id') or 'runtime-event'

        result = start_instance(
            inst,
            config_store.GAME_CFG,
            config_store.LOGGING_CFG,
            serverconfig_b64,
            seasondefinition_b64,
            filename=str(runtime_name),
        )

        if 'error' in result:
            return jsonify(result), 409

        return jsonify({
            **result,
            'runtime_config': runtime_name,
        })

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
