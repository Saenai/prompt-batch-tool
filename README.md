# Prompt Batch Generator

这是一个面向 OpenAI-compatible Chat Completions 接口的本地 prompt 批量生成工具。GUI、Python 批处理引擎和任务规则彼此分离：程序负责组合“模型 × 重复次数 × 输入”，profile 负责定义 system prompt、mode、输出校验和后处理。

## 启动

双击 `launch-gui.cmd`，或运行：

```powershell
python .\app.py --config .\config\app.json
```

无需安装第三方 Python 包；GUI、HTTP client、批次引擎和测试均使用 Python 标准库。GUI 不依赖 PowerShell。

## 架构

```text
app.py (Tkinter GUI)
        ↓
batch_cli.py (CLI)
        ↓
prompt_batch/engine.py
        ├─ backend.py
        ├─ config.py
        ├─ model_source.py
        ├─ profile JSON
        └─ schemas/*.schema.json
```

- `app.py` 只处理 GUI、状态与子进程日志。
- `batch_cli.py` 是权威命令行入口。
- `prompt_batch/engine.py` 处理批次、router 生命周期、校验、后处理与输出。
- `prompt_batch/backend.py` 封装 OpenAI-compatible HTTP、模型发现和环境变量认证。
- `prompt_batch/config.py` 负责配置迁移及运行时校验；`schemas/` 提供编辑器可读取的 JSON Schema。
- `run-batch.ps1` 仅将旧 PowerShell 参数翻译为 Python CLI 参数，不含业务逻辑。

## 执行顺序

```text
model 1 → repeat 1 → input 1, input 2, ...
        → repeat 2 → input 1, input 2, ...
model 2 → repeat 1 → input 1, input 2, ...
```

同一模型会处理完整批次后再切换模型，以减少 llama-swap 反复卸载和加载模型。总请求数为“模型数 × input 数 × repeats”。

输入文件和“直接输入”可以同时使用。GUI 会生成临时 input manifest；引擎把实际内容冻结到最终运行目录，GUI 随后清理临时文件。

## GUI 布局

GUI 仅使用 Python 自带的 Tkinter/ttk。主窗口固定为等宽两列，没有外层区域标题或可拖动分隔条；具体功能仍使用带标题框线区分：

- 左栏：任务设置、输入内容；
- 右栏：后端、模型选择、运行状态；
- 窗口大小会随状态保存。

运行状态区显示结构化进度，包括当前模型、输入、重复序号、完成数以及本轮执行/跳过/失败数量。

## 配置层次

### 应用配置

`config/app.json` 保存环境与后端信息：

- 引擎、profile、状态、输出和模型配置的位置；
- router、运行时及工作目录；
- API endpoint 与超时；
- GUI 默认参数。

所有文件路径都相对于 `app.json` 解析，也支持 `~`、`%ENV_VAR%` 与 `${ENV_VAR}`。代码中不保存本机工作区或用户名的绝对路径。

应用配置当前为 `schema_version: 2`。程序仍接受 v1，并在内存中迁移 `backend.type` 为 `backend.adapter`、补上无认证配置；不会改写原文件。高于当前版本的配置会被拒绝。`schemas/app-config.schema.json` 和 `schemas/profile.schema.json` 使用 JSON Schema Draft 2020-12；即使编辑器不执行 Schema，程序也会使用标准库完成核心字段、类型、版本和 mode 引用校验。

### 后端认证

本地 llama-swap 默认使用：

```json
"auth": {"type": "none"}
```

需要 API key 时，只在配置中引用环境变量：

```json
"auth": {
  "type": "environment",
  "environment_variable": "OPENAI_API_KEY",
  "header": "Authorization",
  "prefix": "Bearer "
}
```

`header` 和 `prefix` 可调整，因此也能表达 `x-api-key` 一类认证。实际密钥只在发送请求时从环境读取，不会进入 GUI 状态、冻结配置或运行 manifest；manifest 只记录环境变量名和认证形式，以便续跑一致性检查。

### Profile

`profiles/*.json` 保存任务特性。当前提供：

- `plain.json`：无结构约束的普通文本生成；
- `h3.json`：MiniMax H3 五种 mode、原生 system prompt、字段校验及 trigger 观察。

GUI 自动发现 profile，并据此刷新 mode 下拉框。新增任务类型通常只需增加 profile，不必复制 GUI 或批处理引擎。

Profile 的主要结构：

```json
{
  "$schema": "../schemas/profile.schema.json",
  "schema_version": 1,
  "id": "example",
  "display_name": "Example",
  "default_mode": "default",
  "allow_auto_mode": false,
  "modes": {
    "default": {
      "system_prompt": "prompts/system.md",
      "validation": {
        "required_patterns": ["(?m)^result:"]
      }
    }
  },
  "observations": [],
  "output": {
    "all_outputs_file": "ALL-OUTPUTS.md"
  }
}
```

应用配置、profile 和单个 mode 都可声明 `request_body`。引擎按“应用 → profile → mode”依次合并，随后用当前模型、messages、max tokens、seed 和 stream 覆盖核心字段。由此可以为新任务声明 temperature、top_p 或后端扩展参数，而不修改引擎。

system prompt 路径相对于 profile 的 `system_prompt_root`；未设置 root 时，相对于 profile 文件。也可使用 `system_prompt_text` 保存短小的内联 system prompt。

