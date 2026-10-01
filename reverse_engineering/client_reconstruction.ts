/**
 * Reconstructed Clean Client for Sky / Computer Use IPC
 * Based on reverse-engineered @oai/sky targets/mac/native-pipe.js & client.js
 */

import * as net from "node:net";
import * as path from "node:path";
import * as os from "node:os";
import {
  JsonRpcRequest,
  JsonRpcResponse,
  RequestEnvelope,
  AppInfo,
  AppStateResult,
  AppAction,
  MouseButtonNum,
  DirectionStr,
  SelectionTypeStr,
} from "./protocol_types";

const MAX_FRAME_SIZE = 8 * 1024 * 1024; // 8MB

export class SkyComputerUseTransportError extends Error {
  constructor(message: string, options?: ErrorOptions) {
    super(message, options);
    this.name = "SkyComputerUseTransportError";
  }
}

export class SkyComputerUseError extends Error {
  public code: number;
  constructor(details: { code: number; message: string }) {
    super(details.message);
    this.name = "SkyComputerUseError";
    this.code = details.code;
  }
}

/**
 * 帧编码：[4 字节 Little-Endian 长度前缀] + [UTF-8 JSON 负载]
 */
export function encodeMessageFrame(jsonString: string): Buffer {
  const payload = Buffer.from(jsonString, "utf8");
  if (payload.length > MAX_FRAME_SIZE) {
    throw new SkyComputerUseTransportError(
      `Sky Computer Use native pipe frame is too large: ${payload.length}`
    );
  }
  const frame = Buffer.alloc(4 + payload.length);
  frame.writeUInt32LE(payload.length, 0);
  payload.copy(frame, 4);
  return frame;
}

/**
 * 帧解码：解析输入缓冲区中的一条或多条完整报文
 */
export function decodeMessageFrames(buffer: Buffer): {
  messages: string[];
  remainingData: Buffer;
} {
  const messages: string[] = [];
  let offset = 0;

  while (buffer.length - offset >= 4) {
    const length = buffer.readUInt32LE(offset);
    if (length > MAX_FRAME_SIZE) {
      throw new SkyComputerUseTransportError(
        `Sky Computer Use native pipe frame is too large: ${length}`
      );
    }
    const totalFrameSize = 4 + length;
    if (buffer.length - offset < totalFrameSize) {
      break;
    }
    const message = buffer.subarray(offset + 4, offset + totalFrameSize).toString("utf8");
    messages.push(message);
    offset += totalFrameSize;
  }

  return {
    messages,
    remainingData: buffer.subarray(offset),
  };
}

/**
 * 传输层管理：UNIX Domain Socket 客户端连接
 */
export class MacNativePipeTransport {
  private socket: net.Socket | null = null;
  private nextId = 1;
  private pendingRequests = new Map<
    number,
    { resolve: (val: any) => void; reject: (err: any) => void; timer: NodeJS.Timeout }
  >();
  private buffer = Buffer.alloc(0);

  constructor(socket: net.Socket) {
    this.socket = socket;

    socket.on("data", (chunk: Buffer) => {
      this.buffer = Buffer.concat([this.buffer, chunk]);
      const { messages, remainingData } = decodeMessageFrames(this.buffer);
      this.buffer = remainingData;

      for (const rawMsg of messages) {
        try {
          const resp: JsonRpcResponse = JSON.parse(rawMsg);
          const pending = this.pendingRequests.get(resp.id);
          if (pending) {
            clearTimeout(pending.timer);
            this.pendingRequests.delete(resp.id);
            if (resp.error) {
              pending.reject(new SkyComputerUseError(resp.error));
            } else {
              pending.resolve(resp.result);
            }
          }
        } catch (e) {
          console.error("Failed to parse JSON-RPC response:", e);
        }
      }
    });

    socket.on("close", () => {
      this.rejectAllPending(new SkyComputerUseTransportError("Socket closed"));
      this.socket = null;
    });

    socket.on("error", (err) => {
      this.rejectAllPending(err);
    });
  }

  private rejectAllPending(err: Error) {
    for (const [, req] of this.pendingRequests) {
      clearTimeout(req.timer);
      req.reject(err);
    }
    this.pendingRequests.clear();
  }

  public static async connect(
    socketPath?: string,
    timeoutMs = 5000
  ): Promise<MacNativePipeTransport> {
    const defaultPath =
      process.env.SKY_CUA_SERVICE_NATIVE_PIPE_PATH ??
      path.join(
        os.homedir(),
        "Library",
        "Group Containers",
        "2DC432GLL2.com.openai.sky.CUAService",
        "IPC",
        "computeruse.sock"
      );

    const targetPath = socketPath ?? defaultPath;

    return new Promise((resolve, reject) => {
      const socket = net.createConnection(targetPath);
      const timer = setTimeout(() => {
        socket.destroy();
        reject(
          new SkyComputerUseTransportError(
            `Connection to ${targetPath} timed out after ${timeoutMs}ms`
          )
        );
      }, timeoutMs);

      socket.on("connect", () => {
        clearTimeout(timer);
        resolve(new MacNativePipeTransport(socket));
      });

      socket.on("error", (err) => {
        clearTimeout(timer);
        reject(err);
      });
    });
  }

