import json
import os
from pathlib import Path
import tempfile
from typing import Any


def write_json_atomic(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    temporary_path: Path | None = None

    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f'.{path.name}.',
            suffix='.tmp',
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, path)
        _sync_parent_directory(path.parent)

        return path
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _sync_parent_directory(directory: Path) -> None:
    if os.name == 'nt' or not hasattr(os, 'O_DIRECTORY'):
        return

    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
