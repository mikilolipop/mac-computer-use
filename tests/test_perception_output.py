"""Synthetic perception tests; no browser or desktop input."""
import base64
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sdk.state_output import render_state
from sdk import mcp_server as mcp
from sdk.cua_client import CuaError


class PerceptionTests(unittest.TestCase):
    def setUp(self):
        self.state = {"snapshotId": "example", "text": "[1] AXComboBox Search", "diff": "+ Search",
                      "elements": [{"index": 1, "role": "AXComboBox", "title": "Search"}],
                      "elementCount": 1, "timingsMs": {"axCollection": 12}}

    def test_default_returns_one_text_representation_without_elements(self):
        response = render_state(self.state)
        out = json.loads(response["content"][0]["text"])
        self.assertNotIn("elements", out)
        self.assertNotIn("diff", out)
        self.assertEqual(out["text"], self.state["text"])
        self.assertEqual(len(response["content"]), 1)
        self.assertIn("elements", self.state)  # Original snapshot remains intact.
        self.assertEqual(out["timingsMs"]["axCollection"], 12)

    def test_diff_mode_keeps_initial_baseline(self):
        state = dict(self.state, diff="(initial baseline tree)")
        first = json.loads(render_state(state, view="diff")["content"][0]["text"])
        self.assertIn("text", first)
        second = json.loads(render_state(self.state, view="diff")["content"][0]["text"])
        self.assertNotIn("text", second)
        self.assertEqual(second["diff"], "+ Search")

    def test_explicit_elements_available(self):
        out = json.loads(render_state(self.state, include_elements=True)["content"][0]["text"])
        self.assertEqual(out["elements"], self.state["elements"])

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Optional Pillow image backend not installed")
    def test_image_is_bounded_with_geometry_metadata(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "preview with spaces.png"
            Image.new("RGB", (3200, 1800), "white").save(path)
            state = dict(self.state, screenshotUrl=path.as_uri(), windowBounds={"x": 20, "y": 40, "width": 1600, "height": 900})
            response = render_state(state, no_img=False, image_max_edge=1280)
        meta = json.loads(response["content"][0]["text"])
        image = response["content"][1]
        self.assertEqual(image["mimeType"], "image/jpeg")
        with Image.open(io.BytesIO(base64.b64decode(image["data"]))) as im:
            self.assertEqual(im.size, (1280, 720))
        self.assertEqual(meta["imageDelivery"]["sourceSize"], [3200, 1800])
        self.assertEqual(meta["windowBounds"], state["windowBounds"])

    def test_missing_image_is_reported(self):
        state = dict(self.state, screenshotUrl="/no/such/image.png")
        response = render_state(state, no_img=False)
        meta = json.loads(response["content"][0]["text"])
        self.assertEqual(meta["imageDelivery"]["status"], "unavailable")
        self.assertEqual(len(response["content"]), 1)

    def test_batch_observes_once_without_another_model_call(self):
        fake = Mock()
        fake.batch.return_value = {"success": True, "status": "dispatched", "executed": 1}
        fake.get_state.return_value = self.state
        with patch.object(mcp, "client", fake):
            response = mcp.handle_call_tool({"name": "batch_actions", "arguments": {
                "app": "fixture", "actions": [{"action": "wait", "waitMs": 0}], "observe_after": True}})
        self.assertEqual(fake.batch.call_count, 1)
        self.assertEqual(fake.get_state.call_count, 1)
        self.assertFalse(response["isError"])
        self.assertEqual(json.loads(response["content"][0]["text"])["observationStatus"], "captured")

    def test_observation_failure_does_not_retry_dispatched_action(self):
        fake = Mock()
        fake.batch.return_value = {"success": True, "status": "dispatched", "executed": 1}
        fake.get_state.side_effect = CuaError({"error": "unavailable"})
        with patch.object(mcp, "client", fake):
            response = mcp.handle_call_tool({"name": "batch_actions", "arguments": {
                "app": "fixture", "actions": [{"action": "wait", "waitMs": 0}], "observe_after": True}})
        out = json.loads(response["content"][0]["text"])
        self.assertEqual(fake.batch.call_count, 1)
        self.assertEqual(out["observationStatus"], "failed")
        self.assertEqual(out["status"], "dispatched")

    def test_default_mcp_state_skips_capture(self):
        fake = Mock()
        fake.get_state.return_value = self.state
        with patch.object(mcp, "client", fake):
            mcp.handle_call_tool({"name": "get_app_state", "arguments": {"app": "fixture"}})
        self.assertTrue(fake.get_state.call_args.kwargs["no_img"])
        self.assertFalse(fake.get_state.call_args.kwargs["annotate"])

    def test_metric_log_contains_counts_not_page_content(self):
        fake = Mock()
        fake.get_state.return_value = dict(self.state, text="PRIVATE_PAGE_CONTENT")
        with patch.object(mcp, "client", fake), self.assertLogs(level="INFO") as logs:
            mcp.dispatch_request({"jsonrpc": "2.0", "id": 123, "method": "tools/call",
                "params": {"name": "get_app_state", "arguments": {"app": "fixture"}}})
        joined = "\n".join(logs.output)
        self.assertIn("toolMs", joined)
        self.assertIn("responseBytes", joined)
        self.assertNotIn("PRIVATE_PAGE_CONTENT", joined)


if __name__ == "__main__":
    unittest.main()
