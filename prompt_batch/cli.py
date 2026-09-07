from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_app_config
from .engine import BatchOptions, run_batch, validate_batch


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile-driven prompt batch generator")
    parser.add_argument("--app-config", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--input-manifest", required=True, type=Path)
    parser.add_argument("--mode", default="auto")
    parser.add_argument("--system-prompt", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-directory", type=Path)
    parser.add_argument("--repeats", required=True, type=int)
    parser.add_argument("--max-tokens", required=True, type=int)
    seed_mode = parser.add_mutually_exclusive_group()
    seed_mode.add_argument("--random-seed", dest="random_seed", action="store_true", help="Generate a random seed base for this new run")
    seed_mode.add_argument("--no-random-seed", dest="random_seed", action="store_false", help="Use the configured seed base")
    parser.set_defaults(random_seed=None)
    parser.add_argument("--seed-base", type=int, help="Fixed seed base; implies --no-random-seed unless --random-seed is explicit")
    parser.add_argument("--model", dest="models", action="append", required=True)
    parser.add_argument("--validate-only", action="store_true")
    strategy = parser.add_mutually_exclusive_group()
    strategy.add_argument("--resume", action="store_true", help="Skip successful items and run failed or missing items")
    strategy.add_argument("--retry-failed", action="store_true", help="Retry only items recorded as failed")
    parser.add_argument("--event-format", choices=("text", "jsonl"), default="text")
    return parser


def main() -> int:
    # Redirected Windows streams otherwise inherit a locale code page that
    # cannot represent every valid input/output path.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    args = build_parser().parse_args()
    app_defaults = load_app_config(args.app_config).get("defaults", {})
    if args.random_seed is True and args.seed_base is not None:
        raise SystemExit("--random-seed and --seed-base cannot be used together")
    random_seed = args.random_seed
    if random_seed is None:
        random_seed = args.seed_base is None and bool(app_defaults.get("random_seed", True))
    seed_base = args.seed_base if args.seed_base is not None else int(app_defaults.get("seed_base", 1))
    options = BatchOptions(
        app_config_path=args.app_config,
        profile_path=args.profile,
        input_manifest_path=args.input_manifest,
        mode=args.mode,
        repeats=args.repeats,
        max_tokens=args.max_tokens,
        seed_base=seed_base,
        model_ids=args.models,
        random_seed=random_seed,
        system_prompt_path=args.system_prompt,
        base_url=args.base_url,
        output_root=args.output_root,
        run_directory=args.run_directory,
        resume=args.resume,
        retry_failed_only=args.retry_failed,
    )
    jsonl = args.event_format == "jsonl"

    def emit(payload: dict) -> None:
        print(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), flush=True)

    def log(message: str) -> None:
        if jsonl:
            emit({"type": "log", "message": message})
        else:
            print(message, flush=True)

    try:
        if args.validate_only:
            report = validate_batch(options)
            if jsonl:
                emit({"type": "validation_finished", "profile": report.profile_id,
                      "inputs": len(report.cases), "models": report.model_count,
                      "cases": [{"id": case.case_id, "mode": case.mode, "source": case.source_kind,
                                 "system": case.system_prompt_source} for case in report.cases]})
            else:
                print(f"Validation OK: profile={report.profile_id}, inputs={len(report.cases)}, models={report.model_count}.")
                for case in report.cases:
                    print(f"  {case.case_id}: mode={case.mode}, source={case.source_kind}, system={case.system_prompt_source}")
        else:
            run_batch(options, log=log, event=emit if jsonl else None)
        return 0
    except Exception as exc:
        if jsonl:
            emit({"type": "error", "message": str(exc)})
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
