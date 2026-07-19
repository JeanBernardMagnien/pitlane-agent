import json
import os
from pathlib import Path
import tempfile
from typing import Any


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


def _write_config(path: Path, config: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f'.{path.name}.',
            suffix='.tmp',
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as temporary_file:
            temporary_file.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, path)
        _sync_parent_directory(path.parent)

        return path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _sync_parent_directory(directory: Path) -> None:
    if os.name == 'nt' or not hasattr(os, 'O_DIRECTORY'):
        return

    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_current_config(game_cfg: dict, instance_id: str, config: dict[str, Any]) -> Path:
    return _write_config(current_config_path(game_cfg, instance_id), config)


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

    return _write_config(path, config)


def load_current_config(game_cfg: dict, instance_id: str) -> tuple[Path, dict[str, Any]]:
    path = current_config_path(game_cfg, instance_id)

    if not path.exists():
        raise FileNotFoundError(f"Aucune config courante pour l'instance {instance_id}")

    config = json.loads(path.read_text(encoding='utf-8'))

    if not isinstance(config, dict):
        raise ValueError(f"La config courante de l'instance {instance_id} est invalide")

    return path, config
