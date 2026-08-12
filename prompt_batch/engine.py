from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .backend import backend_identity, create_backend
from .config import expand_path, load_app_config, load_json, load_profile, resolve_config_paths


LogFunction = Callable[[str], None]
EventFunction = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class BatchOptions:
    app_config_path: Path
    profile_path: Path
    input_manifest_path: Path
    mode: str
    repeats: int
    max_tokens: int
    seed_base: int
    model_ids: list[str]
    system_prompt_path: Path | None = None
    base_url: str | None = None
    output_root: Path | None = None
    run_directory: Path | None = None
    resume: bool = False
    retry_failed_only: bool = False


@dataclass(slots=True)
class Observation:
    observation_id: str
    text: str
    marker: str
    remove_marker_in_final: bool


@dataclass(slots=True)
class InputCase:
    case_id: str
    mode: str
    mode_config: dict[str, Any]
    source_kind: str
    source_path: Path | None
    content: str
    input_sha256: str
    system_prompt_path: Path | None
    system_prompt: str
    system_prompt_source: str
    system_prompt_sha256: str
    observations: list[Observation]


@dataclass(slots=True)
class PreparedBatch:
    options: BatchOptions
    app_config: dict[str, Any]
    profile: dict[str, Any]
    paths: dict[str, Path]
    base_url: str
    output_root: Path
    cases: list[InputCase]


@dataclass(slots=True)
class ValidationReport:
    profile_id: str
    model_count: int
    cases: list[InputCase]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def _profile_sha256(profile: dict[str, Any]) -> str:
    semantic_profile = {key: value for key, value in profile.items() if key != "$schema"}
    return _sha256_text(json.dumps(semantic_profile, ensure_ascii=False, sort_keys=True))


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


def _prepare_batch(options: BatchOptions) -> PreparedBatch:
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
                observations.append(
                    Observation(
                        observation_id=str(definition["id"]),
                        text=match.group(text_group),
                        marker=match.group(marker_group),
                        remove_marker_in_final=bool(definition.get("remove_marker_in_final", False)),
                    )
                )

        cases.append(
            InputCase(
                case_id=case_id,
                mode=case_mode,
                mode_config=mode_config,
                source_kind=source_kind,
                source_path=source_path,
                content=content,
                input_sha256=_sha256_text(content),
                system_prompt_path=system_path,
                system_prompt=system_prompt,
                system_prompt_source=system_source,
                system_prompt_sha256=_sha256_text(system_prompt),
                observations=observations,
            )
        )
    return PreparedBatch(options, app_config, profile, paths, base_url, output_root, cases)


def validate_batch(options: BatchOptions) -> ValidationReport:
    prepared = _prepare_batch(options)
    return ValidationReport(str(prepared.profile["id"]), len(options.model_ids), prepared.cases)


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        taskkill = Path(os.environ.get("SystemRoot", "")) / "System32" / "taskkill.exe"
        if taskkill.is_file():
            subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _start_router(prepared: PreparedBatch, log_dir: Path) -> subprocess.Popen[Any]:
    app = prepared.app_config
    executable = prepared.paths["router_executable"]
    working_directory = prepared.paths["router_working_directory"]
    if not executable.is_file():
        raise FileNotFoundError(f"Configured router executable not found: {executable}")
    stdout_file = (log_dir / "router.stdout.log").open("w", encoding="utf-8")
    stderr_file = (log_dir / "router.stderr.log").open("w", encoding="utf-8")
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            [str(executable), *[str(arg) for arg in app["router"]["arguments"]]],
            cwd=working_directory,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=creation_flags,
        )
    finally:
        stdout_file.close()
        stderr_file.close()
    return process


