/**
 * Reverse-Engineered TypeScript Definitions for OpenAI Sky / Computer Use IPC Protocol
 */

export interface JsonRpcRequest<T = any> {
  id: number;
  jsonrpc: "2.0";
  method: "ping" | "request" | "ensureService";
  params: T;
}

export interface JsonRpcResponse<T = any> {
  id: number;
  jsonrpc: "2.0";
  result?: T;
  error?: {
    code: number;
    message: string;
  };
}

export interface PingParams {
  clientApiVersion: string;
}

export interface PingResult {
  serverApiVersion: string;
}

export interface RequestEnvelope<T = any> {
  clientApiVersion: string;
  codexTurnMetadata?: Record<string, any>;
  deadlineUnixMilliseconds: number;
  requestType: string;
  request: T;
}

export type ComputerUseRequestType =
  | "ComputerUseIPCListAppsRequest"
  | "ComputerUseIPCAppStartRequest"
  | "ComputerUseIPCAppGetSkyshotRequest"
  | "ComputerUseIPCAppPerformActionRequest"
  | "ComputerUseIPCAppPolicyRequest"
  | "ComputerUseIPCStartAudioRecordingRequest"
  | "ComputerUseIPCStopAudioRecordingRequest";

export interface ListAppsRequest {}

export interface AppInfo {
  id: string;
  displayName?: string;
  lastUsedDate?: string;
  useCount?: number;
  isRunning?: boolean;
}

export interface AppStartRequest {
  app: string;
}

export interface AppGetSkyshotRequest {
  app: string;
  disableDiff?: boolean;
}

export interface AppScreenshot {
  url: string;
}

export interface AppStateResult {
  app: string;
  screenshot: AppScreenshot | null;
  text: string;
}

export type MouseButtonNum = 0 | 1 | 2; // 0 = left, 1 = right, 2 = middle
export type DirectionStr = "up" | "down" | "left" | "right";
export type SelectionTypeStr = "text" | "cursor_before" | "cursor_after";

export interface ActionClick {
  click: {
    at: { coordinate: { _0: [number, number] } } | { elementID: { _0: string } };
    clickCount: number;
    mouseButton: MouseButtonNum;
  };
}

export interface ActionDrag {
  drag: {
    from: [number, number];
    to: [number, number];
  };
}

export interface ActionPaste {
  paste: {
    text: string;
    format: "text" | "md" | "html";
  };
}

export interface ActionPerformSecondary {
  performSecondaryAction: {
    action: string;
    elementID: string;
  };
}

export interface ActionPressKey {
  pressKey: {
    _0: string;
  };
}

export interface ActionScroll {
  scroll: {
    at: { coordinate: { _0: [number, number] } } | { elementID: { _0: string } };
    direction: DirectionStr;
    pages: number;
  };
}

export interface ActionSetValue {
  setValue: {
    elementID: string;
    value: string;
  };
}

export interface ActionSelectText {
  selectText: {
    elementID: string;
    text: string;
    prefix?: string;
    suffix?: string;
    selection: SelectionTypeStr;
  };
}

export interface ActionTypeText {
  type: {
    _0: string;
  };
}

export type AppAction =
  | ActionClick
  | ActionDrag
  | ActionPaste
  | ActionPerformSecondary
  | ActionPressKey
  | ActionScroll
  | ActionSetValue
  | ActionSelectText
  | ActionTypeText;

export interface AppPerformActionRequest {
  app: string;
  action: AppAction;
}
