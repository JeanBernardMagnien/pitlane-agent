from copy import deepcopy


def compile_event_config(event_config: dict, instance_cfg: dict) -> dict:
    """Merge a portable hub event config with local instance technical settings."""
    if not isinstance(event_config, dict):
        raise ValueError('event_config must be an object')

    cfg = deepcopy(event_config)
    server = cfg.setdefault('Server', {})

    server['TcpPort'] = int(instance_cfg['tcp_port'])
    server['UdpPort'] = int(instance_cfg['udp_port'])
    server['HttpPort'] = int(instance_cfg['http_port'])
    server.setdefault('ServerName', instance_cfg.get('name', instance_cfg['id']))

    return cfg
