from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from .config import load_json


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_path_component(value: str) -> str:
    """Encode an external identifier for use as one Windows path component."""
    source = str(value)
    encoded: list[str] = []
    last_index = len(source) - 1
    for index, character in enumerate(source):
        if character.isascii() and (character.isalnum() or character in "._-") and not (
            character == "." and index == last_index
        ):
            encoded.append(character)
        else:
            encoded.append(f"~{ord(character):04X}")
    result = "".join(encoded) or "~0000"
    if result.casefold().split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES or result in {".", ".."}:
        result = f"~{result}"
    return result


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
