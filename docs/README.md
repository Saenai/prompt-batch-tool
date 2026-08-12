# 文档索引

本文档集按职责拆分，避免配置说明、实现细节和操作步骤在同一份 README 中互相淹没。

| 文档 | 内容 | 主要读者 |
|---|---|---|
| [running.md](running.md) | GUI、CLI、输入、执行顺序、输出、续跑 | 使用者 |
| [configuration.md](configuration.md) | 应用配置、profile、认证、模型分组 | 配置维护者 |
| [architecture.md](architecture.md) | 模块职责、依赖方向、扩展点 | 开发者 |
| [naming.md](naming.md) | 代码、配置和领域术语的命名约定 | 所有维护者 |
| [development.md](development.md) | 测试、改动流程和维护检查项 | 开发者 |

面向首次使用者的最短入口仍是仓库根目录的 [README](../README.md)。版本变化记录在 [CHANGELOG](../CHANGELOG.md)。

## 文档维护原则

- README 只回答“它是什么、如何开始、去哪里找细节”；
- 行为改变时更新 `running.md`，配置契约改变时更新 `configuration.md`；
- 模块边界改变时更新 `architecture.md`；
- 引入新术语或重命名公开概念时更新 `naming.md`；
- 用户可见变化同步记录到 `CHANGELOG.md` 的 `Unreleased`。

代码、schema 和实际测试结果是事实来源；文档不得凭惯性复制旧结构。
