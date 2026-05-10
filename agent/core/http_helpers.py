from flask import abort, jsonify

from core import config_store
from services.server_manager import get_last_config


def error(msg: str, code: int = 400):
    return jsonify({'error': msg}), code


def get_instance_or_404(instance_id: str) -> dict:
    inst = config_store.get_instance(instance_id)
    if not inst:
        abort(404, f"Instance '{instance_id}' introuvable dans config.yml")
    return inst


def resolve_filename(instance_id: str, body: dict) -> str | None:
    filename = body.get('filename')
    if filename:
        return filename

    last = get_last_config(instance_id)
    return last.get('config')
