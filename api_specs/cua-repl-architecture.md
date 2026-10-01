# CUA REPL 运行时架构解析

`@oai/cua-repl` 是 Codex Desktop 与 ChatGPT 桌面客户端用来运行计算机使用 (Computer Use) 与浏览器控制的核心 REPL 运行时。

## 架构职责

1. **环境初始化**:
   - 依赖 NodeREPL 原生环境，通过 `instructions/banner.js` 进行引导：
     ```javascript
     await import("@oai/cua/tinyskyAlt");
     ```
   - 读取环境变量：
     - `CUA_REPL_NODE_REPL_PATH`: NodeREPL 可执行文件绝对路径。
     - `CUA_REPL_ENABLED_SURFACES`: 启用的交互界面，值为 `browser`、`computer` 或 `browser,computer`。
     - `SKY_CUA_SERVICE_PATH`: 原生服务路径（`Codex Computer Use.app`）。
     - `NODE_REPL_TRUSTED_SERVICES`: 信任的内部服务映射，例如 `{"sky": "@oai/sky/service"}`。

2. **多平台指示 (Instructions)**:
   - 包含 `instructions/macos/`, `instructions/linux/`, `instructions/windows/`。
   - 分别对应平台通用的：
     - `common.md`
     - `browser.md`
     - `computer.md`
     - `output.md`
   - 根据当前系统的 `process.platform` 动态注入对应的模型指令。

3. **模型交互范式 (Interaction Pattern)**:
   - 全局对象直接注入 `sky` 或 `cua`。
   - 状态持久化：在同一次对话会话中，NodeREPL 全局变量保持常驻。
   - 输出机制：通过 `nodeRepl.write(...)` 输出 AX 结构树文本，通过 `nodeRepl.emitImage(...)` 输出屏幕截图。
   - 差异化 AX 树 (AX Tree Diffing)：默认只传输变更部分（`+` 增加、`-` 移除、`~` 修改），大幅降低 Token 消耗。
