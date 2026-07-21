from copy import deepcopy
import hashlib
import hmac
import json
import re


SCHEMA_VERSION = 2
LEGACY_MATERIALIZED_FIELDS = [
    'Server.AdminPassword',
    'Server.DriverPassword',
    'Server.LaunchSessionId',
    'Server.ResultCorrelationId',
    'Server.ResultsPath',
    'Server.ResultsPostUrl',
    'Server.SpectatorPassword',
]
MATERIALIZED_FIELDS = [
    'Server.AdminPassword',
    'Server.DriverPassword',
    'Server.EntryListPath',
    'Server.LaunchSessionId',
    'Server.ResultCorrelationId',
    'Server.ResultsPath',
    'Server.ResultsPostUrl',
    'Server.SpectatorPassword',
]
MATERIALIZED_FIELDS_BY_SCHEMA = {
    1: LEGACY_MATERIALIZED_FIELDS,
    SCHEMA_VERSION: MATERIALIZED_FIELDS,
}


class RuntimeBundleError(ValueError):
    pass


def canonical_json(payload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )


def calculate_runtime_bundle_hash(bundle: dict) -> str:
    return hashlib.sha256(canonical_json(bundle).encode('utf-8')).hexdigest()


def validate_runtime_bundle(
    bundle: dict,
    announced_hash: str,
    materialized_config: dict,
) -> str:
    if not isinstance(bundle, dict):
        raise RuntimeBundleError('runtime_bundle requis')
    schema_version = bundle.get('schema_version')
    expected_materialized_fields = MATERIALIZED_FIELDS_BY_SCHEMA.get(schema_version)
    if expected_materialized_fields is None:
        raise RuntimeBundleError('Version de bundle runtime non supportée')
    if bundle.get('materialized_fields') != expected_materialized_fields:
        raise RuntimeBundleError('Liste des champs matérialisés du bundle invalide')

    canonical_config = bundle.get('runtime_config')
    if not isinstance(canonical_config, dict):
        raise RuntimeBundleError('runtime_bundle.runtime_config requis')
    if not isinstance(materialized_config, dict):
        raise RuntimeBundleError('runtime_config requis')

    normalized_hash = str(announced_hash or '').strip().lower()
    if re.fullmatch(r'[a-f0-9]{64}', normalized_hash) is None:
        raise RuntimeBundleError('Empreinte de bundle runtime invalide')

    calculated_hash = calculate_runtime_bundle_hash(bundle)
    if not hmac.compare_digest(calculated_hash, normalized_hash):
        raise RuntimeBundleError('L’empreinte du bundle runtime ne correspond pas à son contenu')

    redacted_config = deepcopy(materialized_config)
    for path in expected_materialized_fields:
        _copy_path_value(canonical_config, redacted_config, path.split('.'))

    if redacted_config != canonical_config:
        raise RuntimeBundleError('La configuration privée diverge du bundle runtime canonique')

    return normalized_hash


def _copy_path_value(source: dict, target: dict, segments: list[str]) -> None:
    source_cursor = source
    target_cursor = target

    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        if segment not in source_cursor:
            raise RuntimeBundleError(f'Champ canonique absent du bundle : {".".join(segments)}')
        if is_last:
            target_cursor[segment] = deepcopy(source_cursor[segment])
            return
        if not isinstance(source_cursor[segment], dict):
            raise RuntimeBundleError(f'Chemin canonique invalide : {".".join(segments)}')
        if not isinstance(target_cursor.get(segment), dict):
            target_cursor[segment] = {}

        source_cursor = source_cursor[segment]
        target_cursor = target_cursor[segment]
