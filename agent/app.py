import logging
import threading

from flask import Flask, jsonify
from flask_sock import Sock

from core import config_store
from core.auth import require_jwt
from core.system_info import get_system_info
from routes.instances import register_instance_routes
from routes.logs import register_log_routes
from routes.steam import register_steam_routes
from services.hub_ws_client import start_hub_ws_clients
from services.runtime_reporter import start_runtime_reporter
from services.runtime_state import restore_runtime_state


def _watch_config():
    while True:
        threading.Event().wait(1)
        try:
            if config_store.reload_if_changed():
                logging.info('[config] Rechargé')
        except Exception as e:
            logging.error('[config] Erreur rechargement : %s', e)


def create_app():
    app = Flask(__name__)
    sock = Sock(app)

    @app.route('/api/system', methods=['GET'])
    def system_info():
        require_jwt()
        return jsonify(get_system_info())

    register_instance_routes(app)
    register_log_routes(app, sock)
    register_steam_routes(app)

    return app


_watcher = threading.Thread(target=_watch_config, daemon=True)
_watcher.start()

restored_instances = restore_runtime_state(config_store.LOGGING_CFG)
if restored_instances:
    logging.info('[runtime-state] %d instance(s) restaurée(s)', restored_instances)

app = create_app()
start_runtime_reporter()
start_hub_ws_clients()


if __name__ == '__main__':
    from waitress import serve
    print(f"PitLane Server Agent démarré sur {config_store.HTTP_CFG['host']}:{config_store.HTTP_CFG['port']}")
    serve(app, host=config_store.HTTP_CFG['host'], port=config_store.HTTP_CFG['port'])
