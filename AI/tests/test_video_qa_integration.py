"""기존 LUMIA 결과로 실제 FFmpeg QA를 검사한다. 결과 파일이 없으면 명시적으로 건너뛴다."""
import copy
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

import test_script_generator as script_tests
import test_video_qa as qa_tests

ROOT = script_tests.ROOT
ARCHIVE = ROOT / ('output2' if (ROOT / 'output2').is_dir() else 'output')
RENDER = ARCHIVE / 'render_checks/video/LUMIA/55fbdf27410f/render.json'
TTS = ARCHIVE / 'tts_checks/audio/LUMIA/695eca22996d/tts.json'
VALIDATION = ARCHIVE / 'revision_checks/LUMIA_validation.json'
STATE = Path(os.environ['BEAUTYFLOW_RENDER_STATE']) if os.environ.get('BEAUTYFLOW_RENDER_STATE') else None


def relocated(value):
    if isinstance(value, dict): return {k: relocated(v) for k, v in value.items()}
    if isinstance(value, list): return [relocated(v) for v in value]
    if isinstance(value, str) and ('\\output\\' in value or '/output/' in value):
        if not Path(value).exists():
            candidate = value.replace('\\output\\', '\\output2\\').replace('/output/', '/output2/')
            if Path(candidate).exists(): return candidate
    return value


@pytest.mark.integration
@unittest.skipUnless((STATE and STATE.is_file()) or (RENDER.is_file() and TTS.is_file() and VALIDATION.is_file()), 'LUMIA 실측 결과가 없어 실제 영상 QA 검사를 건너뜁니다.')
class VideoQAIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qa_tests.VideoQATests.setUpClass()
        cls.ns = qa_tests.VideoQATests.ns
        cls.ns['subprocess'] = subprocess
        if STATE:
            cls.tts = json.loads(STATE.read_text(encoding='utf-8'))
            cls.render = json.loads(Path(cls.tts['render_json_path']).read_text(encoding='utf-8'))
            cls.validation = {'validation_result': cls.tts['validation_result']}
        else:
            cls.render = relocated(json.loads(RENDER.read_text(encoding='utf-8')))
            cls.tts = relocated(json.loads(TTS.read_text(encoding='utf-8')))
            cls.validation = json.loads(VALIDATION.read_text(encoding='utf-8'))
        version = cls.ns.get('LAYOUT_VERSION')
        if version and cls.render.get('layout_version') != version:
            raise unittest.SkipTest(f'현재 {version} 레이아웃으로 생성한 영상이 필요합니다. BEAUTYFLOW_RENDER_STATE에 새 결과 State를 지정하세요.')
        cls.original = Path(cls.render['video_path'])

    def setUp(self):
        temporary = TemporaryDirectory(prefix='beautyflow_qa_test_')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.video = self.directory / 'case.mp4'

    def transcode(self, options):
        self.ns['qa_ffmpeg'](['-y', '-i', str(self.original), *options, str(self.video)])

    def evaluate(self, subtitle=None):
        report = copy.deepcopy(self.render)
        report['video_path'] = str(self.video)
        if subtitle: report['subtitle_path'] = str(subtitle)
        report_path = self.directory / 'render.json'
        report_path.write_text(json.dumps(report), encoding='utf-8')
        state = {**self.tts, 'file_path': 'data/LUMIA.pptx', 'output_dir': str(self.directory),
                 'video_path': str(self.video), 'render_json_path': str(report_path), 'status': 'running',
                 'validation_result': self.validation['validation_result'], 'retry_count': 0, 'max_retries': 3}
        before = copy.deepcopy(state)
        result = self.ns['video_qa'](state)
        self.assertEqual(state, before)
        return result

    def assert_rejected(self, result, expected):
        self.assertFalse(result['qa_result']['is_passed'], result)
        self.assertIn(expected, result['qa_result']['details'])
        self.assertEqual(result['qa_next_node'], 'VideoRenderer')

    def test_original_mp4_passes(self):
        shutil.copyfile(self.original, self.video)
        result = self.evaluate()
        self.assertTrue(result['qa_result']['is_passed'], result)
        self.assertEqual(result['status'], 'completed')

    def test_missing_audio_is_rejected(self):
        self.transcode(['-map', '0:v:0', '-c:v', 'copy', '-an'])
        self.assert_rejected(self.evaluate(), 'codecs')

    def test_truncated_video_is_rejected(self):
        self.transcode(['-t', '5', '-c', 'copy'])
        self.assert_rejected(self.evaluate(), 'video_duration')

    def test_wrong_resolution_is_rejected(self):
        self.transcode(['-vf', 'scale=540:960', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'copy'])
        self.assert_rejected(self.evaluate(), 'video_spec')

    def test_silent_audio_is_rejected(self):
        self.transcode(['-c:v', 'copy', '-af', 'volume=0', '-c:a', 'aac'])
        self.assert_rejected(self.evaluate(), 'audio_similarity')

    def test_shifted_audio_is_rejected(self):
        self.transcode(['-c:v', 'copy', '-af', 'adelay=500:all=1', '-c:a', 'aac', '-t', str(self.tts['tts_duration_sec'])])
        self.assert_rejected(self.evaluate(), 'audio_similarity')

    def test_absent_burned_captions_are_rejected(self):
        duration = str(self.tts['tts_duration_sec'])
        if str(self.ns.get('LAYOUT_VERSION', '')).startswith('v2_'):
            timeline = self.render['timeline']
            inputs = []
            for item in timeline:
                inputs.extend(['-i', str(self.original.parent / f"scene_{item['scene_no']}.mp4")])
            inputs.extend(['-i', self.tts['audio_path']])
            fc = self.ns['build_xfade_filter_complex'](timeline, bgm_enabled=False, total_sec=self.tts['tts_duration_sec'])
            fc = fc.replace('ass=subtitles.ass,', '')
            self.ns['qa_ffmpeg']([
                '-y', *inputs, '-filter_complex', fc, '-map', '[vfinal]', '-map', f'{len(timeline)}:a:0',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-r', '30',
                '-c:a', 'aac', '-t', duration, str(self.video),
            ])
        else:
            clips = self.original.parent / 'clips.txt'
            self.ns['qa_ffmpeg'](['-y', '-f', 'concat', '-safe', '1', '-i', str(clips), '-i', self.tts['audio_path'],
                                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-t', duration, str(self.video)])
        self.assert_rejected(self.evaluate(), 'scene_1_caption')

    def test_missing_product_region_is_rejected(self):
        self.transcode(['-vf', "drawbox=x=100:y=280:w=880:h=1050:color=black:t=fill:enable='lt(t,6)'",
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-c:a', 'copy'])
        self.assert_rejected(self.evaluate(), 'scene_1_image')


if __name__ == '__main__':
    unittest.main()
