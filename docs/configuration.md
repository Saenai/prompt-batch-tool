# 配置与 profile

## 应用配置

`config/app.json` 描述部署环境，而不是单次任务：

- `paths`：CLI、profile、状态、输出、模型配置、router 和 runtime 的位置；
- `backend`：adapter、Base URL、endpoint、超时、认证和公共请求字段；
- `router` / `runtime`：本地进程参数与版本查询方式；
- `model_source`：模型发现回退和 GUI 分组；
- `defaults`：GUI 的默认 profile、mode、重复次数、token 上限、seed base 和随机 seed 开关。`random_seed` 默认应为 `true`；`seed_base` 仅在关闭随机 seed 时作为固定基准。

路径相对于 `app.json` 解析，也支持 `~`、`%ENV_VAR%` 与 `${ENV_VAR}`。部署相关路径应留在配置中，不能写入 Python 模块。

应用配置当前为 `schema_version: 4`。程序可在内存中迁移 v1–v3 配置，但不会偷偷改写原文件；高于当前支持版本的配置会被拒绝。

默认输出根目录为相对于应用配置的 `../output`，即源码版或便携版程序根目录下的 `output/`。GUI 状态中已经保存的路径仍会覆盖该默认值。

`router.control_base_url`、`router.unload_all_endpoint` 与 `router.control_timeout_seconds` 定义 llama-swap 控制 API。默认按钮调用 `POST /api/models/unload`；地址与超时不写死在 Python 中。若后端认证引用环境变量，控制请求复用相同认证头，但不会把密钥写入状态或日志。

`result_browser.max_entries` 限制 GUI 展示的近期任务数。扫描只检查输出根目录的一级子目录，并优先读取 manifest 记录的聚合文件名，因此不会随逐项结果数量线性膨胀。

## GPU 监视

`gpu_monitor` 控制 GUI 中的本机 NVIDIA GPU 遥测：

```json
"gpu_monitor": {
  "enabled": true,
  "command": "nvidia-smi",
  "poll_interval_ms": 1000,
  "history_samples": 60,
  "query_timeout_seconds": 5
}
```

程序按配置周期调用 NVIDIA 驱动附带的 `nvidia-smi`，不会安装或要求 Python GPU 库。多张 NVIDIA GPU 会动态进入下拉框；命令不存在、驱动不可用或查询超时时，只停用监视显示，不影响批处理。将 `enabled` 改为 `false` 可完全关闭采样。

## 后端认证

本地无认证接口：

```json
"auth": {"type": "none"}
```

需要 API key 时只引用环境变量：

```json
"auth": {
  "type": "environment",
  "environment_variable": "OPENAI_API_KEY",
  "header": "Authorization",
  "prefix": "Bearer "
}
```

实际密钥在请求时读取，不进入 GUI 状态、运行 manifest 或冻结配置。

## Profile

`profiles/*.json` 描述任务语义。当前内置：

- `plain.json`：无结构约束的普通生成；
- `h3.json`：MiniMax H3 的 T2VA、I2VA、FL2VA、L2VA 和 Ref2VA。

最小结构示例：

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
      "validation": {"required_patterns": ["(?m)^result:"]}
    }
  },
  "observations": [],
  "output": {"all_outputs_file": "ALL-OUTPUTS.html"}
}
```

system prompt 路径相对于 `system_prompt_root`；未声明 root 时相对于 profile 文件。短文本可使用 `system_prompt_text`。GUI 中临时指定的 system prompt 会覆盖 profile 对应 mode 的值。

`output` 中只会生成显式声明的集中报告文件；文件名以 `.html` 结尾时，聚合结果会以保留多行文本的 HTML 表格写出。`structured_outputs_file` 会将交付用最终 prompt 写成 JSONL，每行一个对象，适合下游脚本直接读取。未声明的 records、raw、observations、structured 和 summary 文件不会额外生成。

应用配置、profile 和 mode 均可声明 `request_body`，按“应用 → profile → mode”合并。当前模型、messages、max tokens、seed 和 `stream: false` 最后由执行器写入。

`required_patterns` 和 `forbidden_patterns` 使用 Python 正则表达式。`observations` 用于观察指定文本是否被保留，并可为交付版移除只用于测试的 marker；它不替代模型质量评价。

## 输入 manifest

GUI 会为文件输入和直接输入生成临时 manifest。CLI 也可直接接收相同格式：

```json
{
  "inputs": [
    {"id": "scene-a", "path": "input-a.txt", "mode": "t2va"},
    {"id": "scene-b", "text": "直接输入内容", "mode": "t2va"}
  ]
}
```

路径相对于 manifest 文件解析。一个批次可同时包含多个文件和内联输入。

## 模型发现与分组

GUI 优先调用 models endpoint；不可用时根据 `model_source.fallback_format` 读取外部模型配置。模型 ID 不保存在 Python 或 profile 中。

`model_source.grouping` 依次建立两个显示层级：

1. `ModelFamily`：模型系列，例如 Qwen 3.6；
2. `ParameterTier`：参数量，例如 `27B` 或 `26B / A4B`。

正则、捕获组、别名、顺序和无法识别时的显示名均由配置决定。新增模型系列通常不需要改 GUI。

## Schema

`schemas/app-config.schema.json` 和 `schemas/profile.schema.json` 使用 JSON Schema Draft 2020-12，服务于编辑器提示和静态检查。程序仍会使用标准库执行核心运行时校验，不能假设每位使用者的编辑器都加载了 schema。
