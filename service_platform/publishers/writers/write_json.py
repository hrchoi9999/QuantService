"""Simple JSON writing helpers for publisher outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8")


def describe_json_file(path: Path) -> dict[str, Any]:
    return {"path": str(path), "size_bytes": path.stat().st_size}
