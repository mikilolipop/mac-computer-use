# 项目优化审查与建议

审查日期：2026-09-27。状态：审查完成，建议尚未实施。

结论：项目已经具备 Swift CLI、Python SDK、13 项 MCP 工具、OCR、SoM、AX 语义剪枝和独立 Boost 黑板协调器。下一阶段应优先保证“观察到的对象就是操作的对象、失败能正确上报、结果能验证、执行能取消”，再优化性能和扩展动作。

本轮只新增本报告并向 strategy_log.md 追加记录，没有修改执行代码、配置、现有二进制或正式黑板。临时构建与协调器探针均使用临时目录。没有发送聊天消息、输入文本、点击界面或执行 CAD 示例。

## 1. 遍历范围与验证边界

递归清点时共 539 个文件；排除构建缓存、截图、数据库等后，识别到 39 个源代码、文档和配置文件（按文件扩展名统计，不含无扩展名启动器）。工作目录约 370 MB。没有发现 AGENTS.md；当前目录不是 Git 仓库。

| 范围 | 本轮检查内容 |
| --- | --- |
| native_engine、sdk、bin | Swift 执行与浮层源码、构建脚本、SDK、MCP、标注器；现有 CLI 的无 UI 输入探针 |
| tests | 三份测试文件的断言与副作用；执行 Boost 测试，未整套执行桌面交互回归 |
| .agents | MCP 配置、自研 CUA 技能说明、Boost 协调器及模板/状态文件清点；未调用 Agent 编排 |
| plugin、skills、api_specs、reverse_engineering | 官方插件副本与自研入口的关系、API 能力差异、TS 传输层、Mock 服务与文档 |
| 根目录示例 | cad_draw.py、test_edge_nav.py、draw_nut.lsp、CAD HTML 的用途、执行风险与依赖 |
| README、strategy、旧审计 | 文档声明与当前实现对照；旧结论仅作线索，以当前源码及探针为准 |
| 图片、React 缓存、module_cache、.build、scratch | 文件和体积清点；未逐张复核历史截图、未反编译缓存/二进制、未读取数据库内容 |

本报告不是实际桌面全场景认证；多窗口误点、剪贴板竞争等属于代码路径确认的风险，没有在用户现场制造误操作来演示。

## 2. 当前已经做对的部分

- 点击优先尝试 AXPress，键盘前台/后台投递已有互斥分支。
- 批处理已有逐步失败即停，未知动作不再被直接计为成功。
- SDK 子进程已有超时，MCP 常规工具异常和 ping 已有响应路径。
- MCP 已支持真正的 image 内容块；SoM、compact、doctor 有实现。
- Boost 已有统一锁文件、原子替换、依赖检查和孤儿回收；现有 6 组测试本轮通过。

因此，不能照搬 9 月 16 日审计，把上述能力说成仍未实现。但这些局部修复尚不足以证明完整可靠性。

## 3. 优化建议（按优先级）

### P0-1：绑定窗口和快照，修复编号寻址

**证据**：native_engine/mac_cua_engine.swift:322 的 findLiveElement 遍历全部窗口并累计编号；:1024 的 state 优先只收集 focusedWindow。:550 的 performClick 在 live 查找失败后仍使用缓存坐标。

**影响**：同一编号可能对应其他窗口的元素；布局重排后编号也可能指向新元素。过期缓存回退会进一步掩盖失效。SoM 徽章只能显示编号，不能修复编号身份错误。

**建议**：让 state、click、set_value 共用窗口作用域和遍历器，传递 sessionId、PID、windowId、snapshotId 及元素身份摘要；动作执行前校验窗口、角色与身份，失效返回 STALE_SNAPSHOT；默认禁止无验证的旧坐标回退。截图、AX 树和 OCR 使用同一窗口与快照元数据。

**验收**：双窗口、切换焦点、插入新控件、窗口移动、应用重启后，旧引用必须命中原目标或明确拒绝，不能静默点到新目标。

