#!/usr/bin/env python3
"""
Test Native Computer Use Flow on Microsoft Edge
"""

import time
from sdk.cua_client import CuaClient

def main():
    client = CuaClient()
    print("1. Fetching Edge State...")
    state = client.get_state("Microsoft Edge", diff=False)
    print(f"App: {state['app']}, PID: {state['pid']}, Element Count: {state['elementCount']}")
    print(f"Screenshot URL: {state.get('screenshotUrl')}")

    # Find address bar in the text
    lines = state["text"].splitlines()
    addr_line = next((l for l in lines if "地址" in l or "搜索" in l or "address" in l.lower()), None)
    print(f"Address bar line found: {addr_line}")

    # Inspect Diff
    print("\n2. Fetching Edge State with Diff...")
    state2 = client.get_state("Microsoft Edge", diff=True)
    print(f"Diff output: {state2.get('diff')}")

if __name__ == "__main__":
    main()
