from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from .config import join_endpoint


def parse_llama_swap_models(path: Path) -> dict[str, str]:
    models: dict[str, str] = {}
    if not path.is_file():
        return models
    in_models = False
    current_id: str | None = None
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        if not in_models:
            if raw_line.strip() == "models:" and not raw_line.startswith((" ", "\t")):
                in_models = True
            continue
        if raw_line and not raw_line.startswith((" ", "\t", "#")):
            break
        model_match = re.match(r"^  ([^\s:#][^:]*):\s*(?:#.*)?$", raw_line)
        if model_match:
            current_id = model_match.group(1).strip().strip('"\'')
            models[current_id] = current_id
            continue
        name_match = re.match(r"^    name:\s*(.*?)\s*$", raw_line)
        if current_id and name_match:
            value = name_match.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                models[current_id] = value
    return models


def fetch_model_ids(base_url: str, endpoint: str, timeout: float = 2.5) -> list[str]:
    request = urllib.request.Request(join_endpoint(base_url, endpoint), headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8-sig"))
    return sorted({str(item["id"]) for item in payload.get("data", []) if item.get("id")}, key=str.casefold)


def discover_models(
    base_url: str,
    endpoint: str,
    fallback_path: Path,
    fallback_format: str | None,
) -> tuple[list[tuple[str, str]], str]:
    fallback = parse_llama_swap_models(fallback_path) if fallback_format == "llama-swap-yaml" else {}
    try:
        ids = fetch_model_ids(base_url, endpoint)
        return [(model_id, fallback.get(model_id, model_id)) for model_id in ids], "API"
    except Exception:
        return sorted(fallback.items(), key=lambda item: item[0].casefold()), "配置文件"
