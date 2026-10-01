# OpenAI Codex / Sky Computer Use macOS IPC 协议逆向全景规范

## 一、 通信传输层机制 (Transport Layer)

OpenAI Codex Desktop 与 ChatGPT macOS 客户端的 Computer Use 模块采用 **UNIX Domain Socket (UDS)** 进行低延迟、高安全性的进程间通信 (IPC)。

### 1. 套接字路径 (Socket Path)
- **默认路径**：
  `~/Library/Group Containers/2DC432GLL2.com.openai.sky.CUAService/IPC/computeruse.sock`
- **环境变量覆盖**：
  - `SKY_CUA_SERVICE_NATIVE_PIPE_PATH`：显式指定 Socket 路径。
  - `NODE_REPL_HOST_SERVICES_PIPE_PATH`：宿主服务代理管道（如 ChatGPT App 内部转发）。

### 2. 二进制分帧格式 (Frame Protocol)
管道数据流采用**定长前缀包头**机制：
```
+--------------------------+------------------------------------------+
|  4-byte Payload Length   |              JSON Payload                |
|       (uint32_le)        |             (UTF-8 Encoded)              |
+--------------------------+------------------------------------------+
```
- **前 4 字节**：Little-Endian 32 位无符号整型 (`uint32LE`)，表示后续 JSON 报文的字节长度。
- **最大包限制**：`8,388,608` 字节 (8 MB)，超过则抛出 `SkyComputerUseTransportError`。
- **后续字节**：标准 UTF-8 编码的 JSON-RPC 2.0 字符串。

---

## 二、 协议层规范 (JSON-RPC 2.0 Protocol)

所有通信均遵循 JSON-RPC 2.0 格式。

### 1. 握手与保活 (Handshake / Ping)
客户端在初次建立连接时，会先发送 `ping` 请求以校验协议版本：

**请求报文**：
```json
{
  "id": 1,
  "jsonrpc": "2.0",
  "method": "ping",
  "params": {
    "clientApiVersion": "CodexComputerUseIPC-5"
  }
}
```

**响应报文**：
```json
{
  "id": 1,
  "jsonrpc": "2.0",
  "result": {
    "serverApiVersion": "CodexComputerUseIPC-5"
  }
}
```
*注：若服务端返回的 `serverApiVersion` 与客户端不一致，则抛出版本不兼容异常。*

### 2. 核心通用请求报文结构 (Envelope)
客户端通过 `method: "request"` 发送具体操作：
```json
{
  "id": 2,
  "jsonrpc": "2.0",
  "method": "request",
  "params": {
    "clientApiVersion": "CodexComputerUseIPC-5",
    "codexTurnMetadata": {
      "turn_id": "...",
      "session_id": "..."
    },
    "deadlineUnixMilliseconds": 1785420000000,
    "requestType": "ComputerUseIPCAppPerformActionRequest",
    "request": { ... }
  }
}
```

---

## 三、 关键请求类型 (Request Types) 详解

### 1. 获取应用列表 (`ComputerUseIPCListAppsRequest`)
- **requestType**: `"ComputerUseIPCListAppsRequest"`
- **request**: `{}`
- **返回结果**:
  ```json
  [
    {
      "id": "com.google.Chrome",
      "displayName": "Google Chrome",
      "isRunning": true,
      "lastUsedDate": "2026-09-15T12:00:00Z",
      "useCount": 42
    }
  ]
  ```

### 2. 启动应用 (`ComputerUseIPCAppStartRequest`)
- **requestType**: `"ComputerUseIPCAppStartRequest"`
- **request**:
  ```json
  {
    "app": "com.google.Chrome"
  }
  ```

### 3. 获取应用界面状态与截图 (`ComputerUseIPCAppGetSkyshotRequest`)
- **requestType**: `"ComputerUseIPCAppGetSkyshotRequest"`
- **request**:
  ```json
  {
    "app": "com.google.Chrome",
    "disableDiff": false
  }
  ```
- **返回结果**:
  ```json
  {
    "app": "com.google.Chrome",
    "screenshot": {
      "url": "file:///tmp/skyshot_cache/12345.png"
    },
    "text": "AXWindow: Chrome\n  AXToolbar\n    [42] AXTextField: Address and search bar (value: 'openai.com')\n    [43] AXButton: Reload"
  }
  ```
  - `disableDiff` 为 `false` 时，返回紧凑的 AX Tree Diff：`+` 代表新增节点，`-` 代表移除节点，`~` 代表状态或文本变更。

### 4. 执行界面动作 (`ComputerUseIPCAppPerformActionRequest`)
- **requestType**: `"ComputerUseIPCAppPerformActionRequest"`
- **request 封装**:
  ```json
  {
    "app": "com.google.Chrome",
    "action": { ... }
  }
  ```

具体支持的 `action` 动作表：

| 动作名称 | JSON 结构示例 | 说明 |
| :--- | :--- | :--- |
| **点击 (click)** | `{"click": {"at": {"elementID": {"_0": "42"}}, "clickCount": 1, "mouseButton": 0}}` 或 `{"click": {"at": {"coordinate": {"_0": [150, 200]}}, "clickCount": 1, "mouseButton": 0}}` | 优先通过 elementID 定位，兜底支持屏幕坐标。`mouseButton`: 0=left, 1=right, 2=middle |
| **拖拽 (drag)** | `{"drag": {"from": [100, 100], "to": [300, 300]}}` | 连续坐标拖动 |
| **键盘输入 (type)** | `{"type": {"_0": "hello world"}}` | 文本键入 |
| **按键/快捷键 (pressKey)** | `{"pressKey": {"_0": "Return"}}` 或 `{"pressKey": {"_0": "super+c"}}` | 支持 xdotool 命名规范与组合键 |
| **滚动 (scroll)** | `{"scroll": {"at": {"elementID": {"_0": "42"}}, "direction": "down", "pages": 1}}` | 方向支持: `up`, `down`, `left`, `right` |
| **设值 (setValue)** | `{"setValue": {"elementID": "42", "value": "openai.com"}}` | 直接通过 AX 接口设置文本框内容 |
| **文本选取 (selectText)** | `{"selectText": {"elementID": "42", "text": "test", "selection": "text"}}` | 支持 `text`, `cursor_before`, `cursor_after` |
| **粘贴 (paste)** | `{"paste": {"text": "<b>demo</b>", "format": "html"}}` | 格式支持 `text`, `md`, `html`，自动保护并恢复系统剪贴板 |
| **辅助操作 (performSecondaryAction)** | `{"performSecondaryAction": {"action": "Show Menu", "elementID": "42"}}` | 执行无障碍节点声明的二级操作 |

---

## 四、 安全控制与策略拦截 (`ComputerUseIPCAppPolicyRequest`)
在执行对敏感应用的控制前，服务端会校验 `sessions/*.toml` 允许的应用白名单配置：
```toml
[apps]
allowed = ["com.apple.finder", "com.google.Chrome"]
```
若目标应用未授权，原生层守护服务会通过 `CUALockScreenGuardian` 弹窗拦截，向用户请求授权。
