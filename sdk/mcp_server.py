#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server for Native macOS Computer Use
Runs via stdin/stdout JSON-RPC protocol (MCP specification 2024-11-05).
"""

import sys
import os
import json
import base64
import logging
import math
import time
from typing import Any, Dict

try:
    from cua_client import CuaClient, CuaError
    from state_output import render_state
except ImportError:
    from sdk.cua_client import CuaClient, CuaError
    from sdk.state_output import render_state

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[%(asctime)s] %(levelname)s: %(message)s")

client = None  # Construct lazily: tools/list works before the native binary is built.

TOOLS = [
    {
        "name": "doctor",
        "description": "Diagnose macOS system permissions (Accessibility, Screen Recording) and verify engine components readiness.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "boolean", "description": "Whether to prompt macOS permission dialog if permissions are missing. Defaults to false.", "default": False}
            },
            "required": []
        }
    },
    {
        "name": "list_apps",
        "description": "List all active running GUI applications on macOS with PID, bundleId, and localized name.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_app_state",
        "description": "Inspect application state. Returns structured accessibility tree (AXTree), incremental diff against previous state, and window screenshot image with optional Set-of-Marks (SoM) visual index badges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Application display name or bundle ID (e.g. 'Microsoft Edge' or 'com.microsoft.edgemac')"},
                "diff": {"type": "boolean", "description": "Whether to return incremental diff instead of full tree. Defaults to true.", "default": True},
                "no_img": {"type": "boolean", "description": "Whether to skip window screenshot capture. Defaults to false.", "default": False},
                "compact": {"type": "boolean", "description": "Whether to prune empty structural container noise from AXTree (reduces structural text; savings depend on the application). Defaults to true.", "default": True},
                "annotate": {"type": "boolean", "description": "Whether to render Set-of-Marks (SoM) numerical badges onto the screenshot for direct visual indexing. Defaults to true.", "default": True}
            },
            "required": ["app"]
        }
    },
    {
        "name": "click",
        "description": "Click an interactive element by its assigned index ID from get_app_state (prioritizes native AXPress).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Application name or bundle ID"},
                "element_index": {"type": "integer", "description": "The integer index of the element"}
            },
            "required": ["app", "element_index"]
        }
    },
    {
        "name": "set_value",
        "description": "Instantly set the text/value of an interactive accessibility element (such as an address bar or text input) without simulating keyboard typing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Application name or bundle ID"},
                "element_index": {"type": "integer", "description": "The integer index of the element"},
                "value": {"type": "string", "description": "The text value to set"}
            },
            "required": ["app", "element_index", "value"]
        }
    },
    {
        "name": "press_key",
        "description": "Synthesize a key press or hotkey combination (e.g. 'return', 'tab', 'escape', 'space', 'cmd+c', 'cmd+v', 'cmd+a').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name or combo, defaults to 'return'", "default": "return"}
            },
            "required": []
        }
    },
    {
        "name": "type_text",
        "description": "Directly type text via Unicode event injection without clipboard (Cmd+V) or input method (IME) interference. Ideal for CAD command bars, terminal prompts, canvas games, and modal editors.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type via Unicode event injection"},
                "app": {"type": "string", "description": "Optional application display name or bundle ID to activate before typing"},
                "press_return": {"type": "boolean", "description": "Whether to press Return after typing the text. Defaults to false.", "default": False}
            },
            "required": ["text"]
        }
    },
    {
        "name": "click_coord",
        "description": "Click desktop coordinates (fallback when element index is not available).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "Desktop X coordinate"},
                "y": {"type": "number", "description": "Desktop Y coordinate"}
            },
            "required": ["x", "y"]
        }
    },
    {
        "name": "navigate",
        "description": "Atomically navigate a browser application's address bar to a target URL with event dispatch status; page loading is not verified.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Browser application name or bundleId (e.g. 'com.microsoft.edgemac')"},
                "url": {"type": "string", "description": "The destination URL"}
            },
            "required": ["app", "url"]
        }
    },
    {
        "name": "send_chat",
        "description": "Atomically send a message in a chat application (Gemini, ChatGPT, Slack, Teams, etc.) with event dispatch status; message delivery is not verified.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Chat application name or bundle ID (e.g. 'Gemini', 'Slack')"},
                "message": {"type": "string", "description": "The message text to send"},
                "new_chat": {"type": "boolean", "description": "Whether to start a new chat (Cmd+N) before sending. Defaults to false.", "default": False}
            },
            "required": ["app", "message"]
        }
    },
    {
        "name": "find_text",
        "description": "Locate text within target application window using Apple Vision OCR. Returns text, bounds, and desktop coordinates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Application display name or bundle ID"},
                "text": {"type": "string", "description": "Text substring or query to find in window"},
                "exact": {"type": "boolean", "description": "Whether to require exact match. Defaults to false.", "default": False}
            },
            "required": ["app", "text"]
        }
    },
    {
        "name": "click_text",
        "description": "Locate and click text within target application window using Apple Vision OCR in a single high-speed pass.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Application display name or bundle ID"},
                "text": {"type": "string", "description": "Text substring or query to find and click"},
                "exact": {"type": "boolean", "description": "Whether to require exact match. Defaults to false.", "default": False}
            },
            "required": ["app", "text"]
        }
    },
    {
        "name": "batch_actions",
        "description": "Execute a sequence of actions in a single prevalidated pass (without rollback) with strict fail-fast semantics. If any step fails, execution halts immediately.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "Application name or bundle ID (e.g. 'com.microsoft.edgemac' or 'Microsoft Edge')"
                },
                "actions": {
                    "type": "array",
                    "description": "Sequence of actions to execute sequentially. If any step fails, execution halts immediately.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "activate",
                                    "click",
                                    "click_coord",
                                    "click_text",
                                    "wait_text",
                                    "send_chat",
                                    "set_value",
                                    "press_key",
                                    "type_text",
                                    "type",
                                    "paste",
                                    "navigate",
                                    "wait"
                                ],
                                "description": "Action type to perform"
                            },
                            "element": {
                                "type": "integer",
                                "description": "Integer index of element from get_app_state (required for click, set_value)"
                            },
                            "value": {
                                "type": "string",
                                "description": "Text value for set_value or paste"
                            },
                            "text": {
                                "type": "string",
                                "description": "Text content for paste, type_text, click_text, wait_text, send_chat"
                            },
                            "message": {
                                "type": "string",
                                "description": "Message content for send_chat"
                            },
                            "newChat": {
                                "type": "boolean",
                                "description": "Whether to start new chat (Cmd+N) before sending (for send_chat)"
                            },
                            "pressReturn": {
                                "type": "boolean",
                                "description": "Whether to press Return after typing (for type_text)"
                            },
                            "key": {
                                "type": "string",
                                "description": "Key name for press_key (e.g. 'return', 'tab', 'escape', 'cmd+c')"
                            },
                            "url": {
                                "type": "string",
                                "description": "Destination URL for navigate"
                            },
                            "x": {
                                "type": "number",
                                "description": "Desktop X coordinate for click_coord"
                            },
                            "y": {
                                "type": "number",
                                "description": "Desktop Y coordinate for click_coord"
                            },
                            "waitMs": {
                                "type": "integer",
                                "description": "Milliseconds to sleep for wait or timeout for wait_text"
                            },
                            "exact": {
                                "type": "boolean",
                                "description": "Whether to require exact match for click_text/wait_text"
                            }
                        },
                        "required": ["action"]
                    }
                }
            },
            "required": ["app", "actions"]
        }
    }
]

TOOLS.append({"name": "list_windows", "description": "List an app's windows before choosing window_id. IDs are current-session only.",
              "inputSchema": {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]}})

for tool in TOOLS:
    if tool["name"] in ("get_app_state", "batch_actions", "click", "set_value", "type_text", "navigate", "find_text", "click_text", "send_chat"):
        tool["inputSchema"]["properties"]["window_id"] = {"type": "integer", "minimum": 1, "description": "Target from list_windows; input requires this window to be focused. Never falls back to another window."}
    if tool["name"] == "get_app_state":
        props = tool["inputSchema"]["properties"]
        props["no_img"].update(default=True, description="Skip screenshots by default; set false only when visual evidence is needed.")
        props["annotate"].update(default=False, description="Optional SoM annotation when requesting an image.")
        props["diff"]["description"] = "Compute a diff against the previous observation; select view=diff to deliver it."
        props["prepare_web"] = {"type": "boolean", "default": True, "description": "Prepare supported Chromium AX when needed; set false to disable. webAXStatus is not page-load status."}
        props.update(view={"type": "string", "enum": ["text", "diff"], "default": "text"},
                     include_elements={"type": "boolean", "default": False},
                     image_max_edge={"type": "integer", "minimum": 320, "maximum": 2560, "default": 1280},
                     max_nodes={"type": "integer", "minimum": 10, "maximum": 10000, "default": 1000,
                                "description": "Maximum number of accessibility nodes to traverse (default 1000). Set higher for complex web pages."})
    if tool["name"] == "batch_actions":
        tool["inputSchema"]["properties"].update(
            observe_after={"type": "boolean", "default": False, "description": "Return a fresh observation after successful dispatch in the same tool call; does not prove page readiness."},
            observation_no_img={"type": "boolean", "default": True},
            wait_for_text={"type": "string", "minLength": 1, "description": "Wait for this AX text marker after dispatch; choose result-specific text, not the submitted query. Implies observe_after."},
            readiness_timeout_ms={"type": "integer", "minimum": 100, "maximum": 10000, "default": 3000})
    if tool["name"] in ("click", "set_value"):
        tool["inputSchema"]["properties"]["snapshot_id"] = {"type": "string", "description": "snapshotId returned by get_app_state"}
        tool["inputSchema"]["required"].append("snapshot_id")
        tool["inputSchema"]["properties"]["element_index"]["minimum"] = 1
    if tool["name"] == "batch_actions":
        tool["inputSchema"]["properties"]["snapshot_id"] = {"type": "string"}
        props = tool["inputSchema"]["properties"]["actions"]["items"]["properties"]
        props["waitMs"].update(minimum=0, maximum=10000)
        props["element"]["minimum"] = 1

def validate_schema(value, schema, path="arguments"):
    kind = schema.get("type")
    valid = {"object": lambda: isinstance(value, dict),
             "array": lambda: isinstance(value, list),
             "string": lambda: isinstance(value, str),
             "boolean": lambda: type(value) is bool,
             "integer": lambda: type(value) is int,
             "number": lambda: type(value) in (int, float) and math.isfinite(value)}
    if kind in valid and not valid[kind]():
        raise ValueError(f"{path} must be {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} has an unsupported value")
    if kind == "object":
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        for key, item in value.items():
            if key not in schema.get("properties", {}):
                raise ValueError(f"Unknown parameter {path}.{key}")
            validate_schema(item, schema["properties"][key], f"{path}.{key}")
    if kind == "array":
        for i, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{path}[{i}]")
    if "minimum" in schema and value < schema["minimum"]:
        raise ValueError(f"{path} is below minimum")
    if "maximum" in schema and value > schema["maximum"]:
        raise ValueError(f"{path} exceeds maximum")


def handle_call_tool(params: Dict[str, Any]) -> Dict[str, Any]:
    global client
    name = params.get("name")
    args = params.get("arguments", {})

    try:
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        validate_schema(args, tool["inputSchema"])
        if name == "batch_actions" and any(a.get("action") in ("click", "set_value") for a in args.get("actions", [])) and not args.get("snapshot_id"):
            raise ValueError("snapshot_id is required for indexed batch actions")
        if name == "batch_actions" and "readiness_timeout_ms" in args and "wait_for_text" not in args:
            raise ValueError("readiness_timeout_ms requires wait_for_text")
        scope = {"window_id": args["window_id"]} if "window_id" in args else {}
        if "window_id" in args and not args.get("app"):
            raise ValueError("app is required with window_id")
        if name == "batch_actions" and "wait_for_text" in args and not args["wait_for_text"].strip():
            raise ValueError("wait_for_text must not be blank")
        if client is None:
            client = CuaClient()
        if name == "doctor":
            prompt = args.get("prompt", False)
            res = client.doctor(prompt=prompt)
            is_err = not bool(res.get("success", False))
            return {
                "content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=2)}],
                "isError": is_err
            }

        elif name == "list_windows":
            return {"content": [{"type": "text", "text": json.dumps(client.list_windows(args["app"]), ensure_ascii=False)}]}

        elif name == "list_apps":
            apps = client.list_apps()
            return {"content": [{"type": "text", "text": json.dumps(apps, ensure_ascii=False, indent=2)}]}

        elif name == "get_app_state":
            app = args.get("app")
            if not app:
                return {"content": [{"type": "text", "text": "Error: 'app' argument is required"}], "isError": True}
            diff = args.get("diff", True)
            no_img = args.get("no_img", True)
            compact = args.get("compact", True)
            annotate = args.get("annotate", False)
            max_nodes = args.get("max_nodes")
            state = client.get_state(app, diff=diff, no_img=no_img, compact=compact, annotate=annotate,
                                     prepare_web=args.get("prepare_web", True), max_nodes=max_nodes, **scope)

            return render_state(state, no_img=no_img, annotate=annotate,
                                view=args.get("view", "text"), include_elements=args.get("include_elements", False),
                                image_max_edge=args.get("image_max_edge", 1280))

        elif name == "click":
            app = args.get("app")
            idx = args.get("element_index")
            if not app or idx is None:
                return {"content": [{"type": "text", "text": "Error: 'app' and 'element_index' are required"}], "isError": True}
            success = client.click(app, idx, snapshot_id=args["snapshot_id"], **scope)
            return {
                "content": [{"type": "text", "text": json.dumps({"success": success, "status": "dispatched" if success else "failed", "clicked": idx, "app": app})}],
                "isError": not success
            }

        elif name == "set_value":
            app = args.get("app")
            idx = args.get("element_index")
            val = args.get("value")
            if not app or idx is None or val is None:
                return {"content": [{"type": "text", "text": "Error: 'app', 'element_index' and 'value' are required"}], "isError": True}
            success = client.set_value(app, idx, val, snapshot_id=args["snapshot_id"], **scope)
            return {
                "content": [{"type": "text", "text": json.dumps({"success": success, "status": "dispatched" if success else "failed", "element": idx, "value": val, "app": app})}],
                "isError": not success
            }

        elif name == "press_key":
            key = args.get("key", "return")
            success = client.press_key(key)
            return {
                "content": [{"type": "text", "text": json.dumps({"success": success, "status": "dispatched" if success else "failed", "key": key})}],
                "isError": not success
            }

        elif name == "type_text":
            text = args.get("text")
            if text is None:
                return {"content": [{"type": "text", "text": "Error: 'text' argument is required"}], "isError": True}
            app = args.get("app")
            press_return = args.get("press_return", False)
            success = client.type_text(text=text, app=app, press_return=press_return, **scope)
            return {
                "content": [{"type": "text", "text": json.dumps({"success": success, "status": "dispatched" if success else "failed", "typed": text, "app": app, "pressReturn": press_return})}],
                "isError": not success
            }

        elif name == "click_coord":
            x = args.get("x")
            y = args.get("y")
            if x is None or y is None:
                return {"content": [{"type": "text", "text": "Error: 'x' and 'y' are required"}], "isError": True}
            success = client.click_coord(x, y)
            return {
                "content": [{"type": "text", "text": json.dumps({"success": success, "status": "dispatched" if success else "failed", "x": x, "y": y})}],
                "isError": not success
            }

        elif name == "navigate":
            app = args.get("app")
            url = args.get("url")
            if not app or not url:
                return {"content": [{"type": "text", "text": "Error: 'app' and 'url' are required"}], "isError": True}
            success = client.navigate(app, url, **scope)
            return {
                "content": [{"type": "text", "text": json.dumps({"success": success, "status": "dispatched" if success else "failed", "app": app, "url": url})}],
                "isError": not success
            }

        elif name == "find_text":
            app = args.get("app")
            text = args.get("text")
            exact = args.get("exact", False)
            if not app or not text:
                return {"content": [{"type": "text", "text": "Error: 'app' and 'text' are required"}], "isError": True}
            result = client.find_text(app, text, exact=exact, **scope)
            return {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                "isError": not bool(result.get("success", False))
            }

        elif name == "click_text":
            app = args.get("app")
            text = args.get("text")
            exact = args.get("exact", False)
            if not app or not text:
                return {"content": [{"type": "text", "text": "Error: 'app' and 'text' are required"}], "isError": True}
            success = client.click_text(app, text, exact=exact, **scope)
            return {
                "content": [{"type": "text", "text": json.dumps({"success": success, "status": "dispatched" if success else "failed", "app": app, "clickedText": text})}],
                "isError": not success
            }

        elif name == "send_chat":
            app = args.get("app")
            msg = args.get("message")
            new_chat = args.get("new_chat", False)
            if not app or not msg:
                return {"content": [{"type": "text", "text": "Error: 'app' and 'message' are required"}], "isError": True}
            result = client.send_chat(app, msg, new_chat=new_chat, **scope)
            return {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                "isError": not bool(result.get("success", False))
            }

        elif name == "batch_actions":
            app = args.get("app")
            actions = args.get("actions", [])
            if not app or not actions:
                return {"content": [{"type": "text", "text": "Error: 'app' and 'actions' are required"}], "isError": True}
            started = time.perf_counter()
            result = client.batch(app, actions, snapshot_id=args.get("snapshot_id"), **scope)
            if result.get("success") and (args.get("observe_after", False) or "wait_for_text" in args):
                remaining = 15.0 - (time.perf_counter() - started)
                # Never retry the dispatched batch if observation fails.
                try:
                    if remaining <= 0:
                        raise TimeoutError("Observation budget exhausted")
                    readiness = None
                    state = None
                    if "wait_for_text" in args:
                        readiness = client.observe_until(app, args["wait_for_text"],
                            timeout=min(remaining, args.get("readiness_timeout_ms", 3000) / 1000), **scope)
                        state = readiness.pop("state", None)
                        result["readiness"] = readiness
                        if readiness["status"] != "matched":
                            raise TimeoutError("Result marker not observed before deadline")
                    if state is None or not args.get("observation_no_img", True):
                        remaining = 15.0 - (time.perf_counter() - started)
                        if remaining <= 0:
                            raise TimeoutError("Observation budget exhausted")
                        capture_scope = scope or ({"window_id": state["windowId"]} if state and state.get("windowId") else {})
                        state = client.get_state(app, no_img=args.get("observation_no_img", True), annotate=False, timeout=remaining, **capture_scope)
                    response = render_state(state, no_img=args.get("observation_no_img", True))
                    response["content"].insert(0, {"type": "text", "text": json.dumps({"batch": result, "observationStatus": "captured"}, ensure_ascii=False)})
                    return response
                except Exception as exc:
                    result = dict(result, observationStatus="failed", observationError=str(exc),
                                  retryAdvice="Actions already dispatched; observe again, do not repeat the batch.")
            return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "isError": not bool(result.get("success", False))}

        else:
            return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

    except CuaError as e:
        return {"content": [{"type": "text", "text": json.dumps(e.payload, ensure_ascii=False)}], "isError": True}
    except Exception as e:
        logging.error(f"Error executing tool {name}: {e}")
        return {"content": [{"type": "text", "text": f"Tool execution failed: {str(e)}"}], "isError": True}


def rpc_error(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def dispatch_request(req):
    if (not isinstance(req, dict) or req.get("jsonrpc") != "2.0"
            or not isinstance(req.get("method"), str)):
        return rpc_error(None, -32600, "Invalid Request")
    req_id = req.get("id")
    if "id" in req and req_id is not None and type(req_id) not in (str, int):
        return rpc_error(None, -32600, "Invalid request id")
    # Notifications never receive responses and never invoke action tools.
    if "id" not in req:
        return None
    params = req.get("params", {})
    if not isinstance(params, dict):
        return rpc_error(req_id, -32602, "params must be an object")
    method = req["method"]
    try:
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05",
                      "serverInfo": {"name": "mac-cua-native", "version": "1.1.0"},
                      "capabilities": {"tools": {}}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            if not isinstance(params.get("name"), str) or not isinstance(params.get("arguments", {}), dict):
                return rpc_error(req_id, -32602, "name must be a string and arguments an object")
            began = time.perf_counter()
            result = handle_call_tool(params)
            elapsed = (time.perf_counter() - began) * 1000
            payload_bytes = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            logging.info("CUA_METRIC %s", json.dumps({"requestId": req_id, "tool": params["name"],
                "toolMs": round(elapsed, 3), "responseBytes": payload_bytes,
                "isError": bool(result.get("isError", False))}))
        elif method == "ping":
            result = {}
        else:
            return rpc_error(req_id, -32601, f"Method '{method}' not supported")
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except Exception:
        logging.exception("Request failed")
        return rpc_error(req_id, -32603, "Internal error")


def run_stdio_server():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
            response = dispatch_request(req)
        except (json.JSONDecodeError, ValueError):
            response = rpc_error(None, -32700, "Parse error")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_server()
