"""영상 입력·타임라인·자막·실패 및 재시도 계약 검사. API 호출 없음."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import test_script_generator as script_tests
import test_tts_generator as tts_tests
from notebook_loader import load_definitions


class VideoRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tts_tests.TTSGeneratorTests.setUpClass()
        cls.ns = dict(tts_tests.TTSGeneratorTests.ns)
        load_definitions(cls.ns, 'video_renderer')

    def setUp(self):
        fixture = tts_tests.TTSGeneratorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.state = {**fixture.state, **fixture.run_node([6.05, 6.1, 5.8, 5.6])}
        self.commands = []

    def fake_ffmpeg(self, args, directory):
        self.commands.append(args)
        (directory / args[-1]).write_bytes(b'fake MP4 for contract-only test')

    def render(self):
        with patch.dict(self.ns, {'run_video_ffmpeg': self.fake_ffmpeg}):
            return self.ns['video_renderer'](self.state)

    def test_preserves_input_and_records_pending_qa(self):
        before = copy.deepcopy(self.state)
        update = self.render()
        self.assertEqual(update['status'], 'running', update)
        self.assertEqual(self.state, before)
        self.assertEqual(update['retry_count'], before['retry_count'])
        self.assertFalse(update['qa_result']['is_passed'])
        self.assertEqual(self.ns['route_after_video_render']({**self.state, **update}), 'VideoQA')
        report = json.loads(Path(update['render_json_path']).read_text(encoding='utf-8'))
        self.assertEqual(report['resolution'], '1080x1920')
        self.assertTrue(report['requires_video_qa'])
        self.assertEqual(len(self.commands), 5)
        self.assertIn('ass=subtitles.ass', self.commands[-1])
        self.assertIn('1:a:0', self.commands[-1])

    def test_cumulative_frames_do_not_accumulate_rounding(self):
        timeline, _, total = self.ns['prepare_video_timeline'](self.state)
        self.assertAlmostEqual(total, 23.55)
        self.assertEqual(timeline[-1]['end_frame'], 707)
        self.assertEqual(sum(s['frame_count'] for s in timeline), 707)
        self.assertLessEqual(abs(timeline[-1]['end_frame'] / 30 - total), 1 / 60 + 1e-8)
        for a, b in zip(timeline, timeline[1:]):
            self.assertEqual(a['end_frame'], b['start_frame'])

    def test_bad_inputs_stop_before_ffmpeg(self):
        original = copy.deepcopy(self.state)
        for kind in ['status', 'validation', 'image', 'subtitle', 'motion', 'duration', 'total_duration', 'full_script', 'audio']:
            self.state = copy.deepcopy(original)
            if kind == 'status': self.state['status'] = 'failed'
            if kind == 'validation': self.state['validation_result']['is_valid'] = False
            if kind == 'image': self.state['scenes'][0]['image_path'] = 'missing.png'
            if kind == 'subtitle': self.state['scenes'][0]['subtitle'] = 'Different'
            if kind == 'motion': self.state['scenes'][0]['motion_effect'] = 'unsupported'
            if kind == 'duration': self.state['scenes'][0]['duration_sec'] = float('nan')
            if kind == 'total_duration': self.state['tts_duration_sec'] = float('nan')
            if kind == 'full_script': self.state['full_script'] = 'Different'
            if kind == 'audio': self.state['audio_path'] = 'missing.wav'
            update = self.render()
            self.assertEqual(update['status'], 'failed', update)
            self.assertEqual(update['video_path'], '')
        self.assertEqual(self.commands, [])

    def test_audio_content_mismatch_is_detected(self):
        path = Path(self.state['audio_path'])
        raw = bytearray(path.read_bytes())
        raw[-2:] = b'\x20\x00'
        path.write_bytes(raw)
        update = self.render()
        self.assertEqual(update['status'], 'failed')
        self.assertEqual(self.commands, [])

    def test_caption_wrap_preserves_words_and_escapes_controls(self):
        text = self.state['scenes'][0]['subtitle']
        caption, size = self.ns['video_caption'](text)
        self.assertEqual(' '.join(caption.split(r'\N')).split(), text.split())
        font = self.ns['ImageFont'].truetype(str(self.ns['VIDEO_FONT']), size)
        self.assertTrue(all(font.getlength(line) <= 780 for line in caption.split(r'\N')))
        for value in [r'{\pos(0,0)}Injected', 'a' * 500, 'word ' * 200, 'Line\nbreak']:
            with self.assertRaises(ValueError): self.ns['video_caption'](value)

    def test_ffmpeg_failure_clears_previous_video_and_records_error(self):
        self.state['video_path'] = 'old.mp4'
        def fail(*args): raise RuntimeError('simulated encoding failure')
        with patch.dict(self.ns, {'run_video_ffmpeg': fail}):
            update = self.ns['video_renderer'](self.state)
        self.assertEqual(update['status'], 'failed')
        self.assertEqual(update['video_path'], '')
        report = json.loads(Path(update['render_json_path']).read_text(encoding='utf-8'))
        self.assertEqual(report['next_node'], 'END')

    def test_initial_render_allowed_at_budget_but_rerender_is_limited(self):
        self.state['retry_count'] = 3
        self.assertEqual(self.render()['status'], 'running')
        self.state['qa_result'] = {'is_passed': False, 'error_type': 'sync_error'}
        update = self.render()
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(update['retry_count'], 3)
        self.state['retry_count'] = 2
        update = self.render()
        self.assertEqual(update['status'], 'running')
        self.assertEqual(update['retry_count'], 3)

    def test_all_motion_modes_and_new_run_paths(self):
        for mode in ['static', 'zoom_in', 'zoom_out', 'pan_left', 'pan_right']:
            value = self.ns['video_motion_filter'](mode, 150)
            self.assertIn('d=150:s=1080x1920:fps=30', value)
        first, second = self.render(), self.render()
        self.assertNotEqual(first['video_path'], second['video_path'])


if __name__ == '__main__':
    unittest.main()
