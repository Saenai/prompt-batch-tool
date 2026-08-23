# 运行、输入与输出

## Windows 便携版

CI artifact 和版本 Release 提供 Windows x64 便携 ZIP。解压后可直接运行 `PromptBatchGenerator.exe`；`launch-gui.cmd` 继续作为兼容入口。包内另含供 GUI 调用的 `PromptBatchCLI.exe`，无需安装 Python。

默认 `config/app.json` 假定该目录与 `llama-swap`、`llama-current` 处于既定的 `.llama.cpp` 结构。若移动到其他目录，应调整相对路径。每个发布 ZIP 都附带 `.sha256` 文件用于完整性核对。

## GUI

```powershell
python .\app.py
```

界面固定为等宽两列。左侧包含任务设置、输入和近期结果，右侧包含后端、模型选择、GPU 监视和运行状态。具体区域使用带标题边框分隔，没有可拖动的中央分隔条。

GUI 会记住 profile、mode、路径、执行参数、模型选择、筛选、折叠状态和窗口大小。“直接输入”默认不持久化；只有勾选“记住正文”后才写入状态文件。

“卸载全部模型”在批处理空闲时调用配置中的 llama-swap `POST /api/models/unload`。操作前会确认，批处理运行期间按钮禁用，避免终止正在生成的模型。

“近期结果”只扫描当前输出根目录下的一级任务目录，读取 `manifest.json` 中的 `output_files`，并按最近更新时间排序。双击任务可打开聚合结果，也可分别打开摘要或任务目录；批次完成后列表自动刷新。较旧任务若 manifest 没有 `output_files`，会读取运行时冻结的 `input/profile.json`，不依赖固定的 `ALL-PROMPTS.md` 名称。

## 多输入

文件输入和直接输入可同时使用，一个批次可包含多条 prompt。请求顺序为：

```text
model 1 → repeat 1 → input 1, input 2, ...
        → repeat 2 → input 1, input 2, ...
model 2 → repeat 1 → input 1, input 2, ...
```

因此总请求数是“模型数 × 输入数 × repeats”。同一模型先处理完整批次，以减少 llama-swap 的模型切换成本。

## CLI

查看全部参数：

```powershell
python .\batch_cli.py --help
```

便携版对应命令为：

```powershell
.\PromptBatchCLI.exe --help
```

`--validate-only` 只做配置和输入准备。`--event-format jsonl` 输出 GUI 可消费的结构化事件；普通命令行默认输出可读文本。

### Seed

新运行默认启用随机 seed。工具先生成一个随机 `seed_base`，然后使用 `seed_base + repeat` 作为请求 seed；同一批次中不同模型和相同 repeat 仍使用相同 seed，便于横向比较。实际使用的 seed base 会写入 `manifest.json`。

- `--random-seed`：强制本次新运行随机化；
- `--no-random-seed --seed-base N`：使用固定 seed base；
- 两个选项都省略：遵循 `config/app.json` 的 `defaults.random_seed`；若显式给出 `--seed-base N`，则视为固定 seed。

续跑会读取原 manifest 中的 seed base，不会因为随机 seed 默认开启而改变已完成任务的请求身份。

## 运行策略

- `新运行`：创建新目录；指定固定目录时要求它为空；
- `续跑未完成`：跳过成功记录，执行失败或缺失项；
- `仅重试失败`：只执行已有 record 明确标记为失败的项。

后两种策略必须指定已有运行目录。续跑会核对 profile 指纹、后端身份、输入和 system prompt 哈希、模型列表、repeats、max tokens 与 seed，避免不同任务混写。

仅重试失败要求所有请求都有逐项 record；过早版本创建的目录可能只能使用普通续跑。

## 输出

```text
<run>/
  input/                         冻结后的配置、manifest、输入和 system prompt
  results/<model>/<input>/       模型原始文本输出
  final-results/<model>/<input>/ 后处理交付输出
  raw/<model>/<input>/           API 响应、错误和逐项 record
  router-logs/                   本次启动的本地 router 日志
  manifest.json                  批次身份、状态和统计
  profile 声明的集中输出文件       例如 ALL-PROMPTS.html
```

集中输出文件名和格式由 profile 决定；未声明的集中报告不会生成。H3 profile 默认只生成 `ALL-PROMPTS.html`，以序号、Model、Repeat、Prompt 四列展示最终 prompt。新安装的默认输出根目录是程序所在目录的 `output/`；GUI 已保存的路径仍优先。逐项 `run-*.record.json` 使用原子替换写入，是续跑判断的事实来源。失败重试前会删除该项的旧结果，防止聚合阶段误收陈旧内容。

## 本地 router

只有当前 Base URL 与应用配置中的本地 URL 一致且 endpoint 不可用时，工具才会按配置启动 router。用户在 GUI 临时填写其他 URL 时，工具不会擅自启动本地进程。

工具只终止由本次运行自行启动的 router；已经存在的服务不归本次运行所有。

## 兼容入口

`run-batch.ps1` 只把旧 PowerShell 参数翻译为 Python CLI 参数，不含业务逻辑。根目录的 Python 文件同样只转发到包内入口。
