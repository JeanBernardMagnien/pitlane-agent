from flask import jsonify, request

from core import config_store
from core.auth import require_jwt
from core.firewall import close_ports, open_ports
from core.http_helpers import error
from services.current_config_store import (
    load_current_config,
    save_current_config,
    save_launch_history_config,
)
from services.encode_config import encode_payload
from services.runtime_config_compiler import (
    InstancePortsOutOfSync,
    finalize_launch_config,
)
from services.server_manager import (
    _running,
    restart_instance,
    start_instance,
    stop_instance,
)


def _instance_from_payload(body: dict, fallback_instance_id: str | None = None) -> dict | None:
    instance = body.get('instance')
    if not isinstance(instance, dict):
        return None

    instance_id = str(instance.get('id') or fallback_instance_id or '').strip()
    if not instance_id:
        return None

    try:
        return {
            'id': instance_id,
            'name': str(instance.get('name') or instance_id).strip(),
            'tcp_port': int(instance['tcp_port']),
            'udp_port': int(instance['udp_port']),
            'http_port': int(instance['http_port']),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _ports_from_payload(body: dict, key: str = 'ports') -> dict | None:
    ports = body.get(key)
    if not isinstance(ports, dict):
        return None

    try:
        return {
            'tcp_port': int(ports['tcp_port']),
            'udp_port': int(ports['udp_port']),
            'http_port': int(ports['http_port']),
        }
    except (KeyError, TypeError, ValueError):
        return None


def register_instance_routes(app):
    @app.route('/api/instances/<instance_id>/prepare', methods=['POST'])
    def prepare_instance(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        ports = _ports_from_payload(body)

        if not ports:
            return error('ports requis')

        fw_errors = open_ports(
            instance_id,
            ports['tcp_port'],
            ports['udp_port'],
            ports['http_port'],
        )

        response = {'status': 'prepared', 'instance_id': instance_id}
        if fw_errors:
            response['fw_warnings'] = fw_errors

        return jsonify(response)

    @app.route('/api/instances/<instance_id>/network', methods=['PUT'])
    def update_instance_network(instance_id):
        require_jwt()

        if instance_id in _running and _running[instance_id]['process'].poll() is None:
            return error("Arrêtez l'instance avant de modifier ses ports", 409)

        body = request.get_json(silent=True) or {}
        previous_ports = _ports_from_payload(body, 'previous_ports')
        ports = _ports_from_payload(body)

        if not previous_ports or not ports:
            return error('previous_ports et ports requis')

        fw_errors = []
        if previous_ports != ports:
            fw_errors.extend(close_ports(
                instance_id,
                previous_ports['tcp_port'],
                previous_ports['udp_port'],
                previous_ports['http_port'],
            ))
            fw_errors.extend(open_ports(
                instance_id,
                ports['tcp_port'],
                ports['udp_port'],
                ports['http_port'],
            ))

        response = {'status': 'network_updated', 'instance_id': instance_id}
        if fw_errors:
            response['fw_warnings'] = fw_errors

        return jsonify(response)

    @app.route('/api/instances/<instance_id>/cleanup', methods=['POST'])
    def cleanup_instance(instance_id):
        require_jwt()

        if instance_id in _running and _running[instance_id]['process'].poll() is None:
            return error("Arrêtez l'instance avant de la nettoyer", 409)

        body = request.get_json(silent=True) or {}
        ports = _ports_from_payload(body)

        if not ports:
            return error('ports requis')

        fw_errors = close_ports(
            instance_id,
            ports['tcp_port'],
            ports['udp_port'],
            ports['http_port'],
        )

        response = {'status': 'cleaned', 'instance_id': instance_id}
        if fw_errors:
            response['fw_warnings'] = fw_errors

        return jsonify(response)

    @app.route('/api/instances/<instance_id>/launch', methods=['POST'])
    def instance_launch(instance_id):
        require_jwt()

        body = request.get_json(silent=True) or {}
        inst = _instance_from_payload(body, instance_id)

        if not inst:
            return error('instance complète requise')

        runtime_config = body.get('runtime_config')
        launch_id = body.get('launch_id')
        restart_if_running = bool(body.get('restart_if_running', False))

        if not isinstance(runtime_config, dict):
            return error('runtime_config requis')

        try:
            runtime_config = finalize_launch_config(
                runtime_config,
                inst,
                config_store.GAME_CFG,
            )

            save_current_config(
                config_store.GAME_CFG,
                instance_id,
                runtime_config,
            )

            save_launch_history_config(
                config_store.GAME_CFG,
                launch_id,
                instance_id,
                runtime_config,
            )

            serverconfig_b64, seasondefinition_b64 = encode_payload(runtime_config)

        except InstancePortsOutOfSync as e:
            return jsonify({
                'code': 'INSTANCE_PORTS_OUT_OF_SYNC',
                'expected': e.expected,
                'received': e.received,
            }), 409

        except Exception as e:
            return error(f'Erreur préparation lancement : {e}')

        if restart_if_running:
            result = restart_instance(
                instance_id,
                inst,
                config_store.GAME_CFG,
                config_store.LOGGING_CFG,
                serverconfig_b64,
                seasondefinition_b64,
                filename=f'launch-{launch_id or "manual"}',
            )
        else:
            result = start_instance(
                inst,
                config_store.GAME_CFG,
                config_store.LOGGING_CFG,
                serverconfig_b64,
                seasondefinition_b64,
                filename=f'launch-{launch_id or "manual"}',
            )

        if 'error' in result:
            return jsonify(result), 409

        return jsonify(result)

    @app.route('/api/instances/<instance_id>/start', methods=['POST'])
    def instance_start(instance_id):
        require_jwt()

        body = request.get_json(silent=True) or {}
        inst = _instance_from_payload(body, instance_id)

        if not inst:
            return error('instance complète requise')

        try:
            _, runtime_config = load_current_config(
                config_store.GAME_CFG,
                instance_id,
            )

            serverconfig_b64, seasondefinition_b64 = encode_payload(runtime_config)

        except FileNotFoundError as e:
            return error(str(e), 404)

        except Exception as e:
            return error(f'Erreur chargement config : {e}')

        result = start_instance(
            inst,
            config_store.GAME_CFG,
            config_store.LOGGING_CFG,
            serverconfig_b64,
            seasondefinition_b64,
            filename='current-config',
        )

        if 'error' in result:
            return jsonify(result), 409

        return jsonify(result)

    @app.route('/api/instances/<instance_id>/stop', methods=['POST'])
    def instance_stop(instance_id):
        require_jwt()

        result = stop_instance(instance_id, config_store.LOGGING_CFG)

        if 'error' in result:
            return jsonify(result), 409

        return jsonify(result)

    @app.route('/api/instances/<instance_id>/restart', methods=['POST'])
    def instance_restart(instance_id):
        require_jwt()

        body = request.get_json(silent=True) or {}
        inst = _instance_from_payload(body, instance_id)

        if not inst:
            info = _running.get(instance_id)
            inst = info.get('instance') if info else None

        if not inst:
            return error('instance complète requise')

        try:
            _, runtime_config = load_current_config(
                config_store.GAME_CFG,
                instance_id,
            )

            serverconfig_b64, seasondefinition_b64 = encode_payload(runtime_config)

        except FileNotFoundError as e:
            return error(str(e), 404)

        except Exception as e:
            return error(f'Erreur chargement config : {e}')

        result = restart_instance(
            instance_id,
            inst,
            config_store.GAME_CFG,
            config_store.LOGGING_CFG,
            serverconfig_b64,
            seasondefinition_b64,
            filename='current-config',
        )

        return jsonify(result)
