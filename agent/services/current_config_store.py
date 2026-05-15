import json
from pathlib import Path
from typing import Any


def _configs_root(game_cfg: dict) -> Path:
    return Path(game_cfg['configs_path'])


def _current_dir(game_cfg: dict) -> Path:
    return _configs_root(game_cfg) / 'current'


def _history_dir(game_cfg: dict) -> Path:
    return _configs_root(game_cfg) / 'history'


def current_config_path(game_cfg: dict, instance_id: str) -> Path:
    return _current_dir(game_cfg) / f'{instance_id}.json'


def history_config_path(game_cfg: dict, launch_id: str | int, instance_id: str) -> Path:
    return _history_dir(game_cfg) / f'launch_{launch_id}_{instance_id}.json'


def save_current_config(game_cfg: dict, instance_id: str, config: dict[str, Any]) -> Path:
    path = current_config_path(game_cfg, instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    return path


def save_launch_history_config(
    game_cfg: dict,
    launch_id: str | int | None,
    instance_id: str,
    config: dict[str, Any],
) -> Path | None:
    if launch_id in (None, ''):
        return None

    path = history_config_path(game_cfg, launch_id, instance_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )

    return path


def load_current_config(game_cfg: dict, instance_id: str) -> tuple[Path, dict[str, Any]]:
    path = current_config_path(game_cfg, instance_id)

    if not path.exists():
        raise FileNotFoundError(f"Aucune config courante pour l'instance {instance_id}")

    return path, json.loads(path.read_text(encoding='utf-8'))
