"""QA 분기·판정 계약과 파형 비교 검사. API 호출 없음."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

import test_script_generator as script_tests
import test_video_renderer as render_tests
from notebook_loader import load_definitions


class VideoQATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        render_tests.VideoRendererTests.setUpClass()
        cls.ns = dict(render_tests.VideoRendererTests.ns)
        load_definitions(cls.ns, 'video_qa')

    def setUp(self):
        fixture = render_tests.VideoRendererTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.state = {**fixture.state, **fixture.render()}
        self.before = copy.deepcopy(self.state)

    def evaluate(self, fault=None):
        timeline, _, duration = self.ns['prepare_video_timeline'](self.state)
        metadata = {'size': [1080, 1920], 'fps': 30, 'codec': 'h264', 'audio_codec': 'aac',
                    'pix_fmt': 'yuv420p', 'duration': duration, 'format': 'mov,mp4', 'rotation': []}
        if fault == 'resolution': metadata['size'] = [1920, 1080]
        if fault == 'no_audio': metadata['audio_codec'] = None
        if fault == 'length': metadata['duration'] = 31
        if fault == 'sync': metadata['duration'] += 0.5
        if fault == 'rotation': metadata['rotation'] = [90]
        pcm = self.ns['read_tts_wav'](self.state['audio_path'])[1]
        def ffmpeg(arguments, workdir=None):
            if '-progress' in arguments:
                if fault == 'decode': raise self.ns['VideoQAError']('simulated damaged stream')
                return f'frame={timeline[-1]["end_frame"]}\nprogress=end\n'.encode()
            return pcm
        reference = np.full((480, 270, 3), 20, dtype=np.uint8)
        actual = reference.copy()
        if fault == 'image': actual[40:335] = 150
        if fault == 'caption': actual[335:420] = 150
        correlation = {'correlation': 0.2 if fault == 'audio_content' else 1,
                       'offset_sec': 0.5 if fault == 'offset' else 0}
        with patch.dict(self.ns, {'qa_video_metadata': lambda p: metadata, 'qa_ffmpeg': ffmpeg,
                                  'qa_audio_similarity': lambda a, b: correlation,
                                  'qa_frame': lambda *a: actual, 'qa_expected_frame': lambda *a: reference}):
            return self.ns['video_qa'](self.state)

    def test_success_preserves_input_and_completes(self):
        update = self.evaluate()
        self.assertEqual(update['status'], 'completed', update)
        self.assertTrue(update['qa_result']['is_passed'])
        self.assertEqual(self.state, self.before)
        self.assertNotIn('retry_count', update)
        self.assertNotIn('video_path', update)
        self.assertEqual(self.ns['route_after_video_qa']({**self.state, **update}), 'END')
        report = json.loads(Path(update['qa_json_path']).read_text(encoding='utf-8'))
        self.assertTrue(all(item['passed'] for item in report['checks']))
        self.assertEqual(len([c for c in report['checks'] if c['name'].endswith('_caption')]), 4)

    def test_rendering_faults_are_routed_to_renderer(self):
        for fault in ['resolution', 'rotation', 'no_audio', 'length', 'sync', 'decode', 'audio_content', 'offset', 'image', 'caption']:
            with self.subTest(fault=fault):
                update = self.evaluate(fault)
                self.assertFalse(update['qa_result']['is_passed'])
                self.assertEqual(update['status'], 'running', update)
                self.assertEqual(self.ns['route_after_video_qa']({**self.state, **update}), 'VideoRenderer')

    def test_exhausted_budget_stops_but_can_still_pass(self):
        self.state['retry_count'] = 3
        self.assertEqual(self.evaluate()['status'], 'completed')
        update = self.evaluate('caption')
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(update['qa_next_node'], 'END')

    def test_bad_source_stops_instead_of_useless_rerender(self):
        self.state['audio_path'] = 'missing.wav'
        update = self.ns['video_qa'](self.state)
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(update['qa_next_node'], 'END')

    def test_source_length_routes_to_reviser(self):
        short = Path(self.state['output_dir']) / 'short.wav'
        self.ns['write_tts_wav'](short, b'\x10\x00' * (15 * 24000))
        self.state['audio_path'] = str(short)
        update = self.ns['video_qa'](self.state)
        self.assertEqual(update['qa_result']['error_type'], 'duration_error')
        self.assertEqual(update['qa_next_node'], 'ScriptReviser')
        self.assertEqual(update['status'], 'running')
        self.assertEqual(update['tts_duration_sec'], 15)

    def test_changed_ass_is_rejected(self):
        report = json.loads(Path(self.state['render_json_path']).read_text(encoding='utf-8'))
        subtitle = Path(report['subtitle_path'])
        subtitle.write_text(subtitle.read_text(encoding='utf-8').replace('NOVA', 'WRONG'), encoding='utf-8')
        update = self.evaluate()
        self.assertFalse(update['qa_result']['is_passed'])
        self.assertIn('subtitle_script', update['qa_result']['details'])

    def test_changed_timeline_and_missing_video_are_rejected(self):
        report_path = Path(self.state['render_json_path'])
        report = json.loads(report_path.read_text(encoding='utf-8'))
        report['timeline'][0]['end_frame'] += 4
        report_path.write_text(json.dumps(report), encoding='utf-8')
        update = self.evaluate()
        self.assertEqual(update['qa_result']['error_type'], 'sync_error')
        self.state['video_path'] = 'missing.mp4'
        update = self.ns['video_qa'](self.state)
        self.assertEqual(update['qa_next_node'], 'VideoRenderer')

    def test_waveform_comparison_detects_shift_silence_and_wrong_audio(self):
        t = np.arange(24000 * 4) / 24000
        envelope = 0.5 + 0.25 * np.sin(2 * np.pi * 1.7 * t) + 0.2 * np.sin(2 * np.pi * 3.1 * t)
        samples = (12000 * envelope * np.sin(2 * np.pi * 220 * t)).astype('<i2')
        pcm = samples.tobytes()
        same = self.ns['qa_audio_similarity'](pcm, pcm)
        self.assertGreater(same['correlation'], 0.99)
        self.assertEqual(same['offset_sec'], 0)
        shifted = self.ns['qa_audio_similarity'](pcm, np.r_[np.zeros(7200, dtype='<i2'), samples[:-7200]].astype('<i2').tobytes())
        self.assertGreater(abs(shifted['offset_sec']), 0.1)
        silence = self.ns['qa_audio_similarity'](pcm, bytes(len(pcm)))
        self.assertEqual(silence['correlation'], 0)
        rng = np.random.default_rng(42)
        noise = rng.integers(-12000, 12000, len(samples), dtype=np.int16).astype('<i2').tobytes()
        self.assertLess(self.ns['qa_audio_similarity'](pcm, noise)['correlation'], 0.9)


if __name__ == '__main__':
    unittest.main()
