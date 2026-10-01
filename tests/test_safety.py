"""Offline regression tests: never activate apps, click, paste, or type."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sdk import mcp_server as mcp
from sdk.cua_client import CuaClient, CuaError


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.fake = Mock()
        self.scope = patch.object(mcp, "client", self.fake)
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def call(self, name, args):
        return mcp.dispatch_request({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                     "params": {"name": name, "arguments": args}})

    def test_invalid_requests_have_errors(self):
        for req in [[], None, 4, {}, {"jsonrpc": "1.0", "method": "ping"},
                    {"jsonrpc": "2.0", "method": "ping", "id": True}]:
            with self.subTest(req=req):
                self.assertEqual(mcp.dispatch_request(req)["error"]["code"], -32600)

    def test_notifications_do_not_reply_or_execute(self):
        for method in ["ping", "notifications/initialized", "tools/call"]:
            self.assertIsNone(mcp.dispatch_request({"jsonrpc": "2.0", "method": method,
                "params": {"name": "type_text", "arguments": {"text": "DO_NOT_TYPE"}}}))
        self.assertEqual(self.fake.mock_calls, [])

    def test_invalid_params(self):
        req = {"jsonrpc": "2.0", "id": "a", "method": "tools/call", "params": []}
        self.assertEqual(mcp.dispatch_request(req)["error"]["code"], -32602)

    def test_schema_rejects_wrong_types_before_backend(self):
        for name, args in [("click", {"app": "a", "element_index": True, "snapshot_id": "x"}),
                           ("click", {"app": "a", "element_index": 1}),
                           ("click_coord", {"x": float("inf"), "y": 2}),
                           ("type_text", {"text": 4}),
                           ("doctor", {"prompt": "true"}),
                           ("doctor", {"typo": False})]:
            with self.subTest(name=name, args=args):
                self.assertTrue(self.call(name, args)["result"]["isError"])
        self.assertEqual(self.fake.mock_calls, [])

    def test_state_failure_is_tool_error(self):
        self.fake.get_state.return_value = {"success": False, "error": "missing app"}
        self.assertTrue(self.call("get_app_state", {"app": "missing"})["result"]["isError"])

    def test_native_error_payload_survives(self):
        self.fake.click.side_effect = CuaError({"success": False, "code": "STALE_SNAPSHOT", "error": "expired"})
        response = self.call("click", {"app": "a", "element_index": 1, "snapshot_id": "x"})
        self.assertEqual(json.loads(response["result"]["content"][0]["text"])["code"], "STALE_SNAPSHOT")

    def test_snapshot_forwarded(self):
        self.fake.click.return_value = True
        self.call("click", {"app": "a", "element_index": 1, "snapshot_id": "token"})
        self.fake.click.assert_called_once_with("a", 1, snapshot_id="token")

    def test_tool_discovery_is_independent_of_binary(self):
        with patch.object(mcp, "client", None), patch.object(mcp, "CuaClient", side_effect=AssertionError("should not construct")):
            response = mcp.dispatch_request({"jsonrpc": "2.0", "id": 0, "method": "tools/list"})
        names = {t["name"] for t in response["result"]["tools"]}
        self.assertTrue({"doctor", "get_app_state", "batch_actions", "type_text"} <= names)
        self.assertEqual(response["id"], 0)

    def test_stdio_survives_bad_json_and_array(self):
        requests = '{bad\n[]\n' + json.dumps({"jsonrpc": "2.0", "method": "ping"}) + '\n' + json.dumps({"jsonrpc": "2.0", "id": 9, "method": "ping"}) + '\n'
        proc = subprocess.run([sys.executable, str(ROOT / "sdk/mcp_server.py")], input=requests,
                              text=True, capture_output=True, timeout=5)
        responses = [json.loads(x) for x in proc.stdout.splitlines()]
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["error"]["code"], -32600)
        self.assertEqual(responses[2]["id"], 9)


class SDKTests(unittest.TestCase):
    def setUp(self):
        self.client = CuaClient(binary_path=sys.executable)

    def test_invalid_native_json(self):
        with patch("sdk.cua_client.subprocess.run", return_value=Mock(stdout="oops", returncode=1)):
            with self.assertRaises(CuaError) as caught:
                self.client._run(["state"])
        self.assertEqual(caught.exception.payload["code"], "INVALID_RESPONSE")

    def test_nonzero_exit_cannot_look_successful(self):
        with patch("sdk.cua_client.subprocess.run", return_value=Mock(stdout='{"success":true}', returncode=2)):
            with self.assertRaises(CuaError):
                self.client._run(["state"])

    def test_timeout_does_not_echo_private_input(self):
        with patch("sdk.cua_client.subprocess.run", side_effect=subprocess.TimeoutExpired("test", 1)):
            with self.assertRaises(CuaError) as caught:
                self.client._run(["type-text", "--text", "PRIVATE_CONTENT"])
        self.assertNotIn("PRIVATE_CONTENT", str(caught.exception))
        self.assertEqual(caught.exception.payload["code"], "TIMEOUT")

    def test_indexed_action_requires_snapshot(self):
        with patch("sdk.cua_client.subprocess.run") as run:
            with self.assertRaises(CuaError):
                self.client.click("a", 1)
            run.assert_not_called()

    def test_annotation_failure_is_visible(self):
        with tempfile.NamedTemporaryFile() as image:
            with patch.object(self.client, "_run", return_value={"snapshotId": "token", "screenshotUrl": image.name, "elements": [{"index": 1}]}), patch("sdk.cua_client.annotate_screenshot", side_effect=ValueError("bad geometry")):
                state = self.client.get_state("a")
        self.assertEqual(state["annotationStatus"], "failed")
        self.assertEqual(self.client.snapshots["a"], "token")


@unittest.skipUnless(sys.platform == "darwin", "Swift macOS policy tests")
class NativePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="cua_policy_tests_")
        cls.addClassCleanup(cls.tmp.cleanup)
        source = (ROOT / "native_engine/mac_cua_engine.swift").read_text()
        # Compile the actual production functions with a test entrypoint, no UI calls.
        source = source.rsplit("\nmain()", 1)[0]
        harness = (ROOT / "tests/native_policy_harness.swift").read_text()
        path = Path(cls.tmp.name) / "main.swift"
        path.write_text(source + "\n" + harness)
        swiftc_cmd = ["swiftc"]
        if os.path.exists("/usr/bin/swiftc"):
            swiftc_cmd = ["/usr/bin/swiftc"]
        elif subprocess.run(["which", "xcrun"], capture_output=True).returncode == 0:
            try:
                found = subprocess.check_output(["xcrun", "-find", "swiftc"], text=True).strip()
                if os.path.exists(found):
                    swiftc_cmd = [found]
            except Exception:
                pass

        cls.binary = str(Path(cls.tmp.name) / "policy-tests")
        result = subprocess.run(swiftc_cmd + [str(path), "-o", cls.binary], capture_output=True, text=True, timeout=90)
        if result.returncode:
            err = (result.stderr or "") + "\n" + (result.stdout or "")
            raise AssertionError(f"swiftc compilation failed (code {result.returncode}):\n{err.strip()}")

    def test_native_snapshot_and_preflight_policies(self):
        result = subprocess.run([self.binary], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("POLICY_CHECKS_PASSED", result.stdout)

    def test_cli_rejects_entire_batch_before_app_lookup(self):
        for actions in [[{"action": "wait", "waitMs": 0}, {"action": "unknown"}],
                        [{"action": "activate"}, {"action": "set_value", "element": 1}],
                        [{"action": "wait", "waitMs": 4294967295}]]:
            result = subprocess.run([self.binary, "batch", "--app", "APP_THAT_DOES_NOT_EXIST",
                                     "--actions", json.dumps(actions)], capture_output=True, text=True, timeout=5)
            response = json.loads(result.stdout)
            self.assertEqual(response["code"], "INVALID_ARGUMENT")
            self.assertEqual(response["executed"], 0)
            self.assertNotEqual(result.returncode, 0)


class BoostLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="boost_lease_tests_")
        self.addCleanup(self.tmp.cleanup)
        self.board = str(Path(self.tmp.name) / "board.json")
        self.command = [sys.executable, str(ROOT / ".agents/skills/boost/scripts/boost_coordinator.py"),
                        "--board", self.board]
        self.run_cli("init", "--task", "test")
        self.run_cli("add-task", "--id", "A", "--title", "A", "--owner", "worker")

    def run_cli(self, *args):
        return subprocess.run(self.command + list(args), text=True, capture_output=True, timeout=5)

    def test_two_claimants_only_one_wins(self):
        procs = [subprocess.Popen(self.command + ["start-task", "--id", "A", "--owner", owner],
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for owner in ("one", "two")]
        try:
            for p in procs:
                p.communicate(timeout=5)
            self.assertEqual(sum(p.returncode == 0 for p in procs), 1)
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
                p.wait(timeout=5)

    def test_old_lease_cannot_finish_retried_task(self):
        first = json.loads(self.run_cli("start-task", "--id", "A").stdout)["lease_id"]
        self.assertEqual(self.run_cli("reclaim-orphans", "--timeout", "0", "--retry").returncode, 0)
        second = json.loads(self.run_cli("start-task", "--id", "A").stdout)["lease_id"]
        self.assertNotEqual(first, second)
        stale = self.run_cli("complete-task", "--id", "A", "--lease", first, "--output", "stale")
        self.assertNotEqual(stale.returncode, 0)
        valid = self.run_cli("complete-task", "--id", "A", "--lease", second, "--output", "done")
        self.assertEqual(valid.returncode, 0, valid.stderr)

    def test_mission_cannot_finish_early_or_restart_after_abort(self):
        self.assertNotEqual(self.run_cli("complete-mission", "--summary", "premature").returncode, 0)
        self.run_cli("abort-mission", "--reason", "test")
        self.assertNotEqual(self.run_cli("start-task", "--id", "A").returncode, 0)


if __name__ == "__main__":
    unittest.main()
