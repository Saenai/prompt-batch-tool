from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backends import create_backend


@dataclass(frozen=True)
class ModelFamily:
    key: str
    label: str
    models: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ParameterTier:
    key: str
    label: str
    models: tuple[tuple[str, str], ...]


def parse_llama_swap_models(path: Path) -> dict[str, str]:
    models: dict[str, str] = {}
    if path.is_dir():
        config_paths = sorted(
            (candidate for candidate in path.iterdir() if candidate.suffix.casefold() in {".yml", ".yaml"}),
            key=lambda candidate: candidate.name.casefold(),
        )
    elif path.is_file():
        config_paths = [path]
    else:
        return models
    for config_path in config_paths:
        in_models = False
        current_id: str | None = None
        for raw_line in config_path.read_text(encoding="utf-8-sig").splitlines():
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
    config = {
        "adapter": "openai-chat-completions",
        "models_endpoint": endpoint,
        "chat_endpoint": "/chat/completions",
        "auth": {"type": "none"},
    }
    return create_backend(config, base_url).list_model_ids(timeout)


def discover_models(
    base_url: str,
    backend_config: dict[str, Any],
    fallback_path: Path,
    fallback_format: str | None,
) -> tuple[list[tuple[str, str]], str]:
    fallback = parse_llama_swap_models(fallback_path) if fallback_format == "llama-swap-yaml" else {}
    try:
        ids = create_backend(backend_config, base_url).list_model_ids(2.5)
        return [(model_id, fallback.get(model_id, model_id)) for model_id in ids], "API"
    except Exception:
        return sorted(fallback.items(), key=lambda item: item[0].casefold()), "配置文件"


def group_model_families(models: list[tuple[str, str]], config: dict | None = None) -> list[ModelFamily]:
    """Group discovered models without embedding model-family knowledge in the GUI."""
    settings = config or {}
    if not settings.get("enabled", True):
        label = str(settings.get("all_models_label", "全部模型"))
        return [ModelFamily("__all__", label, tuple(models))] if models else []

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
        ModelFamily(key, display_labels[key], tuple(grouped[key]))
        for key in sorted(grouped, key=sort_key)
    ]


def group_parameter_tiers(models: list[tuple[str, str]], config: dict | None = None) -> list[ParameterTier]:
    """Group models by configured parameter-size captures."""
    settings = config or {}
    if not settings.get("enabled", True):
        label = str(settings.get("all_models_label", "全部参数量"))
        return [ParameterTier("__all_sizes__", label, tuple(models))] if models else []

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
        ParameterTier(key, display_labels[key], tuple(grouped[key]))
        for key in sorted(grouped, key=sort_key)
    ]


def _parameter_value(value: str) -> float:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)([kmgtb]?)", value.strip(), re.IGNORECASE)
    if not match:
        return 0.0
    multiplier = {"": 1.0, "k": 1e3, "m": 1e6, "g": 1e9, "b": 1e9, "t": 1e12}
    return float(match.group(1)) * multiplier[match.group(2).casefold()]


# Compatibility aliases for integrations written before the naming cleanup.
ModelGroup = ModelFamily
ModelTier = ParameterTier
group_models = group_model_families
group_model_tiers = group_parameter_tiers


__all__ = [
    "ModelFamily",
    "ParameterTier",
    "discover_models",
    "fetch_model_ids",
    "group_model_families",
    "group_parameter_tiers",
    "parse_llama_swap_models",
]
