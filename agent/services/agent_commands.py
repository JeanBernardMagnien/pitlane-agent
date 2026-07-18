from pathlib import Path

from core import config_store
from core.system_info import get_system_info
from core.firewall import close_ports, open_ports
from services.current_config_store import (
    load_current_config,
    save_current_config,
    save_launch_history_config,
)
from services.encode_config import encode_payload
from services.runtime_config_compiler import (
    InstancePortsOutOfSync,
    finalize_launch_config,
)
from services.runtime_reporter import build_runtime_report
from services.result_pipeline import (
    purge_delivered_result_artifacts,
    register_result_launch,
    resync_result_artifacts,
)
from services.server_manager import (
    _running,
    already_executed_command,
    restart_instance,
    start_instance,
    stop_instance,
)
from services.steam_manager import (
    check_steam_update,
    get_steam_update_logs,
    start_steam_update,
)


def _error(message: str, status_code: int = 400) -> tuple[dict, int]:
    return {'error': message}, status_code


def _instance_from_payload(body: dict, fallback_instance_id: str | None = None) -> dict | None:
    instance = body.get('instance')
    if not isinstance(instance, dict):
        return None

    instance_id = str(instance.get('id') or fallback_instance_id or '').strip()
    if not instance_id:
        return None

    try:
        return {
            'id': instance_id,
            'name': str(instance.get('name') or instance_id).strip(),
            'tcp_port': int(instance['tcp_port']),
            'udp_port': int(instance['udp_port']),
            'http_port': int(instance['http_port']),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _ports_from_payload(body: dict, key: str = 'ports') -> dict | None:
    ports = body.get(key)
    if not isinstance(ports, dict):
        return None

    try:
        return {
            'tcp_port': int(ports['tcp_port']),
            'udp_port': int(ports['udp_port']),
            'http_port': int(ports['http_port']),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _instance_id_from_payload(body: dict) -> str | None:
    instance_id = str(body.get('instance_id') or '').strip()
    if instance_id:
        return instance_id

    instance = body.get('instance')
    if isinstance(instance, dict):
        instance_id = str(instance.get('id') or '').strip()
        if instance_id:
            return instance_id

    return None


def _command_id_from_payload(body: dict) -> str | None:
    command_id = str(body.get('_pitlane_command_id') or '').strip()
    return command_id or None


def prepare_instance_command(instance_id: str, body: dict) -> tuple[dict, int]:
    ports = _ports_from_payload(body)
    if not ports:
        return _error('ports requis')

    fw_errors = open_ports(
        instance_id,
        ports['tcp_port'],
        ports['udp_port'],
        ports['http_port'],
    )

    response = {'status': 'prepared', 'instance_id': instance_id}
    if fw_errors:
        response['fw_warnings'] = fw_errors

    return response, 200


def update_instance_network_command(instance_id: str, body: dict) -> tuple[dict, int]:
    if instance_id in _running and _running[instance_id]['process'].poll() is None:
        return _error("Arrêtez l'instance avant de modifier ses ports", 409)

    previous_ports = _ports_from_payload(body, 'previous_ports')
    ports = _ports_from_payload(body)

    if not previous_ports or not ports:
        return _error('previous_ports et ports requis')

    fw_errors = []
    if previous_ports != ports:
        fw_errors.extend(close_ports(
            instance_id,
            previous_ports['tcp_port'],
            previous_ports['udp_port'],
            previous_ports['http_port'],
        ))
        fw_errors.extend(open_ports(
            instance_id,
            ports['tcp_port'],
            ports['udp_port'],
            ports['http_port'],
        ))

    response = {'status': 'network_updated', 'instance_id': instance_id}
    if fw_errors:
        response['fw_warnings'] = fw_errors

    return response, 200


def cleanup_instance_command(instance_id: str, body: dict) -> tuple[dict, int]:
    if instance_id in _running and _running[instance_id]['process'].poll() is None:
        return _error("Arrêtez l'instance avant de la nettoyer", 409)

    ports = _ports_from_payload(body)
    if not ports:
        return _error('ports requis')

    fw_errors = close_ports(
        instance_id,
        ports['tcp_port'],
        ports['udp_port'],
        ports['http_port'],
    )

    response = {'status': 'cleaned', 'instance_id': instance_id}
    if fw_errors:
        response['fw_warnings'] = fw_errors

    return response, 200


def launch_instance_command(instance_id: str, body: dict) -> tuple[dict, int]:
    inst = _instance_from_payload(body, instance_id)
    if not inst:
        return _error('instance complète requise')

    command_id = _command_id_from_payload(body)
    already_executed = already_executed_command(instance_id, command_id)
    if already_executed is not None:
        return already_executed, 200

    runtime_config = body.get('runtime_config')
    launch_id = body.get('launch_id')
    restart_if_running = bool(body.get('restart_if_running', False))

    if not isinstance(runtime_config, dict):
        return _error('runtime_config requis')

    try:
        runtime_config = finalize_launch_config(
            runtime_config,
            inst,
            config_store.GAME_CFG,
        )

        save_current_config(
            config_store.GAME_CFG,
            instance_id,
            runtime_config,
        )

        save_launch_history_config(
            config_store.GAME_CFG,
            launch_id,
            instance_id,
            runtime_config,
        )

        serverconfig_b64, seasondefinition_b64 = encode_payload(runtime_config)

    except InstancePortsOutOfSync as e:
        return {
            'code': 'INSTANCE_PORTS_OUT_OF_SYNC',
            'expected': e.expected,
            'received': e.received,
        }, 409
    except Exception as e:
        return _error(f'Erreur préparation lancement : {e}')

    try:
        if restart_if_running:
            result = restart_instance(
                instance_id,
                inst,
                config_store.GAME_CFG,
                config_store.LOGGING_CFG,
                serverconfig_b64,
                seasondefinition_b64,
                filename=f'launch-{launch_id or "manual"}',
                before_start=lambda: register_result_launch(instance_id, launch_id, runtime_config),
                command_id=command_id,
            )
        else:
            register_result_launch(instance_id, launch_id, runtime_config)
            result = start_instance(
                inst,
                config_store.GAME_CFG,
                config_store.LOGGING_CFG,
                serverconfig_b64,
                seasondefinition_b64,
                filename=f'launch-{launch_id or "manual"}',
                command_id=command_id,
            )
    except Exception as e:
        return _error(f'Erreur lancement ou collecte résultats : {e}')

    return result, 409 if 'error' in result else 200


def start_instance_command(instance_id: str, body: dict) -> tuple[dict, int]:
    inst = _instance_from_payload(body, instance_id)
    if not inst:
        return _error('instance complète requise')

    command_id = _command_id_from_payload(body)
    already_executed = already_executed_command(instance_id, command_id)
    if already_executed is not None:
        return already_executed, 200

    try:
        _, runtime_config = load_current_config(
            config_store.GAME_CFG,
            instance_id,
        )

        serverconfig_b64, seasondefinition_b64 = encode_payload(runtime_config)

    except FileNotFoundError as e:
        return _error(str(e), 404)
    except Exception as e:
        return _error(f'Erreur chargement config : {e}')

    result = start_instance(
        inst,
        config_store.GAME_CFG,
        config_store.LOGGING_CFG,
        serverconfig_b64,
        seasondefinition_b64,
        filename='current-config',
        command_id=command_id,
    )

    return result, 409 if 'error' in result else 200


def stop_instance_command(instance_id: str, body: dict | None = None) -> tuple[dict, int]:
    body = body or {}
    requested_reason = str(body.get('stop_reason') or 'manual_stop').strip()
    stop_reason = requested_reason if requested_reason in {'manual_stop', 'normal', 'preempted'} else 'manual_stop'
    result = stop_instance(instance_id, config_store.LOGGING_CFG, reason=stop_reason)
    return result, 409 if 'error' in result else 200


def restart_instance_command(instance_id: str, body: dict) -> tuple[dict, int]:
    inst = _instance_from_payload(body, instance_id)

    if not inst:
        info = _running.get(instance_id)
        inst = info.get('instance') if info else None

    if not inst:
        return _error('instance complète requise')

    command_id = _command_id_from_payload(body)
    already_executed = already_executed_command(instance_id, command_id)
    if already_executed is not None:
        return already_executed, 200

    try:
        _, runtime_config = load_current_config(
            config_store.GAME_CFG,
            instance_id,
        )

        serverconfig_b64, seasondefinition_b64 = encode_payload(runtime_config)

    except FileNotFoundError as e:
        return _error(str(e), 404)
    except Exception as e:
        return _error(f'Erreur chargement config : {e}')

    result = restart_instance(
        instance_id,
        inst,
        config_store.GAME_CFG,
        config_store.LOGGING_CFG,
        serverconfig_b64,
        seasondefinition_b64,
        filename='current-config',
        command_id=command_id,
    )

    return result, 409 if 'error' in result else 200


def get_instance_logs_command(instance_id: str, body: dict | None = None) -> tuple[dict, int]:
    logs_path = Path(config_store.LOGGING_CFG['logs_path'])
    max_lines = config_store.LOGGING_CFG.get('max_lines', 500)

    log_files = sorted(logs_path.glob(f"log_{instance_id}_*.log"), reverse=True)
    if not log_files:
        return {'lines': []}, 200

    lines = log_files[0].read_text(encoding='utf-8', errors='replace').splitlines()
    return {'lines': lines[-max_lines:]}, 200


def resync_results_command(instance_id: str, body: dict | None = None) -> tuple[dict, int]:
    body = body or {}
    launch_id = body.get('launch_id')
    result_correlation_id = str(body.get('result_correlation_id') or '').strip() or None
    try:
        normalized_launch_id = int(launch_id) if launch_id not in (None, '') else None
    except (TypeError, ValueError):
        return _error('launch_id invalide')

    return resync_result_artifacts(instance_id, normalized_launch_id, result_correlation_id), 200


def purge_results_command(instance_id: str, body: dict | None = None) -> tuple[dict, int]:
    body = body or {}
    artifact_ids = body.get('artifact_ids')
    if not isinstance(artifact_ids, list) or not all(isinstance(value, str) for value in artifact_ids):
        return _error('artifact_ids doit être une liste de chaînes')

    try:
        return purge_delivered_result_artifacts(
            artifact_ids,
            instance_id=instance_id,
            execute=body.get('execute') is True,
        ), 200
    except ValueError as exc:
        return _error(str(exc))


COMMANDS = {
    'prepare_instance': prepare_instance_command,
    'prepare': prepare_instance_command,
    'update_instance_network': update_instance_network_command,
    'update_network': update_instance_network_command,
    'cleanup_instance': cleanup_instance_command,
    'cleanup': cleanup_instance_command,
    'launch_instance': launch_instance_command,
    'launch_runtime_config': launch_instance_command,
    'launch': launch_instance_command,
    'start_instance': start_instance_command,
    'start': start_instance_command,
    'stop_instance': stop_instance_command,
    'stop': stop_instance_command,
    'restart_instance': restart_instance_command,
    'restart': restart_instance_command,
    'get_instance_logs': get_instance_logs_command,
    'instance_logs': get_instance_logs_command,
    'get_logs': get_instance_logs_command,
    'logs': get_instance_logs_command,
    'resync_result_artifacts': resync_results_command,
    'resync_results': resync_results_command,
    'purge_result_artifacts': purge_results_command,
}


def execute_agent_command(command: str, payload: dict | None = None) -> tuple[dict, int]:
    payload = payload or {}
    if not isinstance(payload, dict):
        return _error('payload invalide')

    if command in ('runtime_report', 'get_runtime_report'):
        return build_runtime_report(), 200

    if command in ('system_info', 'get_system_info'):
        return get_system_info(), 200

    if command in ('steam_update_check', 'check_steam_update', 'update_steam_check'):
        return check_steam_update(config_store.CFG.get('steam', {}), payload)

    if command in ('steam_update', 'update_steam'):
        return start_steam_update(
            config_store.CFG.get('steam', {}),
            config_store.GAME_CFG,
            config_store.LOGGING_CFG,
            payload,
        )

    if command in ('steam_update_logs', 'get_steam_update_logs'):
        return get_steam_update_logs(config_store.LOGGING_CFG)

    handler = COMMANDS.get(command)
    if not handler:
        return _error(f'Commande inconnue : {command}', 404)

    instance_id = _instance_id_from_payload(payload)
    if not instance_id:
        return _error('instance_id requis')

    return handler(instance_id, payload)
