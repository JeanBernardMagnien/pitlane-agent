from flask import jsonify

from services.server_manager import get_last_config


def error(msg: str, code: int = 400):
    return jsonify({'error': msg}), code


def resolve_filename(instance_id: str, body: dict) -> str | None:
    filename = body.get('filename')
    if filename:
        return filename

    last = get_last_config(instance_id)
    return last.get('config')
