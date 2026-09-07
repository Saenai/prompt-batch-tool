# 变更记录

本项目采用面向行为的变更记录；尚未发布的改动维护在 `Unreleased`。

## Unreleased

- 可选本机版本采集增加 10 秒超时及失败容错；外部接口覆盖或关闭本机自动启动时不执行采集。

- 公共配置默认禁用 llama-swap 卸载控制；控制认证独立配置，不再复用推理 API 凭据。CLI 重定向输出使用 UTF-8。

- 修复 API-only 部署的 GUI 自检因缺少可选本地模型注册表而误报失败；Windows 构建支持显式选择 PythonExecutable。

### Added

- 模型系列与参数量双层动态分组；
- 配置版本迁移、JSON Schema 和后端 adapter；
- 断点续跑、仅重试失败项和结构化 GUI 进度；
- 分层中文文档和统一命名约定。
- Windows/Python 3.11 与 3.14 持续集成，以及传输超时、无效 JSON、模型缺失、部分失败和进程终止测试。
- Windows x64 便携 ZIP、CI artifact、`v*` tag 自动 Release，以及中英日三语 README。
- `main` 成功构建后自动更新的 `continuous` prerelease。
- 本机多 NVIDIA GPU 的 VRAM、利用率、温度和短时历史可视化。
- GUI EXE 可直接启动，优先选择 `config/app.local.json`，不存在时使用 `config/app.json`；显式参数仍可覆盖。
- llama-swap 原生 `POST /api/models/unload` 的“卸载全部模型”按钮。
- 当前输出根目录的近期任务列表及聚合结果、摘要和目录直达操作。
- 新运行默认启用随机 seed，并在 manifest 中保存实际 seed base；续跑时保持原 seed。

### Changed

- 公共配置使用 plain 示例和工具内 output，本机配置与 H3 路径放入 Git 忽略的 local 文件；提供隔离目录离线示例。
- `router.auto_start` 控制是否拉起本地路由器。公共配置默认关闭，旧配置省略该字段时保留原行为。
- Windows 发布包只收录明确列出的公共配置和 profile，排除本机配置及外部提示词。

- GUI 改为固定等宽双列布局；
- Python 业务实现迁入 `prompt_batch` 包内；
- 批处理实现按准备、协调、运行时、存储、报表和后端职责拆分；
- 模型选择器从主窗口控制器中拆为独立 GUI 组件；
- GUI 与批处理运行时共用同一进程树终止实现；后端协议错误现在包含 endpoint 上下文。
- `model_source` 公开术语调整为更明确的 `model_catalog`。
- 新安装的默认输出根目录调整为程序目录下的 `output/`；既有 GUI 状态路径保持不变。

### Compatibility

- 根目录启动文件、PowerShell wrapper、`prompt_batch.engine` 和 `prompt_batch.model_source` 继续保留为薄兼容层。