### P0-2：真正整批预检，区分“事件已投递”和“目标已完成”

**证据**：Swift:1436 后在执行循环中逐项校验。无 UI 输入探针 `[wait(0), unknown_action]` 返回 executed=1、failedIndex=2，证明前序步骤已执行。:811 的 send_chat 没找到输入框仍继续粘贴和回车；点击和新建聊天部分返回值被忽略。

**建议**：拆成 validateAll → execute → verify 三阶段；执行前拒绝未知动作、缺参、非法数值、超预算等待。运行时仍逐步检查动态前置条件。输出逐步结果、失败位置、已执行动作和验证状态。聊天输入定位失败必须中止；发送与导航需各自的后置条件。副作用动作超时后先检查结果，避免盲目重试导致重复发送。

**验收**：最后一步静态参数错误时，整批 executed=0；正常事件投递只能记 dispatched，确认界面结果后才记 verified。说明批处理不提供事务回滚。

### P0-3：修复 MCP/SDK 错误闭环和超时语义

**证据**：sdk/mcp_server.py:282 的 get_app_state 未把 state.success=false 映射为 isError=true。本轮对不存在应用调用 state，确实得到错误文本但缺少 isError。:443 附近解析请求直接调用 req.get；输入 `[]` 只记日志，无错误响应。无 id 的 ping 返回 id=null 响应。sdk/cua_client.py 的非零退出可返回 raw_output 字典，异常表示不统一。

**建议**：集中进行请求结构、参数类型、工具参数校验，明确 request 与 notification；统一 SDK 结构化错误，保留错误码、阶段和底层原因。耗时动作共享单调时钟 deadline，并传播取消。wait_text 当前只累计 sleep 时间，不含 OCR/截图耗时，应改为实际截止时间。waitMs 的 UInt32 乘法也应有上限及溢出防护。

**验收**：无效对象、错误参数、未知工具、缺失应用、子进程超时、通知和取消都有确定行为；不存在应用的 state 返回 isError=true；耗时不超过约定预算加合理清理余量。

### P0-4：建立不会改动用户现场的测试基线

**证据**：tests/audit_regression_test.py 在模块顶层执行真实 cmd+c、pbcopy、paste、type-text；末尾仍断言 len(tools_list)==12，当前服务实测 13 个工具。tests/test_optimizations.py 依赖中文 Finder 名和实际权限；SoM 测试只检查图片存在、尺寸与模式。

**建议**：将测试拆为纯单元、协议集成、受控 GUI 验收三层。默认测试使用假的执行后端和合成 AX/截图；GUI 测试必须显式选择并指向专用测试 App。所有子进程设置超时、finally 回收。断言工具契约而非孤立魔法数字；SoM 检查徽章坐标及编号映射，剪枝检查相同元素身份而非只比较数量。

**验收**：在没有 Finder/Edge/Gemini 窗口、没有桌面权限的环境也能完成默认测试；运行默认测试不改剪贴板、不激活应用、不输入文字。

### P1-1：把停止操作、输入归属和剪贴板保护接到执行层

**证据**：overlay.swift:154 的 Esc 仅终止浮层自身；自研执行层没有与浮层共享的取消信号。state 会 activate，postMouseClick 会移动全局指针，独立 press_key 没有 app 参数。performPaste 清空剪贴板后若 setString 失败直接返回，且恢复时不检查用户是否已复制新内容。

**建议**：建立单一桌面输入执行队列和取消令牌，批处理、长文本输入、等待循环检查取消；浮层按 Esc 取消对应任务。键盘输入绑定目标应用/窗口并验证焦点。剪贴板用 defer 做失败恢复，结合 changeCount 避免覆盖用户新复制内容。将被动观察与主动激活作为显式选项。

**验收**：Esc 后不再产生后续输入；目标窗口失焦时停止或重新校验；粘贴失败和用户并发复制均保留正确剪贴板。不能把“退出浮层”记录为“停止自动化”。

