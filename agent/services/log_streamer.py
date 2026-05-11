import time
from pathlib import Path


def tail_log(ws, log_file: str, max_lines: int = 100):
    """
    Envoie les dernières lignes du log au client WebSocket,
    puis continue à streamer les nouvelles lignes en temps réel.
    """
    path = Path(log_file)

    if path.exists():
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        for line in lines[-max_lines:]:
            ws.send(line)

    last_size = path.stat().st_size if path.exists() else 0

    while True:
        time.sleep(0.5)

        if not path.exists():
            continue

        current_size = path.stat().st_size

        if current_size > last_size:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                f.seek(last_size)
                new_content = f.read()
            for line in new_content.splitlines():
                if line.strip():
                    ws.send(line)
            last_size = current_size

        elif current_size < last_size:
            last_size = current_size
