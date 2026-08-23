# Prompt Batch Generator

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md)

A local batch-generation tool for OpenAI-compatible Chat Completions APIs. It executes the Cartesian product of models, inputs, and repeat counts while profiles define system prompts, modes, validation rules, observations, request parameters, and output names.

The source version uses only the Python standard library. The GUI is built with Tkinter; PowerShell remains only as a compatibility entry point.

## Portable Windows package

CI builds a Windows x64 portable ZIP for every commit. It contains the GUI executable, CLI executable, default configuration, profiles, schemas, and documentation, and does not require a separate Python installation.

A successful `main` build automatically updates the rolling [Continuous prerelease](https://github.com/Saenai/prompt-batch-tool/releases/tag/continuous). Pushing a `v*` tag publishes an immutable versioned release. Both include the portable ZIP and its SHA-256 checksum.

Extract the archive and run `PromptBatchGenerator.exe` directly; `launch-gui.cmd` remains as a compatibility launcher. The default paths assume this folder is installed as `.llama.cpp/prompt-batch-tool`, next to `llama-swap` and `llama-current`; edit `config/app.json` for other layouts.

## Quick start from source

Double-click `launch-gui.cmd`, or run from the repository root:

```powershell
python .\app.py
```

Run self-checks and tests:

```powershell
python .\app.py --config .\config\app.json --self-test
python -B -m unittest discover -s tests -v
```

CLI example:

```powershell
python .\batch_cli.py `
  --app-config .\config\app.json `
  --profile .\profiles\plain.json `
  --input-manifest .\inputs.json `
  --mode default `
  --repeats 2 `
  --max-tokens 16384 `
  --random-seed `
  --model model-a
```

New runs use a random seed by default. Each run keeps one random seed base and increments it by repeat, so comparisons within that run remain controlled. Use `--no-random-seed --seed-base 100` for reproducible fixed seeds. Omitting both flags follows `defaults.random_seed` in `config/app.json`.

Add `--validate-only` to validate configuration and inputs without starting the router or sending requests.

## Features

- Combine file inputs, multiple prompts, and direct GUI input in one batch.
- Finish all inputs for one model before switching models, reducing llama-swap reloads.
- Discover models dynamically through the API or an external llama-swap configuration.
- Group, filter, collapse, and select models by family and parameter tier.
- Monitor local NVIDIA VRAM, GPU utilization, temperature, and short-term usage history.
- Unload all active models through llama-swap's native control API.
- Scan recent runs under the current output root and open aggregate results, summaries, or run folders directly.
- Drive modes, system prompts, request parameters, validation, and observations through profiles.
- Write atomic per-request records with resume and failed-only retry support.
- Keep raw responses, deliverable results, aggregate Markdown, CSV, and manifests separate.
- Validate the core, GUI imports, CLI, package, and compatibility wrappers on Windows CI.

## Repository layout

```text
app.py / batch_cli.py       Stable compatibility launchers
prompt_batch/               Python package and implementation
  backends/                 Backend adapters
  gui.py                    Main window and event coordination
  gui_models.py / gui_gpu.py Model selection and GPU monitoring
  gui_results.py             Recent-result browser
  cli.py                    CLI entry point
  runner.py                 Batch orchestration
  preparation.py            Configuration and input preparation
  reporting.py              Aggregate output generation
  runtime.py / storage.py   Process and persistence infrastructure
config/                     Application configuration
profiles/                   Task profiles
schemas/                    JSON Schema documents
docs/                       Maintenance documentation (Chinese)
tests/                      Standard-library test suite
packaging/windows/          Windows portable-package builder
.github/workflows/          CI, continuous, and versioned releases
```

## Configuration

Paths are resolved relative to their configuration file and support `~`, `%ENV_VAR%`, and `${ENV_VAR}`. The example H3 profile refers to MiniMax H3 system prompts outside this repository; that path is deployment configuration, not a hard-coded Python dependency.

Application configuration and profiles are versioned and validated at runtime. The `schemas/` directory also provides JSON Schema files for editors.

Fresh installations write to `output/` under the application directory. A path already saved in GUI state continues to override this default so upgrades do not silently redirect existing work.

## Compatibility

The legacy imports `prompt_batch.engine` and `prompt_batch.model_source`, root launchers, and PowerShell wrapper remain available as thin forwarding layers.

Detailed maintenance documentation starts at [docs/README.md](docs/README.md). Changes are recorded in [CHANGELOG.md](CHANGELOG.md).
