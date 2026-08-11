import socket
import time

import psutil


PORT_RELEASE_TIMEOUT_SECONDS = 5.0
PORT_RELEASE_POLL_INTERVAL_SECONDS = 0.25


class InstancePortInspectionError(RuntimeError):
    pass


def wait_for_instance_ports(
    instance_cfg: dict,
    timeout_seconds: float = PORT_RELEASE_TIMEOUT_SECONDS,
    poll_interval_seconds: float = PORT_RELEASE_POLL_INTERVAL_SECONDS,
) -> list[dict]:
    """Attend brièvement la libération des ports puis retourne les conflits restants."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)

    while True:
        conflicts = inspect_instance_port_conflicts(instance_cfg)
        if not conflicts:
            return []

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return conflicts

        time.sleep(min(max(0.01, poll_interval_seconds), remaining))


def inspect_instance_port_conflicts(instance_cfg: dict) -> list[dict]:
    required_ports = _required_ports(instance_cfg)
    if not required_ports:
        return []

    try:
        connections = psutil.net_connections(kind='inet')
    except (psutil.AccessDenied, OSError) as exc:
        raise InstancePortInspectionError(
            "Impossible de vérifier si les ports de l'instance sont libres."
        ) from exc

    conflicts = set()
    for connection in connections:
        protocol = _connection_protocol(connection)
        local_port = _local_port(connection)
        if protocol is None or local_port is None:
            continue
        if (protocol, local_port) not in required_ports:
            continue
        if protocol == 'TCP' and str(getattr(connection, 'status', '')).upper() != 'LISTEN':
            continue

        pid = getattr(connection, 'pid', None)
        conflicts.add((protocol, local_port, int(pid) if pid is not None else None))

    return [
        {'protocol': protocol, 'port': port, 'pid': pid}
        for protocol, port, pid in sorted(
            conflicts,
            key=lambda item: (item[0], item[1], item[2] if item[2] is not None else -1),
        )
    ]


def _required_ports(instance_cfg: dict) -> set[tuple[str, int]]:
    ports = set()
    for protocol, key in (
        ('TCP', 'tcp_port'),
        ('TCP', 'http_port'),
        ('UDP', 'udp_port'),
    ):
        value = instance_cfg.get(key)
        if value is None:
            continue
        try:
            port = int(value)
        except (TypeError, ValueError):
            continue
        if port > 0:
            ports.add((protocol, port))

    return ports


def _connection_protocol(connection) -> str | None:
    connection_type = getattr(connection, 'type', None)
    if connection_type == socket.SOCK_STREAM:
        return 'TCP'
    if connection_type == socket.SOCK_DGRAM:
        return 'UDP'
    return None


def _local_port(connection) -> int | None:
    local_address = getattr(connection, 'laddr', None)
    if not local_address:
        return None

    value = getattr(local_address, 'port', None)
    if value is None and isinstance(local_address, (tuple, list)) and len(local_address) >= 2:
        value = local_address[1]

    try:
        return int(value)
    except (TypeError, ValueError):
        return None
