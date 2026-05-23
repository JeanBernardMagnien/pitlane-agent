from pathlib import Path

from flask import jsonify

from core import config_store
from core.auth import require_jwt
from services.agent_commands import get_instance_logs_command
from services.log_streamer import tail_log


def register_log_routes(app, sock):
    @sock.route('/api/instances/<instance_id>/logs/stream')
    def logs_stream(ws, instance_id):
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

    @app.route('/api/instances/<instance_id>/logs', methods=['GET'])
    def instance_logs(instance_id):
        require_jwt()
        payload, status_code = get_instance_logs_command(instance_id)
        return jsonify(payload), status_code
