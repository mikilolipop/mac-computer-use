---
name: mac-computer-use
description: Use the local macOS AX/OCR engine for desktop app observation and input. For browser page tasks, first prefer an already connected browser tool that can access the user's actual tab and session.
---

# macOS Computer Use

This project exposes 14 MCP tools through `sdk/mcp_server.py`. Use the registered tool schemas as the parameter source; the MCP key is `app`, not `app_name`. This skill does not itself create a CDP connection or provide a browser extension.

## Choose the available channel once

- For an existing Edge/Chrome web session, prefer a browser connector/CDP tool **only if it can actually see that tab and logged-in session**. Do not silently switch browser/profile, restart the user's browser, expose a debugging port, or discard their tabs to make a connection work.
- If no such connected tool is available, use the native AX/OCR fallback and state that limitation. Do not spend repeated model turns discovering the same missing bridge.
- Use native AX for desktop controls; use OCR/images when AX does not expose the necessary content. The native tool list does not currently contain a scroll or drag tool; do not invent one.

## Observe with the smallest useful payload

`get_app_state({app})` now defaults to text only: `no_img=true`, `annotate=false`, `view="text"`, `include_elements=false`. Text still includes actionable element indices. Full snapshot elements remain stored inside the engine for validation.

- Ask for `no_img=false` when images add evidence. MCP returns a JPEG preview whose longest edge defaults to 1280 pixels; use `image_max_edge` up to 2560 when small text needs more resolution.
- `windowBounds` remains in desktop points. Preview pixels are scaled; do not treat them as desktop coordinates.
- Use `annotate=true` for visual index badges. A badge does not guarantee that a dynamic page stayed unchanged during capture.
- `include_elements=true` returns structured elements when code needs them. `view="diff"` returns a diff, with full text on the initial baseline; use it only when the prior observation is available in context.
- Do not request full text, structured elements, full-resolution images, and diff together by habit.

## Choose the window and prepare web accessibility

- When multiple windows exist, call `list_windows({app})`, inspect the candidate with `get_app_state({app, window_id})`, and retain that ID for subsequent app-scoped actions, OCR and batches. IDs are session-specific; a closed or unavailable window must be reselected explicitly.
- MCP `get_app_state` defaults to `prepare_web=true`. For supported Chromium bundle IDs, it checks for AXWebArea and, when absent, tries AXEnhancedUserInterface with a one-second polling budget. `webAXStatus` reports ready, timeout, attribute_rejected or unsupported_app. AX ready means a web area exists, not that search results loaded. Set false to skip preparation; SDK callers opt in explicitly.
- To bring the selected window forward, put `{"action":"activate"}` first in a batch with `window_id`. The engine verifies focus after raising the window. On focus loss it stops inputs; refresh/restore the target before deciding which remaining actions are safe. No automatic replay.
- For scoped key presses or coordinate clicks use `batch_actions` with `window_id`; standalone `press_key` and `click_coord` remain unscoped compatibility tools.

## Act on verified target identity

- Pass `snapshot_id` from the most recent relevant state to `click`, `set_value`, or a batch containing indexed actions. CLI equivalent: `--snapshot`.
- Snapshots expire after 120 seconds and are scoped to a session, process lifecycle, and window. Unrelated animated elements do not invalidate the target.
- Actions resolve a unique matching target using role, label, actions and AXIdentifier where present. Without a stable identifier, meaningful label and unchanged target bounds are required. Same-role replacements, ambiguous targets and stale scopes are rejected.
- Editable values may change without invalidating the same input. Do not use an old index to refer to a new page. An identity rejection calls for a fresh observation, not bypassing the check.

## Combine deterministic steps and the next observation

Use `batch_actions` for dependent actions whose target and intent are already known. All static parameters are checked before execution. Runtime failure stops later steps; there is no rollback. Limit: 100 actions and 10 seconds of declared waits.

Set `observe_after=true` to return the next state in the same tool call, and `observation_no_img=false` only when an image is needed. This avoids a separate model round trip for a routine follow-up state. For result-dependent work, add `wait_for_text` with a result-specific AX marker and optionally `readiness_timeout_ms` (100–10000, default 3000). This implies observation and returns `readiness.status=matched` or `timeout`. Avoid the submitted query as a marker: it may already exist in the input. A text match only verifies that marker, not all content or network completion. The loop uses text-only observations and reuses the matched state; request an image only when needed. On timeout, actions remain dispatched; never replay them automatically.

```json
{
  "app": "com.microsoft.edgemac",
  "window_id": 12345,
  "snapshot_id": "<snapshotId just returned>",
  "actions": [
    {"action": "set_value", "element": 79, "value": "pixel 8"},
    {"action": "press_key", "key": "return"}
  ],
  "observe_after": true
}
```

The window ID and index above are illustrative: use the index observed in the actual session, and confirm the intended input has focus before sending Return. If a known search URL is available, `navigate` in a batch can avoid input-box discovery; this dispatches navigation, it does not validate search results.

- `set_value`: standard editable AX controls; it does not guarantee focus or submission.
- `paste` in a batch: suitable text inputs, with clipboard restoration. Avoid CAD canvas shortcuts.
- `type_text`: Unicode input; do not assume every application or IME handles it identically.
- `send_chat`: returns `dispatched`; verify the visible result before claiming delivery.

## Recover without turning a user task into engine development

For an ordinary shopping or desktop task, do not edit Swift, weaken checks, install dependencies, or rebuild the engine mid-task. Use at most one fresh observation for a stale target, then use an available alternate channel or explain the concrete blocker. A user-requested engine debugging task is a separate scope and may modify the project.

When `observationStatus=failed` after a successful batch, actions have already been dispatched: repeat the observation, **not the batch**. The same applies to timeouts with unknown outcomes. Retrying a send or other side effect can duplicate it.

## Verify evidence and measure delays

For product comparisons, search-card prices are preliminary. Verify the exact model/SKU, condition, capacity, selected price, warranty/returns and seller on a small shortlist before naming a best buy. Mark unverified details; do not infer genuine Pixel 8 prices from mixed-model titles alone.

Native/SDK `timingsMs` measures AX collection, capture, subprocess round trip and annotation. MCP stderr emits `CUA_METRIC` with tool elapsed time and response bytes, without page content. These measurements do not include model waiting/thinking or prove end-to-end speed. Do not promise fixed subsecond completion, a fixed token reduction, or a 5–10× speedup without a comparable measured run.

Default tests use synthetic data and temporary fixtures. Do not run the historical input scripts in `tests/manual` against the user's live desktop.
