from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from .config import expand_path, load_app_config, load_json, load_profile, resolve_config_paths
from .domain import BatchOptions, InputCase, Observation, PreparedBatch, ValidationReport


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def profile_fingerprint(profile: dict) -> str:
    semantic_profile = {key: value for key, value in profile.items() if key != "$schema"}
    return sha256_text(json.dumps(semantic_profile, ensure_ascii=False, sort_keys=True))


def _safe_id(value: str, fallback_index: int) -> str:
    safe = re.sub(r"[^\w.-]+", "-", value.strip(), flags=re.UNICODE).strip("-")
    return safe or f"input-{fallback_index:02d}"


def _unique_strings(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _first_nonempty_line(content: str) -> str:
    for line in content.splitlines():
        if line.strip():
            return line.strip()
    return ""


def prepare_batch(options: BatchOptions) -> PreparedBatch:
    options.app_config_path = options.app_config_path.resolve()
    options.profile_path = options.profile_path.resolve()
    options.input_manifest_path = options.input_manifest_path.resolve()
    for path in (options.app_config_path, options.profile_path, options.input_manifest_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required file not found: {path}")
    if options.repeats < 1 or options.max_tokens < 1:
        raise ValueError("Repeats and max tokens must be positive integers.")
    if (options.resume or options.retry_failed_only) and not options.run_directory:
        raise ValueError("Resume and retry-failed modes require an explicit run directory.")
    options.model_ids = _unique_strings(options.model_ids)
    if not options.model_ids:
        raise ValueError("At least one model must be selected.")

    app_config = load_app_config(options.app_config_path)
    profile = load_profile(options.profile_path)
    manifest = load_json(options.input_manifest_path)
    entries = manifest.get("inputs")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Input manifest contains no inputs.")

    paths = resolve_config_paths(app_config, options.app_config_path)
    configured_base_url = str(app_config["backend"]["base_url"])
    base_url = options.base_url or configured_base_url
    output_root = options.output_root.resolve() if options.output_root else paths["default_output_root"]
    if options.run_directory:
        options.run_directory = options.run_directory.resolve()
    if options.system_prompt_path:
        options.system_prompt_path = options.system_prompt_path.resolve()
        if not options.system_prompt_path.is_file():
            raise FileNotFoundError(f"System prompt not found: {options.system_prompt_path}")

    profile_dir = options.profile_path.parent
    system_root = expand_path(str(profile.get("system_prompt_root", ".")), profile_dir)
    modes = profile["modes"]
    available_modes = list(modes)
    requested_mode = options.mode.strip()
    if requested_mode != "auto" and requested_mode not in modes:
        raise ValueError(f"Mode '{requested_mode}' is not defined by profile '{profile['id']}'.")
    if requested_mode == "auto" and not profile.get("allow_auto_mode", False):
        requested_mode = str(profile["default_mode"])

    cases: list[InputCase] = []
    used_ids: set[str] = set()
    manifest_dir = options.input_manifest_path.parent
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Input entry {index} must be an object.")
        if entry.get("path"):
            source_path = expand_path(str(entry["path"]), manifest_dir)
            if not source_path.is_file():
                raise FileNotFoundError(f"Input file not found: {source_path}")
            content = source_path.read_text(encoding="utf-8-sig")
            source_kind = "file"
        elif "content" in entry:
            source_path = None
            content = str(entry["content"])
            source_kind = "inline"
        else:
            raise ValueError(f"Input entry {index} must contain path or content.")
        if not content.strip():
            raise ValueError(f"Input entry {index} is empty.")

        candidate = str(entry.get("id") or (source_path.stem if source_path else ""))
        base_id = _safe_id(candidate, index)
        case_id = base_id
        suffix = 2
        while case_id in used_ids:
            case_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(case_id)

        if requested_mode == "auto":
            detection = profile.get("mode_detection", {})
            if detection.get("type", "none") == "first_nonempty_line":
                detected = _first_nonempty_line(content)
                if detection.get("case_sensitive", False):
                    case_mode = detected if detected in modes else ""
                else:
                    lookup = {name.casefold(): name for name in available_modes}
                    case_mode = lookup.get(detected.casefold(), "")
                if not case_mode:
                    raise ValueError(f"Cannot detect a configured mode from input '{case_id}': {detected}")
            else:
                case_mode = str(profile["default_mode"])
        else:
            case_mode = requested_mode
        mode_config = modes[case_mode]

        if options.system_prompt_path:
            system_path = options.system_prompt_path
            system_prompt = system_path.read_text(encoding="utf-8-sig")
            system_source = "explicit-override"
        elif mode_config.get("system_prompt"):
            system_path = expand_path(str(mode_config["system_prompt"]), system_root)
            if not system_path.is_file():
                raise FileNotFoundError(f"System prompt not found: {system_path}")
            system_prompt = system_path.read_text(encoding="utf-8-sig")
            system_source = "profile-file"
        else:
            system_path = None
            system_prompt = str(mode_config.get("system_prompt_text", ""))
            system_source = "profile-inline"

        observations: list[Observation] = []
        for definition in profile.get("observations", []):
            pattern = re.compile(str(definition["input_pattern"]))
            text_group = int(definition.get("text_group", 0))
            marker_group = int(definition.get("marker_group", 0))
            for match in pattern.finditer(content):
                observations.append(Observation(
                    observation_id=str(definition["id"]),
                    text=match.group(text_group),
                    marker=match.group(marker_group),
                    remove_marker_in_final=bool(definition.get("remove_marker_in_final", False)),
                ))

        cases.append(InputCase(
            case_id=case_id,
            mode=case_mode,
            mode_config=mode_config,
            source_kind=source_kind,
            source_path=source_path,
            content=content,
            input_sha256=sha256_text(content),
            system_prompt_path=system_path,
            system_prompt=system_prompt,
            system_prompt_source=system_source,
            system_prompt_sha256=sha256_text(system_prompt),
            observations=observations,
        ))
    return PreparedBatch(options, app_config, profile, paths, base_url, output_root, cases)


def validate_batch(options: BatchOptions) -> ValidationReport:
    prepared = prepare_batch(options)
    return ValidationReport(str(prepared.profile["id"]), len(options.model_ids), prepared.cases)
