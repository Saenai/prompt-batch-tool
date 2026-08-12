# 命名约定

命名应表达领域含义和职责，避免由历史实现方式决定名称。

## 领域术语

| 名称 | 含义 |
|---|---|
| model | 后端公开的可请求模型 ID |
| model catalog | 可用模型集合及其显示元数据 |
| model family | 模型系列分组，例如 Qwen 3.6 |
| parameter tier | 参数量层级，例如 27B 或 26B / A4B |
| profile | 一类任务的模式、system prompt、校验和输出规则 |
| mode | profile 内的一种生成模式 |
| input case | 一条已解析、具有稳定 ID 的输入 |
| observation | 对输出中特定文本保留情况的机械观察 |
| batch | 一次待执行任务定义 |
| run | batch 在某个目录中的一次实际执行或续跑 |
| job record | 单个 model/input/repeat 请求的原子记录 |

“group”只作为一般 UI 操作动词使用；公开数据类型应使用更明确的 `ModelFamily` 和 `ParameterTier`。

## Python 文件

- 模块名使用小写名词或职责名：`reporting.py`、`storage.py`；
- 协调多个组件的流程使用 `runner.py`，不要再使用含义过宽的 `engine.py` 承载实现；
- 第三方协议实现放入复数目录 `backends/`；
- GUI 类使用产品职责名 `PromptBatchApp`，避免模糊的 `App` 或 `BatchApp`；
- 私有帮助函数以 `_` 开头；跨模块使用的能力应有明确公开名并由所属模块导出。

## 配置和输出

- JSON 字段使用 `snake_case`；
- profile ID、mode ID、input case ID 使用稳定的小写短标识；
- 用户可见名称使用 `display_name`，不要把显示文案当作稳定 ID；
- 时间点字段以 `_at` 结尾，时长字段带 `_seconds`，摘要速度带 `_per_second`；
- 哈希字段写明对象和算法，例如 `system_prompt_sha256`；
- 输出文件名由 profile 决定，核心代码不应写入任务专用名称。

## 兼容命名

旧的 `model_source`、`ModelGroup`、`ModelTier` 等名称由薄兼容层保留。新代码不得继续引入这些旧名；待确认外部调用方已迁移后，可在一次明确的破坏性版本中移除。
