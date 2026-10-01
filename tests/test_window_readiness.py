"""Window routing and bounded observation, without desktop input."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdk.cua_client import CuaClient, CuaError
from sdk import mcp_server as mcp

class WindowReadinessTests(unittest.TestCase):
    def setUp(self):
        self.client = CuaClient(binary_path=sys.executable)

    def call(self, name, args):
        return mcp.handle_call_tool({"name": name, "arguments": args})

    def test_window_reaches_native_state_batch_and_ocr(self):
        with patch('sdk.cua_client.subprocess.run', return_value=Mock(stdout='{"success":true}', returncode=0)) as run:
            self.client.get_state('Edge', window_id=42, prepare_web=True, no_img=True)
            argv = run.call_args.args[0]
            self.assertEqual(argv[-2:], ['--window-id', '42'])
            self.assertIn('--prepare-web', argv)
            self.client.batch('Edge', [{'action':'press_key','key':'return'}], window_id=42)
            self.assertEqual(run.call_args.args[0][-2:], ['--window-id', '42'])
            self.client.find_text('Edge', 'result', window_id=42)
            self.assertEqual(run.call_args.args[0][-2:], ['--window-id', '42'])

    def test_invalid_window_never_starts_native(self):
        with patch('sdk.cua_client.subprocess.run') as run:
            for bad in [0, -1, True, '42']:
                with self.assertRaises(ValueError):
                    self.client.get_state('Edge', window_id=bad)
            run.assert_not_called()

    def test_mcp_forwards_window_for_indexed_action(self):
        fake = Mock()
        fake.click.return_value = True
        with patch.object(mcp, 'client', fake):
            self.call('click', {'app':'Edge','element_index':3,'snapshot_id':'token','window_id':42})
        fake.click.assert_called_once_with('Edge', 3, snapshot_id='token', window_id=42)

    def test_delayed_marker_matches_and_pins_observed_window(self):
        with patch.object(self.client, 'get_state', side_effect=[{'text':'loading', 'windowId':42}, {'text':'Results ready', 'windowId':42}]) as state, patch('sdk.cua_client.time.sleep'):
            result = self.client.observe_until('Edge', 'results ready')
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['attempts'], 2)
        self.assertEqual(state.call_args.kwargs['window_id'], 42)
        self.assertTrue(state.call_args.kwargs['no_img'])

    def test_native_observation_timeout_becomes_readiness_timeout(self):
        with patch.object(self.client, 'get_state', side_effect=CuaError({'code':'TIMEOUT'})):
            result = self.client.observe_until('Edge', 'result')
        self.assertEqual(result['status'], 'timeout')

    def test_expired_budget_stops_polling(self):
        with patch('sdk.cua_client.time.perf_counter', side_effect=[0, 2, 2]), patch.object(self.client, 'get_state') as state:
            result = self.client.observe_until('Edge', 'result', timeout=1)
        self.assertEqual(result['status'], 'timeout')
        state.assert_not_called()

    def test_runtime_window_error_is_not_retried(self):
        with patch.object(self.client, 'get_state', side_effect=CuaError({'code':'WINDOW_UNAVAILABLE'})) as state:
            with self.assertRaises(CuaError):
                self.client.observe_until('Edge', 'result', window_id=42)
        state.assert_called_once()

    def test_wait_timeout_preserves_success_and_never_replays_batch(self):
        fake=Mock()
        fake.batch.return_value={'success':True,'executed':2,'status':'dispatched'}
        fake.observe_until.return_value={'status':'timeout','attempts':2}
        with patch.object(mcp,'client',fake):
            out=self.call('batch_actions', {'app':'Edge','window_id':42,'actions':[{'action':'press_key','key':'return'}], 'wait_for_text':'Results'})
        payload=json.loads(out['content'][0]['text'])
        self.assertTrue(payload['success'])
        self.assertEqual(payload['readiness']['status'],'timeout')
        self.assertEqual(payload['observationStatus'],'failed')
        fake.batch.assert_called_once()
        fake.get_state.assert_not_called()

    def test_matching_state_reused_without_extra_capture(self):
        fake=Mock()
        fake.batch.return_value={'success':True}
        fake.observe_until.return_value={'status':'matched','state':{'text':'Results', 'windowId':42}, 'attempts':1}
        with patch.object(mcp,'client',fake):
            out=self.call('batch_actions', {'app':'Edge','actions':[{'action':'press_key','key':'return'}], 'wait_for_text':'Results'})
        self.assertFalse(out.get('isError',False))
        fake.batch.assert_called_once()
        fake.get_state.assert_not_called()

    def test_bad_readiness_options_rejected_before_action(self):
        fake=Mock()
        with patch.object(mcp,'client',fake):
            for options in [{'wait_for_text':' '}, {'readiness_timeout_ms':200}, {'wait_for_text':'R','readiness_timeout_ms':11000}]:
                out=self.call('batch_actions', dict(app='Edge',actions=[{'action':'press_key','key':'return'}], **options))
                self.assertTrue(out['isError'])
        fake.batch.assert_not_called()

    def test_image_after_marker_keeps_same_window(self):
        fake=Mock()
        fake.batch.return_value={'success':True}
        fake.observe_until.return_value={'status':'matched','state':{'text':'Results','windowId':42},'attempts':1}
        fake.get_state.return_value={'text':'Results','windowId':42}
        with patch.object(mcp,'client',fake):
            self.call('batch_actions', {'app':'Edge','actions':[{'action':'press_key','key':'return'}], 'wait_for_text':'Results','observation_no_img':False})
        self.assertEqual(fake.get_state.call_args.kwargs['window_id'],42)

    def test_mcp_prepares_web_by_default_and_can_disable(self):
        fake=Mock()
        fake.get_state.return_value={'text':'browser'}
        with patch.object(mcp,'client',fake):
            self.call('get_app_state', {'app':'Edge','window_id':42})
            self.assertTrue(fake.get_state.call_args.kwargs['prepare_web'])
            self.call('get_app_state', {'app':'Edge','prepare_web':False})
            self.assertFalse(fake.get_state.call_args.kwargs['prepare_web'])

    def test_scoped_type_requires_app_before_backend(self):
        fake=Mock()
        with patch.object(mcp,'client',fake):
            out=self.call('type_text', {'text':'hello','window_id':42})
        self.assertTrue(out['isError'])
        fake.type_text.assert_not_called()
