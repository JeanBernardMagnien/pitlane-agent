from flask import jsonify, request

from core.auth import require_jwt
from services.agent_commands import (
    cleanup_instance_command,
    launch_instance_command,
    prepare_instance_command,
    resync_results_command,
    restart_instance_command,
    start_instance_command,
    stop_instance_command,
    update_instance_network_command,
)


def _json_response(result: tuple[dict, int]):
    payload, status_code = result
    return jsonify(payload), status_code


def register_instance_routes(app):
    @app.route('/api/instances/<instance_id>/prepare', methods=['POST'])
    def prepare_instance(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(prepare_instance_command(instance_id, body))

    @app.route('/api/instances/<instance_id>/network', methods=['PUT'])
    def update_instance_network(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(update_instance_network_command(instance_id, body))

    @app.route('/api/instances/<instance_id>/cleanup', methods=['POST'])
    def cleanup_instance(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(cleanup_instance_command(instance_id, body))

    @app.route('/api/instances/<instance_id>/launch', methods=['POST'])
    def instance_launch(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(launch_instance_command(instance_id, body))

    @app.route('/api/instances/<instance_id>/start', methods=['POST'])
    def instance_start(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(start_instance_command(instance_id, body))

    @app.route('/api/instances/<instance_id>/stop', methods=['POST'])
    def instance_stop(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(stop_instance_command(instance_id, body))

    @app.route('/api/instances/<instance_id>/restart', methods=['POST'])
    def instance_restart(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(restart_instance_command(instance_id, body))

    @app.route('/api/instances/<instance_id>/results/resync', methods=['POST'])
    def instance_results_resync(instance_id):
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(resync_results_command(instance_id, body))
