import hashlib
import json
import re
from pathlib import Path


CATALOG_SCHEMA_VERSION = 1


def _read_json(path: Path, expected_key: str) -> dict:
    if not path.is_file():
        raise ValueError(f'fichier catalogue AC EVO introuvable : {path}')

    try:
        payload = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'fichier catalogue AC EVO invalide : {path}') from exc

    if not isinstance(payload, dict) or not isinstance(payload.get(expected_key), list):
        raise ValueError(f'clé {expected_key} absente du catalogue AC EVO : {path}')

    return payload


def _build_id(appmanifest_path: Path) -> str:
    if not appmanifest_path.is_file():
        raise ValueError(f'appmanifest AC EVO introuvable : {appmanifest_path}')

    content = appmanifest_path.read_text(encoding='utf-8', errors='replace')
    match = re.search(r'"buildid"\s+"(\d+)"', content)
    if not match:
        raise ValueError('buildid introuvable dans l’appmanifest AC EVO')

    return match.group(1)


def _canonical_fingerprint(cars: dict, tracks: dict) -> str:
    canonical = json.dumps(
        {'cars': cars, 'tracks': tracks},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def catalog_snapshot(game_cfg: dict, steam_cfg: dict) -> tuple[dict, int]:
    raw_install_path = str(game_cfg.get('install_path') or '').strip()
    raw_appmanifest_path = str(steam_cfg.get('appmanifest_path') or '').strip()

    if not raw_install_path:
        return {'error': 'Chemin installation AC EVO non configuré'}, 503
    if not raw_appmanifest_path:
        return {'error': 'Chemin appmanifest AC EVO non configuré'}, 503

    install_path = Path(raw_install_path)
    appmanifest_path = Path(raw_appmanifest_path)

    try:
        cars = _read_json(install_path / 'cars.json', 'cars')
        tracks = _read_json(install_path / 'events_race_weekend.json', 'events')
        build_id = _build_id(appmanifest_path)
    except ValueError as exc:
        return {'error': str(exc)}, 422

    return {
        'catalog_schema_version': CATALOG_SCHEMA_VERSION,
        'build_id': build_id,
        'fingerprint': _canonical_fingerprint(cars, tracks),
        'cars': cars,
        'tracks': tracks,
    }, 200
