from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import join_endpoint


@dataclass(frozen=True)
class ModelGroup:
    key: str
    label: str
    models: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ModelTier:
    key: str
    label: str
    models: tuple[tuple[str, str], ...]


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


def group_models(models: list[tuple[str, str]], config: dict | None = None) -> list[ModelGroup]:
    """Group discovered models without embedding model-family knowledge in the GUI."""
    settings = config or {}
    if not settings.get("enabled", True):
        label = str(settings.get("all_models_label", "全部模型"))
        return [ModelGroup("__all__", label, tuple(models))] if models else []

    pattern_text = str(settings.get("pattern", r"^([^-]+)"))
    try:
        pattern = re.compile(pattern_text, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"model_source.grouping.pattern 无效：{exc}") from exc
    try:
        match_group = int(settings.get("match_group", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("model_source.grouping.match_group 必须是整数") from exc

    aliases = {str(key).casefold(): str(value) for key, value in settings.get("aliases", {}).items()}
    order = [str(value).casefold() for value in settings.get("order", [])]
    order_index = {key: index for index, key in enumerate(order)}
    fallback_key = str(settings.get("fallback_group", "other")).strip().casefold() or "other"
    fallback_label = str(settings.get("fallback_label", "其他"))
    grouped: dict[str, list[tuple[str, str]]] = {}
    display_labels: dict[str, str] = {}

    for model_id, model_label in models:
        match = pattern.search(model_id)
        raw_key = ""
        if match:
            try:
                raw_key = match.group(match_group).strip()
            except (IndexError, TypeError) as exc:
                raise ValueError("model_source.grouping.match_group 超出 pattern 的捕获组范围") from exc
        key = raw_key.casefold() if raw_key else fallback_key
        grouped.setdefault(key, []).append((model_id, model_label))
        display_labels.setdefault(key, aliases.get(key, raw_key or fallback_label))

    def sort_key(key: str) -> tuple[int, int | str, str]:
        if key in order_index:
            return (0, order_index[key], key)
        if key == fallback_key:
            return (2, 0, key)
        return (1, display_labels[key].casefold(), key)

    return [
        ModelGroup(key, display_labels[key], tuple(grouped[key]))
        for key in sorted(grouped, key=sort_key)
    ]


def group_model_tiers(models: list[tuple[str, str]], config: dict | None = None) -> list[ModelTier]:
    """Group models by configured parameter-size captures."""
    settings = config or {}
    if not settings.get("enabled", True):
        label = str(settings.get("all_models_label", "全部参数量"))
        return [ModelTier("__all_sizes__", label, tuple(models))] if models else []

    pattern_text = str(settings.get("pattern", r"(?:^|-)(\d+(?:\.\d+)?[bB])(?:-|$)"))
    try:
        pattern = re.compile(pattern_text, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"model_source.grouping.parameter_tiers.pattern 无效：{exc}") from exc
    try:
        size_group = int(settings.get("size_group", 1))
        active_group = int(settings.get("active_group", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("parameter_tiers 的 size_group 和 active_group 必须是整数") from exc

    aliases = {str(key).casefold(): str(value) for key, value in settings.get("aliases", {}).items()}
    fallback_key = str(settings.get("fallback_group", "unknown")).strip().casefold() or "unknown"
    fallback_label = str(settings.get("fallback_label", "参数量未标注"))
    grouped: dict[str, list[tuple[str, str]]] = {}
    display_labels: dict[str, str] = {}
    sort_values: dict[str, float] = {}

    for model_id, model_label in models:
        match = pattern.search(model_id)
        size = ""
        active = ""
        if match:
            try:
                size = (match.group(size_group) or "").strip()
                if active_group > 0:
                    active = (match.group(active_group) or "").strip()
            except (IndexError, TypeError) as exc:
                raise ValueError("parameter_tiers 捕获组超出 pattern 范围") from exc
        if size:
            key = size.casefold() + (f"-a{active.casefold()}" if active else "")
            default_label = size.upper() + (f" / A{active.upper()}" if active else "")
        else:
            key = fallback_key
            default_label = fallback_label
        grouped.setdefault(key, []).append((model_id, model_label))
        display_labels.setdefault(key, aliases.get(key, default_label))
        sort_values.setdefault(key, _parameter_value(size))

    sort_mode = str(settings.get("sort", "size-desc")).casefold()

    def sort_key(key: str) -> tuple[int, float | str, str]:
        if key == fallback_key:
            return (2, 0.0, key)
        if sort_mode == "size-asc":
            return (0, sort_values[key], key)
        if sort_mode == "label":
            return (0, display_labels[key].casefold(), key)
        return (0, -sort_values[key], key)

    return [
        ModelTier(key, display_labels[key], tuple(grouped[key]))
        for key in sorted(grouped, key=sort_key)
    ]


def _parameter_value(value: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kmgtb]?)", value.strip(), re.IGNORECASE)
    if not match:
        return 0.0
    multiplier = {"": 1.0, "k": 1e3, "m": 1e6, "g": 1e9, "b": 1e9, "t": 1e12}
    return float(match.group(1)) * multiplier[match.group(2).casefold()]
