from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any


APP_CONFIG_VERSION = 4
PROFILE_VERSION = 1
GPU_MONITOR_DEFAULTS = {
    "enabled": True,
    "command": "nvidia-smi",
    "poll_interval_ms": 1000,
    "history_samples": 60,
    "query_timeout_seconds": 5,
}


class ConfigValidationError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ConfigValidationError(f"JSON root must be an object: {path}")
    return payload


def _mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{location} must be an object")
    return value


def _required(mapping: dict[str, Any], key: str, location: str) -> Any:
    if key not in mapping:
        raise ConfigValidationError(f"{location}.{key} is required")
    return mapping[key]


def _string(value: Any, location: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ConfigValidationError(f"{location} must be a non-empty string")
    return value


def _string_list(value: Any, location: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigValidationError(f"{location} must be an array of strings")
    return value


def migrate_app_config(payload: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(payload)
    version = migrated.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigValidationError("app config schema_version must be an integer")
    if version == 1:
        backend = _mapping(_required(migrated, "backend", "app config"), "backend")
        adapter = backend.pop("type", "openai-chat-completions")
        backend.setdefault("adapter", adapter)
        backend.setdefault("auth", {"type": "none"})
        migrated["schema_version"] = 2
        version = 2
    if version == 2:
        migrated.setdefault("gpu_monitor", deepcopy(GPU_MONITOR_DEFAULTS))
        migrated["schema_version"] = 3
        version = 3
    if version == 3:
        router = _mapping(_required(migrated, "router", "app config"), "router")
        router.setdefault("control_base_url", "http://127.0.0.1:8081")
        router.setdefault("unload_all_endpoint", "/api/models/unload")
        router.setdefault("control_timeout_seconds", 30)
        migrated.setdefault("result_browser", {"max_entries": 12})
        migrated["schema_version"] = 4
    elif version != APP_CONFIG_VERSION:
        raise ConfigValidationError(
            f"Unsupported app config schema_version {version}; expected 1 through {APP_CONFIG_VERSION}"
        )
    defaults = migrated.setdefault("defaults", {})
    if not isinstance(defaults, dict):
        raise ConfigValidationError("app config.defaults must be an object")
    defaults.setdefault("random_seed", True)
    return migrated


def validate_app_config(config: dict[str, Any]) -> None:
    if config.get("schema_version") != APP_CONFIG_VERSION:
        raise ConfigValidationError(f"app config schema_version must be {APP_CONFIG_VERSION}")
    paths = _mapping(_required(config, "paths", "app config"), "paths")
    for key in (
        "engine", "profiles", "state", "default_output_root", "model_config",
        "router_executable", "router_working_directory", "runtime_executable",
    ):
        _string(_required(paths, key, "paths"), f"paths.{key}")

    backend = _mapping(_required(config, "backend", "app config"), "backend")
    adapter = _string(_required(backend, "adapter", "backend"), "backend.adapter")
    if adapter != "openai-chat-completions":
        raise ConfigValidationError(f"Unsupported backend adapter: {adapter}")
    for key in ("base_url", "models_endpoint", "chat_endpoint"):
        _string(_required(backend, key, "backend"), f"backend.{key}")
    for key in ("request_timeout_seconds", "readiness_timeout_seconds"):
        value = _required(backend, key, "backend")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ConfigValidationError(f"backend.{key} must be a positive number")
    if not isinstance(backend.get("request_body", {}), dict):
        raise ConfigValidationError("backend.request_body must be an object")
    auth = _mapping(backend.get("auth", {"type": "none"}), "backend.auth")
    auth_type = _string(auth.get("type", "none"), "backend.auth.type")
    if auth_type not in {"none", "environment"}:
        raise ConfigValidationError(f"Unsupported backend.auth.type: {auth_type}")
    if auth_type == "environment":
        _string(_required(auth, "environment_variable", "backend.auth"), "backend.auth.environment_variable")
        _string(auth.get("header", "Authorization"), "backend.auth.header")
        _string(auth.get("prefix", "Bearer "), "backend.auth.prefix", allow_empty=True)

    router = _mapping(_required(config, "router", "app config"), "router")
    if not isinstance(router.get("auto_start", True), bool):
        raise ConfigValidationError("router.auto_start must be a boolean")
    if not isinstance(router.get("control_enabled", True), bool):
        raise ConfigValidationError("router.control_enabled must be a boolean")
    control_auth = _mapping(router.get("auth", {"type": "none"}), "router.auth")
    if control_auth.get("type", "none") not in {"none", "environment"}:
        raise ConfigValidationError("Unsupported router.auth.type")
    if control_auth.get("type") == "environment":
        _string(_required(control_auth, "environment_variable", "router.auth"), "router.auth.environment_variable")
        _string(control_auth.get("header", "Authorization"), "router.auth.header")
        _string(control_auth.get("prefix", "Bearer "), "router.auth.prefix", allow_empty=True)
    _string_list(_required(router, "arguments", "router"), "router.arguments")
    _string_list(_required(router, "managed_process_names", "router"), "router.managed_process_names")
    _string(_required(router, "control_base_url", "router"), "router.control_base_url")
    _string(_required(router, "unload_all_endpoint", "router"), "router.unload_all_endpoint")
    control_timeout = _required(router, "control_timeout_seconds", "router")
    if not isinstance(control_timeout, (int, float)) or isinstance(control_timeout, bool) or control_timeout <= 0:
        raise ConfigValidationError("router.control_timeout_seconds must be a positive number")
    runtime = _mapping(_required(config, "runtime", "app config"), "runtime")
    _string_list(_required(runtime, "version_arguments", "runtime"), "runtime.version_arguments")

    gpu_monitor = _mapping(_required(config, "gpu_monitor", "app config"), "gpu_monitor")
    enabled = _required(gpu_monitor, "enabled", "gpu_monitor")
    if not isinstance(enabled, bool):
        raise ConfigValidationError("gpu_monitor.enabled must be a boolean")
    _string(_required(gpu_monitor, "command", "gpu_monitor"), "gpu_monitor.command")
    for key, minimum, maximum in (
        ("poll_interval_ms", 250, 60_000),
        ("history_samples", 10, 600),
    ):
        value = _required(gpu_monitor, key, "gpu_monitor")
        if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
            raise ConfigValidationError(f"gpu_monitor.{key} must be an integer from {minimum} to {maximum}")
    timeout = _required(gpu_monitor, "query_timeout_seconds", "gpu_monitor")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
        raise ConfigValidationError("gpu_monitor.query_timeout_seconds must be a positive number")

    result_browser = _mapping(_required(config, "result_browser", "app config"), "result_browser")
    max_entries = _required(result_browser, "max_entries", "result_browser")
    if not isinstance(max_entries, int) or isinstance(max_entries, bool) or not 1 <= max_entries <= 100:
        raise ConfigValidationError("result_browser.max_entries must be an integer from 1 to 100")

    defaults = _mapping(config.get("defaults", {}), "defaults")
    random_seed = defaults.get("random_seed", True)
    if not isinstance(random_seed, bool):
        raise ConfigValidationError("defaults.random_seed must be a boolean")
    seed_base = defaults.get("seed_base", 1)
    if not isinstance(seed_base, int) or isinstance(seed_base, bool) or seed_base < 1:
        raise ConfigValidationError("defaults.seed_base must be a positive integer")


def load_app_config(path: Path) -> dict[str, Any]:
    config = migrate_app_config(load_json(path))
    validate_app_config(config)
    return config


def validate_profile(profile: dict[str, Any]) -> None:
    version = profile.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ConfigValidationError("profile schema_version must be an integer")
    if version != PROFILE_VERSION:
        raise ConfigValidationError(f"Unsupported profile schema_version {version}; expected {PROFILE_VERSION}")
    _string(_required(profile, "id", "profile"), "profile.id")
    default_mode = _string(_required(profile, "default_mode", "profile"), "profile.default_mode")
    modes = _mapping(_required(profile, "modes", "profile"), "profile.modes")
    if not modes:
        raise ConfigValidationError("profile.modes must not be empty")
    if default_mode not in modes:
        raise ConfigValidationError("profile.default_mode must name an entry in profile.modes")
    for mode_id, value in modes.items():
        _string(mode_id, "profile mode id")
        mode = _mapping(value, f"profile.modes.{mode_id}")
        if "system_prompt" in mode:
            _string(mode["system_prompt"], f"profile.modes.{mode_id}.system_prompt")
        if "system_prompt_text" in mode:
            _string(mode["system_prompt_text"], f"profile.modes.{mode_id}.system_prompt_text", allow_empty=True)
        if not isinstance(mode.get("request_body", {}), dict):
            raise ConfigValidationError(f"profile.modes.{mode_id}.request_body must be an object")
        validation = _mapping(mode.get("validation", {}), f"profile.modes.{mode_id}.validation")
        for key in ("required_patterns", "forbidden_patterns"):
            _string_list(validation.get(key, []), f"profile.modes.{mode_id}.validation.{key}")
    if not isinstance(profile.get("request_body", {}), dict):
        raise ConfigValidationError("profile.request_body must be an object")
    validation = _mapping(profile.get("validation", {}), "profile.validation")
    for key in ("required_patterns", "forbidden_patterns"):
        _string_list(validation.get(key, []), f"profile.validation.{key}")
    if not isinstance(profile.get("observations", []), list):
        raise ConfigValidationError("profile.observations must be an array")
    _mapping(profile.get("output", {}), "profile.output")


def load_profile(path: Path) -> dict[str, Any]:
    profile = load_json(path)
    profile.setdefault("schema_version", PROFILE_VERSION)
    validate_profile(profile)
    return profile


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