### P1-2：隔离缓存与捕获，再按测量结果引入常驻服务

**证据**：SDK 每次调用 subprocess；captureWindow:378 内实际执行 /usr/sbin/screencapture 并 waitUntilExit；截图路径按 PID 固定，树缓存把所有非 ASCII 字符替换成下划线，且没有会话锁。原生引擎没有 UDS 服务。reverse_engineering 的 UDS 是另一条客户端/Mock 路径。

**建议**：先按 session/PID/window/snapshot 建独立缓存，使用原子写入、私有目录、清理期限，避免中文名称碰撞和并发覆盖。为进程启动、AX、截图、OCR、标注分别计时。随后评估常驻 Swift 服务与原生截图 API，把图像直接送 OCR，减少启动与磁盘读写；保留 CLI 兼容入口。后台 AX 和必须占用前台的动作分别报告能力。

**验收**：并发读取不同窗口不串图、不串树；超时清理截图子进程；基准报告 p50/p95、成功率及环境，不能只报告单次最快值。

### P1-3：让 diff、剪枝与 SoM 真正降低总上下文成本

**证据**：Swift:507 用 Set 比较文本行，不能完整表达顺序和重复数变化；state 同时返回 full text、diff、elements，MCP 又完整序列化。紧凑模式仍遍历原树并读取属性。visual_annotator.py 为所有元素绘制标签，没有避让策略；标注异常被 SDK 静默吞掉。没有 AX 节点时本标注器不会凭空识别画布按钮。

**建议**：提供 full/diff/summary 输出模式，保留恢复基线；按窗口稳定身份表达变化，只在需要时返回 elements 和图片。标注器限制可见标签、处理遮挡/边界和标签密度，并报告 annotationStatus。多屏和 1×/2× 缩放用合成图和受控窗口校验。将“降低 70%”“消除幻觉”改为可复测指标与适用条件。

**验收**：比较完整 MCP 文本字节/token 与图像体积，不只比较 AX 行数；控件顺序变化可检测；标注失败可见；密集界面标签仍可读。

### P1-4：给 Boost 增加任务领取租约与终态约束

**证据**：boost_coordinator.py:287 的 start-task 不拒绝 in_progress；:382 的 complete-task 不核对 owner/当前状态；:497 的 complete-mission 不检查子任务是否完成。本轮临时黑板先由 worker1 开始 A，再由 worker2 开始 A，两次均成功；随后使命标 completed，而 A 仍 in_progress。

**建议**：在文件锁内检查合法状态转移；领取返回 leaseId/attempt，heartbeat/complete/fail 必须匹配。孤儿重试废除旧租约，拒绝迟到结果；completed/aborted 的使命拒绝新执行。使命完成必须核验所有必要任务。缺失依赖也应在启动前校验。

**验收**：两个 worker 同时领取仅一个成功；重试后旧 worker 无权提交；仍有运行中任务不能宣称使命完成。已有并发文件写测试不能代替这些业务一致性测试。

### P1-5：统一安装入口和真实能力清单

**证据**：plugin/bin/computer-use-client-launcher 指向用户 Codex 安装里的官方客户端；.agents/mcp_config.json 才指向自研 Python 服务且硬编码本机路径。Pillow 有 import，但无 pyproject/requirements；TS 无 package.json/tsconfig。build.sh 只构建主引擎，不构建浮层。

**建议**：把资料归档、独立自研运行时、实验示例分开。为自研包提供明确名称、依赖锁定、环境检查和可移植启动器；构建引擎与浮层并记录版本/源码摘要。README 给出一条从干净环境到 MCP 工具发现的路径和能力矩阵。

**验收**：不依赖本机绝对路径即可构建和发现工具；能明确识别官方客户端模式与自研模式。doctor 区分权限、依赖、二进制及可用能力；当前 --prompt 只给 AX 传入 prompt，屏幕录制仅 preflight，说明应准确。

### P2-1：按真实任务补基础动作与应用适配

