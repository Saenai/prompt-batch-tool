from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .backends import backend_identity, create_backend
from .config import load_json
from .domain import BatchOptions, EventFunction, LogFunction, PreparedBatch, ValidationReport
from .preparation import prepare_batch, profile_fingerprint, validate_batch
from .reporting import is_valid_output, write_batch_reports
from .runtime import runtime_version, start_router, terminate_process_tree
from .storage import atomic_write_json, load_optional_json


def _emit(event: EventFunction | None, event_type: str, **payload: Any) -> None:
    if event is not None:
        event({"type": event_type, **payload})


def _resume_identity(prepared: PreparedBatch) -> dict[str, Any]:
    options = prepared.options
    return {
        "profile_id": str(prepared.profile["id"]),
        "profile_sha256": profile_fingerprint(prepared.profile),
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


def run_batch(options: BatchOptions, log: LogFunction = print, event: EventFunction | None = None) -> Path:
    prepared = prepare_batch(options)
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
                record = load_optional_json(raw_dir / model_id / case.case_id / f"{stem}.record.json")
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
        "profile_sha256": profile_fingerprint(profile),
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
        "runtime_version": runtime_version(prepared),
    }
    atomic_write_json(manifest_path, manifest)
    _emit(event, "batch_started", run_directory=str(run_dir), total=total_requested, planned=planned_requests,
          strategy=manifest["run_strategy"])
    try:
        if planned_requests and not backend.ready():
            if not may_start_router:
                raise RuntimeError(f"Endpoint is unavailable and does not match the configured local router URL: {models_uri}")
            router_process = start_router(prepared, log_dir)
            manifest["router_started_by_script"] = True
            atomic_write_json(manifest_path, manifest)
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
                            "success": True, "valid_output": is_valid_output(content, profile, case.mode_config),
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
                        atomic_write_json(record_path, record)
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
                        atomic_write_json(record_path, record)
                        completed_items += 1
                        executed_items += 1
                        log(f"WARNING: {model_id}/{case.case_id}/{stem} failed: {exc}")
                        _emit(event, "item_finished", model=model_id, input=case.case_id, repeat=repeat,
                              status="failed", completed=completed_items, total=total_requested,
                              elapsed_seconds=record["api_elapsed_seconds"], error=str(exc))

        output_files = write_batch_reports(run_dir, prepared, records, result_dir, final_dir)
        manifest["failures"] = failures
        manifest["status"] = "completed_with_failures" if failures else "completed"
        manifest["completed_at"] = datetime.now().astimezone().isoformat()
        manifest["executed_items_this_run"] = executed_items
        manifest["skipped_items_this_run"] = skipped_items
        manifest["output_files"] = output_files
        atomic_write_json(manifest_path, manifest)
        _emit(event, "batch_finished", run_directory=str(run_dir), total=total_requested, completed=completed_items,
              executed=executed_items, skipped=skipped_items, failures=len(failures), status=manifest["status"])
    except Exception as exc:
        manifest["status"] = "interrupted"
        manifest["updated_at"] = datetime.now().astimezone().isoformat()
        manifest["error"] = str(exc)
        atomic_write_json(manifest_path, manifest)
        _emit(event, "batch_failed", run_directory=str(run_dir), error=str(exc), completed=completed_items,
              total=total_requested)
        raise
    finally:
        if router_process is not None:
            terminate_process_tree(router_process)

    log(f"Completed: {run_dir}")
    if failures:
        raise RuntimeError(f"Failures: {len(failures)}")
    return run_dir
