# 开发与维护

## 环境

运行时只需要可用的 Python 3 和标准库。不要因为开发便利，悄悄给正常运行增加第三方依赖。

## 验证命令

```powershell
python -B -m unittest discover -s tests -v
python .\app.py --config .\config\app.json --self-test
python .\batch_cli.py --help
```

涉及 PowerShell 兼容入口时，还应执行语法解析检查。涉及 GUI 行为时，至少做一次隐藏窗口启动/销毁 smoke test；布局变化需要实际观察界面。

## 改动落点

- 新任务或 mode：优先添加/修改 profile；
- 新配置字段：同时更新运行时校验、schema、示例配置和文档；
- 新后端：实现 `ChatBackend`，注册 factory，补适配器测试；
- 新报表：放入 `reporting.py`，不要增加 runner 的格式化职责；
- 新持久化格式：放入 `storage.py`，并考虑中断和原子性；
- 新任务表单或运行状态呈现：放入 `gui.py`；模型选择行为放入 `gui_models.py`，业务规则仍由核心模块提供。

## 质量检查清单

提交前确认：

- 根目录入口仍可启动，旧导入路径仍通过兼容测试；
- 不含模型 ID 清单、密钥或无必要的本机绝对路径；
- 新路径相对于配置文件或项目根解析；
- runner 没有重新复制配置准备、HTTP、存储或报表逻辑；
- 用户可见变化已更新相应文档和 `CHANGELOG.md`；
- 测试覆盖正常运行以及至少一个失败或边界路径；
- 只暂存本次改动文件，并检查 diff 后再提交。

## 文档维护

文档职责见 [文档索引](README.md)。修改同一事实时只保留一处详细说明，其他位置使用链接。命令示例必须能从仓库根目录执行。

## 版本兼容

兼容门面是过渡边界，不是第二套 API。旧名只能转发到新实现；禁止在 `engine.py`、`model_source.py` 或根目录 launcher 中增加业务分支。
