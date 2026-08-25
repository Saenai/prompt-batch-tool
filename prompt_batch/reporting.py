from __future__ import annotations

import json
import re
from html import escape
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


def _render_markdown_aggregate(title: str, profile: dict[str, Any], run_dir: Path,
                               rows: list[tuple[str, int, str]]) -> str:
    lines = [
        f"# {title}", "", f"- Profile: {profile.get('display_name', profile['id'])}",
        f"- Run directory: {run_dir}", "",
    ]
    for model_id, repeat, content in rows:
        lines.extend([
            f"# Model: {model_id}", "", f"### Result {repeat:02d}", "", "```text",
            content, "```", "",
        ])
    return "\n".join(lines)


def _render_html_aggregate(title: str, profile: dict[str, Any], rows: list[tuple[str, int, str]]) -> str:
    body = []
    for sequence, (model_id, repeat, content) in enumerate(rows, start=1):
        body.append(
            "<tr>"
            f"<td class=\"sequence\">{sequence}</td>"
            f"<td>{escape(model_id)}</td>"
            f"<td>{repeat}</td>"
            f"<td class=\"prompt\"><pre>{escape(content)}</pre></td>"
            "</tr>"
        )
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ margin: 1.5rem; font-family: system-ui, sans-serif; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
th, td {{ border: 1px solid #8888; padding: .55rem .7rem; vertical-align: top; text-align: left; }}
th {{ position: sticky; top: 0; background: Canvas; z-index: 1; }}
th:nth-child(1), td:nth-child(1) {{ width: 3.5rem; text-align: center; }}
th:nth-child(2), td:nth-child(2) {{ width: 21%; overflow-wrap: anywhere; }}
th:nth-child(3), td:nth-child(3) {{ width: 5rem; text-align: center; }}
td.prompt pre {{ margin: 0; max-height: 32rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p>Profile: {profile}</p>
<table>
<thead><tr><th>#</th><th>Model</th><th>Repeat</th><th>Prompt</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body>
</html>
""".format(
        title=escape(title),
        profile=escape(str(profile.get("display_name", profile["id"]))),
        rows="\n".join(body),
    )


def _render_jsonl_prompts(rows: list[dict[str, Any]]) -> str:
    """Render final prompts as one self-contained JSON object per line."""
    return "\n".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        for row in rows
    ) + ("\n" if rows else "")


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
        key: str(value)
        for key, config_key in (
            ("records", "records_file"), ("observations", "observations_file"),
            ("all", "all_outputs_file"), ("raw", "raw_outputs_file"),
            ("structured", "structured_outputs_file"), ("summary", "summary_file"),
        )
        if (value := output_config.get(config_key))
    }
    if "records" in files:
        write_csv(run_dir / files["records"], records, RECORD_FIELDS)
    if "observations" in files:
        write_csv(run_dir / files["observations"], records, RECORD_FIELDS[:12])

    title = str(output_config.get("aggregate_title", "Prompt Batch Outputs"))
    final_rows: list[tuple[str, int, str]] = []
    raw_rows: list[tuple[str, int, str]] = []
    structured_rows: list[dict[str, Any]] = []
    sequence = 0
    for model_id in options.model_ids:
        for case in prepared.cases:
            for repeat in range(1, options.repeats + 1):
                name = f"run-{repeat:02d}.md"
                model_directory = safe_path_component(model_id)
                final_path = final_dir / model_directory / case.case_id / name
                result_path = result_dir / model_directory / case.case_id / name
                final_content = final_path.read_text(encoding="utf-8").strip() if final_path.is_file() else "[MISSING RESULT]"
                raw_content = result_path.read_text(encoding="utf-8").strip() if result_path.is_file() else "[MISSING RESULT]"
                final_rows.append((model_id, repeat, final_content))
                raw_rows.append((model_id, repeat, raw_content))
                if final_path.is_file():
                    sequence += 1
                    structured_rows.append({
                        "sequence": sequence,
                        "model": model_id,
                        "repeat": repeat,
                        "input": case.case_id,
                        "mode": case.mode,
                        "prompt": final_content,
                    })
    for key, rows, report_title in (("all", final_rows, title), ("raw", raw_rows, f"{title} - Raw")):
        if key not in files:
            continue
        path = run_dir / files[key]
        if path.suffix.casefold() == ".html":
            path.write_text(_render_html_aggregate(report_title, profile, rows), encoding="utf-8")
        else:
            path.write_text(_render_markdown_aggregate(report_title, profile, run_dir, rows), encoding="utf-8")
    if "structured" in files:
        (run_dir / files["structured"]).write_text(
            _render_jsonl_prompts(structured_rows), encoding="utf-8"
        )

    denominator = len(prepared.cases) * options.repeats
    if "summary" in files:
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
