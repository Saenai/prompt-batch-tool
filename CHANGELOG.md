# 变更记录

本项目采用面向行为的变更记录；尚未发布的改动维护在 `Unreleased`。

## Unreleased

### Added

- 模型系列与参数量双层动态分组；
- 配置版本迁移、JSON Schema 和后端 adapter；
- 断点续跑、仅重试失败项和结构化 GUI 进度；
- 分层中文文档和统一命名约定。
- Windows/Python 3.11 与 3.14 持续集成，以及传输超时、无效 JSON、模型缺失、部分失败和进程终止测试。
- Windows x64 便携 ZIP、CI artifact、`v*` tag 自动 Release，以及中英日三语 README。
- `main` 成功构建后自动更新的 `continuous` prerelease。
- 本机多 NVIDIA GPU 的 VRAM、利用率、温度和短时历史可视化。
- GUI EXE 可直接启动并默认读取同目录 `config/app.json`，不再依赖 launcher 传参。

### Changed

- GUI 改为固定等宽双列布局；
- Python 业务实现迁入 `prompt_batch` 包内；
- 批处理实现按准备、协调、运行时、存储、报表和后端职责拆分；
- 模型选择器从主窗口控制器中拆为独立 GUI 组件；
- GUI 与批处理运行时共用同一进程树终止实现；后端协议错误现在包含 endpoint 上下文。
- `model_source` 公开术语调整为更明确的 `model_catalog`。

### Compatibility

- 根目录启动文件、PowerShell wrapper、`prompt_batch.engine` 和 `prompt_batch.model_source` 继续保留为薄兼容层。
