import json
from pathlib import Path
import re
from typing import Any

from services.atomic_json_store import write_json_atomic


ENTRY_LIST_SCHEMA_VERSION = 1
ENTRY_LIST_MODE_DISABLED = 'disabled'
ENTRY_LIST_MODE_STEAM_ID_WHITELIST = 'steamid_whitelist'


def materialize_entry_list(
    config: dict,
    game_cfg: dict,
    launch_id: str | int | None,
    instance_id: str,
) -> dict:
    server = config.setdefault('Server', {})
    entry_list = config.get('EntryList')

    # Compatibilité avec les configurations créées avant la Phase 6.
    if entry_list is None:
        server['EntryListPath'] = ''
        return config

    if not isinstance(entry_list, dict):
        raise ValueError('EntryList doit être un objet')
    if entry_list.get('schema_version') != ENTRY_LIST_SCHEMA_VERSION:
        raise ValueError('Version EntryList non supportée')

    mode = entry_list.get('mode')
    if mode == ENTRY_LIST_MODE_DISABLED:
        server['EntryListPath'] = ''
        return config
    if mode != ENTRY_LIST_MODE_STEAM_ID_WHITELIST:
        raise ValueError('Mode EntryList non supporté')

    native_payload = _validated_native_payload(entry_list)
    path = save_launch_entry_list(
        game_cfg,
        launch_id,
        instance_id,
        native_payload,
    )
    server['EntryListPath'] = str(path)

    return config


def entry_list_path(
    game_cfg: dict,
    launch_id: str | int | None,
    instance_id: str,
) -> Path:
    root = Path(game_cfg['configs_path']) / 'entrylists'
    safe_launch_id = _safe_name(launch_id, 'manual')
    safe_instance_id = _safe_name(instance_id, 'instance')

    return root / f'launch_{safe_launch_id}_{safe_instance_id}.json'


def save_launch_entry_list(
    game_cfg: dict,
    launch_id: str | int | None,
    instance_id: str,
    native_payload: dict[str, Any],
) -> Path:
    path = entry_list_path(game_cfg, launch_id, instance_id)
    if path.exists():
        existing = json.loads(path.read_text(encoding='utf-8'))
        if existing != native_payload:
            raise ValueError(
                f'L’Entry list historique du lancement {launch_id or "manual"} est immuable'
            )
        return path

    return write_json_atomic(path, native_payload)


def _validated_native_payload(entry_list: dict) -> dict[str, list]:
    native_payload = entry_list.get('native_payload')
    if not isinstance(native_payload, dict):
        raise ValueError('EntryList.native_payload doit être un objet')

    whitelist = native_payload.get('steamid_whitelist')
    entrylist = native_payload.get('entrylist')
    blacklist = native_payload.get('steamid_blacklist')
    if not isinstance(whitelist, list):
        raise ValueError('EntryList.native_payload.steamid_whitelist doit être une liste')
    if entrylist != []:
        raise ValueError('EntryList V1 ne permet pas encore d’imposer une voiture')
    if blacklist != []:
        raise ValueError('EntryList V1 ne permet pas de blacklist locale')

    steam_ids = []
    normalized_whitelist = []
    for item in whitelist:
        steam_id = item.get('steamid') if isinstance(item, dict) else None
        if not isinstance(steam_id, str) or re.fullmatch(r'\d{17}', steam_id) is None:
            raise ValueError('Entry list : SteamID invalide')
        if steam_id in steam_ids:
            raise ValueError('Entry list : SteamID dupliqué')

        steam_ids.append(steam_id)
        normalized_whitelist.append({'steamid': steam_id})

    if entry_list.get('authorized_count') != len(normalized_whitelist):
        raise ValueError('EntryList.authorized_count ne correspond pas à la whitelist')

    metadata_entries = entry_list.get('entries')
    if not isinstance(metadata_entries, list):
        raise ValueError('EntryList.entries doit être une liste')
    metadata_steam_ids = [
        item.get('steam_id')
        for item in metadata_entries
        if isinstance(item, dict)
    ]
    if metadata_steam_ids != steam_ids:
        raise ValueError('EntryList.entries diverge de la whitelist native')

    return {
        'entrylist': [],
        'steamid_whitelist': normalized_whitelist,
        'steamid_blacklist': [],
    }


def _safe_name(value: str | int | None, fallback: str) -> str:
    raw_value = str(value or fallback).strip() or fallback
    return Path(raw_value).name
