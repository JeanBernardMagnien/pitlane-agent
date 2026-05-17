import sys, json, zlib, base64


def _encode(data):
    json_str = json.dumps(data, indent=2, ensure_ascii=False).replace('\n', '\r\n')
    json_bytes = json_str.encode('utf-8')
    compressed = zlib.compress(json_bytes, level=6)
    length = len(json_bytes)
    header = bytes([0x00, 0x00, (length >> 8) & 0xFF, length & 0xFF])
    return base64.b64encode(header + compressed).decode('ascii')


def _empty_session(name: str) -> dict:
    return {
        "forceTimeDuration": name != "Race",
        "TimeMultiplier": 1,
        "IsVisible": False,
        "Name": name,
        "Duration": 0,
        "Length": 0,
        "Hour": 0,
        "Minute": 0,
        "MaxWaitToBox": 0,
        "OvertimeWaitingNextSession": 0,
        "MinWaitingForPlayers": 0,
        "MaxWaitingForPlayers": 0,
    }


def _session(sessions: dict, key: str, name: str) -> dict:
    return sessions.get(key) or _empty_session(name)


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


def encode_payload(cfg: dict) -> tuple[str, str]:
    """Prend un payload JSON maître, retourne (serverconfig_b64, seasondefinition_b64)."""
    server = cfg['Server']
    cars = [{"car_name": c['name'], "ballast": 0, "restrictor": 0.0} for c in cfg['Event']['Cars'] if c['IsSelected']]
    track_parts = cfg['Event']['SelectedTrackValue'].split('|')
    sessions = cfg['Sessions']
    practice = _session(sessions, 'PracticeSession', 'Practice')
    qualifying = _session(sessions, 'QualifyingSession', 'Qualify')
    warmup = _session(sessions, 'WarmupSession', 'Warmup')
    race = _session(sessions, 'RaceSession', 'Race')

    server_config = {
        "server_tcp_listener_port": server['TcpPort'],
        "server_udp_listener_port": server['UdpPort'],
        "server_tcp_internal_port": server['TcpPort'],
        "server_udp_internal_port": server['UdpPort'],
        "server_http_port": server['HttpPort'],
        "server_name": server['ServerName'],
        "max_players": server['MaxPlayers'],
        "cycle": server['IsCycleEnabled'],
        "allowed_cars_list_full": cars,
        "driver_password": server['DriverPassword'],
        "spectator_password": server['SpectatorPassword'],
        "admin_password": server['AdminPassword'],
        "type": server['SelectedServerTypeValue'],
        "entry_list_path": server['EntryListPath'],
        "results_path": server['ResultsPath']
    }

    season_def = {
        "game_type": cfg['Event']['SelectedSessionTypeValue'],
        "event": {
            "track": track_parts[0],
            "layout": track_parts[1],
            "event_name": track_parts[2],
            "track_length": track_parts[3]
        },
        "export_json": False,
        "game_config": {
            "practice_duration": practice['Length'],
            "practice_time_of_day": _time_of_day(practice),
            "practice_overtime_waiting_next_session": practice['OvertimeWaitingNextSession'],
            "practice_max_wait_to_box": practice['MaxWaitToBox'],
            "qualify_duration": qualifying['Length'],
            "qualify_time_of_day": _time_of_day(qualifying),
            "qualify_overtime_waiting_next_session": qualifying['OvertimeWaitingNextSession'],
            "qualify_max_wait_to_box": qualifying['MaxWaitToBox'],
            "warmup_duration": warmup['Length'],
            "warmup_time_of_day": _time_of_day(warmup),
            "warmup_overtime_waiting_next_session": warmup['OvertimeWaitingNextSession'],
            "warmup_max_wait_to_box": warmup['MaxWaitToBox'],
            "race_duration": race['Length'],
            "race_duration_type": "GameModeSelectionDuration_TIME",
            "race_time_of_day": _time_of_day(race),
            "race_overtime_waiting_next_session": race['OvertimeWaitingNextSession'],
            "race_max_wait_to_box": race['MaxWaitToBox'],
            "min_waiting_for_players": practice['MinWaitingForPlayers'],
            "max_waiting_for_players": practice['MaxWaitingForPlayers']
        },
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