自研 CLI/MCP 尚无完整 scroll、drag、右键、双击、窗口指定与区域捕获接口；资料目录的 API 不等于自研实现。建议先补滚动和窗口定位，再按任务需要补拖拽/菜单。网页路由到 CDP 目前主要是文档建议，需要能力检测、错误回退和接口契约。CAD/聊天采用应用适配器，验证焦点、就绪状态和后置结果。

cad_draw.py 仍保留已记录失败的 osascript+固定延时路径，并有 _ERASE/_ALL 示例；应移入明确标记的实验目录。draw_nut.lsp 与 HTML 展示参数不同，应共享参数和产物校验；本轮未验证机械标准符合性或 DWG 结果。

### P2-2：加固参考 TS IPC 与 Mock

client_reconstruction.ts:108 在 data 回调中把 decodeMessageFrames 放在 try/catch 外，超大帧可能成为未捕获异常。getTransport 没有共享连接中的 Promise，握手失败后 transport 状态清理不足。Mock 解帧没有同等帧长上限，单连接可占据 accept 循环，未知业务 requestType 返回空成功。

建议添加分片/粘包/超大帧/断线/握手失败测试，统一拒绝 pending requests、清理连接并支持受控重连；Mock 明确只作测试替身。该线路不是当前自研 CLI 的性能瓶颈，排在执行可靠性之后。

### P2-3：整理项目和战略日志，建立可追溯基准

module_cache 约 64 MB、scratch 约 141 MB、.build 约 127 MB，合计约 332 MB。建议先建立版本管理和 .gitignore，再将截图/运行产物归到按日期命名的 artifacts，缓存归到构建目录；保留需要的历史证据，不直接清空。

日志的“≤2 次工具调用”适合限制普通 GUI 任务中的无效试探，不适合整个项目审计或修复；应改为按任务复杂度、风险和时间预算控制。历史记录保留，新增纠正说明，区分“计划、实现、验证、未验证”。“100% 通过”只表示那组断言通过；“完美复刻”“通用 <1 秒”等结论需要独立基准支持。

## 4. 本轮实际验证结果

| 验证 | 结果 |
| --- | --- |
| 两份 Swift 源码，swiftc -O 输出到临时目录 | 都成功；主引擎 launchApplication 有弃用警告，未替换 bin |
| SDK、测试、Mock、Boost 共 8 份 Python 文件 AST 解析 | 全部通过；只证明语法可解析 |
| python3 tests/test_boost_coordinator.py | 6 组通过，包含 90 次并发写入；不代表任务状态完整正确 |
| MCP tools/list | 13 个工具，与旧测试的 12 冲突 |
| MCP 缺失应用 get_app_state | 返回 success=false 文本，但缺少工具 isError |
| MCP `[]` 输入 | stderr AttributeError，无响应；进程继续处理后续 ping |
| MCP 无 id 的 ping | 返回 id=null 响应 |
| CLI wait(0) 后接未知动作 | exit=1、executed=1、failedIndex=2；没有产生 UI 输入 |
| Boost 重复 start 与未完成使命提交 | 两次领取均成功，使命 completed / 子任务 in_progress |

未运行整套 audit_regression_test.py、test_optimizations.py；未实测 CAD、真实聊天发送、中文 IME、双窗口误点、多显示器、权限拒绝或取消中的输入行为。没有据历史截图宣布这些场景已验证。

## 5. 建议实施顺序

1. 第一批：先建立无副作用回归基线，同时修复窗口/快照寻址、整批预检和 MCP 错误传递。
2. 第二批：动作后置验证、取消与输入队列、剪贴板保护、Boost 租约与状态机。
3. 第三批：安装构建可复现、缓存隔离、总耗时与上下文基准，再决定常驻服务/原生截图改造。
4. 第四批：补基础动作、应用适配、IPC 参考实现测试及目录整理。

每批独立记录相关文件、现象、根因、对策和实际验证结果；本报告中的建议当前均不标记为已实施。
