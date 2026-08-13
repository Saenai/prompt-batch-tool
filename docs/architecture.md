# 架构与依赖边界

## 设计目标

工具采用 profile 驱动的批处理核心。GUI 和 CLI 负责收集参数，批处理包负责验证、执行和落盘，外部任务规则由 JSON profile 表达。这样新增任务类型通常不需要复制界面或执行循环。

## 模块结构

```text
兼容入口 app.py / batch_cli.py
           │
           ├── prompt_batch.gui
           └── prompt_batch.cli
                         │
                 prompt_batch.engine  公开兼容 API
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
  preparation          runner          domain
        │                │
      config     ┌───────┼────────┬────────────┐
                 │       │        │            │
              backends runtime reporting    storage
```

| 模块 | 单一职责 |
|---|---|
| `domain.py` | 共享数据类型，不执行 I/O |
| `config.py` | 配置加载、迁移、路径解析和契约校验 |
| `model_catalog.py` | 模型发现、显示名称、系列和参数量分组 |
| `preparation.py` | 将用户参数、配置和输入转换成可执行批次 |
| `runner.py` | 协调任务次序、请求和批次状态 |
| `backends/` | 后端协议与具体 API 适配器 |
| `runtime.py` | 本地 router 生命周期及运行时版本 |
| `reporting.py` | 输出有效性判断和批次汇总 |
| `storage.py` | 原子 JSON、可选记录读取和 CSV 写入 |
| `gui.py` | 主窗口、任务表单和子进程事件协调 |
| `gui_models.py` | 模型筛选、系列/参数量层级和选择状态 |
| `gpu_monitor.py` | 无 GUI 依赖的 NVIDIA GPU 遥测采集与解析 |
| `gui_gpu.py` | VRAM 当前值、设备选择和短时历史曲线 |
| `cli.py` | 命令行参数和文本/JSONL 事件呈现 |
| `engine.py` | 稳定公开 API 的兼容门面 |

## 依赖规则

- `domain` 不导入任何项目内高层模块；
- `storage`、`runtime`、`reporting` 和 `backends` 不依赖 GUI 或 CLI；
- `runner` 只负责协调，不复制配置准备、报表或后端协议实现；
- GUI 不直接构造 HTTP 请求，也不解析 llama-swap 业务配置；
- 主窗口通过 `ModelSelector` 的公开方法读取模型选择状态，不操作其内部控件；
- profile 不包含本机密钥，源码不包含模型清单或任务专用绝对路径；
- 兼容模块只能转发公开名称，不承载新逻辑。

这些约束的目的不是追求目录数量，而是使变化有明确落点。例如新增后端只改 `backends/` 和配置验证；新增报表只改 `reporting.py`；新增任务模式优先改 profile。

## 执行流程

1. `preparation.prepare_batch` 加载并验证应用配置、profile 和 input manifest；
2. `runner.run_batch` 创建或校验运行目录及 manifest；
3. 后端不可用且 URL 对应受管本地 router 时，由 `runtime` 启动 router；
4. 按模型、重复序号、输入的顺序发送请求；
5. 每个请求先写独立结果和原子 record；
6. `reporting.write_batch_reports` 生成集中输出、CSV 和摘要；
7. runner 更新最终 manifest，并只终止由本次运行启动的 router。

## 扩展点

后端通过 `ChatBackend` 协议接入。目前实现 `openai-chat-completions`。添加 adapter 时应在 `backends/` 中实现协议，并由 `create_backend` 按配置选择。

任务类型通过 profile 扩展。只有 profile 无法表达的通用能力，才应进入 Python 核心。

## 兼容层

以下名称暂时保留：

- 根目录 `app.py` 与 `batch_cli.py`；
- `prompt_batch.engine`；
- `prompt_batch.model_source`；
- `ModelGroup`、`ModelTier`、`group_models` 和 `group_model_tiers`。

新代码应分别使用 `gui`、`cli`、包根公开 API、`model_catalog`、`ModelFamily`、`ParameterTier`、`group_model_families` 和 `group_parameter_tiers`。
