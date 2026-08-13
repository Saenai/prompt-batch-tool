from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RecentRun:
    run_directory: Path
    aggregate_path: Path
    summary_path: Path | None
    status: str
    updated_timestamp: float

    @property
    def display_time(self) -> str:
        return datetime.fromtimestamp(self.updated_timestamp).strftime("%Y-%m-%d %H:%M")


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _configured_output_names(run_directory: Path, manifest: dict[str, Any]) -> tuple[str | None, str | None]:
    files = manifest.get("output_files")
    if isinstance(files, dict):
        aggregate = files.get("all")
        summary = files.get("summary")
        if isinstance(aggregate, str) and aggregate.strip():
            return aggregate, summary if isinstance(summary, str) and summary.strip() else None

    profile = _read_object(run_directory / "input" / "profile.json")
    output = profile.get("output") if profile else None
    if isinstance(output, dict):
        aggregate = output.get("all_outputs_file")
        summary = output.get("summary_file")
        if isinstance(aggregate, str) and aggregate.strip():
            return aggregate, summary if isinstance(summary, str) and summary.strip() else None
    return None, None


def _resolve_output(run_directory: Path, name: str | None) -> Path | None:
    if not name:
        return None
    candidate = run_directory / name
    try:
        resolved = candidate.resolve()
        resolved.relative_to(run_directory.resolve())
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def scan_recent_runs(output_root: Path, max_entries: int) -> list[RecentRun]:
    root = output_root.expanduser().resolve()
    if not root.is_dir():
        return []
    entries: list[RecentRun] = []
    try:
        children = list(root.iterdir())
    except OSError:
        return []
    for run_directory in children:
        if not run_directory.is_dir():
            continue
        manifest_path = run_directory / "manifest.json"
        manifest = _read_object(manifest_path)
        if manifest is None:
            continue
        aggregate_name, summary_name = _configured_output_names(run_directory, manifest)
        aggregate_path = _resolve_output(run_directory, aggregate_name)
        if aggregate_path is None:
            continue
        summary_path = _resolve_output(run_directory, summary_name)
        try:
            updated = max(manifest_path.stat().st_mtime, aggregate_path.stat().st_mtime)
        except OSError:
            continue
        entries.append(
            RecentRun(
                run_directory=run_directory.resolve(),
                aggregate_path=aggregate_path,
                summary_path=summary_path,
                status=str(manifest.get("status", "unknown")),
                updated_timestamp=updated,
            )
        )
    entries.sort(key=lambda entry: entry.updated_timestamp, reverse=True)
    return entries[:max_entries]