def _runtime_version(prepared: PreparedBatch) -> str | None:
    executable = prepared.paths.get("runtime_executable")
    if not executable or not executable.is_file():
        return None
    result = subprocess.run(
        [str(executable), *[str(arg) for arg in prepared.app_config.get("runtime", {}).get("version_arguments", [])]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return (result.stdout + result.stderr).strip()


def _valid_output(content: str, profile: dict[str, Any], mode_config: dict[str, Any]) -> bool:
    required = [*profile.get("validation", {}).get("required_patterns", []), *mode_config.get("validation", {}).get("required_patterns", [])]
    forbidden = [*profile.get("validation", {}).get("forbidden_patterns", []), *mode_config.get("validation", {}).get("forbidden_patterns", [])]
    return all(re.search(pattern, content) for pattern in required) and not any(re.search(pattern, content) for pattern in forbidden)


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _average(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return sum(values) / len(values) if values else None


def _format_average(value: float | None, digits: int) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _emit(event: EventFunction | None, event_type: str, **payload: Any) -> None:
    if event is not None:
        event({"type": event_type, **payload})


def _resume_identity(prepared: PreparedBatch) -> dict[str, Any]:
    options = prepared.options
    return {
        "profile_id": str(prepared.profile["id"]),
        "profile_sha256": _profile_sha256(prepared.profile),
        "backend": backend_identity(prepared.app_config["backend"], prepared.base_url),
        "inputs": [
            {
                "id": case.case_id,
                "mode": case.mode,
                "input_sha256": case.input_sha256,
                "system_prompt_sha256": case.system_prompt_sha256,
            }
            for case in prepared.cases
        ],
        "models": options.model_ids,
        "repeats_per_input": options.repeats,
        "max_tokens": options.max_tokens,
        "seed_base": options.seed_base,
    }


def _validate_resume_manifest(existing: dict[str, Any], prepared: PreparedBatch) -> None:
    expected = _resume_identity(prepared)
    existing_inputs = [
        {
            "id": item.get("id"),
            "mode": item.get("mode"),
            "input_sha256": item.get("input_sha256"),
            "system_prompt_sha256": item.get("system_prompt_sha256"),
        }
        for item in existing.get("inputs", [])
        if isinstance(item, dict)
    ]
    existing_backend = existing.get("backend")
    if existing_backend is None and existing.get("endpoint"):
        existing_backend = backend_identity(prepared.app_config["backend"], str(existing["endpoint"]))
        existing_backend["request_body"] = existing.get("backend_request_body", {})
    actual = {
        "profile_id": existing.get("profile_id"),
        "profile_sha256": existing.get("profile_sha256"),
        "backend": existing_backend,
        "inputs": existing_inputs,
        "models": existing.get("models"),
        "repeats_per_input": existing.get("repeats_per_input"),
        "max_tokens": existing.get("max_tokens"),
        "seed_base": existing.get("seed_base"),
    }
    mismatches = [key for key, value in expected.items() if actual.get(key) != value]
    if mismatches:
        raise ValueError(f"Run directory is incompatible with the requested batch: {', '.join(mismatches)}")


def _load_job_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = load_json(path)
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def run_batch(options: BatchOptions, log: LogFunction = print, event: EventFunction | None = None) -> Path:
    prepared = _prepare_batch(options)
    app = prepared.app_config
    profile = prepared.profile
    output_config = profile.get("output", {})
    prefix = str(output_config.get("run_prefix", profile["id"]))
    if options.run_directory:
        run_dir = options.run_directory
        run_id = run_dir.name
    else:
        run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{prefix}-{len(prepared.cases)}inputs"
        run_dir = prepared.output_root / run_id
    manifest_path = run_dir / "manifest.json"
    resume_requested = options.resume or options.retry_failed_only
    existing_manifest: dict[str, Any] | None = None
    if resume_requested:
        if not run_dir.is_dir() or not manifest_path.is_file():
            raise ValueError(f"Resume requires an existing run directory with manifest.json: {run_dir}")
        existing_manifest = load_json(manifest_path)
        _validate_resume_manifest(existing_manifest, prepared)
    elif run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError(f"Run directory is not empty; choose resume or another directory: {run_dir}")
    input_dir = run_dir / "input"
    system_dir = input_dir / "system-prompts"
    result_dir = run_dir / "results"
    final_dir = run_dir / "final-results"
    raw_dir = run_dir / "raw"
    log_dir = run_dir / "router-logs"
    for directory in (input_dir, system_dir, result_dir, final_dir, raw_dir, log_dir):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(options.app_config_path, input_dir / "app-config.json")
    shutil.copy2(options.profile_path, input_dir / "profile.json")
    shutil.copy2(options.input_manifest_path, input_dir / "input-manifest.json")
    for case in prepared.cases:
        (input_dir / f"{case.case_id}.txt").write_text(case.content, encoding="utf-8")
        (system_dir / f"{case.case_id}.txt").write_text(case.system_prompt, encoding="utf-8")

    backend = create_backend(app["backend"], prepared.base_url)
    models_uri = backend.models_uri
    configured_base = str(app["backend"]["base_url"]).rstrip("/")
    may_start_router = prepared.base_url.rstrip("/") == configured_base
    router_process: subprocess.Popen[Any] | None = None
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    total_requested = len(options.model_ids) * options.repeats * len(prepared.cases)
    existing_records: dict[tuple[str, str, int], dict[str, Any]] = {}
    for model_id in options.model_ids:
        for repeat in range(1, options.repeats + 1):
            stem = f"run-{repeat:02d}"
            for case in prepared.cases:
                record = _load_job_record(raw_dir / model_id / case.case_id / f"{stem}.record.json")
                if record is not None:
                    existing_records[(model_id, case.case_id, repeat)] = record
    if options.retry_failed_only and len(existing_records) != total_requested:
        raise ValueError("Retry-failed mode requires a complete set of per-item records; use normal resume for older or interrupted runs.")

    def should_run(model_id: str, case_id: str, repeat: int) -> bool:
        if not resume_requested:
            return True
        previous = existing_records.get((model_id, case_id, repeat))
        if previous is None:
            return not options.retry_failed_only
        return not bool(previous.get("success"))

    planned_requests = sum(
        should_run(model_id, case.case_id, repeat)
        for model_id in options.model_ids
        for repeat in range(1, options.repeats + 1)
        for case in prepared.cases
    )
    completed_items = 0
    executed_items = 0
    skipped_items = 0
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "created_at": (existing_manifest or {}).get("created_at", datetime.now().astimezone().isoformat()),
        "updated_at": datetime.now().astimezone().isoformat(),
        "status": "running",
        "profile_id": str(profile["id"]),
        "profile_sha256": _profile_sha256(profile),
        "profile_path": str(options.profile_path),
        "app_config_path": str(options.app_config_path),
        "endpoint": prepared.base_url,
        "backend": backend_identity(app["backend"], prepared.base_url),
        "inputs": [
            {
                "id": case.case_id,
                "mode": case.mode,
                "source_kind": case.source_kind,
                "source_path": str(case.source_path) if case.source_path else None,
                "input_sha256": case.input_sha256,
                "system_prompt_path": str(case.system_prompt_path) if case.system_prompt_path else None,
                "system_prompt_source": case.system_prompt_source,
                "system_prompt_sha256": case.system_prompt_sha256,
            }
            for case in prepared.cases
        ],
        "models": options.model_ids,
        "repeats_per_input": options.repeats,
        "input_count": len(prepared.cases),
        "outputs_per_model": options.repeats * len(prepared.cases),
        "total_requested": total_requested,
        "planned_requests_this_run": planned_requests,
        "run_strategy": "retry-failed" if options.retry_failed_only else "resume" if options.resume else "new",
        "resume_count": int((existing_manifest or {}).get("resume_count", 0)) + (1 if resume_requested else 0),
        "max_tokens": options.max_tokens,
        "seed_base": options.seed_base,
        "request_order": "model -> repeat -> input",
        "router_started_by_script": False,
        "runtime_version": _runtime_version(prepared),
    }
    _write_json(manifest_path, manifest)
    _emit(event, "batch_started", run_directory=str(run_dir), total=total_requested, planned=planned_requests,
          strategy=manifest["run_strategy"])
    try:
        if planned_requests and not backend.ready():
            if not may_start_router:
                raise RuntimeError(f"Endpoint is unavailable and does not match the configured local router URL: {models_uri}")
            router_process = _start_router(prepared, log_dir)
            manifest["router_started_by_script"] = True
            _write_json(manifest_path, manifest)
            timeout = int(app["backend"].get("readiness_timeout_seconds", 60))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if backend.ready():
                    break
                if router_process.poll() is not None:
                    raise RuntimeError(f"Router exited before becoming ready: exit {router_process.returncode}")
                time.sleep(1)
            else:
                raise RuntimeError(f"Router did not become ready: {models_uri}")

        if planned_requests:
            available = set(backend.list_model_ids(10))
            missing_models = [model_id for model_id in options.model_ids if model_id not in available]
            if missing_models:
                raise RuntimeError(f"Models are not visible: {', '.join(missing_models)}")

        request_timeout = int(app["backend"].get("request_timeout_seconds", 3600))
        for model_index, model_id in enumerate(options.model_ids, start=1):
            log(f"[{model_index}/{len(options.model_ids)}] {model_id}")
            _emit(event, "model_started", model=model_id, index=model_index, total_models=len(options.model_ids))
            for repeat in range(1, options.repeats + 1):
                seed = options.seed_base + repeat
                for case in prepared.cases:
                    case_result = result_dir / model_id / case.case_id
                    case_final = final_dir / model_id / case.case_id
                    case_raw = raw_dir / model_id / case.case_id
                    for directory in (case_result, case_final, case_raw):
                        directory.mkdir(parents=True, exist_ok=True)
                    stem = f"run-{repeat:02d}"
                    record_path = case_raw / f"{stem}.record.json"
                    previous = existing_records.get((model_id, case.case_id, repeat))
                    if not should_run(model_id, case.case_id, repeat):
                        if previous is not None:
                            records.append(previous)
                            if not previous.get("success"):
                                failures.append({"model": model_id, "input": case.case_id, "repeat": repeat,
                                                 "error": str(previous.get("error") or "previous request error")})
                        completed_items += 1
                        skipped_items += 1
                        log(f"  {case.case_id} {stem} skipped")
                        _emit(event, "item_finished", model=model_id, input=case.case_id, repeat=repeat,
                              status="skipped", completed=completed_items, total=total_requested)
                        continue
                    for stale_path in (
                        case_result / f"{stem}.md",
                        case_result / f"{stem}.reasoning.txt",
                        case_final / f"{stem}.md",
                        case_raw / f"{stem}.json",
                        case_raw / f"{stem}.error.txt",
                    ):
                        stale_path.unlink(missing_ok=True)
                    messages: list[dict[str, str]] = []
                    if case.system_prompt:
                        messages.append({"role": "system", "content": case.system_prompt})
                    messages.append({"role": "user", "content": case.content})
                    body: dict[str, Any] = {}
                    for source in (app["backend"].get("request_body"), profile.get("request_body"), case.mode_config.get("request_body")):
                        if isinstance(source, dict):
                            body.update(source)
                    body.update({"model": model_id, "messages": messages, "max_tokens": options.max_tokens, "seed": seed, "stream": False})
                    _emit(event, "item_started", model=model_id, input=case.case_id, repeat=repeat,
                          completed=completed_items, total=total_requested)
                    started = time.perf_counter()
                    try:
                        raw_response, response = backend.chat_completions(body, request_timeout)
                        elapsed = time.perf_counter() - started
                        (case_raw / f"{stem}.json").write_text(raw_response, encoding="utf-8")
                        choice = response["choices"][0]
                        message = choice["message"]
                        content = str(message.get("content") or "")
                        (case_result / f"{stem}.md").write_text(content, encoding="utf-8")
                        if message.get("reasoning_content"):
                            (case_result / f"{stem}.reasoning.txt").write_text(str(message["reasoning_content"]), encoding="utf-8")
                        final_content = content
                        missing: list[str] = []
                        retained: list[str] = []
                        for observation in case.observations:
                            if observation.text not in content:
                                missing.append(f"{observation.observation_id}:{observation.text}")
                            if observation.marker in content:
                                retained.append(f"{observation.observation_id}:{observation.marker}")
                                if observation.remove_marker_in_final:
                                    final_content = final_content.replace(observation.marker, observation.text)
                        (case_final / f"{stem}.md").write_text(final_content, encoding="utf-8")
                        timings = response.get("timings") or {}
                        usage = response.get("usage") or {}
                        predicted_ms = timings.get("predicted_ms")
                        record = {
                            "model": model_id, "input": case.case_id, "mode": case.mode, "repeat": repeat, "seed": seed,
                            "success": True, "valid_output": _valid_output(content, profile, case.mode_config),
                            "observation_count": len(case.observations), "observations_preserved": not missing,
                            "missing_observations": " | ".join(missing), "markers_retained": bool(retained), "retained_markers": " | ".join(retained),
                            "finish_reason": str(choice.get("finish_reason") or ""), "api_elapsed_seconds": round(elapsed, 3),
                            "generation_seconds": round(float(predicted_ms) / 1000, 3) if predicted_ms is not None else None,
                            "generation_tokens_per_second": round(float(timings["predicted_per_second"]), 3) if timings.get("predicted_per_second") is not None else None,
                            "prompt_tokens": int(usage["prompt_tokens"]) if usage.get("prompt_tokens") is not None else None,
                            "completion_tokens": int(usage["completion_tokens"]) if usage.get("completion_tokens") is not None else None,
                            "output_characters": len(content),
                        }
                        records.append(record)
                        _write_json(record_path, record)
                        (case_raw / f"{stem}.error.txt").unlink(missing_ok=True)
                        completed_items += 1
                        executed_items += 1
                        log(f"  {case.case_id} {stem} seed={seed}")
                        _emit(event, "item_finished", model=model_id, input=case.case_id, repeat=repeat,
                              status="success", completed=completed_items, total=total_requested,
                              elapsed_seconds=record["api_elapsed_seconds"])
                    except Exception as exc:
                        elapsed = time.perf_counter() - started
                        (case_raw / f"{stem}.error.txt").write_text(repr(exc), encoding="utf-8")
                        failures.append({"model": model_id, "input": case.case_id, "repeat": repeat, "error": str(exc)})
                        record = {
                            "model": model_id, "input": case.case_id, "mode": case.mode, "repeat": repeat, "seed": seed,
                            "success": False, "valid_output": False, "observation_count": len(case.observations),
                            "observations_preserved": False, "missing_observations": "request_error", "markers_retained": False,
                            "retained_markers": "", "finish_reason": "request_error", "api_elapsed_seconds": round(elapsed, 3),
                            "generation_seconds": None, "generation_tokens_per_second": None, "prompt_tokens": None,
                            "completion_tokens": None, "output_characters": None, "error": str(exc),
                        }
                        records.append(record)
                        _write_json(record_path, record)
                        completed_items += 1
                        executed_items += 1
                        log(f"WARNING: {model_id}/{case.case_id}/{stem} failed: {exc}")
                        _emit(event, "item_finished", model=model_id, input=case.case_id, repeat=repeat,
                              status="failed", completed=completed_items, total=total_requested,
                              elapsed_seconds=record["api_elapsed_seconds"], error=str(exc))

        records_file = str(output_config.get("records_file", "BATCH-RECORDS.csv"))
        observations_file = str(output_config.get("observations_file", "OBSERVATIONS.csv"))
        all_file = str(output_config.get("all_outputs_file", "ALL-OUTPUTS.md"))
        raw_file = str(output_config.get("raw_outputs_file", "ALL-OUTPUTS-RAW.md"))
        summary_file = str(output_config.get("summary_file", "BATCH-SUMMARY.md"))
        record_fields = [
            "model", "input", "mode", "repeat", "seed", "success", "valid_output", "observation_count",
            "observations_preserved", "missing_observations", "markers_retained", "retained_markers", "finish_reason",
            "api_elapsed_seconds", "generation_seconds", "generation_tokens_per_second", "prompt_tokens",
            "completion_tokens", "output_characters",
        ]
        observation_fields = record_fields[:12]
        _write_csv(run_dir / records_file, records, record_fields)
        _write_csv(run_dir / observations_file, records, observation_fields)

        title = str(output_config.get("aggregate_title", "Prompt Batch Outputs"))
        final_lines = [f"# {title}", "", f"- Profile: {profile.get('display_name', profile['id'])}", f"- Run directory: {run_dir}", ""]
        raw_lines = [f"# {title} - Raw", "", f"- Profile: {profile.get('display_name', profile['id'])}", f"- Run directory: {run_dir}", ""]
        for model_id in options.model_ids:
            final_lines.extend([f"# Model: {model_id}", ""])
            raw_lines.extend([f"# Model: {model_id}", ""])
            for case in prepared.cases:
                final_lines.extend([f"## Input: {case.case_id} [{case.mode}]", ""])
                raw_lines.extend([f"## Input: {case.case_id} [{case.mode}]", ""])
                for repeat in range(1, options.repeats + 1):
                    name = f"run-{repeat:02d}.md"
                    final_path = final_dir / model_id / case.case_id / name
                    result_path = result_dir / model_id / case.case_id / name
                    final_content = final_path.read_text(encoding="utf-8").strip() if final_path.is_file() else "[MISSING RESULT]"
                    raw_content = result_path.read_text(encoding="utf-8").strip() if result_path.is_file() else "[MISSING RESULT]"
                    final_lines.extend([f"### Result {repeat:02d}", "", "```text", final_content, "```", ""])
                    raw_lines.extend([f"### Result {repeat:02d}", "", "```text", raw_content, "```", ""])
        (run_dir / all_file).write_text("\n".join(final_lines), encoding="utf-8")
        (run_dir / raw_file).write_text("\n".join(raw_lines), encoding="utf-8")

        summary_title = str(output_config.get("summary_title", "Prompt Batch Summary"))
        denominator = len(prepared.cases) * options.repeats
        summary = [
            f"# {summary_title}", "", f"- Profile: {profile.get('display_name', profile['id'])}",
            f"- Models: {len(options.model_ids)}", f"- Inputs: {len(prepared.cases)}", f"- Repeats per input: {options.repeats}",
            f"- Total requested: {len(options.model_ids) * denominator}", "- Request order: model -> repeat -> input", "",
            "| Model | HTTP | Valid | Gen avg (s) | Avg tok/s | Avg completion tokens |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for model_id in options.model_ids:
            model_rows = [row for row in records if row["model"] == model_id]
            ok_rows = [row for row in model_rows if row["success"]]
            valid_count = sum(bool(row["valid_output"]) for row in model_rows)
            summary.append(
                f"| {model_id} | {len(ok_rows)}/{denominator} | {valid_count}/{denominator} | "
                f"{_format_average(_average(ok_rows, 'generation_seconds'), 2)} | "
                f"{_format_average(_average(ok_rows, 'generation_tokens_per_second'), 2)} | "
                f"{_format_average(_average(ok_rows, 'completion_tokens'), 0)} |"
            )
        (run_dir / summary_file).write_text("\n".join(summary), encoding="utf-8")
        manifest["failures"] = failures
        manifest["status"] = "completed_with_failures" if failures else "completed"
        manifest["completed_at"] = datetime.now().astimezone().isoformat()
        manifest["executed_items_this_run"] = executed_items
        manifest["skipped_items_this_run"] = skipped_items
        manifest["output_files"] = {"all": all_file, "raw": raw_file, "records": records_file, "observations": observations_file, "summary": summary_file}
        _write_json(manifest_path, manifest)
        _emit(event, "batch_finished", run_directory=str(run_dir), total=total_requested, completed=completed_items,
              executed=executed_items, skipped=skipped_items, failures=len(failures), status=manifest["status"])
    except Exception as exc:
        manifest["status"] = "interrupted"
        manifest["updated_at"] = datetime.now().astimezone().isoformat()
        manifest["error"] = str(exc)
        _write_json(manifest_path, manifest)
        _emit(event, "batch_failed", run_directory=str(run_dir), error=str(exc), completed=completed_items,
              total=total_requested)
        raise
    finally:
        if router_process is not None:
            _terminate_process_tree(router_process)

    log(f"Completed: {run_dir}")
    if failures:
        raise RuntimeError(f"Failures: {len(failures)}")
    return run_dir
