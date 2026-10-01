#!/usr/bin/env python3
"""
Python SDK Wrapper for Native macOS Computer Use Engine (mac-cua)
"""

import json
import subprocess
import os
import uuid
import time
from typing import List, Dict, Optional, Any

try:
    from visual_annotator import annotate_screenshot
except ImportError:
    try:
        from sdk.visual_annotator import annotate_screenshot
    except ImportError:
        annotate_screenshot = None

class CuaError(RuntimeError):
    def __init__(self, payload):
        self.payload = payload
        super().__init__(str(payload.get("error", "Native operation failed")))


class CuaClient:
    def __init__(self, binary_path: Optional[str] = None):
        self.session_id = str(uuid.uuid4())
        self.snapshots = {}
        if binary_path:
            self.binary_path = binary_path
        else:
            # Default to ../bin/mac-cua relative to this file
            cur_dir = os.path.dirname(os.path.abspath(__file__))
            self.binary_path = os.path.join(cur_dir, "..", "bin", "mac-cua")

        if not os.path.exists(self.binary_path):
            raise FileNotFoundError(f"Native binary not found at {self.binary_path}. Please build it first.")

    def _run(self, args: List[str], timeout: float = 15.0, allow_list: bool = False, window_id: Optional[int] = None) -> Any:
        if window_id is not None:
            if isinstance(window_id, bool) or not isinstance(window_id, int) or window_id <= 0:
                raise ValueError("window_id must be a positive integer")
            args = args + ["--window-id", str(window_id)]
        started = time.perf_counter()
        cmd = [self.binary_path] + args
        env = dict(os.environ, MAC_CUA_SESSION=self.session_id)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired as e:
            raise CuaError({"success": False, "code": "TIMEOUT", "error": f"Native {args[0]} timed out; outcome may be unknown; inspect before retrying"}) from e
        try:
            payload = json.loads(res.stdout)
        except (json.JSONDecodeError, TypeError) as e:
            raise CuaError({"success": False, "code": "INVALID_RESPONSE", "error": "Native engine returned invalid JSON", "exitCode": res.returncode}) from e
        if allow_list and res.returncode == 0 and isinstance(payload, list) and all(isinstance(x, dict) for x in payload):
            return payload
        if not isinstance(payload, dict):
            raise CuaError({"success": False, "code": "INVALID_RESPONSE", "error": "Expected native response object"})
        if res.returncode != 0 or payload.get("success") is False:
            payload.update(success=False, exitCode=res.returncode)
            payload.setdefault("code", "NATIVE_ERROR")
            payload.setdefault("error", "Native operation failed")
            raise CuaError(payload)
        payload.setdefault("timingsMs", {})["nativeRoundTrip"] = round((time.perf_counter() - started) * 1000, 3)
        return payload

    def _snapshot_args(self, app, snapshot_id):
        snapshot_id = snapshot_id or self.snapshots.get(app)
        if not snapshot_id:
            raise CuaError({"success": False, "code": "STALE_SNAPSHOT", "error": "Call get_state before indexed actions"})
        return ["--snapshot", snapshot_id]

    def list_apps(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """List active GUI applications on macOS."""
        return self._run(["list-apps"], timeout=timeout, allow_list=True)

    def list_windows(self, app: str, timeout: float = 15.0):
        return self._run(["list-windows", "--app", app], timeout=timeout, allow_list=True)

    def observe_until(self, app: str, text: str, timeout: float = 3.0, window_id=None):
        """Bounded text observation; never repeats an input action. Text is a caller-chosen marker."""
        if not text.strip() or not 0 < timeout <= 10:
            raise ValueError("Nonempty text and timeout in (0, 10] required")
        started = time.perf_counter()
        deadline = started + timeout
        attempts = 0
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return {"status": "timeout", "attempts": attempts,
                        "elapsedMs": round((time.perf_counter() - started) * 1000, 3)}
            try:
                state = self.get_state(app, no_img=True, annotate=False, diff=False,
                                       timeout=remaining, window_id=window_id)
            except CuaError as exc:
                if exc.payload.get("code") != "TIMEOUT":
                    raise
                return {"status": "timeout", "attempts": attempts + 1,
                        "elapsedMs": round((time.perf_counter() - started) * 1000, 3)}
            attempts += 1
            if window_id is None:
                window_id = state.get("windowId")
            if text.casefold() in state.get("text", "").casefold():
                return {"status": "matched", "attempts": attempts, "state": state,
                        "elapsedMs": round((time.perf_counter() - started) * 1000, 3)}
            remaining = deadline - time.perf_counter()
            if remaining > 0:
                time.sleep(min(0.15, remaining))

    def doctor(self, prompt: bool = False, timeout: float = 10.0) -> Dict[str, Any]:
        """Diagnose system permissions (Accessibility, Screen Recording) and engine readiness."""
        args = ["doctor"]
        if prompt:
            args.append("--prompt")
        return self._run(args, timeout=timeout)

    def get_state(
        self,
        app: str,
        diff: bool = True,
        no_img: bool = False,
        compact: bool = True,
        annotate: bool = True,
        timeout: float = 15.0,
        window_id: Optional[int] = None,
        prepare_web: bool = False,
        max_nodes: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Inspect application state.
        Returns:
          - app: App name
          - pid: Process ID
          - windowId: Window ID
          - windowBounds: ElementBounds dict
          - text: Pruned or full Accessibility tree with indices
          - diff: Incremental Diff from last state
          - screenshotUrl: File URL to clean window screenshot
          - annotatedScreenshotUrl: File URL to Set-of-Marks annotated screenshot (if annotate=True)
          - elementCount: Total interactive elements
          - elements: List of interactive elements
        """
        args = ["state", "--app", app]
        if diff:
            args.append("--diff")
        if no_img:
            args.append("--no-img")
        if compact:
            args.append("--compact")
        if max_nodes is not None:
            if isinstance(max_nodes, bool) or not isinstance(max_nodes, int) or max_nodes <= 0:
                raise ValueError("max_nodes must be a positive integer")
            args += ["--max-nodes", str(max_nodes)]

        if prepare_web:
            args += ["--prepare-web", "true"]
        state = self._run(args, timeout=timeout, window_id=window_id)

        if state.get("snapshotId"):
            self.snapshots[app] = state["snapshotId"]
        state["annotationStatus"] = "disabled" if not annotate or no_img else "unavailable"

        annotation_started = time.perf_counter()
        # Inject Set-of-Marks visual annotation if screenshot and elements are available
        if annotate and not no_img and annotate_screenshot and state.get("screenshotUrl"):
            clean_path = state["screenshotUrl"]
            if clean_path.startswith("file://"):
                clean_path = clean_path[7:]
            elements = state.get("elements", [])
            window_bounds = state.get("windowBounds")
            if os.path.exists(clean_path) and elements:
                try:
                    annotated_path = annotate_screenshot(clean_path, elements, window_bounds)
                    state["annotationStatus"] = "ready" if annotated_path != clean_path else "failed"
                    state["annotatedScreenshotUrl"] = f"file://{annotated_path}"
                except Exception as exc:
                    state["annotationStatus"] = "failed"
                    state["annotationError"] = str(exc)

        state.setdefault("timingsMs", {})["annotation"] = round((time.perf_counter() - annotation_started) * 1000, 3)
        return state

    def click(self, app: str, element_index: int, timeout: float = 15.0, snapshot_id: Optional[str] = None, window_id: Optional[int] = None) -> bool:
        """Click an interactive element by its index ID."""
        res = self._run(["click", "--app", app, "--element", str(element_index)] + self._snapshot_args(app, snapshot_id), timeout=timeout, window_id=window_id)
        return bool(res.get("success", False))

    def click_coord(self, x: float, y: float, timeout: float = 15.0) -> bool:
        """Click specific desktop coordinates."""
        res = self._run(["click-coord", "--x", str(x), "--y", str(y)], timeout=timeout)
        return bool(res.get("success", False))

    def set_value(self, app: str, element_index: int, value: str, timeout: float = 15.0, snapshot_id: Optional[str] = None, window_id: Optional[int] = None) -> bool:
        """Instantly set text value of an element (like an address bar or input field)."""
        res = self._run(["set-value", "--app", app, "--element", str(element_index), "--value", value] + self._snapshot_args(app, snapshot_id), timeout=timeout, window_id=window_id)
        return bool(res.get("success", False))

    def press_key(self, key: str = "return", timeout: float = 15.0) -> bool:
        """Press a special key (e.g. 'return', 'tab', 'escape', 'space', 'cmd+c')."""
        res = self._run(["press-key", "--key", key], timeout=timeout)
        return bool(res.get("success", False))

    def type_text(self, text: str, app: Optional[str] = None, press_return: bool = False, timeout: float = 15.0, window_id: Optional[int] = None) -> bool:
        """
        Type text directly via Unicode injection without clipboard (Cmd+V) or IME interference.
        Ideal for terminals, CAD command prompts, canvas editors, or anywhere Cmd+V / IMEs fail.
        """
        args = ["type-text", "--text", text]
        if app:
            args.extend(["--app", app])
        if press_return:
            args.append("--press-return")
        res = self._run(args, timeout=timeout, window_id=window_id)
        return bool(res.get("success", False))

    def navigate(self, app: str, url: str, timeout: float = 15.0, window_id: Optional[int] = None) -> bool:
        """Dispatch browser navigation; page load completion is not verified."""
        res = self._run(["navigate", "--app", app, "--url", url], timeout=timeout, window_id=window_id)
        return bool(res.get("success", False))

    def batch(self, app: str, actions: List[Dict[str, Any]], timeout: float = 15.0, snapshot_id: Optional[str] = None, window_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Execute a sequence of actions with strict fail-fast semantics.
        actions format: [{'action': 'click', 'element': 7}, {'action': 'set_value', 'value': '...'}, ...]
        """
        actions_json = json.dumps(actions)
        extra = self._snapshot_args(app, snapshot_id) if any(a.get("action") in ("click", "set_value") for a in actions) else []
        return self._run(["batch", "--app", app, "--actions", actions_json] + extra, timeout=timeout, window_id=window_id)

    def scroll(self, app: str, direction: str = "down", amount: int = 5, x: Optional[float] = None, y: Optional[float] = None, timeout: float = 15.0, window_id: Optional[int] = None) -> bool:
        """Scroll application contents using native CGEvent scroll wheel."""
        args = ["scroll", "--app", app, "--direction", direction, "--amount", str(amount)]
        if x is not None:
            args.extend(["--x", str(x)])
        if y is not None:
            args.extend(["--y", str(y)])
        res = self._run(args, timeout=timeout, window_id=window_id)
        return bool(res.get("success", False))

    def find_text(self, app: str, text: str, exact: bool = False, min_confidence: float = 0.0, timeout: float = 15.0, window_id: Optional[int] = None) -> Dict[str, Any]:
        """Locate text within target application window using compiled Apple Vision OCR."""
        args = ["find-text", "--app", app, "--text", text]
        if exact:
            args.append("--exact")
        if min_confidence > 0:
            args.extend(["--min-confidence", str(min_confidence)])
        return self._run(args, timeout=timeout, window_id=window_id)

    def click_text(self, app: str, text: str, exact: bool = False, occurrence: Optional[int] = None, min_confidence: float = 0.0, timeout: float = 15.0, window_id: Optional[int] = None) -> bool:
        """Locate and click text within target application window using compiled Apple Vision OCR."""
        args = ["click-text", "--app", app, "--text", text]
        if exact:
            args.append("--exact")
        if occurrence is not None:
            args.extend(["--occurrence", str(occurrence)])
        if min_confidence > 0:
            args.extend(["--min-confidence", str(min_confidence)])
        res = self._run(args, timeout=timeout, window_id=window_id)
        return bool(res.get("success", False))

    def send_chat(self, app: str, message: str, new_chat: bool = False, timeout: float = 15.0, window_id: Optional[int] = None) -> Dict[str, Any]:
        """Dispatch chat input; delivery must be verified by the caller."""
        args = ["send-chat", "--app", app, "--message", message]
        if new_chat:
            args.append("--new-chat")
        return self._run(args, timeout=timeout, window_id=window_id)




if __name__ == "__main__":
    client = CuaClient()
    apps = client.list_apps()
    print(f"Found {len(apps)} running GUI applications.")
    edge_app = next((a for a in apps if "edge" in a.get("name", "").lower()), None)
    if edge_app:
        print("Testing get_state on Edge...")
        state = client.get_state(edge_app["name"], diff=True)
        print(f"Element count: {state['elementCount']}")
        print(f"Diff: {state.get('diff')}")
        print("First 5 lines of AXTree:")
        print("\n".join(state["text"].splitlines()[:5]))
