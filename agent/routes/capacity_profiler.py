from flask import jsonify, request

from core.auth import require_local
from services import capacity_profiler_runner


def _json_response(result: tuple[dict, int]):
    payload, status_code = result
    return jsonify(payload), status_code


def register_capacity_profiler_routes(app):
    @app.route('/api/capacity-profiler/runs', methods=['POST'])
    def capacity_profiler_start():
        require_local()
        body = request.get_json(silent=True) or {}
        return _json_response(capacity_profiler_runner.start_run(body))

    @app.route('/api/capacity-profiler/runs/<int:run_id>/stop', methods=['POST'])
    def capacity_profiler_stop(run_id):
        require_local()
        body = request.get_json(silent=True) or {}
        stop_reason = body.get('stop_reason') or 'manual'
        return _json_response(capacity_profiler_runner.stop_run(run_id, stop_reason))

    @app.route('/api/capacity-profiler/runs/current', methods=['GET'])
    def capacity_profiler_current():
        require_local()
        status = capacity_profiler_runner.current_status()
        return jsonify(status or {'active': False}), 200

    @app.route('/api/capacity-profiler/runs', methods=['GET'])
    def capacity_profiler_list():
        require_local()
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        return jsonify(capacity_profiler_runner.list_runs(limit, offset)), 200

    @app.route('/api/capacity-profiler/runs/<int:run_id>', methods=['GET'])
    def capacity_profiler_get(run_id):
        require_local()
        run = capacity_profiler_runner.get_run(run_id)
        return (jsonify(run), 200) if run else (jsonify({'error': 'not_found'}), 404)

    @app.route('/api/capacity-profiler/runs/<int:run_id>/snapshots', methods=['GET'])
    def capacity_profiler_snapshots(run_id):
        require_local()
        since = request.args.get('since')
        limit = request.args.get('limit', 500, type=int)
        return jsonify(capacity_profiler_runner.list_snapshots(run_id, since, limit)), 200

    @app.route('/api/capacity-profiler/settings', methods=['GET'])
    def capacity_profiler_get_settings():
        require_local()
        return jsonify(capacity_profiler_runner.get_settings()), 200

    @app.route('/api/capacity-profiler/settings', methods=['PUT'])
    def capacity_profiler_update_settings():
        require_local()
        body = request.get_json(silent=True) or {}
        return jsonify(capacity_profiler_runner.update_settings(body)), 200
