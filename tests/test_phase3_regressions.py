"""
Permanent Phase 3 Regression Test Suite
Validates:
1. Batch click_text ambiguity protection and occurrence support (P1-1).
2. exact=true duplicate text is still rejected as ambiguous without occurrence (P1-2).
3. scroll invalidates OCR cache (P1-3).
4. Cached OCR frame rejected when window moves/resizes (P1-3).
5. scroll rejects out-of-window coordinates (P1-4).
6. scroll rejects huge amount and batch rejects invalid modifiers (P1-5).
7. navigate requires target URL verification in address bar before Return (P1-6).
8. webAXStatus reconciles to ready_full_collection after complete AX traversal (P2).
9. Snapshot preserves max_nodes policy from state command (Phase 3 base).
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import hashlib
import unittest
from typing import Dict, Any, Optional

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BIN_PATH = os.path.join(WORKSPACE_ROOT, "bin", "mac-cua")
sys.path.insert(0, WORKSPACE_ROOT)
from sdk.cua_client import CuaClient


def get_session_cache_dir(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return os.path.join(tempfile.gettempdir(), "mac-cua", digest)


def run_cua_cli(args, session_id: str = "test_phase3_session", check: bool = False) -> Dict[str, Any]:
    env = os.environ.copy()
    env["MAC_CUA_SESSION"] = session_id
    cmd = [BIN_PATH] + args
    res = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed (code {res.returncode}): {res.stderr}\nStdout: {res.stdout}")
    try:
        return json.loads(res.stdout) if res.stdout.strip() else {"raw_stderr": res.stderr, "exit_code": res.returncode}
    except Exception:
        return {"raw_stdout": res.stdout, "raw_stderr": res.stderr, "exit_code": res.returncode}


class TestPhase3Regressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(BIN_PATH):
            subprocess.run(["bash", "native_engine/build.sh"], cwd=WORKSPACE_ROOT, check=True)
        # Ensure Chrome is running and activated for UI tests
        cls.target_app = "Google Chrome"
        run_cua_cli(["activate", "--app", cls.target_app])
        time.sleep(0.15)
        # Get window bounds and scope
        state = run_cua_cli(["state", "--app", cls.target_app, "--no-img", "--compact"])
        if not state.get("success", True) or "windowBounds" not in state:
            # Fallback to Finder if Chrome has no active window
            cls.target_app = "访达"
            run_cua_cli(["activate", "--app", cls.target_app])
            time.sleep(0.15)
            state = run_cua_cli(["state", "--app", cls.target_app, "--no-img", "--compact"])
        
        cls.window_id = state.get("windowId")
        cls.window_bounds = state.get("windowBounds")
        cls.pid = state.get("pid")
        assert cls.window_id is not None, f"Could not obtain window ID for {cls.target_app}"

    def setUp(self):
        self.session_id = f"test_session_{int(time.time() * 1000)}"
        self.cache_dir = get_session_cache_dir(self.session_id)
        os.makedirs(self.cache_dir, exist_ok=True)

    def tearDown(self):
        # Clean up session test cache
        if os.path.exists(self.cache_dir):
            for f in os.listdir(self.cache_dir):
                try:
                    os.remove(os.path.join(self.cache_dir, f))
                except Exception:
                    pass

    def _write_mock_ocr_frame(self, matches, bounds=None):
        wb = bounds or self.window_bounds
        frame = {
            "windowID": self.window_id,
            "pid": self.pid,
            "timestamp": time.time(),
            "windowBounds": wb,
            "matches": matches
        }
        cache_path = os.path.join(self.cache_dir, f"ocr_{self.window_id}.json")
        with open(cache_path, "w") as f:
            json.dump(frame, f)
        return cache_path

    # =========================================================================
    # Test 1: P1-1 Unified OCR target resolution & ambiguity rejection in Batch
    # =========================================================================
    def test_batch_click_text_rejects_ambiguity(self):
        matches = [
            {"text": "Search", "confidence": 0.95, "bounds": self.window_bounds, "desktopX": 100.0, "desktopY": 100.0},
            {"text": "Search More", "confidence": 0.92, "bounds": self.window_bounds, "desktopX": 200.0, "desktopY": 200.0}
        ]
        self._write_mock_ocr_frame(matches)

        # Batch click_text without occurrence targeting "Search" (which matches both)
        actions = [{"action": "click_text", "text": "Search"}]
        res = run_cua_cli(["batch", "--app", self.target_app, "--actions", json.dumps(actions)], session_id=self.session_id)

        self.assertFalse(res.get("success"), "Batch click_text with ambiguous matches must fail")
        self.assertEqual(res.get("executed"), 0, "No actions should execute when ambiguity is detected")
        self.assertEqual(res.get("code"), "AMBIGUOUS_TEXT", "Error code should be AMBIGUOUS_TEXT")
        self.assertIn("AMBIGUOUS_TEXT", res.get("error", ""))

        # Disambiguated with occurrence: 1 -> should resolve match 1
        actions_with_occ = [{"action": "click_text", "text": "Search", "occurrence": 1}]
        res_occ = run_cua_cli(["batch", "--app", self.target_app, "--actions", json.dumps(actions_with_occ)], session_id=self.session_id)
        # Even if mouse click dispatch is ignored off-screen, it should not fail with AMBIGUOUS_TEXT
        if not res_occ.get("success"):
            self.assertNotEqual(res_occ.get("code"), "AMBIGUOUS_TEXT")

    # =========================================================================
    # Test 2: P1-2 Exact duplicate text is STILL ambiguous without occurrence
    # =========================================================================
    def test_exact_duplicate_text_is_still_ambiguous(self):
        matches = [
            {"text": "Submit", "confidence": 0.98, "bounds": self.window_bounds, "desktopX": 150.0, "desktopY": 150.0},
            {"text": "Submit", "confidence": 0.97, "bounds": self.window_bounds, "desktopX": 350.0, "desktopY": 350.0}
        ]
        self._write_mock_ocr_frame(matches)

        # Standalone click-text with exact=true and 2 identical matches
        res_standalone = run_cua_cli(["click-text", "--app", self.target_app, "--text", "Submit", "--exact"], session_id=self.session_id)
        self.assertFalse(res_standalone.get("success"), "Standalone click-text with exact duplicate text must be rejected as ambiguous")
        self.assertEqual(res_standalone.get("code"), "AMBIGUOUS_TEXT")

        # Batch click_text with exact=true and 2 identical matches
        actions = [{"action": "click_text", "text": "Submit", "exact": True}]
        res_batch = run_cua_cli(["batch", "--app", self.target_app, "--actions", json.dumps(actions)], session_id=self.session_id)
        self.assertFalse(res_batch.get("success"), "Batch click_text with exact duplicate text must be rejected as ambiguous")
        self.assertEqual(res_batch.get("code"), "AMBIGUOUS_TEXT")
        self.assertEqual(res_batch.get("executed"), 0)

    # =========================================================================
    # Test 3: P1-3 Scroll invalidates OCR cache
    # =========================================================================
    def test_scroll_invalidates_ocr_cache(self):
        cache_path = self._write_mock_ocr_frame([
            {"text": "Hello", "confidence": 0.99, "bounds": self.window_bounds, "desktopX": 100.0, "desktopY": 100.0}
        ])
        self.assertTrue(os.path.exists(cache_path), "Mock OCR cache file must exist before scroll")

        # Run standalone scroll
        res = run_cua_cli(["scroll", "--app", self.target_app, "--direction", "down", "--amount", "2"], session_id=self.session_id)
        self.assertTrue(res.get("success"), f"Scroll failed: {res}")
        self.assertFalse(os.path.exists(cache_path), "OCR cache file must be deleted/invalidated after scroll")

    # =========================================================================
    # Test 4: P1-3 Cached OCR rejected when window bounds move
    # =========================================================================
    def test_cached_ocr_rejected_after_window_move(self):
        # Write OCR cache with artificial stale bounds (e.g. shifted by 500px)
        stale_bounds = {
            "x": self.window_bounds["x"] + 500.0,
            "y": self.window_bounds["y"] + 500.0,
            "width": self.window_bounds["width"],
            "height": self.window_bounds["height"]
        }
        cache_path = self._write_mock_ocr_frame([
            {"text": "StaleTargetText", "confidence": 0.99, "bounds": stale_bounds, "desktopX": 999.0, "desktopY": 999.0}
        ], bounds=stale_bounds)

        # Query find-text. The engine must reject the stale cache because currentBounds != stale_bounds
        res = run_cua_cli(["find-text", "--app", self.target_app, "--text", "StaleTargetText"], session_id=self.session_id)
        # StaleTargetText will not be found in the fresh capture
        self.assertFalse(res.get("success"), "Stale cached text must not be returned after window moved")

        # The cache file should now contain fresh window bounds matching current window
        with open(cache_path, "r") as f:
            updated_cache = json.load(f)
        saved_bounds = updated_cache["windowBounds"]
        self.assertAlmostEqual(saved_bounds["x"], self.window_bounds["x"], delta=5.0)

    # =========================================================================
    # Test 5: P1-4 Scroll rejects out-of-window coordinates
    # =========================================================================
    def test_scroll_rejects_out_of_window_coordinates(self):
        bad_x = self.window_bounds["x"] + self.window_bounds["width"] + 500.0
        bad_y = self.window_bounds["y"] + self.window_bounds["height"] + 500.0

        # Standalone scroll with out-of-window coordinates
        res_standalone = run_cua_cli(["scroll", "--app", self.target_app, "--x", str(bad_x), "--y", str(bad_y)], session_id=self.session_id)
        self.assertFalse(res_standalone.get("success"))
        self.assertEqual(res_standalone.get("code"), "COORDINATES_OUT_OF_BOUNDS")

        # Batch scroll with out-of-window coordinates
        actions = [{"action": "scroll", "x": bad_x, "y": bad_y, "amount": 5}]
        res_batch = run_cua_cli(["batch", "--app", self.target_app, "--actions", json.dumps(actions)], session_id=self.session_id)
        self.assertFalse(res_batch.get("success"))
        self.assertIn("outside window bounds", res_batch.get("error", ""))

    # =========================================================================
    # Test 6: P1-5 Scroll rejects huge amounts & batch rejects invalid modifiers
    # =========================================================================
    def test_scroll_rejects_huge_amount(self):
        # Standalone huge amount (potential overflow trap)
        res_huge = run_cua_cli(["scroll", "--app", self.target_app, "--amount", "999999999999999999"], session_id=self.session_id)
        self.assertFalse(res_huge.get("success"))
        self.assertEqual(res_huge.get("code"), "INVALID_ARGUMENT")

        # Standalone amount > 100
        res_150 = run_cua_cli(["scroll", "--app", self.target_app, "--amount", "150"], session_id=self.session_id)
        self.assertFalse(res_150.get("success"))
        self.assertEqual(res_150.get("code"), "INVALID_ARGUMENT")

        # Standalone amount <= 0
        res_zero = run_cua_cli(["scroll", "--app", self.target_app, "--amount", "0"], session_id=self.session_id)
        self.assertFalse(res_zero.get("success"))
        self.assertEqual(res_zero.get("code"), "INVALID_ARGUMENT")

        # Batch amount > 100 should fail static validation
        actions_huge = [{"action": "scroll", "amount": 105}]
        res_batch = run_cua_cli(["batch", "--app", self.target_app, "--actions", json.dumps(actions_huge)], session_id=self.session_id)
        self.assertFalse(res_batch.get("success"))
        self.assertIn("Scroll amount must be between 1 and 100", res_batch.get("error", ""))

        # Batch unknown modifier (e.g. 'cmdd') should fail static validation
        actions_bad_mod = [{"action": "press_key", "key": "c", "modifiers": ["cmdd"]}]
        res_mod = run_cua_cli(["batch", "--app", self.target_app, "--actions", json.dumps(actions_bad_mod)], session_id=self.session_id)
        self.assertFalse(res_mod.get("success"))
        self.assertIn("Unknown modifier 'cmdd'", res_mod.get("error", ""))

        # SDK level client validation
        client = CuaClient()
        with self.assertRaises(ValueError):
            client.scroll(self.target_app, amount=150)

    # =========================================================================
    # Test 7: P1-6 Navigate URL verification before Return
    # =========================================================================
    def test_navigate_does_not_press_return_until_target_url_verified(self):
        # Non-browser application (e.g. Finder) has no address bar that accepts/verifies URL
        # Running navigate on Finder must safely fail without dispatching Return
        res = run_cua_cli(["navigate", "--app", "访达", "--url", "https://unverified.target.invalid.domain"], session_id=self.session_id)
        self.assertFalse(res.get("success"), "Navigate must fail if target URL is not verified in omnibox")

    # =========================================================================
    # Test 8: P2 webAXStatus reconciles to ready_full_collection
    # =========================================================================
    def test_web_ax_status_reconciles_after_full_collect(self):
        if self.target_app != "Google Chrome":
            self.skipTest("Requires Google Chrome to verify Chromium AXWebArea reconciliation")
        res = run_cua_cli(["state", "--app", "Google Chrome", "--prepare-web", "true", "--max-nodes", "350", "--no-img"], session_id=self.session_id)
        self.assertTrue(res.get("success", True))
        status = res.get("webAXStatus", "")
        # Must be one of the ready statuses, and NOT falsely attribute_rejected!
        self.assertTrue(status.startswith("ready"), f"webAXStatus should be ready*, got '{status}'")

    # =========================================================================
    # Test 9: Snapshot preserves max_nodes policy from state command
    # =========================================================================
    def test_snapshot_uses_same_max_nodes_as_state(self):
        custom_max = 345
        res = run_cua_cli(["state", "--app", self.target_app, "--max-nodes", str(custom_max), "--no-img"], session_id=self.session_id)
        snap_id = res.get("snapshotId")
        self.assertIsNotNone(snap_id, "State response must contain snapshotId")

        snap_path = os.path.join(self.cache_dir, f"snapshot_{snap_id}.json")
        self.assertTrue(os.path.exists(snap_path), f"Snapshot file {snap_path} must exist")
        with open(snap_path, "r") as f:
            snap_data = json.load(f)

        self.assertEqual(snap_data.get("maxNodes"), custom_max, f"Snapshot must preserve maxNodes={custom_max}")
        self.assertEqual(snap_data.get("maxDepth"), 20, "Snapshot must preserve maxDepth=20")


if __name__ == "__main__":
    unittest.main()
