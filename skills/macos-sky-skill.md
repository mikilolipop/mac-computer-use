---
name: macos-sky
description: Control local Mac apps through @oai/sky. Use for tasks that require reading or operating app UI by clicking, typing, selecting text, scrolling, dragging, pressing keys, or setting values.
---

# macOS Sky Computer Use Guide

## node_repl + @oai/sky (Computer Use)

- Use `node_repl` (JavaScript) for all Computer Use actions.
- Do not use AppleScript, `osascript`, JXA, or System Events scripting for app interaction.
- `node_repl` state is persistent across calls.
- For text output, use `nodeRepl.write(...)`. `nodeRepl.write(...)` takes a string. If you would like to read a whole object, wrap with `JSON.stringify(...)`.

## API Surface

```typescript
type Sky = {
  click: (args: { app: string, element_index?: number, x?: number, y?: number, mouse_button?: MouseButton, click_count?: number }) => Promise<void>;
  drag: (args: { app: string, from_x: number, from_y: number, to_x: number, to_y: number }) => Promise<void>;
  get_app_state: (args: { app: string, disableDiff?: boolean }) => Promise<AppState>;
  list_apps: () => Promise<Array<App>>;
  paste: (args: { app: string, text: string, format: "text" | "md" | "html" }) => Promise<void>;
  perform_secondary_action: (args: { app: string, element_index: number, action: string }) => Promise<void>;
  press_key: (args: { app: string, key: string }) => Promise<void>;
  scroll: (args: { app: string, element_index?: number, x?: number, y?: number, direction: Direction, pages?: number }) => Promise<void>;
  select_text: (args: { app: string, element_index: number, text: string, prefix?: string, suffix?: string, selection_type?: SelectionType }) => Promise<void>;
  set_value: (args: { app: string, element_index: number, value: string }) => Promise<void>;
  type_text: (args: { app: string, text: string }) => Promise<void>;
};

type App = {
  id: string;
  displayName?: string;
  lastUsedDate?: string;
  useCount?: number;
  isRunning?: boolean;
};

type AppState = {
  app: string;
  screenshot: Screenshot | null;
  text: string;
};

type Screenshot = {
  url: string;
};

type Direction = "up" | "down" | "left" | "right" | "u" | "d" | "l" | "r";
type SelectionType = "text" | "cursor_before" | "cursor_after";
type MouseButton = "left" | "right" | "middle" | "l" | "r" | "m";
```

## Workflow

### 1. Initialize

Start by importing the package API and then getting the state for the app you want to use, like this:

```javascript
var sky = (globalThis.sky ??= (await import("@oai/sky")).sky);
var state = await sky.get_app_state({ app: "com.google.Chrome" });
nodeRepl.write(state.text); // This will return the accessibility tree
```

If you already know the app's bundle identifier or app name, reference it directly. If it's unclear which app to use, start by listing the available apps:

```javascript
var sky = (globalThis.sky ??= (await import("@oai/sky")).sky);
var apps = await sky.list_apps();
nodeRepl.write(JSON.stringify(apps));
```

After performing one or more UI actions, call `get_app_state(...)` before deciding what to do next. This keeps you in the current UI state and forces you to re-derive fresh `element_index` values from the latest accessibility text instead of reusing stale ones.

For token efficiency, when appropriate, the accessibility tree will be returned as a diff from the most previous accessibility tree, listing only the elements that were removed, added, or changed. Prefer this default diff output; pass true for `disableDiff` only when you need a fresh full accessibility tree.

### 2. Actions using app

Perform one or more actions, and then fetch the latest state:

```javascript
await sky.click({ app: "Google Chrome", element_index: 42 });
await sky.set_value({ app: "Google Chrome", element_index: 42, value: "openai.com" });
await sky.press_key({ app: "Google Chrome", key: "Return" });
await sky.type_text({ app: "Google Chrome", text: "hello" });
await sky.scroll({ app: "Google Chrome", element_index: 42, direction: "down", pages: 1 });
await sky.select_text({ app: "Google Chrome", element_index: 42, text: "hello" });
await sky.perform_secondary_action({
  app: "Google Chrome",
  element_index: 42,
  action: "Show Menu",
});
nodeRepl.write((await sky.get_app_state({ app: "Google Chrome" })).text);
```

Or you can use the bundle id instead of the name:

```javascript
await sky.click({ app: "com.google.Chrome", element_index: 42 });
```

### Notes & Best Practices

- Prefer `element_index`-based actions over coordinate actions whenever an accessibility element is available. If AX actions are not available or not working, fall back to using screenshots and coordinate clicks.
- If the UI is not behaving as expected, try fetching the latest `get_app_state(...)` to make sure you have the latest context.
- Prefer using accessibility text over screenshots for efficiency, but if the interface is not fully working or not providing enough context, fetch a screenshot. The accessibility interface may be incomplete in some applications (like Electron canvas or games), so a screenshot helps fully understand what's going on.
- `perform_secondary_action` is for invoking an accessibility action that an element exposes besides a normal click, such as expanding a disclosure row, showing a menu, incrementing a control, or cancelling something. It requires an action actually exposed for that element in the accessibility text.
- `select_text` selects matching text in an editable element.
- `press_key` presses a key or key combination (xdotool style syntax, e.g., `"Return"`, `"super+c"`, `"Tab"`).
- No need to manually open or launch apps; `get_app_state` transparently launches the app in the background if it's not already running.
- If an action or `get_app_state(...)` fails with an app display name, immediately retry with the app's bundle identifier.
