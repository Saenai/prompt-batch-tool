# 变更记录

本项目采用面向行为的变更记录；尚未发布的改动维护在 `Unreleased`。

## Unreleased

### Added

- 模型系列与参数量双层动态分组；
- 配置版本迁移、JSON Schema 和后端 adapter；
- 断点续跑、仅重试失败项和结构化 GUI 进度；
- 分层中文文档和统一命名约定。

### Changed

- GUI 改为固定等宽双列布局；
- Python 业务实现迁入 `prompt_batch` 包内；
- 批处理实现按准备、协调、运行时、存储、报表和后端职责拆分；
- 模型选择器从主窗口控制器中拆为独立 GUI 组件；
- `model_source` 公开术语调整为更明确的 `model_catalog`。

### Compatibility

- 根目录启动文件、PowerShell wrapper、`prompt_batch.engine` 和 `prompt_batch.model_source` 继续保留为薄兼容层。
