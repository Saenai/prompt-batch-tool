from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from .config import load_json


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return load_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
