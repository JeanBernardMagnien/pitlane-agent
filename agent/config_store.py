import threading
from pathlib import Path

import yaml


CONFIG_PATH = Path('config.yml')
_config_lock = threading.Lock()
_config_mtime = CONFIG_PATH.stat().st_mtime
CFG = {}
GAME_CFG = {}
AUTH_CFG = {}
HTTP_CFG = {}
LOGGING_CFG = {}
INSTANCES = {}


def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def save_config(cfg: dict):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def _apply_config(cfg: dict):
    global CFG, GAME_CFG, AUTH_CFG, HTTP_CFG, LOGGING_CFG, INSTANCES
    CFG = cfg
    GAME_CFG = cfg['game']
    AUTH_CFG = cfg['auth']
    HTTP_CFG = cfg['http']
    LOGGING_CFG = cfg['logging']
    INSTANCES = {inst['id']: inst for inst in cfg['instances']}


def reload_from_disk():
    global _config_mtime
    cfg = load_config()
    with _config_lock:
        _apply_config(cfg)
        _config_mtime = CONFIG_PATH.stat().st_mtime


def reload_if_changed() -> bool:
    global _config_mtime
    mtime = CONFIG_PATH.stat().st_mtime
    if mtime == _config_mtime:
        return False

    cfg = load_config()
    with _config_lock:
        _apply_config(cfg)
        _config_mtime = mtime
    return True


def mark_saved():
    global _config_mtime
    with _config_lock:
        _config_mtime = CONFIG_PATH.stat().st_mtime


def get_instances() -> list[dict]:
    with _config_lock:
        return list(INSTANCES.values())


def get_instance(instance_id: str) -> dict | None:
    with _config_lock:
        return INSTANCES.get(instance_id)


def has_instance(instance_id: str) -> bool:
    with _config_lock:
        return instance_id in INSTANCES


def set_instance(instance_id: str, instance: dict):
    with _config_lock:
        INSTANCES[instance_id] = instance


def remove_instance(instance_id: str):
    with _config_lock:
        INSTANCES.pop(instance_id, None)


reload_from_disk()
