# Prompt Batch Generator

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md)

一个面向 OpenAI-compatible Chat Completions 接口的本地 prompt 批量生成工具。它按“模型 × 输入 × 重复次数”执行任务，并通过 profile 描述 system prompt、模式、校验、观察项和输出命名。

项目只依赖 Python 标准库；GUI 使用 Tkinter，PowerShell 仅作为旧入口兼容层。

## 便携版

CI 会为每次提交构建 Windows x64 便携 ZIP，其中包含 GUI、CLI、默认配置、profile、schema 和文档，无需预装 Python。`main` 构建成功后会自动更新 [Continuous prerelease](https://github.com/Saenai/prompt-batch-tool/releases/tag/continuous)；推送 `v*` tag 时则发布不可变的正式版本。两者均附带 ZIP 和 SHA-256 校验文件。

解压后可直接运行 `PromptBatchGenerator.exe`，`launch-gui.cmd` 作为兼容启动入口继续保留。默认目录关系按 `.llama.cpp/prompt-batch-tool`、相邻 `llama-swap` 和 `llama-current` 设计；放到其他位置时应修改 `config/app.json`。

## 快速开始

双击 `launch-gui.cmd`，或在仓库根目录运行：

```powershell
python .\app.py
```

运行自检：

```powershell
python .\app.py --config .\config\app.json --self-test
python -B -m unittest discover -s tests -v
```

命令行用法：

```powershell
python .\batch_cli.py `
  --app-config .\config\app.json `
  --profile .\profiles\plain.json `
  --input-manifest .\inputs.json `
  --mode default `
  --repeats 2 `
  --max-tokens 2048 `
  --seed-base 100 `
  --model model-a
```

加入 `--validate-only` 可只校验任务，不启动 router 或发送请求。

## 主要能力

- 文件输入、批量多输入和 GUI 直接输入可组合使用；
- 同一模型连续处理全部输入，减少 llama-swap 反复换模；
- 模型列表由 API 或外部 llama-swap 配置动态发现，不写死在 GUI；
- 模型按系列和参数量层级分组、筛选、折叠与批量选择；
- 动态显示本机 NVIDIA GPU 的 VRAM、利用率、温度和短时占用曲线；
- profile 驱动模式、system prompt、请求参数、输出校验及观察项；
- 逐项原子记录，支持断点续跑和仅重试失败项；
- 原始响应、交付结果、汇总 Markdown、CSV 和 manifest 分离保存。
- Windows CI 在 Python 3.11 与 3.14 上验证核心、GUI 导入、CLI 和兼容入口。

## 仓库结构

```text
app.py / batch_cli.py       兼容启动入口
prompt_batch/               Python 包与业务实现
  backends/                 后端适配器
  gui.py                    主窗口与事件协调
  gui_models.py / gui_gpu.py 模型选择与 GPU 监视组件
  cli.py                    命令行入口
  runner.py                 批次流程协调
  preparation.py            配置、输入与任务准备
  reporting.py              汇总输出
  runtime.py / storage.py   进程和持久化基础设施
config/                     应用配置
profiles/                   任务 profile
schemas/                    JSON Schema
docs/                       维护文档
tests/                      标准库单元测试
packaging/windows/          Windows 便携包构建脚本
.github/workflows/          CI、continuous 与版本 Release
```

根目录的 `app.py`、`batch_cli.py`、`run-batch.ps1` 是稳定兼容入口；新代码应放在 `prompt_batch/` 内。

## 文档

- [文档索引](docs/README.md)
- [运行、输入与输出](docs/running.md)
- [配置与 profile](docs/configuration.md)
- [架构与依赖边界](docs/architecture.md)
- [命名约定](docs/naming.md)
- [开发与维护](docs/development.md)
- [变更记录](CHANGELOG.md)

## 配置说明

所有配置路径相对于其配置文件解析，并支持 `~`、`%ENV_VAR%` 和 `${ENV_VAR}`。示例 `profiles/h3.json` 会引用仓库外的 MiniMax H3 system prompt；这是部署配置，不是 Python 源码中的本机路径。

应用配置和 profile 均带版本号，并由程序执行运行时校验；`schemas/` 同时为编辑器提供 JSON Schema。

## 兼容性

旧的 Python 导入路径 `prompt_batch.engine`、`prompt_batch.model_source` 以及根目录启动脚本继续可用。它们是薄转发层，不再承载业务实现。
