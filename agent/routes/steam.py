from flask import jsonify, request

from core import config_store
from core.auth import require_jwt
from services.steam_manager import (
    check_steam_update,
    get_steam_update_logs,
    start_steam_update,
)


def _json_response(result: tuple[dict, int]):
    payload, status_code = result
    return jsonify(payload), status_code


def register_steam_routes(app):
    @app.route('/api/steam/update-check', methods=['POST'])
    def steam_update_check():
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(check_steam_update(config_store.CFG.get('steam', {}), body))

    @app.route('/api/steam/update', methods=['POST'])
    def steam_update():
        require_jwt()
        body = request.get_json(silent=True) or {}
        return _json_response(start_steam_update(
            config_store.CFG.get('steam', {}),
            config_store.GAME_CFG,
            config_store.LOGGING_CFG,
            body,
        ))

    @app.route('/api/steam/update/logs', methods=['GET'])
    def steam_update_logs():
        require_jwt()
        return _json_response(get_steam_update_logs(config_store.LOGGING_CFG))
