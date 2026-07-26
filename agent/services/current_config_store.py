import json
from pathlib import Path
from typing import Any

from services.atomic_json_store import write_json_atomic


def _configs_root(game_cfg: dict) -> Path:
    return Path(game_cfg['configs_path'])


def _current_dir(game_cfg: dict) -> Path:
    return _configs_root(game_cfg) / 'current'


def _history_dir(game_cfg: dict) -> Path:
    return _configs_root(game_cfg) / 'history'


def _safe_name(value: str | int | None, fallback: str) -> str:
    raw_value = str(value or fallback).strip() or fallback
    return Path(raw_value).name


def current_config_path(game_cfg: dict, instance_id: str) -> Path:
    safe_instance_id = _safe_name(instance_id, 'instance')
    return _current_dir(game_cfg) / f'{safe_instance_id}.json'


def history_config_path(game_cfg: dict, launch_id: str | int | None, instance_id: str) -> Path:
    safe_launch_id = _safe_name(launch_id, 'manual')
    safe_instance_id = _safe_name(instance_id, 'instance')
    return _history_dir(game_cfg) / f'launch_{safe_launch_id}_{safe_instance_id}.json'


def save_current_config(game_cfg: dict, instance_id: str, config: dict[str, Any]) -> Path:
    return write_json_atomic(current_config_path(game_cfg, instance_id), config)


def delete_current_config(game_cfg: dict, instance_id: str) -> bool:
    path = current_config_path(game_cfg, instance_id)
    if not path.exists():
        return False

    path.unlink()
    return True


def save_launch_history_config(
    game_cfg: dict,
    launch_id: str | int | None,
    instance_id: str,
    config: dict[str, Any],
) -> Path:
    path = history_config_path(game_cfg, launch_id, instance_id)
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        if existing != config:
            raise ValueError(
                f'La configuration historique du lancement {launch_id or "manual"} est immuable'
            )
        return path

    return write_json_atomic(path, config)


def load_current_config(game_cfg: dict, instance_id: str) -> tuple[Path, dict[str, Any]]:
    path = current_config_path(game_cfg, instance_id)

    if not path.exists():
        raise FileNotFoundError(f"Aucune config courante pour l'instance {instance_id}")

    config = json.loads(path.read_text(encoding='utf-8'))

    if not isinstance(config, dict):
        raise ValueError(f"La config courante de l'instance {instance_id} est invalide")

    return path, config
