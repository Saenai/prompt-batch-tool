# 运行、输入与输出

## GUI

```powershell
python .\app.py --config .\config\app.json
```

界面固定为等宽两列。左侧包含任务设置和输入，右侧包含后端、模型选择和运行状态。具体区域使用带标题边框分隔，没有可拖动的中央分隔条。

GUI 会记住 profile、mode、路径、执行参数、模型选择、筛选、折叠状态和窗口大小。“直接输入”默认不持久化；只有勾选“记住正文”后才写入状态文件。

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

`--validate-only` 只做配置和输入准备。`--event-format jsonl` 输出 GUI 可消费的结构化事件；普通命令行默认输出可读文本。

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
  *.md / *.csv                   集中输出和摘要
```

集中输出文件名由 profile 决定。逐项 `run-*.record.json` 使用原子替换写入，是续跑判断的事实来源。失败重试前会删除该项的旧结果，防止聚合阶段误收陈旧内容。

## 本地 router

只有当前 Base URL 与应用配置中的本地 URL 一致且 endpoint 不可用时，工具才会按配置启动 router。用户在 GUI 临时填写其他 URL 时，工具不会擅自启动本地进程。

工具只终止由本次运行自行启动的 router；已经存在的服务不归本次运行所有。

## 兼容入口

`run-batch.ps1` 只把旧 PowerShell 参数翻译为 Python CLI 参数，不含业务逻辑。根目录的 Python 文件同样只转发到包内入口。
