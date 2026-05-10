import subprocess


def firewall_rule_name(instance_id: str, port: int, proto: str) -> str:
    return f"PitLane-{instance_id}-{proto}-{port}"


def open_ports(instance_id: str, tcp_port: int, udp_port: int, http_port: int) -> list[str]:
    rules = [
        (tcp_port, 'TCP', 'jeu AC EVO TCP'),
        (udp_port, 'UDP', 'jeu AC EVO UDP'),
        (http_port, 'TCP', 'HTTP statut AC EVO'),
    ]
    errors = []
    for port, proto, _desc in rules:
        name = firewall_rule_name(instance_id, port, proto)
        cmd = [
            'powershell', '-NonInteractive', '-Command',
            f'New-NetFirewallRule -DisplayName "{name}" '
            f'-Direction Inbound -Protocol {proto} '
            f'-LocalPort {port} -Action Allow -ErrorAction Stop',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append(f"{proto}/{port}: {result.stderr.strip()}")
    return errors


def close_ports(instance_id: str, tcp_port: int, udp_port: int, http_port: int) -> list[str]:
    rules = [
        (tcp_port, 'TCP'),
        (udp_port, 'UDP'),
        (http_port, 'TCP'),
    ]
    errors = []
    for port, proto in rules:
        name = firewall_rule_name(instance_id, port, proto)
        cmd = [
            'powershell', '-NonInteractive', '-Command',
            f'Remove-NetFirewallRule -DisplayName "{name}" -ErrorAction SilentlyContinue',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            errors.append(f"{proto}/{port}: {result.stderr.strip()}")
    return errors
