from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def expand_path(value: str, base: Path) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(value))
    path = Path(expanded)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def resolve_config_paths(config: dict[str, Any], config_path: Path) -> dict[str, Path]:
    return {
        name: expand_path(str(value), config_path.resolve().parent)
        for name, value in config["paths"].items()
    }


def join_endpoint(base_url: str, endpoint: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")