  public async request<T = any>(
    method: string,
    params: any,
    timeoutMs = 30000
  ): Promise<T> {
    if (!this.socket) {
      throw new SkyComputerUseTransportError("Socket is not connected");
    }

    const id = this.nextId++;
    const rpcReq: JsonRpcRequest = {
      id,
      jsonrpc: "2.0",
      method: method as any,
      params,
    };

    const frame = encodeMessageFrame(JSON.stringify(rpcReq));

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingRequests.delete(id);
        reject(
          new SkyComputerUseTransportError(
            `Request ${method} (id=${id}) timed out after ${timeoutMs}ms`
          )
        );
      }, timeoutMs);

      this.pendingRequests.set(id, { resolve, reject, timer });
      this.socket!.write(frame);
    });
  }

  public close() {
    if (this.socket) {
      this.socket.end();
      this.socket = null;
    }
  }
}

/**
 * 高级客户端：封装应用状态与操作接口
 */
export class ReconstructedMacComputerUseClient {
  private transport: MacNativePipeTransport | null = null;
  private apiVersion = "CodexComputerUseIPC-5";

  constructor(private socketPath?: string) {}

  public async getTransport(): Promise<MacNativePipeTransport> {
    if (!this.transport) {
      this.transport = await MacNativePipeTransport.connect(this.socketPath);
      // 握手校验
      const pingResult = await this.transport.request<{ serverApiVersion: string }>(
        "ping",
        { clientApiVersion: this.apiVersion }
      );
      if (pingResult.serverApiVersion !== this.apiVersion) {
        throw new SkyComputerUseTransportError(
          `Version mismatch: client=${this.apiVersion} server=${pingResult.serverApiVersion}`
        );
      }
    }
    return this.transport;
  }

  private async sendRequest<T = any>(
    requestType: string,
    requestPayload: any,
    timeoutSeconds = 60
  ): Promise<T> {
    const transport = await this.getTransport();
    const envelope: RequestEnvelope = {
      clientApiVersion: this.apiVersion,
      deadlineUnixMilliseconds: Date.now() + timeoutSeconds * 1000,
      requestType,
      request: requestPayload,
    };
    return transport.request<T>("request", envelope, timeoutSeconds * 1000);
  }

  public async listApps(): Promise<AppInfo[]> {
    return this.sendRequest<AppInfo[]>("ComputerUseIPCListAppsRequest", {});
  }

  public async getAppState(app: string, disableDiff = false): Promise<AppStateResult> {
    return this.sendRequest<AppStateResult>("ComputerUseIPCAppGetSkyshotRequest", {
      app,
      disableDiff,
    });
  }

  public async performAction(app: string, action: AppAction): Promise<void> {
    return this.sendRequest<void>("ComputerUseIPCAppPerformActionRequest", {
      app,
      action,
    });
  }

  public async click(params: {
    app: string;
    elementIndex?: number;
    x?: number;
    y?: number;
    mouseButton?: "left" | "right" | "middle" | 0 | 1 | 2;
    clickCount?: number;
  }): Promise<void> {
    let mb: MouseButtonNum = 0;
    if (params.mouseButton === "right" || params.mouseButton === 1) mb = 1;
    if (params.mouseButton === "middle" || params.mouseButton === 2) mb = 2;

    const at =
      params.elementIndex !== undefined
        ? { elementID: { _0: String(params.elementIndex) } }
        : { coordinate: { _0: [params.x ?? 0, params.y ?? 0] as [number, number] } };

    return this.performAction(params.app, {
      click: {
        at,
        clickCount: params.clickCount ?? 1,
        mouseButton: mb,
      },
    });
  }

  public async typeText(params: { app: string; text: string }): Promise<void> {
    return this.performAction(params.app, {
      type: { _0: params.text },
    });
  }

  public async pressKey(params: { app: string; key: string }): Promise<void> {
    return this.performAction(params.app, {
      pressKey: { _0: params.key },
    });
  }

  public async setValue(params: {
    app: string;
    elementIndex: number;
    value: string;
  }): Promise<void> {
    return this.performAction(params.app, {
      setValue: {
        elementID: String(params.elementIndex),
        value: params.value,
      },
    });
  }

  public async scroll(params: {
    app: string;
    elementIndex?: number;
    x?: number;
    y?: number;
    direction: DirectionStr;
    pages?: number;
  }): Promise<void> {
    const at =
      params.elementIndex !== undefined
        ? { elementID: { _0: String(params.elementIndex) } }
        : { coordinate: { _0: [params.x ?? 0, params.y ?? 0] as [number, number] } };

    return this.performAction(params.app, {
      scroll: {
        at,
        direction: params.direction,
        pages: params.pages ?? 1,
      },
    });
  }

  public async paste(params: {
    app: string;
    text: string;
    format: "text" | "md" | "html";
  }): Promise<void> {
    return this.performAction(params.app, {
      paste: {
        text: params.text,
        format: params.format,
      },
    });
  }
}
