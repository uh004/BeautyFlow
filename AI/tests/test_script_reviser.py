"""대본 수정의 범위 보존·재검증·재시도 계약 검사. API 호출 없음."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
import test_claim_validator as claim_tests
import test_script_generator as script_tests
from notebook_loader import load_definitions


class ScriptReviserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        claim_tests.ClaimValidatorTests.setUpClass()
        cls.ns = dict(claim_tests.ClaimValidatorTests.ns)
        load_definitions(cls.ns, 'script_reviser')

    def setUp(self):
        fixture = script_tests.ScriptGeneratorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.state = fixture.state
        scenes, script, _ = fixture.resolve()
        self.state.update(scenes=scenes, full_script=script, retry_count=0,
                          validation_result={'is_valid': True, 'error_type': 'none', 'issues': []})
        self.calls = []

    def make_error(self):
        scene = self.state['scenes'][1]
        scene.update(narration='It spreads smoothly. Repairs damaged skin.',
                     subtitle='It spreads smoothly. Repairs damaged skin.')
        self.state['full_script'] = ' '.join(s['narration'] for s in self.state['scenes'])
        self.state['validation_result'] = {'is_valid': False, 'error_type': 'script_error', 'issues': [
            {'scene_no': 2, 'target_field': 'narration,subtitle', 'claim': 'Repairs damaged skin.',
             'error_type': 'script_error', 'status': 'unsupported', 'reason': 'Not in source.',
             'suggested_action': 'Use the original application claim.'}]}

    def run_node(self, replacements=None, fail=False):
        calls, ns = self.calls, self.ns
        class FakeChat:
            def __init__(self, **kwargs):
                assert kwargs['max_retries'] == 0
            def with_structured_output(self, schema, **kwargs):
                assert schema == ns['ScriptRevision'].model_json_schema()
                def respond(prompt):
                    calls.append(prompt)
                    if fail:
                        raise RuntimeError('simulated API failure')
                    slots = json.loads(prompt.to_messages()[1].content.split('## Editable slots and original evidence\n')[1])
                    edits = replacements if replacements is not None else [
                        {'edit_id': s['edit_id'], 'text': 'For an easy, even application.'} for s in slots]
                    return {'parsed': {'edits': edits}, 'parsing_error': None,
                            'raw': AIMessage(content='', usage_metadata={
                                'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120})}
                return RunnableLambda(respond)
        with patch.dict(ns, {'ChatOpenAI': FakeChat}):
            return ns['script_reviser'](self.state)

    def test_valid_noop_and_upstream_routing(self):
        update = self.run_node()
        self.assertEqual(self.ns['route_after_script_revision']({**self.state, **update}), 'TTSGenerator')
        self.state['validation_result'].update(is_valid=False, error_type='usp_error')
        update = self.run_node()
        self.assertEqual(self.ns['route_after_script_revision']({**self.state, **update}), 'ProductAnalyzer')
        self.assertEqual(self.calls, [])
        self.assertEqual(update['retry_count'], 0)

    def test_only_failed_sentence_changes_and_invalidates_artifacts(self):
        self.make_error()
        self.state.update(audio_path='old.wav', tts_duration_sec=26, video_path='old.mp4')
        before = copy.deepcopy(self.state)
        update = self.run_node()
        self.assertEqual(update['status'], 'running', update)
        self.assertEqual(self.state, before)
        self.assertEqual(update['scenes'][1]['narration'], 'It spreads smoothly. For an easy, even application.')
        for old, new in zip(before['scenes'], update['scenes']):
            for key in ['scene_no', 'image_path', 'purpose', 'motion_effect', 'usp_ids', 'source_text_ids', 'source_slide_nos']:
                self.assertEqual(old[key], new[key])
            if old['scene_no'] != 2:
                self.assertEqual(old['narration'], new['narration'])
            self.assertEqual(new['subtitle'], new['narration'])
            self.assertIsNone(new['audio_segment_path'])
        self.assertFalse(update['validation_result']['is_valid'])
        self.assertEqual(update['audio_path'], '')
        self.assertEqual(update['video_path'], '')
        self.assertEqual(update['tts_duration_sec'], 0)
        self.assertEqual(update['retry_count'], 1)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.ns['route_after_script_revision']({**self.state, **update}), 'ClaimValidator')
        report = json.loads(Path(update['revision_json_path']).read_text(encoding='utf-8'))
        self.assertTrue(report['requires_claim_validation'])
        self.assertEqual(len(report['revision_history'][0]['changes']), 1)

    def test_bad_edit_ids_and_unsupported_numbers_blocked(self):
        self.make_error()
        for edits in [[], [{'edit_id': 'unknown', 'text': 'Smooth.'}],
                      [{'edit_id': 's2_sentence2', 'text': 'Lasts 99 hours.'}],
                      [{'edit_id': 's2_sentence2', 'text': 'Smooth.'}] * 2]:
            with self.subTest(edits=edits):
                update = self.run_node(edits)
                self.assertEqual(update['status'], 'fallback_review_required')
                self.assertNotIn('scenes', update)

    def test_budget_stale_uncertain_and_missing_source_block_before_call(self):
        self.make_error()
        original = copy.deepcopy(self.state)
        for kind in ['budget', 'stale', 'uncertain', 'source']:
            self.state = copy.deepcopy(original)
            if kind == 'budget': self.state['retry_count'] = 3
            if kind == 'stale': self.state['validation_result']['issues'][0]['claim'] = 'Old draft.'
            if kind == 'uncertain': self.state['validation_result']['issues'][0]['status'] = 'uncertain'
            if kind == 'source': self.state['scenes'][1]['source_text_ids'] = ['missing']
            update = self.run_node()
            self.assertEqual(update['status'], 'fallback_review_required', update)
        self.assertEqual(self.calls, [])

    def test_local_subtitle_and_full_script_repair_without_model(self):
        self.state['scenes'][1]['subtitle'] = 'Old caption.'
        self.state['full_script'] = 'Old script.'
        self.state['validation_result'] = {'is_valid': False, 'error_type': 'script_error', 'issues': [
            {'scene_no': 2, 'target_field': 'subtitle', 'status': 'structure_error', 'error_type': 'script_error'},
            {'target_field': 'full_script', 'status': 'structure_error', 'error_type': 'script_error'}]}
        before = [s['narration'] for s in self.state['scenes']]
        update = self.run_node()
        self.assertEqual(update['status'], 'running', update)
        self.assertEqual([s['narration'] for s in update['scenes']], before)
        self.assertEqual(update['full_script'], ' '.join(before))
        self.assertEqual(self.calls, [])
        self.assertEqual(update['retry_count'], 1)

    def test_api_failure_consumes_one_attempt(self):
        self.make_error()
        update = self.run_node(fail=True)
        self.assertEqual(update['status'], 'failed')
        self.assertEqual(update['retry_count'], 1)
        self.assertNotIn('scenes', update)

    def test_measured_tts_length_uses_measured_speed(self):
        for duration, texts in [
            (40, ['Meet NOVA Soft Cream with smooth application.',
                  'It spreads smoothly for easy even application.',
                  'Enjoy soft finish and comfortable feeling skin.',
                  'Discover NOVA Soft Cream with soft finish.']),
            (15, [s['narration'] + ' ' + 'Enjoy a smooth soft comfortable finish every day.' for s in self.state['scenes']])]:
            self.state['tts_duration_sec'] = duration
            request = self.ns['prepare_script_revision'](self.state)
            self.assertEqual(request['mode'], 'shorten' if duration > 30 else 'expand')
            edits = [{'edit_id': s['edit_id'], 'text': text} for s, text in zip(request['slots'], texts)]
            update = self.run_node(edits)
            self.assertEqual(update['status'], 'running', update)
            report = json.loads(Path(update['revision_json_path']).read_text(encoding='utf-8'))
            self.assertTrue(20 <= report['estimated_duration_sec'] <= 30)
            self.assertEqual(update['tts_duration_sec'], 0)

    def test_short_audio_cannot_pass_by_padding_scene_durations(self):
        self.state['tts_duration_sec'] = 15
        request = self.ns['prepare_script_revision'](self.state)
        edits = [{'edit_id': s['edit_id'], 'text': s['original']} for s in request['slots']]
        update = self.run_node(edits)
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertNotIn('scenes', update)


if __name__ == '__main__':
    unittest.main()
