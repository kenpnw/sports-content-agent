from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def write_json(path: Path, payload: Any) -> None:
    """Atomic JSON write: serialize to a sibling .tmp file, then rename.

    Prevents the destination file from being half-written if the process is
    interrupted, the disk buffer isn't fully flushed, or a mount-side cache
    sees the file mid-write. This was triggering UTF-8 decode errors on
    ~28 KB reports under Windows mounts.
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)  # os.replace is atomic on both POSIX and Windows.


def write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))
