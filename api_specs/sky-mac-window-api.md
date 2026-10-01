# Sky Window API (macOS)

## API Reference

Use this as the supported `sky` window API surface for macOS:

```ts
import { sky } from "@oai/sky";

const state = await sky.get_app_state({ app: "Weather" });

interface WindowComputerUseClient {
  list_apps(): Promise<Array<ListAppsApp>>; // List apps that can be targeted by the window API.
  get_app_state(input: GetAppStateInput): Promise<AppState>; // Capture the current state, screenshot, and accessibility text for an app window.
  click(input: ClickInput): Promise<void>; // Click either an indexed element from the latest app state or a coordinate in the app window.
  press_key(input: PressKeyInput): Promise<void>; // Press a `+`-separated keyboard chord in an app window.
  type_text(input: TypeTextInput): Promise<void>; // Type text into the current focus in an app window.
  scroll(input: ScrollInput): Promise<void>; // Scroll at either an indexed element from the latest app state or a coordinate in the app window.
  set_value(input: SetValueInput): Promise<void>; // Replace the value of an indexed editable element.
  drag(input: DragInput): Promise<void>; // Drag from one app-window coordinate to another.
  perform_secondary_action(input: PerformSecondaryActionInput): Promise<void>; // Invoke a secondary accessibility action on an indexed element.
  paste(input: PasteInput): Promise<void>; // Paste content into an app window, then restore the previous clipboard contents.
  select_text(input: SelectTextInput): Promise<void>; // Select matching text in an indexed editable element.
  target: "mac";
}

type ListAppsApp = {
  displayName?: string; // User-visible app name when available.
  id: string; // Canonical app id to pass as `app` when targeting a window.
  isRunning?: boolean; // Whether the app currently appears to be running.
  lastUsedDate?: string; // ISO 8601 timestamp for recent app usage when available.
  useCount?: number; // Usage count signal when available.
};

type GetAppStateInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  disableDiff?: boolean; // Return a full accessibility tree instead of a diff from the previous tree.
};

type AppState = {
  app: AppIdentifier; // App identifier for the captured window.
  screenshot: Screenshot | null; // Screenshot captured for the app window.
  text: string; // Accessibility text, prefixed with app-specific guidance on first access when available.
};

type ClickInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  click_count?: number; // Number of clicks to perform.
  element_index?: number; // Element index from the latest `get_app_state()` text.
  mouse_button?: MouseButton; // Mouse button to click.
  x?: number; // X coordinate in the app-window screenshot.
  y?: number; // Y coordinate in the app-window screenshot.
};

type PressKeyInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  key: string; // Key or `+`-separated key chord using X Window System keysym-style names, such as `a`, `space`, `Return`, `Tab`, `Control_L+a`, or `Super_L+d`; whitespace around `+` is ignored, and common aliases such as `Control`, `Ctrl`, `Alt`, and `Shift` are accepted.
};

type TypeTextInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  text: string; // Text to type into the current focus.
};

type ScrollInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  direction: Direction; // Direction to scroll.
  element_index?: number; // Element index from the latest `get_app_state()` text.
  pages?: number; // Number of pages to scroll.
  x?: number; // X coordinate in the app-window screenshot.
  y?: number; // Y coordinate in the app-window screenshot.
};

type SetValueInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  element_index: number; // Element index from the latest `get_app_state()` text.
  value: string; // Replacement value for the editable element.
};

type DragInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  from_x: number; // Starting X coordinate in the app-window screenshot.
  from_y: number; // Starting Y coordinate in the app-window screenshot.
  to_x: number; // Ending X coordinate in the app-window screenshot.
  to_y: number; // Ending Y coordinate in the app-window screenshot.
};

type PerformSecondaryActionInput = {
  action: string; // Accessibility action name to invoke on the element.
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  element_index: number; // Element index from the latest `get_app_state()` text.
};

type PasteInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  format: "text" | "md" | "html"; // Content format: plain text, Markdown, or HTML.
  text: string; // Plain text, HTML, or Markdown content to insert into the current focus.
};

type SelectTextInput = {
  app: AppIdentifier; // App id, display name, process name, or other supported app identifier from `list_apps()`.
  element_index: number; // Element index from the latest `get_app_state()` text.
  prefix?: string; // Optional text immediately before the target text to disambiguate matches.
  selection_type?: SelectTextSelectionType; // Whether to select the text itself or place the cursor before or after it.
  suffix?: string; // Optional text immediately after the target text to disambiguate matches.
  text: string; // Text to locate within the editable element.
};

type AppIdentifier = string;

type Screenshot = {
  url: string; // Screenshot image as a data URL or file:// URL.
};

type MouseButton = "left" | "right" | "middle" | "l" | "r" | "m";

type Direction = "up" | "down" | "left" | "right" | "u" | "d" | "l" | "r";

type SelectTextSelectionType = "text" | "cursor_before" | "cursor_after";
```
