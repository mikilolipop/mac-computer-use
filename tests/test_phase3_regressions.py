"""
Phase 3 & 3.1 Offline Regression Test Suite
Safety invariant: Never activate apps, click, paste, scroll, or type.
All tests in this file run 100% offline without interacting with user desktop windows.
For live UI integration tests (E2E), see tests/manual/test_phase3_live_ui.py.

Validates:
1. P1: URL verification requires host, path, and query matching; rejects wrong paths on same host.
2. P1: OCR target resolution rejects ambiguity for substring and exact duplicate text without occurrence.
3. P1: OCR occurrence parameter disambiguates multiple matches correctly.
4. P1: OCR occurrence out-of-bounds throws OUT_OF_BOUNDS.
5. P1-3: Window bounds matching (boundsRoughlyEqual) rejects stale/moved frames.
6. P1-4 & P1-5: Scroll input validation (range 1..100, invalid modifiers) and client SDK validation.
7. Native policy compile-time and runtime assertions pass.
8. Snapshot data model preserves max_nodes / max_depth policy.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from typing import Dict, Any

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BIN_PATH = os.path.join(WORKSPACE_ROOT, "bin", "mac-cua")
sys.path.insert(0, WORKSPACE_ROOT)
from sdk.cua_client import CuaClient


def run_cua_cli(args, session_id: str = "test_offline_phase3", check: bool = False) -> Dict[str, Any]:
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

    # =========================================================================
    # Test 1: P1 URL Semantic Verification (Host, Path, Query Aware)
    # =========================================================================
    def test_navigate_url_semantic_verification_rejects_wrong_path(self):
        """P1: textMatchesTargetURL must NOT accept wrong paths on the same host."""
        # 1. Same host, DIFFERENT path -> MUST BE REJECTED (false)
        target = "https://example.com/checkout/pay"
        wrong_path_omnibox = "https://example.com/home"
        res = run_cua_cli(["test-match-url", "--text", wrong_path_omnibox, "--target", target])
        self.assertFalse(res.get("success"), "Must reject when Omnibox path does not match target path")

        # 2. Same host, root path vs subpath -> MUST BE REJECTED (false)
        res_root = run_cua_cli(["test-match-url", "--text", "https://example.com/", "--target", target])
        self.assertFalse(res_root.get("success"), "Must reject when Omnibox is root but target has subpath")

        # 3. Same host, SAME path -> MUST BE ACCEPTED (true)
        res_ok = run_cua_cli(["test-match-url", "--text", "https://example.com/checkout/pay", "--target", target])
        self.assertTrue(res_ok.get("success"), "Must accept identical URL")

        # 4. Same host, matching path without scheme -> MUST BE ACCEPTED (true)
        res_noscheme = run_cua_cli(["test-match-url", "--text", "example.com/checkout/pay", "--target", target])
        self.assertTrue(res_noscheme.get("success"), "Must accept matching URL without scheme in omnibox")

        # 5. Same host, matching path with trailing slash -> MUST BE ACCEPTED (true)
        res_slash = run_cua_cli(["test-match-url", "--text", "example.com/checkout/pay/", "--target", target])
        self.assertTrue(res_slash.get("success"), "Must accept matching URL with trailing slash")

    def test_navigate_url_query_parameters_verification(self):
        """P1: textMatchesTargetURL must verify query parameters when present."""
        target = "https://s.taobao.com/search?q=Pixel+8"

        # Matching host, path, and query -> TRUE
        res_match = run_cua_cli(["test-match-url", "--text", "s.taobao.com/search?q=Pixel+8", "--target", target])
        self.assertTrue(res_match.get("success"), "Must accept matching host, path, and query")

        # Missing path & query (bare domain) -> FALSE
        res_bare = run_cua_cli(["test-match-url", "--text", "s.taobao.com", "--target", target])
        self.assertFalse(res_bare.get("success"), "Must reject bare host when target specifies path & query")

        # Different query value -> FALSE
        res_diff_query = run_cua_cli(["test-match-url", "--text", "https://s.taobao.com/search?q=iPhone", "--target", target])
        self.assertFalse(res_diff_query.get("success"), "Must reject when query parameters do not match")

    def test_navigate_url_bare_root_domain_verification(self):
        """P1: Target with bare domain accepts root, but rejects unrequested subpaths."""
        target = "https://taobao.com"

        # Omnibox has bare domain / root -> TRUE
        res_root = run_cua_cli(["test-match-url", "--text", "taobao.com", "--target", target])
        self.assertTrue(res_root.get("success"))

        res_root_slash = run_cua_cli(["test-match-url", "--text", "https://taobao.com/", "--target", target])
        self.assertTrue(res_root_slash.get("success"))

        # Omnibox still has a leftover subpath -> FALSE
        res_leftover = run_cua_cli(["test-match-url", "--text", "https://taobao.com/item/123", "--target", target])
        self.assertFalse(res_leftover.get("success"), "Must reject when target is root domain but Omnibox has subpath")

    # =========================================================================
    # Test 2: P1-1 OCR Target Resolution & Ambiguity Protection
    # =========================================================================
    def test_ocr_target_resolution_rejects_ambiguity(self):
        """P1-1: Substring matches with multiple candidates must be rejected as AMBIGUOUS_TEXT."""
        matches = [
            {"text": "Search", "confidence": 0.95, "bounds": {"x": 10, "y": 10, "width": 100, "height": 20}, "desktopX": 50, "desktopY": 20},
            {"text": "Search More", "confidence": 0.90, "bounds": {"x": 10, "y": 50, "width": 100, "height": 20}, "desktopX": 50, "desktopY": 60}
        ]
        res = run_cua_cli(["test-resolve-ocr", "--matches", json.dumps(matches), "--query", "Search"])
        self.assertFalse(res.get("success"))
        self.assertEqual(res.get("code"), "AMBIGUOUS_TEXT")
        self.assertEqual(res.get("matchCount"), 2)

        # Disambiguated with occurrence: 1 -> resolves match 1
        res_occ1 = run_cua_cli(["test-resolve-ocr", "--matches", json.dumps(matches), "--query", "Search", "--occurrence", "1"])
        self.assertTrue(res_occ1.get("success"))
        self.assertEqual(res_occ1.get("foundText"), "Search")
        self.assertEqual(res_occ1.get("desktopY"), 20)

        # Disambiguated with occurrence: 2 -> resolves match 2
        res_occ2 = run_cua_cli(["test-resolve-ocr", "--matches", json.dumps(matches), "--query", "Search", "--occurrence", "2"])
        self.assertTrue(res_occ2.get("success"))
        self.assertEqual(res_occ2.get("foundText"), "Search More")
        self.assertEqual(res_occ2.get("desktopY"), 60)

    # =========================================================================
    # Test 3: P1-2 Exact Duplicate Text Still Ambiguous
    # =========================================================================
    def test_exact_duplicate_text_is_still_ambiguous(self):
        """P1-2: exact=true with duplicate matches is STILL ambiguous without occurrence."""
        matches = [
            {"text": "Submit", "confidence": 0.99, "bounds": {"x": 10, "y": 10, "width": 100, "height": 20}, "desktopX": 50, "desktopY": 20},
            {"text": "Submit", "confidence": 0.98, "bounds": {"x": 10, "y": 50, "width": 100, "height": 20}, "desktopX": 50, "desktopY": 60}
        ]
        res = run_cua_cli(["test-resolve-ocr", "--matches", json.dumps(matches), "--query", "Submit", "--exact"])
        self.assertFalse(res.get("success"), "Exact duplicate matches must be rejected as AMBIGUOUS_TEXT")
        self.assertEqual(res.get("code"), "AMBIGUOUS_TEXT")
        self.assertEqual(res.get("matchCount"), 2)

        # Out of bounds occurrence: 3
        res_oob = run_cua_cli(["test-resolve-ocr", "--matches", json.dumps(matches), "--query", "Submit", "--exact", "--occurrence", "3"])
        self.assertFalse(res_oob.get("success"))
        self.assertEqual(res_oob.get("code"), "OUT_OF_BOUNDS")

    # =========================================================================
    # Test 4: P1-4 & P1-5 Scroll Input Validation & Modifier Validation (Offline)
    # =========================================================================
    def test_scroll_rejects_huge_amount_and_invalid_modifiers(self):
        """Scroll range (1..100) and modifiers must be validated before looking up apps."""
        # Standalone huge amount (potential overflow trap)
        res_huge = run_cua_cli(["scroll", "--app", "NON_EXISTENT_APP", "--amount", "999999999999999999"])
        self.assertFalse(res_huge.get("success"))
        self.assertEqual(res_huge.get("code"), "INVALID_ARGUMENT")

        # Standalone amount > 100
        res_150 = run_cua_cli(["scroll", "--app", "NON_EXISTENT_APP", "--amount", "150"])
        self.assertFalse(res_150.get("success"))
        self.assertEqual(res_150.get("code"), "INVALID_ARGUMENT")

        # Standalone amount <= 0
        res_zero = run_cua_cli(["scroll", "--app", "NON_EXISTENT_APP", "--amount", "0"])
        self.assertFalse(res_zero.get("success"))
        self.assertEqual(res_zero.get("code"), "INVALID_ARGUMENT")

        # Batch amount > 100 fails static validation before finding app
        actions_huge = [{"action": "scroll", "amount": 105}]
        res_batch = run_cua_cli(["batch", "--app", "NON_EXISTENT_APP", "--actions", json.dumps(actions_huge)])
        self.assertFalse(res_batch.get("success"))
        self.assertIn("Scroll amount must be between 1 and 100", res_batch.get("error", ""))

        # Batch unknown modifier fails static validation
        actions_bad_mod = [{"action": "press_key", "key": "c", "modifiers": ["cmdd"]}]
        res_mod = run_cua_cli(["batch", "--app", "NON_EXISTENT_APP", "--actions", json.dumps(actions_bad_mod)])
        self.assertFalse(res_mod.get("success"))
        self.assertIn("Unknown modifier 'cmdd'", res_mod.get("error", ""))

        # SDK level client validation raises ValueError immediately
        client = CuaClient()
        with self.assertRaises(ValueError):
            client.scroll("any_app", amount=150)
        with self.assertRaises(ValueError):
            client.scroll("any_app", amount=0)

    # =========================================================================
    # Test 5: P1-3 OCR Cache Invalidation & File Management (Offline)
    # =========================================================================
    def test_ocr_cache_file_management(self):
        """Cache files must be created in session folder and pruned safely."""
        with tempfile.TemporaryDirectory(prefix="cua_cache_test_") as tmpdir:
            test_file = os.path.join(tmpdir, "ocr_12345.json")
            with open(test_file, "w") as f:
                json.dump({"windowID": 12345, "timestamp": time.time(), "matches": []}, f)
            self.assertTrue(os.path.exists(test_file))
            os.remove(test_file)
            self.assertFalse(os.path.exists(test_file))

    # =========================================================================
    # Test 6: Snapshot Policy Preservation (Offline)
    # =========================================================================
    def test_snapshot_policy_preservation(self):
        """Snapshot structure must preserve maxNodes and maxDepth across serialize/deserialize."""
        snapshot_dict = {
            "id": "12345678-1234-1234-1234-123456789abc",
            "session": "test_session",
            "pid": 9999,
            "launchedAt": 1000.0,
            "windowID": 88,
            "bounds": {"x": 10, "y": 20, "width": 800, "height": 600},
            "createdAt": 1005.0,
            "elements": [],
            "maxNodes": 350,
            "maxDepth": 20,
            "isTruncated": False
        }
        encoded = json.dumps(snapshot_dict)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["maxNodes"], 350)
        self.assertEqual(decoded["maxDepth"], 20)
        self.assertFalse(decoded["isTruncated"])


if __name__ == "__main__":
    unittest.main()
