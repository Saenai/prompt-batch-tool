from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .domain import PreparedBatch
from .storage import safe_path_component, write_csv


RECORD_FIELDS = [
    "model", "input", "mode", "repeat", "seed", "success", "valid_output", "observation_count",
    "observations_preserved", "missing_observations", "markers_retained", "retained_markers", "finish_reason",
    "api_elapsed_seconds", "generation_seconds", "generation_tokens_per_second", "prompt_tokens",
    "completion_tokens", "output_characters",
]


def is_valid_output(content: str, profile: dict[str, Any], mode_config: dict[str, Any]) -> bool:
    required = [
        *profile.get("validation", {}).get("required_patterns", []),
        *mode_config.get("validation", {}).get("required_patterns", []),
    ]
    forbidden = [
        *profile.get("validation", {}).get("forbidden_patterns", []),
        *mode_config.get("validation", {}).get("forbidden_patterns", []),
    ]
    return all(re.search(pattern, content) for pattern in required) and not any(
        re.search(pattern, content) for pattern in forbidden
    )


def _average(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return sum(values) / len(values) if values else None


def _format_average(value: float | None, digits: int) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def write_batch_reports(
    run_dir: Path,
    prepared: PreparedBatch,
    records: list[dict[str, Any]],
    result_dir: Path,
    final_dir: Path,
) -> dict[str, str]:
    profile = prepared.profile
    options = prepared.options
    output_config = profile.get("output", {})
    files = {
        "records": str(output_config.get("records_file", "BATCH-RECORDS.csv")),
        "observations": str(output_config.get("observations_file", "OBSERVATIONS.csv")),
        "all": str(output_config.get("all_outputs_file", "ALL-OUTPUTS.md")),
        "raw": str(output_config.get("raw_outputs_file", "ALL-OUTPUTS-RAW.md")),
        "summary": str(output_config.get("summary_file", "BATCH-SUMMARY.md")),
    }
    write_csv(run_dir / files["records"], records, RECORD_FIELDS)
    write_csv(run_dir / files["observations"], records, RECORD_FIELDS[:12])

    title = str(output_config.get("aggregate_title", "Prompt Batch Outputs"))
    final_lines = [
        f"# {title}", "", f"- Profile: {profile.get('display_name', profile['id'])}",
        f"- Run directory: {run_dir}", "",
    ]
    raw_lines = [
        f"# {title} - Raw", "", f"- Profile: {profile.get('display_name', profile['id'])}",
        f"- Run directory: {run_dir}", "",
    ]
    for model_id in options.model_ids:
        final_lines.extend([f"# Model: {model_id}", ""])
        raw_lines.extend([f"# Model: {model_id}", ""])
        for case in prepared.cases:
            final_lines.extend([f"## Input: {case.case_id} [{case.mode}]", ""])
            raw_lines.extend([f"## Input: {case.case_id} [{case.mode}]", ""])
            for repeat in range(1, options.repeats + 1):
                name = f"run-{repeat:02d}.md"
                model_directory = safe_path_component(model_id)
                final_path = final_dir / model_directory / case.case_id / name
                result_path = result_dir / model_directory / case.case_id / name
                final_content = final_path.read_text(encoding="utf-8").strip() if final_path.is_file() else "[MISSING RESULT]"
                raw_content = result_path.read_text(encoding="utf-8").strip() if result_path.is_file() else "[MISSING RESULT]"
                final_lines.extend([f"### Result {repeat:02d}", "", "```text", final_content, "```", ""])
                raw_lines.extend([f"### Result {repeat:02d}", "", "```text", raw_content, "```", ""])
    (run_dir / files["all"]).write_text("\n".join(final_lines), encoding="utf-8")
    (run_dir / files["raw"]).write_text("\n".join(raw_lines), encoding="utf-8")

    denominator = len(prepared.cases) * options.repeats
    summary = [
        f"# {output_config.get('summary_title', 'Prompt Batch Summary')}", "",
        f"- Profile: {profile.get('display_name', profile['id'])}",
        f"- Models: {len(options.model_ids)}", f"- Inputs: {len(prepared.cases)}",
        f"- Repeats per input: {options.repeats}",
        f"- Total requested: {len(options.model_ids) * denominator}",
        "- Request order: model -> repeat -> input", "",
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
    (run_dir / files["summary"]).write_text("\n".join(summary), encoding="utf-8")
    return files
