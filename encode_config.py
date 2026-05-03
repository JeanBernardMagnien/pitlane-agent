import sys, json, zlib, base64, struct

def _encode(data):
    json_str = json.dumps(data, indent=2, ensure_ascii=False).replace('\n', '\r\n')
    json_bytes = json_str.encode('utf-8')
    compressed = zlib.compress(json_bytes, level=6)
    length = len(json_bytes)
    header = bytes([0x00, 0x00, (length >> 8) & 0xFF, length & 0xFF])
    return base64.b64encode(header + compressed).decode('ascii')


def encode_file(filepath: str) -> tuple[str, str]:
    """Prend un fichier JSON maître, retourne (serverconfig_b64, seasondefinition_b64)."""
    with open(filepath, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    server = cfg['Server']
    cars = [{"car_name": c['name'], "ballast": 0, "restrictor": 0.0} for c in cfg['Event']['Cars'] if c['IsSelected']]
    track_parts = cfg['Event']['SelectedTrackValue'].split('|')
    sessions = cfg['Sessions']

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
        "spectator_password": "",
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
            "practice_duration": sessions['PracticeSession']['Length'],
            "practice_time_of_day": {"year": 2024, "month": 8, "day": 15, "hour": sessions['PracticeSession']['Hour'], "minute": sessions['PracticeSession']['Minute'], "second": 0, "time_multiplier": 1},
            "practice_overtime_waiting_next_session": sessions['PracticeSession']['OvertimeWaitingNextSession'],
            "practice_max_wait_to_box": sessions['PracticeSession']['MaxWaitToBox'],
            "qualify_duration": sessions['QualifyingSession']['Length'],
            "qualify_time_of_day": {"year": 2024, "month": 8, "day": 15, "hour": sessions['QualifyingSession']['Hour'], "minute": sessions['QualifyingSession']['Minute'], "second": 0, "time_multiplier": 1},
            "qualify_overtime_waiting_next_session": sessions['QualifyingSession']['OvertimeWaitingNextSession'],
            "qualify_max_wait_to_box": sessions['QualifyingSession']['MaxWaitToBox'],
            "warmup_duration": sessions['WarmupSession']['Length'],
            "warmup_time_of_day": {"year": 2024, "month": 8, "day": 15, "hour": sessions['WarmupSession']['Hour'], "minute": sessions['WarmupSession']['Minute'], "second": 0, "time_multiplier": 1},
            "warmup_overtime_waiting_next_session": sessions['WarmupSession']['OvertimeWaitingNextSession'],
            "warmup_max_wait_to_box": sessions['WarmupSession']['MaxWaitToBox'],
            "race_duration": sessions['RaceSession']['Length'],
            "race_duration_type": "GameModeSelectionDuration_TIME",
            "race_time_of_day": {"year": 2024, "month": 8, "day": 15, "hour": sessions['RaceSession']['Hour'], "minute": sessions['RaceSession']['Minute'], "second": 0, "time_multiplier": 1},
            "race_overtime_waiting_next_session": sessions['RaceSession']['OvertimeWaitingNextSession'],
            "race_max_wait_to_box": sessions['RaceSession']['MaxWaitToBox'],
            "min_waiting_for_players": sessions['PracticeSession']['MinWaitingForPlayers'],
            "max_waiting_for_players": sessions['PracticeSession']['MaxWaitingForPlayers']
        },
        "weather_type": cfg['Event']['SelectedWeatherTypeValue'],
        "weather_behaviour": cfg['Event']['SelectedWeatherBehaviorValue'],
        "initial_grip": cfg['Event']['SelectedInitialGripValue']
    }

    return _encode(server_config), _encode(season_def)


# Permet de toujours l'utiliser en ligne de commande aussi
if __name__ == '__main__':
    sc, sd = encode_file(sys.argv[1])
    print(f"-serverconfig {sc} -seasondefinition {sd}")