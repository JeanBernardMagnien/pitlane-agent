import os
import re
import subprocess
import threading
from pathlib import Path

from services.server_manager import _running


_steam_process = None
_steam_process_lock = threading.Lock()


def _vdf_block(text: str, key: str, start: int = 0) -> str | None:
    m = re.search(rf'"{ re.escape(key) }"\s*\{{', text[start:])
    if not m:
        return None

    pos = start + m.end()
    depth = 1

    while pos < len(text) and depth:
        if text[pos] == '{':
            depth += 1
        elif text[pos] == '}':
            depth -= 1
        pos += 1

    return text[start + m.end(): pos - 1]


def _read_steam_log(log_path: Path) -> list[str]:
    if not log_path.exists():
        return []

    raw = log_path.read_bytes()
    if not raw:
        return []

    for encoding in ('utf-8', 'cp850', 'cp1252'):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode('utf-8', errors='replace')

    lines = []
    for line in text.replace('\r', '\n').split('\n'):
        line = line.strip()
        if line:
            lines.append(line)

    return lines[-100:]


def check_steam_update(steam_cfg: dict, body: dict) -> tuple[dict, int]:
    steamcmd_path = steam_cfg.get('steamcmd_path', '')
    if not steamcmd_path:
        return {'error': 'steamcmd non configuré'}, 503

    appmanifest_path = steam_cfg.get('appmanifest_path', '')
    if not appmanifest_path:
        return {'error': 'Chemin appmanifest non configuré'}, 503

    username = str(body.get('steam_username') or '').strip()
    password = str(body.get('steam_password') or '').strip()
    if not username or not password:
        return {'error': 'steam_username et steam_password requis'}, 400

    manifest_file = Path(appmanifest_path)
    if not manifest_file.exists():
        return {'error': f"appmanifest introuvable : {appmanifest_path}"}, 404

    content = manifest_file.read_text(encoding='utf-8', errors='replace')
    local_match = re.search(r'"buildid"\s+"(\d+)"', content)
    if not local_match:
        return {'error': 'buildid introuvable dans appmanifest'}, 500

    local_buildid = int(local_match.group(1))
    app_id = str(steam_cfg.get('app_id', 4564210))

    try:
        result = subprocess.run(
            [
                steamcmd_path,
                '+login', username, password,
                '+app_info_update', '1',
                '+app_info_print', app_id,
                '+quit',
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        output = result.stdout
    except subprocess.TimeoutExpired:
        return {'error': 'steamcmd timeout (90s)'}, 504
    except Exception as e:
        return {'error': f"steamcmd erreur : {e}"}, 502

    branches_block = _vdf_block(output, 'branches')
    if not branches_block:
        return {'error': 'Section "branches" introuvable dans la sortie steamcmd'}, 502

    public_block = _vdf_block(branches_block, 'public')
    if not public_block:
        return {'error': 'Branche "public" introuvable dans steamcmd'}, 502

    remote_match = re.search(r'"buildid"\s+"(\d+)"', public_block)
    if not remote_match:
        return {'error': 'buildid distant introuvable dans la branche public'}, 502

    remote_buildid = int(remote_match.group(1))
    up_to_date = local_buildid == remote_buildid

    return {
        'up_to_date': up_to_date,
        'local_build': local_buildid,
        'remote_build': remote_buildid,
        'update_available': not up_to_date,
    }, 200


def start_steam_update(steam_cfg: dict, logging_cfg: dict, body: dict) -> tuple[dict, int]:
    global _steam_process

    logs_path = logging_cfg['logs_path']
    steamcmd_path = steam_cfg.get('steamcmd_path', '')
    if not steamcmd_path:
        return {'error': 'Mise à jour à distance non configurée'}, 503

    running_instances = [
        iid for iid, info in _running.items()
        if info['process'].poll() is None
    ]
    if running_instances:
        return {'error': 'Arrêtez les instances avant de mettre à jour'}, 409

    username = body.get('steam_username')
    password = body.get('steam_password')
    if not username or not password:
        return {'error': 'steam_username et steam_password requis'}, 400

    app_id = str(steam_cfg.get('app_id', 4564210))
    logs_dir = Path(logs_path)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / 'steam_update.log'
    steamcmd_dir = str(Path(steamcmd_path).parent)

    cmd = [
        steamcmd_path,
        '+force_install_dir', steamcmd_dir,
        '+login', username, password,
        '+app_update', app_id, 'validate',
        '+quit',
    ]

    create_flags = 0x08000000 if os.name == 'nt' else 0
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=create_flags,
    )

    def _drain(proc, path):
        with open(path, 'wb') as f:
            while True:
                chunk = proc.stdout.read(256)
                if not chunk:
                    break
                f.write(chunk)
                f.flush()

    threading.Thread(target=_drain, args=(process, str(log_path)), daemon=True).start()
    with _steam_process_lock:
        _steam_process = {
            'process': process,
            'pid': process.pid,
            'log_path': str(log_path),
        }

    return {'status': 'started', 'pid': process.pid}, 202


def get_steam_update_logs(logging_cfg: dict) -> tuple[dict, int]:
    try:
        default_log_path = Path(logging_cfg['logs_path']) / 'steam_update.log'

        with _steam_process_lock:
            steam_state = _steam_process.copy() if _steam_process else {}

        log_path = Path(steam_state.get('log_path') or default_log_path)

        try:
            lines = _read_steam_log(log_path)
            log_size = log_path.stat().st_size if log_path.exists() else 0
        except Exception as e:
            return {
                'lines': [f'Erreur lecture log: {e}'],
                'finished': False,
                'running': True,
                'success': False,
                'exit_code': None,
                'pid': steam_state.get('pid'),
                'log_path': str(log_path),
                'log_size': None,
            }, 200

        proc = steam_state.get('process')
        if proc is not None:
            exit_code = proc.poll()
            finished = exit_code is not None
            success = finished and exit_code == 0
            running = not finished
        else:
            exit_code = None
            finished = True
            success = False
            running = False

        return {
            'lines': lines,
            'finished': finished,
            'running': running,
            'success': success,
            'exit_code': exit_code,
            'pid': steam_state.get('pid'),
            'log_path': str(log_path),
            'log_size': log_size,
        }, 200

    except Exception as e:
        return {
            'lines': [f'Erreur route logs: {e}'],
            'finished': True,
            'running': False,
            'success': False,
            'exit_code': None,
            'pid': None,
        }, 500
