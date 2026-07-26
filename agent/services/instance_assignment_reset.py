from datetime import datetime, timezone
from pathlib import Path


def archive_instance_logs(logging_cfg: dict, instance_id: str) -> int:
    logs_path = Path(logging_cfg.get('logs_path') or 'logs')
    safe_instance_id = Path(str(instance_id)).name
    log_files = sorted(logs_path.glob(f'log_{safe_instance_id}_*.log'))
    if not log_files:
        return 0

    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    archive_path = (
        logs_path
        / 'assignment-history'
        / safe_instance_id
        / timestamp
    )
    archive_path.mkdir(parents=True, exist_ok=False)

    for log_file in log_files:
        log_file.replace(archive_path / log_file.name)

    return len(log_files)
