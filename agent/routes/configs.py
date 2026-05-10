import json
from pathlib import Path

from flask import jsonify, request

from core import config_store
from core.auth import require_jwt
from core.http_helpers import error
from services.server_manager import list_configs


def register_config_routes(app):
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
            return error(f"'{safe_name}' introuvable", 404)

        dest.write_text(json.dumps(body['content'], indent=2), encoding='utf-8')
        return jsonify({'updated': safe_name})

    @app.route('/api/configs/<filename>', methods=['DELETE'])
    def config_delete(filename):
        require_jwt()
        safe_name = Path(filename).name
        dest = Path(config_store.GAME_CFG['configs_path']) / safe_name
        if not dest.exists():
            return error(f"'{safe_name}' introuvable", 404)

        dest.unlink()
        return jsonify({'deleted': safe_name})
