import sys, json, zlib, base64

SESSION_KEY_MAP = {
    'PracticeSession': 'practice',
    'QualifyingSession': 'qualify',
    'WarmupSession': 'warmup',
    'RaceSession': 'race',
}


def _encode(data):
    json_str = json.dumps(data, indent=2, ensure_ascii=False).replace('\n', '\r\n')
    json_bytes = json_str.encode('utf-8')
    compressed = zlib.compress(json_bytes, level=6)
    length = len(json_bytes)
    header = bytes([0x00, 0x00, (length >> 8) & 0xFF, length & 0xFF])
    return base64.b64encode(header + compressed).decode('ascii')


def _time_of_day(session: dict) -> dict:
    return {
        "year": 2024,
        "month": 8,
        "day": 15,
        "hour": session['Hour'],
        "minute": session['Minute'],
        "second": 0,
        "time_multiplier": 1,
    }


def _apply_session(game_config: dict, source_key: str, session: dict) -> None:
    prefix = SESSION_KEY_MAP.get(source_key)
    if not prefix:
        return

    game_config[f"{prefix}_duration"] = session['Length']
    game_config[f"{prefix}_time_of_day"] = _time_of_day(session)
    game_config[f"{prefix}_overtime_waiting_next_session"] = session['OvertimeWaitingNextSession']
    game_config[f"{prefix}_max_wait_to_box"] = session['MaxWaitToBox']

    if source_key == 'RaceSession':
        game_config["race_duration_type"] = "GameModeSelectionDuration_TIME"


def encode_payload(cfg: dict) -> tuple[str, str]:
    """Prend un payload JSON maître, retourne (serverconfig_b64, seasondefinition_b64)."""
    server = cfg['Server']
    cars = [{"car_name": c['name'], "ballast": 0, "restrictor": 0.0} for c in cfg['Event']['Cars'] if c['IsSelected']]
    track_parts = cfg['Event']['SelectedTrackValue'].split('|')
    sessions = cfg['Sessions']

    server_config = {
        'server_tcp_listener_port': server['TcpPort'],
        'server_udp_listener_port': server['UdpPort'],
        'server_tcp_internal_port': server['TcpPort'],
        'server_udp_internal_port': server['UdpPort'],
        'server_http_port': server['HttpPort'],
        'server_name': server['ServerName'],
        'max_players': server['MaxPlayers'],
        'cycle': server['IsCycleEnabled'],
        'allowed_cars_list_full': cars,
        'driver_password': server['DriverPassword'],
        'spectator_password': server['SpectatorPassword'],
        'admin_password': server['AdminPassword'],
        'type': server['SelectedServerTypeValue'],
        'tuning_type': server.get('SelectedTuningTypeValue', 'TuningDenied'),
    }

    optional_server_fields = {
        'entry_list_server_url': server.get('EntryListUrl', ''),
        'entry_list_path': server.get('EntryListPath', ''),
        'results_post_url': server.get('ResultsPostUrl', ''),
        'results_path': server.get('ResultsPath', ''),
    }
    for key, value in optional_server_fields.items():
        if value:
            server_config[key] = value

    game_config = {}
    waiting_session = None

    ordered_sessions = sorted(
        sessions.items(),
        key=lambda item: item[1].get('Order', 999)
    )

    for source_key, session in ordered_sessions:
        _apply_session(game_config, source_key, session)
        if source_key in ('RaceSession', 'PracticeSession'):
            waiting_session = session

    if waiting_session:
        game_config["min_waiting_for_players"] = waiting_session['MinWaitingForPlayers']
        game_config["max_waiting_for_players"] = waiting_session['MaxWaitingForPlayers']

    season_def = {
        "game_type": cfg['Event']['SelectedSessionTypeValue'],
        "event": {
            "track": track_parts[0],
            "layout": track_parts[1],
            "event_name": track_parts[2],
            "track_length": track_parts[3]
        },
        "export_json": False,
        "game_config": game_config,
        "weather_type": cfg['Event']['SelectedWeatherTypeValue'],
        "weather_behaviour": cfg['Event']['SelectedWeatherBehaviorValue'],
        "initial_grip": cfg['Event']['SelectedInitialGripValue']
    }

    return _encode(server_config), _encode(season_def)


def encode_file(filepath: str) -> tuple[str, str]:
    """Prend un fichier JSON maître, retourne (serverconfig_b64, seasondefinition_b64)."""
    with open(filepath, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    return encode_payload(cfg)


if __name__ == '__main__':
    sc, sd = encode_file(sys.argv[1])
    print(f"-serverconfig {sc} -seasondefinition {sd}")
