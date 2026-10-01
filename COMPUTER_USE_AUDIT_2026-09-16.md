# Computer Use 复刻项目审计

审计日期：2026-09-16。目标：定位当前 Skill 和实现的问题，明确接入 Antigravity、复现 Codex Computer Use 体验的实际缺口。

结论：当前项目是官方接口资料、依赖官方客户端的插件副本、自研 Swift CLI、Python MCP 四部分的集合。基础原生控制已实现，但这些部分没有组成一条可独立运行、可靠验证结果的 Antigravity 调用链。修改提示词本身不足以补齐这些缺口。

本轮完成代码与配置审计、无 UI 输入的故障复现。没有操作浏览器页面、发送消息、启动浮层、修改全局配置或改动执行代码。历史网站对话测试没有重跑。下述“静态确认”不等于所有界面场景已实测。

## 1. Skill 与运行时没有对接

### 1.1 项目中的 Skill 依赖 Codex 宿主

- `plugin/skills/computer-use/SKILL.md:6–19` 要求 `node_repl`、`nodeRepl.write`、`@oai/sky`。
- `skills/macos-sky-skill.md` 同样是 Sky 使用说明。
- `skills/record-and-replay-skill.md` 依赖 `event_stream_start/status/stop`；自研 MCP 没有这些工具。
- 自研执行接口却在 `sdk/mcp_server.py`，提供 8 个 Python MCP 工具，没有上述 Node 运行时或录制工具。
- Sky 的 `state.screenshot.url`、`disableDiff`、带 app 的按键等接口，与自研的 `screenshotUrl`、`diff`、无 app 的独立按键接口并不一致。

影响：模型照着 Skill 调用的工具，不是实际自研服务暴露的工具；复制 Markdown 不会创建它所依赖的宿主能力。

### 1.2 插件启动器仍指向官方程序

`plugin/.mcp.json` 调用 `plugin/bin/computer-use-client-launcher`。启动器第 5–13 行转发到用户目录中的 `SkyComputerUseClient`，没有调用本项目的 `sdk/mcp_server.py`。

检查时官方程序路径确实存在；问题不是“启动器文件缺失”，而是这条路径仍依赖 Codex 安装，与自研引擎是两套实现。不能据此宣称已独立复刻。

### 1.3 Antigravity 尚未注册本项目服务

本机 Antigravity 版本为 2.13.0。检查结果：

- 工作区没有 `.agents/skills/`、`.agent/skills/` 或 `.agents/mcp_config.json`。
- `~/.gemini/config/mcp_config.json` 与旧路径 `~/.gemini/antigravity/mcp_config.json` 中仅看到 `chrome-devtools-mcp` 和 `gmp-code-assist`。
- `~/.gemini/config/skills/` 中有 `accidental-data-loss-prevention`、`macos-swift-first-strategy`，没有本项目的 Computer Use Skill。

这些是配置文件检查，未对 Antigravity 当前进程的工具列表做 UI 验证。手工要求模型读取项目文件可能生效，但不同于自动发现和正式接入。

