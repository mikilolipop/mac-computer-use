"""
Live UI Phase 3 & 3.1 Integration Tests
WARNING: This test suite interacts with the real desktop and active user applications!
It is excluded from default unittest discovery (tests/test_*.py) and will ONLY run if
explicitly targeted AND RUN_LIVE_UI_TESTS=1 is set in the environment.

Usage:
    RUN_LIVE_UI_TESTS=1 python3 -m unittest tests/manual/test_phase3_live_ui.py
"""

import json
import os
import subprocess
import sys
import time
import unittest
from typing import Dict, Any

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BIN_PATH = os.path.join(WORKSPACE_ROOT, "bin", "mac-cua")


def run_cua_cli(args, session_id: str = "test_live_session") -> Dict[str, Any]:
    env = os.environ.copy()
    env["MAC_CUA_SESSION"] = session_id
    cmd = [BIN_PATH] + args
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    try:
        return json.loads(res.stdout) if res.stdout.strip() else {"raw_stderr": res.stderr, "exit_code": res.returncode}
    except Exception:
        return {"raw_stdout": res.stdout, "raw_stderr": res.stderr, "exit_code": res.returncode}


@unittest.skipUnless(os.environ.get("RUN_LIVE_UI_TESTS") == "1", "Live UI test skipped: set RUN_LIVE_UI_TESTS=1 to run")
class TestPhase3LiveUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(BIN_PATH):
            subprocess.run(["bash", "native_engine/build.sh"], cwd=WORKSPACE_ROOT, check=True)
        
        cls.target_app = "Google Chrome"
        run_cua_cli(["activate", "--app", cls.target_app])
        time.sleep(0.2)
        state = run_cua_cli(["state", "--app", cls.target_app, "--no-img", "--compact"])
        if not state.get("success", True) or "windowBounds" not in state:
            cls.target_app = "访达"
            run_cua_cli(["activate", "--app", cls.target_app])
            time.sleep(0.2)
            state = run_cua_cli(["state", "--app", cls.target_app, "--no-img", "--compact"])

        cls.window_id = state.get("windowId")
        cls.window_bounds = state.get("windowBounds")
        cls.pid = state.get("pid")
        assert cls.window_id is not None, f"Could not obtain window for {cls.target_app}"

    def test_live_web_ax_status_reconciles_after_full_collect(self):
        if self.target_app != "Google Chrome":
            self.skipTest("Requires Google Chrome to verify Chromium AXWebArea reconciliation")
        res = run_cua_cli(["state", "--app", "Google Chrome", "--prepare-web", "true", "--max-nodes", "350", "--no-img"])
        self.assertTrue(res.get("success", True))
        status = res.get("webAXStatus", "")
        self.assertTrue(status.startswith("ready"), f"webAXStatus should be ready*, got '{status}'")

    def test_live_navigate_verification_guards_return(self):
        # On Finder or an app without Omnibox matching the target URL, navigate fails without dispatching Return
        res = run_cua_cli(["navigate", "--app", "访达", "--url", "https://example.com/checkout/pay"])
        self.assertFalse(res.get("success"), "Navigate must fail if target URL is not verified in omnibox")


if __name__ == "__main__":
    unittest.main()
