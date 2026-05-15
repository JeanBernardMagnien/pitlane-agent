from copy import deepcopy
from pathlib import Path


class InstancePortsOutOfSync(ValueError):
    def __init__(self, instance_id: str, expected: dict, received: dict):
        self.instance_id = instance_id
        self.expected = expected
        self.received = received
        super().__init__(
            f"Les ports reçus ne correspondent pas à l'instance {instance_id}. "
            "Resynchronisez les instances depuis le Hub."
        )


def _read_int(server: dict, key: str) -> int | None:
    value = server.get(key)

    if value in (None, ''):
        return None

    return int(value)


def validate_instance_ports(config: dict, instance_cfg: dict) -> None:
    if not isinstance(config, dict):
        raise ValueError('config must be an object')

    server = config.get('Server')
    if not isinstance(server, dict):
        raise ValueError('config.Server must be an object')

    expected = {
        'tcp': int(instance_cfg['tcp_port']),
        'udp': int(instance_cfg['udp_port']),
        'http': int(instance_cfg['http_port']),
    }

    received = {
        'tcp': _read_int(server, 'TcpPort'),
        'udp': _read_int(server, 'UdpPort'),
        'http': _read_int(server, 'HttpPort'),
    }

    if expected != received:
        raise InstancePortsOutOfSync(str(instance_cfg['id']), expected, received)


def finalize_launch_config(config: dict, instance_cfg: dict, game_cfg: dict) -> dict:
    """
    Finalise uniquement les champs locaux dépendants de la machine agent.

    Le Hub reste propriétaire de la configuration métier et des ports.
    L'agent vérifie les ports et injecte uniquement les chemins locaux.
    """
    validate_instance_ports(config, instance_cfg)

    cfg = deepcopy(config)
    server = cfg.setdefault('Server', {})

    install_path = Path(game_cfg['install_path'])
    results_path = install_path / 'Results' / str(instance_cfg['id'])

    server['ResultsPath'] = str(results_path)

    return cfg
