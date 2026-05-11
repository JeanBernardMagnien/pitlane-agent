import threading

from flask import Flask, jsonify
from flask_sock import Sock

from core import config_store
from core.auth import require_jwt
from core.system_info import get_system_info
from routes.configs import register_config_routes
from routes.instances import register_instance_routes
from routes.logs import register_log_routes
from routes.steam import register_steam_routes
from services.hub_client import post_json
from services.monitor import SnapshotMonitor

_monitor = None


def _watch_config():
    while True:
        threading.Event().wait(1)
        try:
            if config_store.reload_if_changed():
                print(f"[config] Rechargé — {len(config_store.get_instances())} instance(s)")
        except Exception as e:
            print(f"[config] Erreur rechargement : {e}")


def _start_monitor():
    global _monitor

    hub_cfg = config_store.CFG.get('hub', {})
    base_url = str(hub_cfg.get('base_url', '')).rstrip('/')
    endpoint = str(hub_cfg.get('state_endpoint', '/api/agent/instances/state'))
    interval = int(hub_cfg.get('monitor_interval', 5))
    token = config_store.AUTH_CFG['jwt_secret']

    if not base_url:
        print('[monitor] Hub push disabled: hub.base_url is empty')
        return

    target_url = f'{base_url}{endpoint}'

    def push_state(snapshot):
        payload = {
            'instances': snapshot,
            'system_info': get_system_info(),
        }
        result = post_json(target_url, payload, token=token)
        if not result.get('ok'):
            print(f"[monitor] Hub push failed: {result.get('status')} {result.get('body')}")

    _monitor = SnapshotMonitor(interval=interval)
    _monitor.start(on_change=push_state)
    push_state(_monitor.snapshot())
    print(f'[monitor] Hub push enabled every {interval}s -> {target_url}')


def create_app():
    app = Flask(__name__)
    sock = Sock(app)

    @app.route('/api/system', methods=['GET'])
    def system_info():
        require_jwt()
        return jsonify(get_system_info())

    register_instance_routes(app)
    register_config_routes(app)
    register_log_routes(app, sock)
    register_steam_routes(app)

    return app


_watcher = threading.Thread(target=_watch_config, daemon=True)
_watcher.start()
_start_monitor()

app = create_app()


if __name__ == '__main__':
    from waitress import serve
    print(f"PitLane Server Agent démarré sur {config_store.HTTP_CFG['host']}:{config_store.HTTP_CFG['port']}")
    serve(app, host=config_store.HTTP_CFG['host'], port=config_store.HTTP_CFG['port'])
