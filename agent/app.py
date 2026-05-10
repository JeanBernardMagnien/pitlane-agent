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


def _watch_config():
    while True:
        threading.Event().wait(1)
        try:
            if config_store.reload_if_changed():
                print(f"[config] Rechargé — {len(config_store.get_instances())} instance(s)")
        except Exception as e:
            print(f"[config] Erreur rechargement : {e}")


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

app = create_app()


if __name__ == '__main__':
    from waitress import serve
    print(f"PitLane Server Agent démarré sur {config_store.HTTP_CFG['host']}:{config_store.HTTP_CFG['port']}")
    serve(app, host=config_store.HTTP_CFG['host'], port=config_store.HTTP_CFG['port'])
