"""Publish complete JSON files for readers in other Web/worker processes."""
import json
import os
from pathlib import Path
import time
import uuid


def _retry_windows(operation):
    for attempt in range(20):
        try:
            return operation()
        except PermissionError:
            if os.name != 'nt' or attempt == 19:
                raise
            time.sleep(.01)


def read_json(path: Path):
    # Windows can briefly deny opening a path while its directory entry is replaced.
    return json.loads(_retry_windows(lambda: Path(path).read_text(encoding='utf-8')))


def json_file_signature(path: Path) -> tuple[int, int, int]:
    stat = _retry_windows(lambda: Path(path).stat())
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def atomic_write_json(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # Windows may briefly deny replacement while another reader opens it.
                if os.name != 'nt' or attempt == 19:
                    raise
                time.sleep(.01)
    finally:
        temporary.unlink(missing_ok=True)
