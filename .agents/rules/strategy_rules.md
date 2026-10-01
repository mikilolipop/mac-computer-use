# Computer Use Native CUA 核心规避策略与开发准则

智能体在进行任何开发、调用或调试前，必须遵循以下 20 条核心战略准则，防止底层代码与行为发生倒退（Regression）：

- **原则 1**：在执行关键逆向和复刻任务前，明确源文件路径和依赖项，不破坏原有环境配置。
- **原则 2**：对系统级操作（macOS 辅助功能、屏幕截图、键鼠模拟等）遵循 macOS 安全权限与原生适配准则。
- **原则 3**：逆向 macOS 系统级 AI Agent 架构时，应由外向内排查：提示词/Skill -> REPL 运行时 -> 本地 IPC 管道 (UDS) -> 原生系统守护进程。
- **原则 4**：底层 IPC 数据流采用小端 4 字节 uint32LE 定长包头与 JSON-RPC 2.0，在编写客户端和 Mock 服务端时需严格维护缓冲队列以防粘包/半包。
- **原则 5**：高质量无感的 Computer Use 绝不能使用外部 Shell（如 `open`/`osascript`/`screencapture`）暴力模拟，必须基于常驻 UDS 守护进程、AXTree 语义树增量 Diff、窗口级精确捕获及原生 UI 遮罩。
- **原则 6**：原生 UI 悬浮描边层 (NSPanel) 必须配置 `ignoresMouseEvents = true` 与 `level = .floating`，确保用户鼠标与点击事件无阻穿透到底层应用，且支持全局 Esc 物理热键监听以便随时退出。
- **原则 7**：区分“桌面原生应用控制”与“浏览器网页控制”。桌面原生应用走 AXTree + 常驻 UDS 守护进程；对于 Chrome/Edge 等现代网页，禁止纯靠桌面 AX 强行穿透 Blink 树，官方采用 CDP (Chrome DevTools Protocol) / 浏览器扩展专有桥接。
- **原则 8**：消除“大模型单步往返通信延迟 (Single-Step Ping-Pong)”与硬编码 `sleep`。必须提供复合原子批处理流水线 (Batch Pipeline)，并在原生层通过事件通知 (`kAXLoadComplete`) 自适应等待。
- **原则 9**：批处理执行必须严格遵循“预检校验与失败即停 (Fail-Fast)”机制。严禁跳过未知动作或缺参动作，严禁丢弃底层执行结果，任何步骤失败必须立即终止并回传 `failedIndex` 与真实 `executedCount`，绝不允许向模型汇报假成功。
- **原则 10**：MCP 服务端必须维护完备的 JSON-RPC 2.0 错误与请求 ID 闭环。任何异常、未知工具或参数错误必须立即回传对应 `id` 的标准响应；显式处理 `ping` 请求；子进程必须添加防御性超时，杜绝宿主因丢包无限死等。
- **原则 11**：统一无障碍树遍历与元素查找逻辑，杜绝“两张皮”。元素点击必须优先调用系统原生 `kAXPressAction`，仅在不支持时结合最新 live bounds 回退点击；文本粘贴必须完整备份并还原用户原有剪贴板，严禁破坏用户现场。
- **原则 12**：杜绝“走一步看一步”的微观往返式模型调用。大模型每次 Tool Call 伴随 20~30 秒深度推理思考与网络往返，若拆解成十余次单步探针，总等待时间必然膨胀至 7~13 分钟。必须将同目标动作（激活、定位、输入、按键、结果捕获）全面收敛至原生原子批处理（Batch Pipeline），单次下发即刻完成，将真实响应时间锁定在秒级。
- **原则 13**：**单轮工具调用预算熔断机制（严格 ≤ 2 次）**。耗时 17 分钟的终极元凶正是 Agent 自身在单轮内疯狂循环调用了数十次工具。每次调用大模型都要重新做数十秒的深度 CoT 推理，工具调用激增必然导致耗时爆炸。执行普通任务时单轮工具调用严禁超过 2 次，禁止多余探针与过度修饰。
- **原则 14**：**多 Agent 协同去中心化与非侵入式后台控制（Non-Intrusive Background Execution）**。多 Agent 严禁采用阻塞式串行嵌套等待（父等子、子等孙导致延迟雪崩）；系统自动化演进应瞄准“不偷光标、不抢焦点”的后台原生无障碍/无头操作，并探索基于 Apple Silicon 虚拟化框架的轻量安全沙箱。
- **原则 15**：**/boost 网格协同与深度熔断准则（Mesh Decentralization & Anti-Waterfall）**。彻底废除“父等子、子等孙”的层级阻塞等待（Max Agent Depth 严格锁定为 1）。多 Agent 必须通过局部原子黑板（`blackboard.json` + `flock`）实现去中心化异步共享与快速阻断（Fail-Fast Signal Bus）；主控 Agent 在子任务运行期间严禁空转死等，必须并行推进验证装配与周边探测。
- **原则 16**：**视觉定位原生编译与原子流水线融合（Compiled Vision Engine & Single-Shot Pipeline）**：在无障碍树缺失的 Electron/自绘视图中，严禁通过外部解释型脚本或大模型多轮往返反复截图探查。必须将 Apple Vision OCR 深度编译进原生 CUA 引擎中，结合无阴影视窗捕获 (`-o`) 与单次原子批处理指令 (`click_text` / `wait_text`)，将跨视图多步动作整体执行耗时从 90 秒压制至 1.6 秒内。
- **原则 17**：**应用进程消歧与高阶复合语义宏指令（Process Disambiguation & Semantic Macro Invariants）**：在桌面应用寻址中，必须明确将 regular GUI 应用作为一级寻址池，强力过滤 `FinderSync`、`Extension`、`Helper`、`XPC` 等后台辅助进程；在高频复合场景（如应用聊天、URL 导航）中，严禁下发多步零碎的寻址、探焦、粘贴与击键试错，必须在端侧编译高阶复合宏指令（如 `send-chat` / `navigate`），确保无论界面如何异步重绘，均能在 < 1 秒内单发直达。
- **原则 18**：**系统事件发送防重与多轮上下文连续性（Event Tap Deduplication & Dialogue Invariants）**：在实现按键与剪贴板注入（`performKeyPress` / `performPaste`）时，绝对禁止同时向 `down.postToPid(pid)` 和 `down.post(tap: .cghidEventTap)` 发送，否则会导致系统收到重复事件（双倍粘贴/双击回车）；对前台活跃应用优先路由至系统级事件分发器，非活跃应用才路由至 PID。在多轮连续交互中，必须默认继承当前活动视窗上下文，严禁在后续轮次中盲目新建对话导致上下文割裂。
- **原则 19**：**专业 CAD/模态命令行交互准则（IME Isolation & Modal Command Synchronization）**：在控制专业工程软件（如 AutoCAD、Blender、Vim 等具备复杂内部命令行及画布快捷键绑定的专业工具）时：
  1. 剪贴板注入（`Cmd+V`）在非显式聚焦的文本区极易被画布拦截为应用级快捷键（如 AutoCAD 画布直接拦截 `Cmd+V` 触发 `PASTECLIP` 粘贴图块，而非输入文本），严禁在未知焦点状态下盲目使用粘贴注入；
  2. 字符输入必须防范输入法（IME）污染。macOS 处于中文输入法状态时，下发 keystroke 会丢失前导下划线 `_` 并将英文命令吞入拼音缓冲区形成乱码串（如 `aSHADEMODEaCaZOOMaE`），必须走原生独立 Unicode 字符注入或通过脚本文件（`_SCRIPT` / AutoLISP）无损执行；
  3. 模态命令具备多阶段交互状态机（如 `_ERASE` -> `_ALL` -> 确认选择 -> 确认执行），严禁在无回执校验下按固定短延时盲目下发后续命令，否则前序阻塞会导致全部后续命令被当作错误参数吞没。
- **原则 20**：**视觉标注直连与语义树剪枝降噪准则（Set-of-Marks Visual Anchoring & Semantic AXTree Pruning）**：
  1. **消除视觉坐标幻觉（Set-of-Marks）**：在高分屏与视网膜缩放（Retina 2x/3x）下，视觉大模型直接预测绝对 `(X, Y)` 坐标极易产生偏移与脱靶。必须在端侧截图中为所有可交互元素动态打上高对比度序号徽章（`[1]`, `[2]`, ...），引导模型直接通过元素编号触发系统原生动作（`kAXPressAction`）；
  2. **无障碍树语义剪枝（AXTree Pruning）**：禁止将无标题、无描述、无值且非交互的纯排版容器节点（`AXGroup`, `AXGenericElement` 等结构噪声）倾倒给大模型，必须在原生端执行语义剪枝（`--compact`），使上下文 Token 消耗降低 70% 以上并大幅加速大模型首字生成；
  3. **前置权限健康诊断（Preflight Doctor）**：系统在任务启动或排障时，必须提供毫秒级系统 TCC 权限自检（Accessibility 与 Screen Recording 探测 `doctor`），支持一键唤起系统授权弹窗，杜绝因权限缺失产生隐蔽异常。
