"""v2 동적 레이아웃·핵심 포인트(headline/badge)·청크 자막·헤드라인 검증/수정 계약 검사."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import test_claim_validator as claim_tests
import test_script_generator as script_tests
import test_script_reviser as reviser_tests
import test_video_qa as qa_tests
import test_video_renderer as render_tests


class V2FeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        render_tests.VideoRendererTests.setUpClass()
        cls.ns = dict(render_tests.VideoRendererTests.ns)
        if not str(cls.ns.get('LAYOUT_VERSION', '')).startswith('v2_'):
            raise unittest.SkipTest('v2 노트북(MVP_v2.ipynb)에서만 실행되는 테스트입니다.')

    def test_script_generator_populates_v2_fields_and_diversifies_adjacent_focus(self):
        fixture = script_tests.ScriptGeneratorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = copy.deepcopy(fixture.plan)
        plan['scenes'][0]['headline'] = 'Soft Satin Finish'
        plan['scenes'][1]['headline'] = 'Smooth Application'
        scenes, _, _ = fixture.resolve(plan)
        self.assertEqual(scenes[0]['badge_label'], 'NOVA · CREAM')
        self.assertEqual(scenes[1]['badge_label'], 'POINT 01')
        self.assertEqual(scenes[2]['badge_label'], 'POINT 02')
        self.assertEqual(scenes[0]['headline'], 'Soft Satin Finish')
        self.assertEqual(scenes[1]['headline'], 'Smooth Application')
        # 인접 장면이 같은 이미지를 공유할 때 crop_focus가 자동 분산됨
        for prev, curr in zip(scenes, scenes[1:]):
            if prev['image_path'] == curr['image_path']:
                self.assertNotEqual(prev['crop_focus'], curr['crop_focus'])

    def test_headline_unsupported_number_is_rejected(self):
        fixture = script_tests.ScriptGeneratorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        plan = copy.deepcopy(fixture.plan)
        plan['scenes'][1]['headline'] = '24 Hour Smoothness'
        with self.assertRaises(ValueError):
            fixture.resolve(plan)

    def test_claim_validator_reviews_headlines_and_routes_headline_error(self):
        fixture = claim_tests.ClaimValidatorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.state['scenes'][1]['headline'] = 'Instant Repair Formula'
        update = fixture.validate(lambda v, c: fixture.reject(v, c, 'scene:2:headline'))
        self.assertFalse(update['validation_result']['is_valid'])
        self.assertEqual(update['validation_result']['error_type'], 'script_error')
        self.assertEqual(fixture.next_node(update), 'ScriptReviser')
        self.assertEqual(update['validation_result']['issues'][0]['target_field'], 'headline')

    def test_script_reviser_edits_only_headline_slot_when_flagged(self):
        fixture = reviser_tests.ScriptReviserTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        orig_narration = fixture.state['scenes'][1]['narration']
        fixture.state['scenes'][1]['headline'] = 'Instant Repair Formula'
        fixture.state['validation_result'] = {
            'is_valid': False, 'error_type': 'script_error',
            'issues': [{
                'scene_no': 2, 'target_field': 'headline', 'claim': 'Instant Repair Formula',
                'error_type': 'script_error', 'status': 'unsupported',
                'reason': 'Not in source.', 'suggested_action': 'Use smooth application wording.',
            }],
        }
        update = fixture.run_node([{'edit_id': 's2_headline', 'text': 'Smooth Even Application'}])
        self.assertEqual(update['status'], 'running', update)
        self.assertEqual(update['scenes'][1]['headline'], 'Smooth Even Application')
        self.assertEqual(update['scenes'][1]['narration'], orig_narration)
        self.assertEqual(update['retry_count'], 1)

    def test_timed_subtitle_chunks_preserve_all_words_and_limit_lines(self):
        import re
        text = "Coverage lets natural detail show; blending outward for an even-looking complexion."
        chunks = self.ns['split_subtitle_chunks'](text)
        self.assertGreaterEqual(len(chunks), 2)
        orig_words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text)
        reconstructed_words = re.findall(
            r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*",
            ' '.join(c for c, _ in chunks),
        )
        self.assertEqual(reconstructed_words, orig_words)
        for chunk_text, _ in chunks:
            # 항상 깔끔한 1줄 자막(줄바꿈 없음) + 끝 구두점(; , : —) 제거 확인
            self.assertNotIn(r'\N', chunk_text)
            self.assertNotRegex(chunk_text, r'[,;:—\-]$')
            self.assertNotIn(';', chunk_text)

    def test_tts_transcript_matches_allows_only_single_article_variation(self):
        fn = self.ns['tts_transcript_matches']
        # 완전 일치
        self.assertEqual(fn("Without a sticky after-feel.", "Without a sticky after-feel."), (True, False))
        # 관사 1개 차이: strict=False이면 불일치, allow_article_only=True이면 허용
        self.assertEqual(
            fn("It smooths over dry-feeling skin without a sticky after-feel.",
               "It smooths over dry-feeling skin without sticky after-feel.", False),
            (False, False),
        )
        self.assertEqual(
            fn("It smooths over dry-feeling skin without a sticky after-feel.",
               "It smooths over dry-feeling skin without sticky after-feel.", True),
            (True, True),
        )
        # 임의 단어 추가(환각)는 allow_article_only=True여도 절대 차단
        self.assertEqual(
            fn("It smooths over dry-feeling skin without leaving a sticky after-feel.",
               "It smooths over dry-feeling skin without sticky after-feel.", True),
            (False, False),
        )
        self.assertEqual(
            fn("Smooth finish invented claim.", "Smooth finish.", True),
            (False, False),
        )

    def test_compose_scene_assets_handles_square_and_ultrawide_images(self):
        fixture = render_tests.VideoRendererTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        workdir = Path(fixture.state['output_dir']) / 'asset_test'
        workdir.mkdir(parents=True, exist_ok=True)
        wide_path = workdir / 'wide_2to1.jpg'
        Image.new('RGB', (1800, 866), (210, 185, 165)).save(wide_path)
        item = {
            'scene_no': 2, 'image_path': str(wide_path),
            'motion_effect': 'pan_right', 'crop_focus': 'left',
        }
        assets = self.ns['compose_scene_assets'](item, total_scenes=5, workdir=workdir)
        with Image.open(assets['bg']) as bg:
            self.assertEqual(bg.size, (1080, 1920))
        with Image.open(assets['mask']) as mask:
            self.assertEqual(mask.size, (self.ns['HERO_W'], self.ns['HERO_H']))
        with Image.open(assets['src']) as src:
            # 2.08:1 와이드 패닝 소스는 높이 1800px에 맞춰 폭이 3500px 이상으로 유지돼야 함
            self.assertEqual(src.size[1], self.ns['HERO_H'] * 2)
            self.assertGreater(src.size[0], 3500)

    def test_optional_bgm_filter_and_missing_bgm_rejection(self):
        fixture = render_tests.VideoRendererTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        bgm = Path(fixture.state['output_dir']) / 'bgm.wav'
        bgm.write_bytes(b'RIFF0000WAVE')
        fixture.state['bgm_path'] = str(bgm)
        update = fixture.render()
        self.assertEqual(update['status'], 'running', update)
        joined = ' '.join(fixture.commands[-1])
        self.assertIn('volume=-22dB', joined)
        self.assertIn('amix=inputs=2', joined)
        fixture.state['bgm_path'] = str(Path(fixture.state['output_dir']) / 'missing_bgm.wav')
        failed = fixture.render()
        self.assertEqual(failed['status'], 'failed')

    def test_creative_direction_tokens_brand_guide_and_3_visual_themes(self):
        # 1) brand_guide가 LLM 추론값보다 우선 적용됨
        cd = self.ns['resolve_creative_direction'](
            {'concept': 'premium_editorial', 'background_tone': 'deep_dark', 'accent_color': 'champagne_gold',
             'typography_style': 'editorial_serif', 'motion_pacing': 'calm_elegant', 'narration_tone': 'calm_refined',
             'rationale': 'Luxury cue.'},
            brand_guide={'background_tone': 'soft_light', 'accent_color': 'ice_blue', 'typography_style': 'modern_sans'},
        )
        self.assertEqual(cd['background_tone'], 'soft_light')
        self.assertEqual(cd['accent_color'], 'ice_blue')
        self.assertEqual(cd['typography_style'], 'modern_sans')

        # 2) 3가지 배경 톤과 글꼴이 실제 배경 밝기 및 ASS 스타일에 반영됨
        fixture = render_tests.VideoRendererTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        means = {}
        fonts_seen = {}
        for tone, typo, accent in [
            ('deep_dark', 'editorial_serif', 'champagne_gold'),
            ('warm_neutral', 'clean_soft', 'soft_rose'),
            ('soft_light', 'modern_sans', 'ice_blue'),
        ]:
            fixture.state['creative_direction'] = {
                'concept': 'clinical_calm' if tone == 'soft_light' else 'premium_editorial',
                'background_tone': tone, 'accent_color': accent,
                'typography_style': typo, 'motion_pacing': 'steady_clean',
                'narration_tone': 'warm_reassuring', 'rationale': 'Test theme.',
            }
            update = fixture.render()
            self.assertEqual(update['status'], 'running', update)
            report = json.loads(Path(update['render_json_path']).read_text(encoding='utf-8'))
            ass_text = Path(report['subtitle_path']).read_text(encoding='utf-8')
            fonts_seen[tone] = report['headline_font_name']
            if tone == 'soft_light':
                # 밝은 배경에서는 헤드라인이 딥차콜 잉크(&H00382B22)로 자동 전환됨
                self.assertIn('&H00382B22', ass_text)
            bg_img = Path(report['video_path']).parent / 'scene_1_bg.png'
            with Image.open(bg_img) as im:
                import numpy as np
                means[tone] = float(np.asarray(im)[:360].mean())
        # soft_light 상단 영역은 deep_dark보다 확연히 밝아야 함
        self.assertGreater(means['soft_light'], means['deep_dark'] + 70)
        self.assertEqual(len(set(fonts_seen.values())), 3)

    def test_v23_cosmetic_claim_guard_blocks_unsupported_and_hands_off_to_reviser(self):
        # 1) 원문에 없는 SPF/임상 표현은 API 0회로 1차 코드 차단 + 5번 노드 문장 부분 수정 연계
        c_fix = claim_tests.ClaimValidatorTests()
        c_fix.setUp()
        self.addCleanup(c_fix.doCleanups)
        c_fix.change_narration('It spreads smoothly. Clinically proven SPF 50 protection.')
        val_update = c_fix.validate()
        self.assertFalse(val_update['validation_result']['is_valid'])
        self.assertEqual(val_update['validation_result']['error_type'], 'script_error')
        self.assertEqual(c_fix.next_node(val_update), 'ScriptReviser')
        self.assertEqual(c_fix.calls, [])
        report = json.loads(Path(val_update['validation_json_path']).read_text(encoding='utf-8'))
        self.assertEqual(report['code_checks']['cosmetic_claim_guard'], 'failed')

        # 5번 노드(ScriptReviser)로 그대로 넘겼을 때 문제 문장만 정확히 수정되는지 확인
        r_fix = reviser_tests.ScriptReviserTests()
        r_fix.setUp()
        self.addCleanup(r_fix.doCleanups)
        r_fix.state = copy.deepcopy(c_fix.state)
        r_fix.state.update(retry_count=0, validation_result=val_update['validation_result'])
        rev_update = r_fix.run_node([{'edit_id': 's2_sentence2', 'text': 'Enjoy an easy, even application.'}])
        self.assertEqual(rev_update['status'], 'running', rev_update)
        self.assertEqual(rev_update['scenes'][1]['narration'], 'It spreads smoothly. Enjoy an easy, even application.')

        # 2) 원문에 실제로 SPF 50이 적힌 문서라면 코드 가드가 통과시켜야 함 (하드코딩 없음 검증)
        c_fix2 = claim_tests.ClaimValidatorTests()
        c_fix2.setUp()
        self.addCleanup(c_fix2.doCleanups)
        c_fix2.state['raw_slides'][0]['texts'].append('Daily formula with SPF 50 protection.')
        c_fix2.state['scenes'][1]['source_text_ids'].append(f"s1_t{len(c_fix2.state['raw_slides'][0]['texts'])}")
        c_fix2.change_narration('Daily formula with SPF 50 protection.')
        ok_update = c_fix2.validate()
        self.assertTrue(ok_update['validation_result']['is_valid'], ok_update)
        self.assertEqual(len(c_fix2.calls), 1)

        # 3) "No SPF value is stated" 같은 부정 표현은 과장 주장으로 오탐하지 않음
        finder = c_fix2.ns['find_unsupported_cosmetic_claims']
        self.assertEqual(finder('No SPF value or test result is stated in the text.', 'Daily sun serum.'), [])
        self.assertEqual(finder('Provides SPF 50 protection.', 'Daily sun serum.'), ['SPF 50'])

    def test_v23_common_analysis_and_usp_type_errors_route_to_product_analyzer(self):
        c_fix = claim_tests.ClaimValidatorTests()
        c_fix.setUp()
        self.addCleanup(c_fix.doCleanups)
        c_fix.state['common_analysis'] = {
            'result_effect': {'summary': 'Soft finish.', 'source_text_ids': ['s99_t99'], 'quotes': []},
        }
        c_fix.state['usps'][0]['usp_type'] = 'invented_type'
        val_update = c_fix.validate()
        self.assertFalse(val_update['validation_result']['is_valid'])
        self.assertEqual(val_update['validation_result']['error_type'], 'usp_error')
        self.assertEqual(c_fix.next_node(val_update), 'ProductAnalyzer')
        self.assertEqual(c_fix.calls, [])
        report = json.loads(Path(val_update['validation_json_path']).read_text(encoding='utf-8'))
        self.assertEqual(report['code_checks']['common_analysis'], 'failed')
        self.assertEqual(report['code_checks']['usp_types'], 'failed')

    def test_v23_badge_and_creative_direction_errors_auto_repair_in_reviser_without_llm(self):
        c_fix = claim_tests.ClaimValidatorTests()
        c_fix.setUp()
        self.addCleanup(c_fix.doCleanups)
        c_fix.state['brand_guide'] = {'background_tone': 'soft_light', 'accent_color': 'ice_blue'}
        c_fix.state['creative_direction'] = {
            'concept': 'clinical_calm', 'background_tone': 'deep_dark', 'accent_color': 'champagne_gold',
            'typography_style': 'modern_sans', 'motion_pacing': 'steady_clean', 'narration_tone': 'warm_reassuring',
            'rationale': 'Mismatch test.',
        }
        c_fix.state['scenes'][0]['badge_label'] = 'NOVA · 99% OFF'
        val_update = c_fix.validate()
        self.assertFalse(val_update['validation_result']['is_valid'])
        self.assertEqual(val_update['validation_result']['error_type'], 'script_error')
        self.assertEqual(c_fix.next_node(val_update), 'ScriptReviser')
        self.assertEqual(c_fix.calls, [])

        # 5번 노드(ScriptReviser)가 LLM 호출 0회로 배지·brand_guide 모두 자동 복구하는지 확인
        r_fix = reviser_tests.ScriptReviserTests()
        r_fix.setUp()
        self.addCleanup(r_fix.doCleanups)
        r_fix.state = copy.deepcopy(c_fix.state)
        r_fix.state.update(retry_count=0, validation_result=val_update['validation_result'])
        rev_update = r_fix.run_node()
        self.assertEqual(rev_update['status'], 'running', rev_update)
        self.assertEqual(r_fix.calls, [])
        self.assertEqual(rev_update['creative_direction']['background_tone'], 'soft_light')
        self.assertEqual(rev_update['creative_direction']['accent_color'], 'ice_blue')
        self.assertNotIn('99%', rev_update['scenes'][0]['badge_label'])

    def test_v23_renderer_safe_area_and_brand_guide_fallback(self):
        fixture = render_tests.VideoRendererTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.state['creative_direction'] = {
            'concept': 'premium_editorial', 'background_tone': 'deep_dark', 'accent_color': 'champagne_gold',
            'typography_style': 'editorial_serif', 'motion_pacing': 'calm_elegant', 'narration_tone': 'calm_refined',
            'rationale': 'Default dark.',
        }
        fixture.state['brand_guide'] = {'background_tone': 'soft_light', 'accent_color': 'ice_blue'}
        update = fixture.render()
        self.assertEqual(update['status'], 'running', update)
        report = json.loads(Path(update['render_json_path']).read_text(encoding='utf-8'))
        # 1) render.json safe_area가 최신 1줄 자막 규격과 일치
        self.assertEqual(report['safe_area']['caption_center_x'], 540)
        self.assertEqual(report['safe_area']['caption_bottom_y'], 1510)
        self.assertEqual(report['safe_area']['max_text_width'], 820)
        self.assertEqual(report['safe_area']['max_chunk_lines'], 1)
        # 2) 7번 단독 실행에서도 brand_guide가 최우선 적용되고, 상단 배지 박스(Badge)는 렌더링하지 않음
        self.assertEqual(report['creative_direction']['background_tone'], 'soft_light')
        self.assertEqual(report['creative_direction']['accent_color'], 'ice_blue')
        ass_text = Path(report['subtitle_path']).read_text(encoding='utf-8')
        self.assertNotIn('Style: Badge', ass_text)

    def test_v23_video_qa_checks_identity_single_line_and_fade_free_frame(self):
        qa_tests.VideoQATests.setUpClass()
        fixture = qa_tests.VideoQATests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)

        # 1) 정상 통과 시 brand_identity + subtitle_single_line 체크 모두 기록 및 통과
        ok = fixture.evaluate()
        self.assertEqual(ok['status'], 'completed', ok)
        qa_report = json.loads(Path(ok['qa_json_path']).read_text(encoding='utf-8'))
        check_names = {c['name']: c['passed'] for c in qa_report['checks']}
        self.assertTrue(check_names.get('brand_identity'))
        self.assertTrue(check_names.get('subtitle_single_line'))

        # 2) render.json의 브랜드 스타일 변조 시 VideoRenderer로 차단
        rpath = Path(fixture.state['render_json_path'])
        saved = json.loads(rpath.read_text(encoding='utf-8'))
        orig_saved = copy.deepcopy(saved)
        saved['creative_direction']['background_tone'] = 'soft_light' if saved['creative_direction']['background_tone'] != 'soft_light' else 'deep_dark'
        rpath.write_text(json.dumps(saved), encoding='utf-8')
        bad_id = fixture.evaluate()
        self.assertFalse(bad_id['qa_result']['is_passed'])
        self.assertIn('brand_identity', bad_id['qa_result']['details'])
        self.assertEqual(bad_id['qa_next_node'], 'VideoRenderer')
        rpath.write_text(json.dumps(orig_saved), encoding='utf-8')

        # 3) 2토막 자막 장면에서 qa_pick_sample_local_frame이 50% 페이드 경계를 회피하는지 확인
        picker = qa_tests.VideoQATests.ns['qa_pick_sample_local_frame']
        sample_item = {
            'start_frame': 0, 'frame_count': 132, 'transition_frames': 9,
            'caption_chunks': [
                {'text': 'First clean subtitle line', 'start_sec': 0.0, 'end_sec': 2.2},
                {'text': 'Second clean subtitle line.', 'start_sec': 2.2, 'end_sec': 4.4},
            ],
        }
        picked = picker(sample_item)
        picked_sec = picked / 30.0
        # 2.2s 페이드 경계(2.06s~2.34s)에서 충분히 떨어진 선명한 프레임 선택
        self.assertGreater(abs(picked_sec - 2.2), 0.4)


if __name__ == '__main__':
    unittest.main(verbosity=2)
