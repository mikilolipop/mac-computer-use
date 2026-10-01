#!/usr/bin/env python3
"""
Mock Sky / Codex Computer Use Daemon
Implements the exact 4-byte uint32LE framing and JSON-RPC 2.0 protocol over a UNIX domain socket.
Useful for offline testing and verifying the reverse-engineered client.
"""

import os
import socket
import struct
import json
import logging
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

SOCKET_PATH = "/tmp/mock_computeruse.sock"
API_VERSION = "CodexComputerUseIPC-5"

def decode_frames(buffer: bytearray):
    messages = []
    while len(buffer) >= 4:
        length = struct.unpack("<I", buffer[:4])[0]
        if len(buffer) < 4 + length:
            break
        payload = buffer[4:4+length].decode("utf-8")
        messages.append(payload)
        del buffer[:4+length]
    return messages

def encode_frame(data: Dict[str, Any]) -> bytes:
    payload = json.dumps(data).encode("utf-8")
    header = struct.pack("<I", len(payload))
    return header + payload

def handle_rpc(request: Dict[str, Any]) -> Dict[str, Any]:
    req_id = request.get("id")
    method = request.get("method")
    params = request.get("params", {})

    logging.info(f"Received RPC method: {method} (id={req_id})")

    if method == "ping":
        client_version = params.get("clientApiVersion")
        logging.info(f"Ping from client version: {client_version}")
        return {
            "id": req_id,
            "jsonrpc": "2.0",
            "result": {
                "serverApiVersion": API_VERSION
            }
        }
    
    elif method == "request":
        req_type = params.get("requestType")
        payload = params.get("request", {})
        logging.info(f"Executing requestType: {req_type} with payload: {payload}")

        if req_type == "ComputerUseIPCListAppsRequest":
            return {
                "id": req_id,
                "jsonrpc": "2.0",
                "result": [
                    {
                        "id": "com.apple.finder",
                        "displayName": "Finder",
                        "isRunning": True,
                        "lastUsedDate": "2026-09-15T12:00:00Z",
                        "useCount": 100
                    },
                    {
                        "id": "com.google.Chrome",
                        "displayName": "Google Chrome",
                        "isRunning": True,
                        "lastUsedDate": "2026-09-15T12:10:00Z",
                        "useCount": 50
                    }
                ]
            }

        elif req_type == "ComputerUseIPCAppGetSkyshotRequest":
            app = payload.get("app", "Unknown")
            return {
                "id": req_id,
                "jsonrpc": "2.0",
                "result": {
                    "app": app,
                    "screenshot": {
                        "url": "file:///tmp/mock_screenshot.png"
                    },
                    "text": (
                        f"AXApplication: {app}\n"
                        "  AXWindow: Main Window\n"
                        "    [10] AXButton: Close\n"
                        "    [20] AXTextField: Search Input (value: '')\n"
                        "    [30] AXButton: Submit"
                    )
                }
            }

        elif req_type == "ComputerUseIPCAppPerformActionRequest":
            action = payload.get("action", {})
            logging.info(f"Action performed: {action}")
            return {
                "id": req_id,
                "jsonrpc": "2.0",
                "result": None
            }

        else:
            return {
                "id": req_id,
                "jsonrpc": "2.0",
                "result": {}
            }

    return {
        "id": req_id,
        "jsonrpc": "2.0",
        "error": {
            "code": -32601,
            "message": f"Method {method} not found"
        }
    }

def run_server():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(5)
    logging.info(f"Mock Computer Use daemon listening on {SOCKET_PATH}...")

    try:
        while True:
            conn, _ = server.accept()
            logging.info("Client connected.")
            buf = bytearray()
            try:
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    buf.extend(data)
                    for frame_str in decode_frames(buf):
                        req = json.loads(frame_str)
                        resp = handle_rpc(req)
                        conn.sendall(encode_frame(resp))
            except Exception as e:
                logging.error(f"Error handling connection: {e}")
            finally:
                conn.close()
                logging.info("Client disconnected.")
    finally:
        server.close()
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

if __name__ == "__main__":
    run_server()
