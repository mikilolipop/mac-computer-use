# OpenAI Codex / Sky Computer Use 逆向分析与复刻全景指南

> **2026-09-27 实现更新**：当前自研接口、迁移方式、测试结果和未完成项见 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)。下文保留历史逆向说明及早期性能记录，不作为当前通用性能承诺。编号操作现在需要快照；自研启动入口是 `python3 -m sdk.mcp_server`。


本项目对本地系统中由 **OpenAI Codex Desktop / ChatGPT macOS 客户端** 驱动的 **Computer Use** 完整技术链路进行了逆向工程与深度解构，并将所有插件规范、Skills、跨平台 API 规范、底层 IPC 协议以及重构客户端代码归档至此。

---

## 目录索引

- [一、 本地系统关键文件定位](#一-本地系统关键文件定位)
- [二、 核心架构全景图](#二-核心架构全景图)
- [三、 各层级核心机制深度剖析](#三-各层级核心机制深度剖析)
  - [1. 提示词与 Skill 规范层](#1-提示词与-skill-规范层)
  - [2. 客户端 SDK 与 REPL 运行时](#2-客户端-sdk-与-repl-运行时)
  - [3. 底层 IPC 进程间通信协议](#3-底层-ipc-进程间通信协议)
  - [4. macOS 原生服务层 (SkyComputerUseService)](#4-macos-原生服务层-skycomputeruseservice)
  - [5. MCP 服务桥接模式](#5-mcp-服务桥接模式)
  - [6. 工作流录制与技能自生长 (Record & Replay)](#6-工作流录制与技能自生长-record--replay)
- [四、 本复刻工程文件结构说明](#四-本复刻工程文件结构说明)
- [五、 如何基于本项目进行独立复刻与测试](#五-如何基于本项目进行独立复刻与测试)

---

## 一、 本地系统关键文件定位

在本地机器上，OpenAI 的 Computer Use 体系分布在以下四个核心位置：

1. **Codex 官方捆绑插件目录**：
   - 路径：`~/.codex/plugins/cache/openai-bundled/computer-use/1.0.1000968/`
   - 包含：`.codex-plugin/plugin.json`、`skills/computer-use/SKILL.md`、`.mcp.json`、`bin/computer-use-client-launcher`。
2. **Codex 原生服务与运行配置**：
   - 路径：`~/.codex/computer-use/`
   - 包含：`Codex Computer Use.app`（原生守护服务）、`config.json`（本地化文案与高亮色）、`sessions/*.toml`（授权应用白名单）。
3. **全局配置文件**：
   - 路径：`~/.codex/config.toml`
   - 包含：`[plugins."computer-use@openai-bundled"]`、`[mcp_servers.node_repl]`、`[mcp_servers.computer-use]` 等环境注入项。
4. **ChatGPT 桌面内置 CUA Node 运行时与 @oai SDK 库**：
   - 路径：`/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/@oai/`
   - 包含：
     - `@oai/sky`: 原生 Computer Use 客户端实现、全平台 API 规范（`sky-full-desktop-api.md`, `sky-window-api.md`, `sky-window2-api.md`）及反混淆前源码。
     - `@oai/cua`: 统一跨端控制层（`tinyskyAlt`）。
     - `@oai/cua-repl`: 多合一 REPL 引导程序与分平台执行指南。

---

## 二、 核心架构全景图

```mermaid
graph TD
    subgraph Agent / Codex 运行时
        A[ChatGPT / Codex LLM] -->|提示词引导| B[Skill 规范 / Confirmations Policy]
        B -->|执行脚本| C[node_repl 运行时]
        C -->|引入| D[@oai/sky SDK]
    end

    subgraph 进程间通信 IPC
        D -->|UNIX Domain Socket| E[computeruse.sock]
        E -->|二进制分帧: uint32LE + JSON-RPC 2.0| F[IPC 消息派发器]
    end

    subgraph macOS 原生守护进程: Codex Computer Use.app
        F --> G[SkyComputerUseService 核心服务]
        G --> H[CUALockScreenGuardian 锁屏守卫]
        G --> I[macOS Accessibility API (AXUIElement 树)]
        G --> J[ScreenCaptureKit / CoreGraphics 屏幕截图]
        G --> K[CGEvent 虚拟键鼠驱动]
    end

    subgraph 外部扩展机制
        L[SkyComputerUseClient] -->|mcp 参数| M[独立 MCP Server 接口]
        N[Record & Replay 插件] -->|录制用户操作流| O[自动逆向生成新 Skill]
    end
```

---

## 三、 各层级核心机制深度剖析

### 1. 提示词与 Skill 规范层
- **核心理念**：优先依赖语义化的无障碍树节点（`element_index`），仅在无障碍树失效时降级为“坐标点击 + 屏幕截图”。
- **AX 增量差异树 (Tree Diffing)**：
  - 默认调用 `sky.get_app_state({ app })` 时，只返回相比上一帧发生变动的节点：
    - `+`：新增 DOM/AX 节点
    - `-`：移除节点
    - `~`：属性变更（如文本更新、焦点改变）
  - 极大节约了视觉大模型每次交互所消耗的 Context Token。
- **安全拦截政策 (Confirmation Policy)**：
  - 划分 4 级权限策略：完全放行（无需确认）、预授权（Prompt 明确提及即可）、强交互阻塞确认（删除数据、资金交易、系统设置变更、执行新软件等）、完全交还人工（修改密码、绕过安全屏障）。

### 2. 客户端 SDK 与 REPL 运行时
- **运行时注入**：全局单例 `globalThis.sky`。
- **核心 API 概览**：
  - `sky.get_app_state({ app, disableDiff? })`: 获取应用界面 AX 树及可选截屏路径。
  - `sky.click({ app, element_index, x, y, mouse_button, click_count })`: 智能点击。
  - `sky.type_text({ app, text })`: 模拟键盘输入。
  - `sky.set_value({ app, element_index, value })`: 无障碍属性直接注入（无需聚焦输入）。
  - `sky.press_key({ app, key })`: 支持 `xdotool` 格式按键（如 `"super+c"`, `"Return"`, `"Tab"`）。
  - `sky.scroll({ app, element_index, direction, pages })`: 页面滚动。
  - `sky.paste({ app, text, format })`: 支持富文本粘贴（`text`, `md`, `html`），操作后自动还原用户原有剪贴板。

### 3. 底层 IPC 进程间通信协议
- **通信介质**：UNIX Domain Socket（`~/Library/Group Containers/2DC432GLL2.com.openai.sky.CUAService/IPC/computeruse.sock`）。
- **数据帧 (Frame Format)**：
  - `[0..3] 字节`: `uint32LE`（小端 4 字节整数），表示后续负载长度。
  - `[4..N] 字节`: JSON-RPC 2.0 字符串（UTF-8）。
- **方法集**：
  - `ping`: 协议版本协商（当前版本为 `CodexComputerUseIPC-5`）。
  - `request`: 业务操作封装，核心请求类型包括：
    - `ComputerUseIPCListAppsRequest`: 枚举系统应用及运行状态。
    - `ComputerUseIPCAppStartRequest`: 启动指定应用。
    - `ComputerUseIPCAppGetSkyshotRequest`: 抓取 AX 树与屏幕图像。
    - `ComputerUseIPCAppPerformActionRequest`: 发起键鼠与辅助功能动作。

### 4. macOS 原生服务层 (SkyComputerUseService)
- **工程框架**：基于 Swift 5 与 Bazel 构建，依赖内部的 `@cua_package//:ComputerUse`、`@cua_package//:SlimCore` 与 `Protobuf`。
- **权限需求**：
  - `AXIsProcessTrusted`（辅助功能权限）：遍历和操作应用 UI 树。
  - `CGRequestScreenCaptureAccess`（屏幕录制权限）：捕获窗口图像。
- **安全保护**：集成 `CUALockScreenGuardian`，在屏幕锁定状态下自动熔断所有自动化指令。

### 5. MCP 服务桥接模式
- OpenAI 将原生客户端 `SkyComputerUseClient` 编译为一个通用命令行程序。当以 `SkyComputerUseClient mcp` 启动时，它会自动转换为标准 Model Context Protocol (MCP) 服务器，供任何支持 MCP 的宿主直接操控。

### 6. 工作流录制与技能自生长 (Record & Replay)
- 系统内置 `record-and-replay` 插件。
- 允许人类用户亲自在 macOS 上演示操作，底层捕获全量事件流（AX 焦点、键盘、鼠标轨迹），由 LLM 分析提炼出可泛化参数的输入，并直接自动生成符合规范的 `SKILL.md`。

---

## 四、 本复刻工程文件结构说明

```
.
├── README.md                                  # 本文档：架构逆向全景解析
├── strategy_log.md                            # 本地避坑日志（永久行为准则与排错记录）
│
├── plugin/                                    # 提取自 ~/.codex 的官方插件完整包
│   ├── .codex-plugin/
│   │   ├── plugin.json                        # 插件元数据与交互声明
│   │   └── computer-use-node-repl.md          # 插件说明文档
│   ├── .mcp.json                              # MCP 启动配置（指向 launcher 脚本）
│   ├── bin/
│   │   └── computer-use-client-launcher       # 自动寻找原生服务的启动脚本
│   └── skills/
│       └── computer-use/
│           └── SKILL.md                       # 核心 Skill 完整规范（含确认安全策略）
│
├── skills/                                    # 提取与梳理的核心 Skills
│   ├── computer-use-skill.md                  # 核心 Computer Use Skill
│   ├── macos-sky-skill.md                     # @oai/sky macOS 专属引导指南
│   └── record-and-replay-skill.md             # Record & Replay 动作录制转技能指南
│
├── api_specs/                                 # 跨平台官方 API 接口定义（TypeScript）
│   ├── sky-mac-window-api.md                  # macOS 窗口与应用操作 API
│   ├── sky-full-desktop-api.md                # 完整桌面操作 API (Linux/全屏)
│   ├── sky-windows-window2-api.md             # Windows 窗口操作 API
│   └── cua-repl-architecture.md               # CUA REPL 架构与多平台支持机制
│
├── reverse_engineering/                       # 逆向重构代码与详细技术规格
│   ├── ipc_protocol.md                        # UDS 协议与报文格式深度分析
│   ├── native_architecture.md                 # macOS 原生服务 (SkyComputerUseService) 架构
│   ├── protocol_types.ts                      # 完整 TypeScript 类型契约
│   ├── client_reconstruction.ts               # 反混淆、解耦后纯净可用的 TS/Node.js 客户端实现
│   └── mock_computer_use_daemon.py            # 离线自测 Python Mock 守护进程
│
└── config/                                    # 提取的配置模板
    ├── codex_config_snippet.toml              # Codex config.toml 关键配置段
    └── computer_use_config.json               # 本地语言与 UI 配置
```

---

## 五、 如何基于本项目进行独立复刻与测试

### 1. 本地免依赖离线联调 (Mock 模式)
我们编写了 `reverse_engineering/mock_computer_use_daemon.py`，它完全兼容原生协议分帧与 JSON-RPC 2.0 格式：

1. **启动 Mock 守护服务端**：
   ```bash
   python3 reverse_engineering/mock_computer_use_daemon.py
   ```
   它会在 `/tmp/mock_computeruse.sock` 上建立监听。

2. **运行测试客户端**：
   在任何 TypeScript / Node.js 脚本中使用 `client_reconstruction.ts`：
   ```typescript
   import { ReconstructedMacComputerUseClient } from "./reverse_engineering/client_reconstruction";

   const client = new ReconstructedMacComputerUseClient("/tmp/mock_computeruse.sock");
   const apps = await client.listApps();
   console.log("Apps:", apps);

   const state = await client.getAppState("Google Chrome");
   console.log("AX Tree:\n", state.text);
   ```

### 2. 真实对接 macOS 系统
若要连接系统正在运行的 `SkyComputerUseService` 原生守护进程：
1. 确保已开启 macOS 辅助功能权限与屏幕录制权限。
2. 保持客户端默认套接字路径连接：
   `~/Library/Group Containers/2DC432GLL2.com.openai.sky.CUAService/IPC/computeruse.sock`
3. 即可直接发起真实的窗口控制、截屏与自动化交互！

---

## 六、 本工程自主落地：原生 Swift 丝滑 CUA 引擎 (`bin/mac-cua`)

为了彻底解决外部 Shell 脚本模拟带来的生硬、延迟、频繁权限弹窗问题，我们在本项目中实现了一套**真正原生级、毫秒响应、零外部依赖**的 macOS Computer Use 引擎：

### 1. 核心组件分布
- **`native_engine/mac_cua_engine.swift`**：基于 Swift 5 与 `ApplicationServices`、`CoreGraphics`、`AppKit` 编写的高性能引擎。
- **`bin/mac-cua`**：使用 `swiftc -O` 编译生成的独立 ARM64 原生 Mach-O 二进制文件。
- **`sdk/cua_client.py`**：面向 Python 开发者的简洁 SDK 客户端。
- **`sdk/mcp_server.py`**：标准 Model Context Protocol (MCP) stdio 服务端，可直接挂载进 Claude、Cursor、Antigravity 等任意 AI 宿主。

### 2. 实测性能对比矩阵

| 指标 | 传统 Shell 模拟 (open/osascript) | 本工程原生 Swift 引擎 (bin/mac-cua) | 体验提升 |
| :--- | :--- | :--- | :--- |
| **应用状态与控件定位** | 盲猜/无状态（无法获取控件树） | **AXUIElement 语义树毫秒级遍历** | 彻底摆脱盲猜 |
| **状态同步开销** | 每次必须截取 4K 全屏（数 MB 图像） | **AXTree 增量 Diff（仅几十字节文本）** | Token 与传输消耗降低 98% |
| **窗口截屏纯净度** | 截取全桌面（包含终端窗与菜单栏） | **定向 Window 边界纯净捕获** | 隐私保护与精准画布裁剪 |
| **文本输入速度** | 逐字模拟敲击（慢、易丢字） | **AXValueAttribute 瞬时注入 (<10ms)** | 瞬间填充地址栏与长文本 |
| **用户打扰度** | 频繁弹窗、抢占前台焦点 | **后台定向操作、无感静默执行** | 达到 Codex 级丝滑质感 |

### 3. 极速上手使用示例

#### 命令行调用：
```bash
# 1. 枚举活跃应用
./bin/mac-cua list-apps

# 2. 毫秒获取 Edge 状态与增量 Diff
./bin/mac-cua state --app "Microsoft Edge" --diff

# 3. 无痕秒级注入 URL
./bin/mac-cua set-value --app "Microsoft Edge" --element 9 --value "https://www.tradingview.com"
./bin/mac-cua press-key --key "return"
```

#### Python SDK 调用：
```python
from sdk.cua_client import CuaClient

client = CuaClient()
# 获取应用状态
state = client.get_state("Microsoft Edge", diff=True)
print("控件数:", state["elementCount"])
print("增量变化:", state["diff"])

# 瞬时给地址栏注入值并跳转
client.set_value("Microsoft Edge", element_index=9, value="https://www.tradingview.com")
client.press_key("return")
```