官方当前文档规定工作区 Skill 位于 `.agents/skills/<name>/SKILL.md`；全局 Skill 位于 `~/.gemini/config/skills/`。MCP 可在 `.agents/mcp_config.json` 或全局配置中注册。参考：[Skills](https://antigravity.google/docs/skills)、[MCP](https://antigravity.google/docs/mcp)。

补充：已阅读实际安装的 `macos-swift-first-strategy/SKILL.md`。它建议优先评估 Swift CLI，明确允许主控通过子进程调用；它没有提供 Computer Use，也没有要求牺牲稳定性。无法仅凭该文件断定它是过往架构选择的原因。

## 2. 已复现的错误

### 2.1 批处理把未执行的动作计为成功（优先修复）

代码：`native_engine/mac_cua_engine.swift:740–787`。

向现有二进制传入以下动作，目标是正在运行的 Finder：

```json
[
  {"action":"audit_unknown_action"},
  {"action":"click"},
  {"action":"set_value"}
]
```

这些分支均不产生 UI 输入：未知动作跳过；click 缺 element；set_value 缺 element/value。实际退出码为 0，输出：

```json
{"success":true,"app":"com.apple.finder","executed":3}
```

此外，正常 click/set_value 分支也丢弃底层 Bool 返回值。模型因此无法区分成功、失败、未执行，可能继续输入或提交。批处理只是顺序执行，不具备事务回滚，也没有失败即停机制，不应称为具有事务语义的“原子操作”。

修复要求：执行前完整校验；逐项回传结果；失败即停；返回失败位置与实际完成数；操作后检查结果状态。

### 2.2 MCP 错误没有响应，宿主只能继续等待（优先修复）

代码：`sdk/mcp_server.py:184–229`、`sdk/cua_client.py:23–31`。

通过 stdio 发送 initialize、tools/list、两个失败工具请求以及 ping。工具请求分别指向不存在的应用、未知工具。实际收到的响应 ID 为 `[1, 2, 5]`，失败请求 3、4 没有响应，仅在 stderr 中报错；ping 返回 method-not-found。

根因：最外层 except 仅 logging.error，没有生成与请求 ID 对应的错误响应。子进程调用也没有 timeout。实际宿主超时时长未测，不能把日志中的 13 分钟全部归因于此，但这里已具备确定的超时诱因。

修复要求：工具执行失败返回 MCP tool error；非法请求返回规范错误；处理 ping/通知；对子进程设置超时；将取消传递到执行层。

### 2.3 截图没有作为图片返回

代码：`sdk/mcp_server.py:139–144`。

用合成 state（含 screenshotUrl）替换 get_state 的返回值，调用 MCP handler，返回内容类型仍只有 `['text']`。它把文件 URL 序列化成文本，没有传图片内容。

因此仅凭此次 MCP 响应不能保证模型实际看到了截图；宿主需要另行读图，而项目没有把这一步接成闭环。应返回 MCP image 内容块并验证 Antigravity 的实际视觉输入，附带窗口原点、尺寸和缩放信息。

## 3. 静态确认的执行层问题

| 问题 | 代码位置 | 后果与修复方向 |
| --- | --- | --- |
| 观察和 set_value 对元素编号的规则不同 | Swift:80–179、283–334 | TreeCollector 有角色过滤、边界条件和深度限制；findAX 使用另一套规则。相同 index 可能落在不同控件上。统一映射并绑定 snapshot/window/session。 |
| 所谓元素点击仍是旧坐标点击 | Swift:265–280、594–608 | 从磁盘缓存读 bounds 后点击中心，没有 AXPress、快照有效期或窗口位置校验。窗口移动、弹窗、布局更新后可能点错。 |
| 未知按键静默变成 Return | Swift:337–369、675–681 | keyMap 找不到就默认 0x24；Skill 宣称支持的 super+c 等组合键没有解析。可能误提交。未知键应报错；按键应明确绑定 app。 |
| 批处理 Schema 缺少现有动作 | MCP:115–120；Swift:766–778 | Swift 支持 paste/click_coord，但 MCP enum 未声明，也没有 text/x/y 参数。模型无法从工具契约正确发现能力。 |
| 粘贴覆盖用户剪贴板 | Swift:373–378 | clearContents 后没有恢复，和所复制 Skill 的承诺相反。需要保留并恢复兼容格式，处理期间用户主动复制的情况。 |
| 截图与 AX 不一定对应同一窗口 | Swift:187–235、513–519 | 截图选 PID 下最大窗口，AX 遍历所有窗口；没有统一 windowId 选择与坐标转换契约。 |
| UI 内容被截断与过滤 | Swift:80、88、168 | 深度超过 10 停止，菜单子树被丢弃，value 超 60 字截断。会影响菜单控制和长文本验证，不能把所有缺失都归因于浏览器。 |
| JSON 输出不统一 | Swift:673、681、707、787 | 部分输出通过字符串插值拼 JSON，双引号、反斜线和换行可破坏格式；Python 又退回 raw_output。应统一 JSONEncoder，解析失败应显式报错。 |

以上未通过真实点击验证误操作，以免影响用户当前应用；结论来自执行路径审计。

## 4. 日志中的架构结论需要纠正

| strategy_log.md 的描述 | 当前可确认事实 |
| --- | --- |
| 常驻 UDS 原生守护进程 | 实际自研链路是 MCP → subprocess.run → 一次性 Swift CLI；UDS 代码和 Mock 位于 reverse_engineering，未接入该链路。 |
| ScreenCaptureKit、零外部依赖 | captureWindow 实际启动 `/usr/sbin/screencapture -l`。已做到窗口截屏，但不是实现了 ScreenCaptureKit 捕获。 |
| Zero Sleep / 事件自适应等待 | Swift 中有多处 usleep，没有 AXObserver 或加载完成事件接线。短按键间隔不一定是错误，但它不能代替界面就绪判定。 |
| 浏览器与桌面双轨已跑通 | 自研 navigate 仍是 Cmd+L → 粘贴 → Return；项目执行代码没有 CDP/扩展后端。Antigravity 已配置另一个 chrome-devtools-mcp，但不能把它算成本项目已接通。 |
| 完全无感后台操作 | state、navigate、click 会激活应用；坐标点击发送全局鼠标事件。Swift 本身不会自动消除焦点干扰。 |
| Esc 可以取消 | overlay.swift:152–157 只终止浮层进程；执行引擎没有对应取消通道。当前浮层也未由 MCP/执行器统一管理。 |
| 仅返回增量树、显著降低 Token | state 同时返回 fullText 与 diff；MCP 原样序列化两者。computeDiff 是按文本行 Set 比较，不是稳定节点身份的结构差分。 |
| 几次对话证明通用稳定与性能提升 | 日志记录的是特定窗口布局下的成功案例，含硬编码桌面坐标。没有本轮可核验的系统基准，不能推出跨窗口、跨页面的成功率或倍数。 |

官方安装包的 Computer Use Skill 第 115 行明确说明，动作后获取状态通常会等待约 1 秒，加载迹象可能带来额外延迟。因而“官方完全零等待、整段动作始终低于 100ms”不能由该资料支持。

同一 Skill 使用 Chrome 演示 AX 操作，并提供截图/坐标回退，所以“官方绝不通过桌面 AX 操作浏览器”也过于绝对。浏览器专用工具是一条有价值的路线，不能将不同工具的能力混成某一实现已经完成的证据。

从原生 API 调用、二进制符号或接口资料推断内部设计，需要明确标为推断；不能据此宣称已恢复全部实现。

## 5. 建议的实现顺序

目标调用链：

```text
Antigravity 中的模型
  → 项目专用 Skill（只描述实际工具、观察与验证规则）
  → MCP（文本 + 图片 + 错误 + 取消）
  → 会话执行器（串行操作、快照映射、超时、有限批处理）
  → macOS 后端（AX + 必要的键鼠回退 + 窗口截图）
  → 新状态与结果校验 → 模型继续判断

可选浏览器分支：已有浏览器 MCP / CDP / 扩展
浮层与 Esc：连接同一个执行会话及取消信号
```

1. **先建立可信最小闭环。** 修复错误响应、假成功、元素编号、按键校验和图片回传。定义统一参数/返回值。自研工具使用自己的名称和 Skill，避免暗示是官方原包。
2. **再完成 Antigravity 接入。** 将 MCP 指向自研入口，增加可被发现的项目 Skill，实际检查宿主工具列表和图片输入。保留官方资料作为 reference，避免作为运行指令混用。
3. **补齐运行时。** 建立常驻进程和会话级状态、统一窗口定位、取消/超时、失败即停、剪贴板恢复。UDS 是传输选择之一；先让契约正确，再按测量决定是否引入。
4. **增加按条件等待与观察点。** 激活/焦点确认、控件出现或属性变化、超时退出。只批量执行已知且可验证的短动作；页面跳转、弹窗和动态布局之后重新观察。不要把整个未知网页流程盲目一次提交。
5. **最后优化和扩展。** 评估 ScreenCaptureKit、增量树、浏览器专用后端，以及独立 JS 执行层。滚动、拖拽、右键、富文本、选区和录制逐项实现与验收，不能仅沿用官方 Skill 中的声明。

OpenAI 当前公开指南也描述了“持久环境、脚本或结构化动作、文本/图片反馈、结果检查”的集成方式，并允许保留自定义 UI 工具/MCP；这些原则不要求复用 Codex 私有 `node_repl`。该指南是公开 API 文档，不是 Codex 内部架构证明。[Computer use](https://developers.openai.com/api/docs/guides/tools-computer-use)

验收应覆盖：未知参数明确失败、应用未运行、控件消失、窗口移动/缩放、多窗口、中文/多行输入、弹窗拦截、页面慢加载、剪贴板恢复、中途 Esc。测量任务总时间、工具时间、页面等待、重试数和任务成功率；底层发完按键不等于页面加载或任务完成。

## 6. 已有成果与本轮验证边界

已有可复用部分：原生应用枚举、AX 遍历、窗口截屏包装、基础键鼠/赋值/粘贴、批处理原型、MCP 基础握手、浮层绘制、协议研究资料。

本轮实测：现有二进制能枚举 10 个 GUI 应用；无效批处理的假成功已复现；MCP 错误请求丢失响应已复现；Schema 缺项与纯文本截图返回已验证；Python 文件可通过语法解析。

未宣称完成：Swift 重新编译、真实 UI 完整回归、当前 TCC 权限验收、Antigravity 工具实际加载、官方服务直连兼容性、性能基准、独立复刻完成。当前执行代码和原始 strategy log 保持原样，便于后续按证据修复。
