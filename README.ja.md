# Prompt Batch Generator

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md)

OpenAI 互換 Chat Completions API 向けのローカル一括生成ツールです。「モデル × 入力 × 反復回数」を順に実行し、profile で system prompt、mode、検証規則、観測項目、リクエストパラメータ、出力名を定義します。

ソース版の実行依存は Python 標準ライブラリのみです。GUI は Tkinter を使用し、PowerShell は旧インターフェースとの互換層としてのみ残しています。

## Windows ポータブル版

CI は各 commit に対して Windows x64 用ポータブル ZIP を生成します。GUI、CLI、既定設定、profile、schema、文書を同梱しているため、Python を別途インストールする必要はありません。

`main` の build が成功すると、rolling [Continuous prerelease](https://github.com/Saenai/prompt-batch-tool/releases/tag/continuous) が自動更新されます。`v*` tag を push した場合は変更されない versioned release を公開します。どちらにも ZIP と SHA-256 checksum が含まれます。

展開後は `PromptBatchGenerator.exe` を直接実行できます。`launch-gui.cmd` は互換 launcher として残しています。既定パスは `.llama.cpp/prompt-batch-tool` に配置し、隣接する `llama-swap` と `llama-current` を利用する構成です。別の配置では `config/app.json` を編集します。

## ソース版のクイックスタート

`launch-gui.cmd` をダブルクリックするか、repository root で次を実行します。

```powershell
python .\app.py
```

自己診断とテスト：

```powershell
python .\app.py --config .\config\app.json --self-test
python -B -m unittest discover -s tests -v
```

CLI の例：

```powershell
python .\batch_cli.py `
  --app-config .\config\app.json `
  --profile .\profiles\plain.json `
  --input-manifest .\inputs.json `
  --mode default `
  --repeats 2 `
  --max-tokens 2048 `
  --random-seed `
  --model model-a
```

新しい実行では既定でランダム seed を使用します。同じ batch 内では一つのランダムな seed base を使い、repeat ごとに加算するため、同一実行内の比較条件は維持されます。再現可能な固定 seed が必要な場合は `--no-random-seed --seed-base 100` を指定してください。両方を省略した場合は `config/app.json` の `defaults.random_seed` に従います。

`--validate-only` を追加すると、router の起動や API リクエストを行わず、設定と入力だけを検証できます。

## 主な機能

- ファイル入力、複数 prompt、GUI の直接入力を同一 batch で併用。
- 一つのモデルで全入力を処理してから切り替え、llama-swap の再ロードを削減。
- API または外部 llama-swap 設定からモデルを動的に取得。
- model family と parameter tier によるグループ化、絞り込み、折り畳み、一括選択。
- ローカル NVIDIA GPU の VRAM、使用率、温度、短時間の履歴グラフを表示。
- llama-swap の native control API で、読み込み済み model を一括 unload。
- 現在の output root にある最近の task を走査し、aggregate result、summary、task directory を直接開く。
- profile による mode、system prompt、リクエストパラメータ、検証、観測項目の定義。
- リクエスト単位の原子的 record、resume、失敗項目のみの再試行。
- raw response、納品用結果、集約 Markdown、CSV、manifest を分離保存。
- Windows CI で core、GUI import、CLI、配布 package、互換 wrapper を検証。

## Repository 構成

```text
app.py / batch_cli.py       安定した互換 launcher
prompt_batch/               Python package と実装
  backends/                 backend adapter
  gui.py                    メインウィンドウと event coordination
  gui_models.py / gui_gpu.py モデル選択と GPU monitor UI
  gui_results.py             Recent result browser
  cli.py                    CLI entry point
  runner.py                 batch の進行管理
  preparation.py            設定と入力の準備
  reporting.py              集約出力
  runtime.py / storage.py   process と永続化基盤
config/                     アプリケーション設定
profiles/                   タスク profile
schemas/                    JSON Schema
docs/                       保守文書（中国語）
tests/                      標準ライブラリによる test suite
packaging/windows/          Windows ポータブル版 build script
.github/workflows/          CI、continuous release、versioned release
```

## 設定

各 path は設定ファイルを基準に解決され、`~`、`%ENV_VAR%`、`${ENV_VAR}` を利用できます。H3 profile の例は repository 外部の MiniMax H3 system prompt を参照しますが、これは deployment 設定であり Python source の固定依存ではありません。

アプリケーション設定と profile は version 管理され、実行時に検証されます。`schemas/` は editor 向け JSON Schema も提供します。

新規環境の既定出力先は application directory 配下の `output/` です。GUI state に既存の出力 path が保存されている場合は、その値を優先し、upgrade 時に作業先を勝手に変更しません。

## 互換性

旧 import path の `prompt_batch.engine` と `prompt_batch.model_source`、root launcher、PowerShell wrapper は、薄い転送層として引き続き利用できます。

詳細な保守文書は [docs/README.md](docs/README.md)、変更履歴は [CHANGELOG.md](CHANGELOG.md) を参照してください。
