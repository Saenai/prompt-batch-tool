from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


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