`required_patterns` 和 `forbidden_patterns` 使用 Python `re` 正则表达式。`observations` 可从输入捕获需要观察的文本，并声明是否只在模型原样返回 marker 时生成去 marker 的交付副本。

## 状态记忆

状态文件位置由 `app.json` 的 `paths.state` 决定。GUI 关闭或开始运行时会记住：

- profile 与 mode；
- 输出路径、API、repeats、max tokens、seed；
- input 文件列表；
- 模型勾选和筛选词；
- 窗口大小。

“直接输入”正文默认不会持久化。只有显式勾选“记住正文”后才会写入状态文件。状态使用同目录临时文件加原子替换，避免异常退出留下半截 JSON。

若要恢复初始状态，关闭 GUI 后删除 `state/gui-state.json` 即可。

## 模型发现

GUI 优先请求应用配置中的 models endpoint。接口不可用时，按 `model_source.fallback_format` 从模型配置中读取；当前配置使用 `llama-swap-yaml`。模型 ID 不写在 Python 或 profile 中。

模型列表按 `model_source.grouping` 动态分组。默认从模型 ID 的第一个 `-` 之前提取系列键，再由配置中的 `aliases` 设置易读名称、由 `order` 控制组顺序；Python GUI 中没有写死 Qwen、Gemma 等系列。新系列即使没有 alias 也会自动出现为独立分组。

系列下面再按 `parameter_tiers` 划分参数量层级，并按总参数量降序显示。例如 `26b-a4b` 显示为 `26B / A4B`，分别表达总参数量和激活参数量；无法从 ID 可靠识别时归入“参数量未标注”。

系列和参数层均可折叠，也可分别全选或清空。折叠状态随 GUI 状态保存；输入筛选词时，包含匹配结果的层级会临时展开。筛选状态下的全局、系列或参数层操作只影响当前可见模型。

分组配置示例：

```json
"grouping": {
  "enabled": true,
  "pattern": "^([^-]+)",
  "match_group": 1,
  "aliases": {"qwen3.6": "Qwen 3.6"},
  "order": ["qwen3.6"],
  "parameter_tiers": {
    "enabled": true,
    "pattern": "(?:^|-)(\\d+(?:\\.\\d+)?[bB])(?:-a(\\d+(?:\\.\\d+)?[bB]))?(?:-|$)",
    "size_group": 1,
    "active_group": 2,
    "sort": "size-desc"
  }
}
```

当前实现的后端 adapter 是 `openai-chat-completions`。如果 GUI 中填写的 Base URL 与应用配置不同，接口不可用时程序不会擅自启动本地 router；只有配置中的本地 URL 才对应配置中的 router 启动命令。

## 输出

通用目录结构为：

```text
results/<model>/<input>/run-*.md
final-results/<model>/<input>/run-*.md
raw/<model>/<input>/run-*.json
input/
manifest.json
```

集中输出、CSV 和摘要的文件名由 profile 决定。原始输出与后处理交付版始终分开保存。

每个请求还会在对应的 `raw/<model>/<input>/` 下写入 `run-*.record.json`。该逐项记录使用原子替换写入，是断点续跑和失败重试的判断依据。

## 断点续跑与失败重试

GUI 的“运行策略”提供三种互斥模式：

- `新运行`：创建新目录，或要求指定的固定运行目录为空；
- `续跑未完成`：跳过已有成功记录，继续执行失败和缺失项；
- `仅重试失败`：只执行记录中明确失败的项，要求全部请求都有逐项记录。

后两种模式必须指定已有的“固定运行目录”。续跑前会核对 profile 内容、endpoint、后端请求参数、模型清单、输入与 system prompt 哈希、repeats、max tokens 和 seed；不一致时拒绝混写。重试前会删除该请求的旧结果文件，防止失败后聚合输出误用陈旧内容。

逐项记录由本版本开始生成，因此更早的运行目录不能使用“仅重试失败”；若其中已有部分新格式记录，可以使用“续跑未完成”。GUI 强制取消后，已经原子写完的结果和记录仍可用于续跑。

## 命令行与验证

Python CLI 直接调用示例：

```powershell
python .\batch_cli.py `
  --app-config .\config\app.json `
  --profile .\profiles\plain.json `
  --input-manifest .\inputs.json `
  --mode default `
  --repeats 2 `
  --max-tokens 2048 `
  --seed-base 100 `
  --model model-a `
  --model model-b
```

加入 `--validate-only` 只检查配置、输入和 system prompt，不启动 router 或模型。

对已有运行目录续跑：

```powershell
python .\batch_cli.py <其余参数> --run-directory .\existing-run --resume
```

仅重试已有失败项时改用 `--retry-failed`。加入 `--event-format jsonl` 后，CLI 会逐行输出结构化事件；GUI 使用此模式驱动进度条，默认 CLI 输出仍为普通文本。

GUI 自检：

```powershell
python .\app.py --config .\config\app.json --self-test
```

运行内置 mock API 测试：

```powershell
python -B -m unittest discover -s tests -v
```

## 兼容入口

`run-batch.ps1`、原来的 `..\h3-prompt-gui` 与 `..\scripts\generate-h3-prompts.ps1` 保留为薄兼容层。它们最终都调用 `batch_cli.py`，默认 H3 入口使用 `profiles/h3.json`。新功能与配置只在 Python 引擎和本目录维护。
