"""TTS 계약과 Realtime 이벤트 처리 검사. 실제 API 호출 없음."""
import base64
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_script_generator as script_tests
import test_script_reviser as reviser_tests
from notebook_loader import load_definitions


class TTSGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reviser_tests.ScriptReviserTests.setUpClass()
        cls.ns = dict(reviser_tests.ScriptReviserTests.ns)
        load_definitions(cls.ns, 'tts_generator')

    def setUp(self):
        fixture = script_tests.ScriptGeneratorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.state = fixture.state
        scenes, script, _ = fixture.resolve()
        self.state.update(scenes=scenes, full_script=script,
                          validation_result={'is_valid': True, 'error_type': 'none', 'issues': []},
                          audio_path='old.wav', video_path='old.mp4', tts_duration_sec=25)
        self.sent = []
        self.connects = []

    def fake_connect(self, durations=None, bad=None):
        durations = durations or [6] * 4
        sent, connects = self.sent, self.connects
        class Socket:
            def __init__(self):
                self.queue = [{'type': 'session.created'}]
                self.index = 0
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def send(self, raw):
                data = json.loads(raw)
                sent.append(data)
                if data['type'] == 'session.update':
                    self.queue.append({'type': 'session.updated'})
                    return
                self.index += 1
                text = data['response']['input'][0]['content'][0]['text']
                pcm = b'\x10\x00' * round(durations[self.index - 1] * 24000)
                if bad == 'truncated_pcm': pcm = b'\x00'
                if bad == 'empty': pcm = b''
                if bad == 'silence': pcm = bytes(len(pcm))
                transcript = text + ' invented claim' if bad == 'transcript' else text
                usage = {'input_tokens': 100, 'output_tokens': 70,
                         'input_token_details': {'text_tokens': 100, 'audio_tokens': 0,
                                                 'cached_tokens_details': {'text_tokens': 0, 'audio_tokens': 0}},
                         'output_token_details': {'text_tokens': 20, 'audio_tokens': 50}}
                if bad == 'missing_usage': usage = None
                self.queue += [
                    {'type': 'response.created'},
                    {'type': 'response.output_audio.delta', 'delta': base64.b64encode(pcm).decode()},
                    {'type': 'response.output_audio_transcript.done', 'transcript': transcript},
                    {'type': 'response.output_audio.done'},
                    {'type': 'response.done', 'response': {
                        'status': 'incomplete' if bad == 'incomplete' else 'completed', 'usage': usage}},
                ]
                if bad == 'api': self.queue = [{'type': 'error', 'error': {'code': 'invalid_request'}}]
                if bad == 'second_scene' and self.index == 2: self.queue = [{'type': 'error'}]
            def recv(self, timeout):
                assert timeout > 0
                if bad == 'timeout': raise TimeoutError('simulated timeout')
                return json.dumps(self.queue.pop(0))
        def connect(*args, **kwargs):
            connects.append(args)
            return Socket()
        return connect

    def run_node(self, durations=None, bad=None):
        with patch.dict(self.ns, {'realtime_connect': self.fake_connect(durations, bad)}):
            return self.ns['tts_generator'](self.state)

    def test_success_real_wav_merge_preserves_script_and_input(self):
        before = copy.deepcopy(self.state)
        update = self.run_node([8, 5, 5, 6])
        self.assertEqual(update['status'], 'running', update)
        self.assertEqual(self.state, before)
        self.assertEqual(update['tts_duration_sec'], 24)
        self.assertEqual(self.ns['route_after_tts']({**self.state, **update}), 'VideoRenderer')
        self.assertNotIn('retry_count', update)
        self.assertEqual(update['video_path'], '')
        self.assertFalse(update['qa_result']['is_passed'])
        for old, new in zip(self.state['scenes'], update['scenes']):
            for key in old.keys() - {'audio_segment_path', 'duration_sec'}:
                self.assertEqual(old[key], new[key])
            duration, _ = self.ns['read_tts_wav'](new['audio_segment_path'])
            self.assertEqual(duration, new['duration_sec'])
        self.assertEqual(len(self.connects), 1)
        self.assertEqual(len(self.sent), 5)
        self.assertTrue(all(s['response']['conversation'] == 'none' for s in self.sent[1:]))
        report = json.loads(Path(update['tts_json_path']).read_text(encoding='utf-8'))
        self.assertEqual(report['model_calls'], 4)
        self.assertTrue(report['tts_measured'])
        self.assertGreater(report['estimated_cost_usd'], 0)

    def test_duration_boundaries_and_revision_routes(self):
        for duration, route in [(20, 'VideoRenderer'), (30, 'VideoRenderer'), (19.6, 'ScriptReviser'), (30.4, 'ScriptReviser')]:
            with self.subTest(duration=duration):
                update = self.run_node([duration / 4] * 4)
                self.assertEqual(update['status'], 'running', update)
                self.assertEqual(self.ns['route_after_tts']({**self.state, **update}), route)
                self.assertAlmostEqual(update['tts_duration_sec'], duration)

    def test_exhausted_budget_only_blocks_length_error(self):
        self.state['retry_count'] = 3
        update = self.run_node([8] * 4)
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(update['tts_duration_sec'], 32)
        self.assertEqual(self.ns['route_after_tts']({**self.state, **update}), 'END')
        update = self.run_node()
        self.assertEqual(self.ns['route_after_tts']({**self.state, **update}), 'VideoRenderer')

    def test_unverified_or_inconsistent_inputs_block_before_connection(self):
        original = copy.deepcopy(self.state)
        for kind in ['status', 'unverified', 'issues', 'subtitle', 'full_script', 'scene_order', 'language', 'excluded']:
            self.state = copy.deepcopy(original)
            if kind == 'status': self.state['status'] = 'failed'
            if kind == 'unverified': self.state['validation_result']['is_valid'] = False
            if kind == 'issues': self.state['validation_result']['issues'] = [{'claim': 'unresolved'}]
            if kind == 'subtitle': self.state['scenes'][0]['subtitle'] = 'Different.'
            if kind == 'full_script': self.state['full_script'] = 'Different.'
            if kind == 'scene_order': self.state['scenes'][0]['scene_no'] = 2
            if kind == 'language': self.state['scenes'][0]['narration'] = '한국어 문장'
            if kind == 'excluded': self.state['scenes'][0]['narration'] = 'Price $20'
            update = self.run_node()
            self.assertEqual(update['status'], 'failed', update)
            self.assertEqual(update['audio_path'], '')
        self.assertEqual(self.connects, [])

    def test_failed_partial_generation_never_exposes_audio(self):
        for kind in ['second_scene', 'transcript', 'incomplete', 'empty', 'silence', 'truncated_pcm', 'api', 'timeout']:
            with self.subTest(kind=kind):
                update = self.run_node(bad=kind)
                self.assertEqual(update['status'], 'failed', update)
                self.assertEqual(update['audio_path'], '')
                self.assertEqual(update['tts_duration_sec'], 0)
                self.assertTrue(all(s['audio_segment_path'] is None for s in update['scenes']))
                self.assertEqual(self.ns['route_after_tts']({**self.state, **update}), 'END')
                report = json.loads(Path(update['tts_json_path']).read_text(encoding='utf-8'))
                self.assertEqual(report['status'], 'failed')
                self.assertIsNone(report['estimated_cost_usd'])

    def test_missing_usage_does_not_report_free_generation(self):
        update = self.run_node(bad='missing_usage')
        self.assertEqual(update['status'], 'running')
        report = json.loads(Path(update['tts_json_path']).read_text(encoding='utf-8'))
        self.assertIsNone(report['estimated_cost_usd'])

    def test_runs_use_separate_directories(self):
        first, second = self.run_node(), self.run_node()
        self.assertNotEqual(first['audio_path'], second['audio_path'])
        self.assertTrue(Path(first['audio_path']).is_file())

    def test_wav_corruption_and_transcript_normalization(self):
        path = Path(self.state['output_dir']) / 'bad.wav'
        path.write_bytes(b'not a wav')
        with self.assertRaises(Exception): self.ns['read_tts_wav'](path)
        self.assertEqual(self.ns['tts_text_key']("Meet NOVA’s Cream!"), self.ns['tts_text_key']("meet nova's cream."))
        self.assertNotEqual(self.ns['tts_text_key']('15 hours'), self.ns['tts_text_key']('50 hours'))


if __name__ == '__main__':
    unittest.main()
