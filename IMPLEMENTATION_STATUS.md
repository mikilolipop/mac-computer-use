# 优化实施状态（2026-09-27）

本文件跟踪实际实现，原审查报告保留为审查时点的记录。

**第二批动态页面更新**：当前以 [DYNAMIC_PAGE_REVIEW.md](DYNAMIC_PAGE_REVIEW.md) 为准。编号操作改为唯一目标身份匹配（120 秒），不再要求全树一致；MCP 默认文本优先，图片按需缩放；新增批处理后观察和耗时记录；工作区启动器使用项目 .venv。下方第一批描述保留作实现历史。

## 本轮已实施

- **窗口与快照绑定**：state 与编号操作共用焦点窗口作用域及 TreeCollector；快照绑定 session、PID、进程启动时间、窗口 ID、窗口边界、元素属性/AXIdentifier 和 60 秒有效期。窗口、布局或元素属性变化时保守拒绝；去掉旧缓存坐标回退。观察不再自动 activate。无唯一窗口匹配时返回错误。
- **接口迁移**：CLI 编号操作新增必需 `--snapshot`；MCP click/set_value 必需 `snapshot_id`，batch 中含编号操作时也必需。Python 同一个 CuaClient 可沿用最近 get_state 的快照，也可以显式传入 snapshot_id。不同 SDK 实例隔离会话。
- **整批预检**：所有静态参数检查在查找应用和执行之前完成。最多 100 个动作；单次/累计声明等待不超过 10 秒；未知动作、未知字段、缺参、无效键和超范围等待提前拒绝，executed=0。运行时继续失败即停，没有事务回滚。
- **MCP/SDK 错误**：请求格式、ID、参数类型检查；非法请求有标准错误；notification 不响应也不触发动作；发现工具不依赖二进制存在。SDK 失败抛 CuaError，MCP 保留其结构化负载。超时提示结果可能未知，不建议自动重试副作用动作。
- **诚实的操作状态**：成功投递的批处理/导航/聊天等标为 dispatched，不等同于消息已送达或页面已加载。聊天定位不到输入框时中止。
- **缓存与感知**：会话目录、散列键、唯一截图路径和原子写入；OCR 与 state 使用同一焦点窗口选择规则；截图子进程有超时，OCR 临时图片用后删除；diff 能表达顺序和重复项变化；标注失败显式报告。
- **剪贴板**：defer 覆盖失败恢复；仅在 changeCount 仍属于本次写入时还原，避免覆盖用户新复制的内容。
- **Boost 租约**：只有 pending 任务可领取；start-task 返回 lease_id，heartbeat/complete-task/fail-task 必需 `--lease`。孤儿回收废除旧租约；任务执行要求使命处于 in_progress；使命完成要求所有子任务已完成。正式黑板未迁移或改动；旧运行中的无租约任务需要在后续新使命中重新领取。
- **测试与构建**：副作用测试原文移入 tests/manual/*.py.disabled；新默认测试只用 mock、临时黑板及编译后的纯逻辑测试入口。build.sh 同时构建引擎和浮层，编译全部成功后替换二进制。

## 使用变化

```python
from sdk.cua_client import CuaClient, CuaError
client = CuaClient()
state = client.get_state("com.apple.finder", no_img=True)
# 先由调用者从 state 确认目标，不能盲用固定编号。
# client.click("com.apple.finder", chosen_index, snapshot_id=state["snapshotId"])
```

CLI 需先获取 state，再把 `snapshotId` 传给 `click --snapshot <id>` 或 `set-value --snapshot <id>`。缺少快照、过期或 UI 变化会拒绝，需重新观察。连续编号操作之间如果改变了元素属性，也需重新观察；不会自动把旧编号映射到新页面。

Boost：保存 start-task 输出的 lease_id，后续使用 `heartbeat/complete-task/fail-task --id <task> --lease <lease_id>`。测试客户端已同步迁移。

```sh
bash native_engine/build.sh
python3 -m unittest discover -s tests -p 'test_safety.py' -v
python3 tests/test_boost_coordinator.py
python3 -m sdk.mcp_server
```

Pillow 是可选标注依赖，requirements.txt 声明兼容范围，尚非完整锁定环境。plugin/ 中的官方客户端副本不是自研启动入口。

## 尚未完成或验证

- **本轮是第一批可靠性加固，未完成整份路线图。** MCP 请求执行仍同步；执行层取消、Esc 与任务联动、全局输入串行队列尚未实现。
- 真实聊天送达、页面载入、CAD 命令完成等后置条件尚未实现；dispatched 只代表底层调用成功。剪贴板仍使用有限等待，不保证任意应用已经消费内容。
- 快照校验为保守比较，动态文本也可能导致拒绝；没有提供稳定 AXIdentifier 的应用，不能保证区分所有外观完全相同的控件。校验到动作之间仍存在系统 UI 的竞争窗口；真实多窗口、双屏和动态界面需受控 App 验收。
- 单次截图设置 3 秒超时；wait_text 使用单调时钟计时，但一次进行中的 OCR/截图可能超过该步 deadline，完整取消/硬截止传播仍待做。
- 尚无常驻 Swift UDS 服务、原生内存截图、完整性能基准、输出模式裁剪、SoM 避让与完整依赖锁定；旧 session 缓存的生命周期清理仍待做。
- 滚动、拖拽、右键、CDP 路由、CAD 适配及参考 TS IPC 加固仍待实施。
- 本轮没有点击真实应用、发送聊天消息或运行 CAD；离线测试不能替代这些端到端验收。Swift 的 launchApplication 弃用警告暂未处理。

## 回退

改动前备份：artifacts/backups/pre-hardening-20260927-152144.tar.gz，包含执行源码、SDK、测试、Boost 文件、README、strategy 和两份二进制。恢复时只取需要的文件，不应覆盖之后的新日志或用户新工作。

## 本轮验证结果

- 19 项离线测试通过；原生策略测试包含多个身份、过期、预检与 diff 断言。
- 6 组 Boost 回归通过，含 90 次并发写入。
- 引擎与浮层构建成功，现有 bin 已替换；主引擎仍有一项弃用警告。
- 新二进制与实际 MCP 进程的无 UI 输入探针通过，结果及 SHA-256 见 artifacts/hardening-verification.json。
- 已启动的宿主需重启本项目 MCP 进程，才能加载新代码及工具参数。

## 2026-09-27 第三批更新（覆盖上文对应旧状态）

已实现窗口枚举、app-scoped window_id、选定窗口激活与投递前焦点检查、Chromium AX 准备、批处理后的 AX 文字条件等待。MCP 现为 14 个工具；get_app_state 默认 prepare_web=true。wait_for_text 表示观察到指定文字，不等于整个网页完成加载。超时后保持动作已执行状态，不重放。

41 项离线回归、Swift 构建、MCP 启动器和技能校验通过；真实多窗口/全屏 Edge、AX 启用成功率和淘宝总耗时尚未复测。AX 初始化的 1 秒是轮询预算，同步调用仍受 SDK 外层超时约束。窗口检查与事件投递之间仍存在系统竞争，不能声称绝对避免焦点抢占。

详细参数、验证结果和回退位置以 strategy_log.md 的 19:30 条目为准。需重新加载本项目 MCP 进程使用新接口。
