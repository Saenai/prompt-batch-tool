from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def safe_path_component(value: str) -> str:
    """Match prompt-batch-tool's Windows-safe external identifier encoding."""
    source = str(value)
    encoded: list[str] = []
    last_index = len(source) - 1
    for index, character in enumerate(source):
        if character.isascii() and (character.isalnum() or character in "._-") and not (
            character == "." and index == last_index
        ):
            encoded.append(character)
        else:
            encoded.append(f"~{ord(character):04X}")
    return "".join(encoded) or "~0000"


def export_prompts(run_dir: Path, output_path: Path | None = None) -> Path:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest.json not found: {manifest_path}")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    models = manifest.get("models")
    inputs = manifest.get("inputs")
    repeats = manifest.get("repeats_per_input")
    if not isinstance(models, list) or not all(isinstance(model, str) for model in models):
        raise ValueError("manifest.models must be a list of strings")
    if not isinstance(inputs, list) or not all(isinstance(item, dict) for item in inputs):
        raise ValueError("manifest.inputs must be a list of objects")
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError("manifest.repeats_per_input must be a positive integer")

    rows: list[dict[str, Any]] = []
    sequence = 0
    final_root = run_dir / "final-results"
    for model in models:
        for item in inputs:
            case_id = item.get("id")
            mode = item.get("mode")
            if not isinstance(case_id, str) or not isinstance(mode, str):
                raise ValueError("manifest.inputs entries require string id and mode")
            case_root = final_root / safe_path_component(model) / case_id
            for repeat in range(1, repeats + 1):
                prompt_path = case_root / f"run-{repeat:02d}.md"
                if not prompt_path.is_file():
                    continue
                sequence += 1
                rows.append({
                    "sequence": sequence,
                    "model": model,
                    "repeat": repeat,
                    "input": case_id,
                    "mode": mode,
                    "prompt": prompt_path.read_text(encoding="utf-8").strip(),
                })

    target = output_path or (run_dir / "prompts.jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Export an existing prompt-batch run as prompts.jsonl.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Existing prompt-batch run directory")
    parser.add_argument("--output", type=Path, help="Output JSONL path; defaults to <run-dir>/prompts.jsonl")
    args = parser.parse_args()
    target = export_prompts(args.run_dir.expanduser().resolve(), args.output.expanduser().resolve() if args.output else None)
    print(f"Exported: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
