from pathlib import Path


def build_process_args(exe_path: Path, game_cfg: dict, serverconfig_b64: str,
                       seasondefinition_b64: str) -> list[str]:
    args = [
        str(exe_path),
        '-serverconfig', serverconfig_b64,
        '-seasondefinition', seasondefinition_b64,
    ]

    if game_cfg.get('no_lobby'):
        args.append('-no_lobby')

    log_debug = game_cfg.get('log_debug')
    if log_debug:
        args += ['-log_debug', str(log_debug)]

    if game_cfg.get('write_server_results'):
        args.append('-write_server_results')

    return args
