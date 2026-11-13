"""노트북 영상 기획 노드의 계약·실패 조건 검사. 실제 API는 호출하지 않는다."""
import base64
import contextlib
import copy
import io
import json
import re
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, List, Literal, Optional, TypedDict
from unittest.mock import patch

from PIL import Image
from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from notebook_loader import load_definitions


ROOT = Path(__file__).resolve().parents[2]


class ScriptGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = dict(globals(), BytesIO=io.BytesIO, PROJECT_ROOT=ROOT, OPENAI_API_KEY='offline-test')
        with contextlib.redirect_stdout(io.StringIO()):
            load_definitions(cls.ns, 'VideoAgentState', 'product_analyzer', 'script_generator')

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = str(Path(self.temp.name) / 'synthetic.jpg')
        Image.new('RGB', (80, 100), 'white').save(self.image)
        self.texts = ['NOVA Soft Cream',
                      'It spreads smoothly across skin for an easy, even application.',
                      'Enjoy a soft finish that helps skin feel comfortable every day.']
        self.state = {'file_path': 'data/NOVA.pptx', 'output_dir': self.temp.name,
                      'status': 'running', 'retry_count': 2, 'max_retries': 3,
                      'raw_slides': [{'slide_no': 1, 'texts': self.texts,
                                      'image_paths': [self.image]}],
                      'product_info': {'brand': 'NOVA', 'product_name': 'Soft Cream', 'category': 'Cream',
                                       'volume': None, 'how_to_use': None},
                      'usps': [{'usp_id': i, 'title': title, 'description': self.texts[i],
                                'source_slide_no': 1, 'source_quote': self.texts[i],
                                'matched_image_path': self.image}
                               for i, title in [(1, 'Smooth application'), (2, 'Soft finish')]]}
        self.context = self.ns['prepare_script_context'](self.state)
        narrations = ['Meet NOVA Soft Cream, a cream with a smooth, comfortable, soft finish.',
                      self.texts[1], self.texts[2],
                      'Discover NOVA Soft Cream and its smooth application with a soft finish.']
        self.plan = {'creative_direction': 'Product, application, finish, product.', 'scenes': [
            {'purpose': purpose, 'image_id': 's1_i1', 'narration': narration, 'motion_effect': 'static',
             'usp_ids': usp_ids, 'source_text_ids': source_ids}
            for purpose, narration, usp_ids, source_ids in zip(
                ['hook', 'usp', 'usp', 'outro'], narrations,
                [[], [1], [2], []], [['s1_t1', 's1_t2', 's1_t3'], ['s1_t2'], ['s1_t3'], ['s1_t1', 's1_t2', 's1_t3']])
        ]}

    def resolve(self, value=None):
        return self.ns['resolve_storyboard'](self.ns['StoryboardPlan'](**(value or self.plan)), self.context)

    def test_contract_and_subtitle_consistency(self):
        before = copy.deepcopy(self.state)
        scenes, script, checks = self.resolve()
        self.assertEqual(script, ' '.join(s['narration'] for s in scenes))
        self.assertTrue(all(s['subtitle'] == s['narration'] for s in scenes))
        self.assertTrue(all(s['audio_segment_path'] is None for s in scenes))
        self.assertEqual(checks['estimated_duration_sec'], 25.0)
        self.assertTrue(all(2 <= s['duration_sec'] <= 7 for s in scenes))
        self.assertTrue(45 <= checks['word_count'] <= 65)
        self.assertFalse(checks['tts_measured'])
        self.assertEqual(self.state, before)

    def test_prompt_context_and_image_connections(self):
        values = self.ns['script_prompt_inputs'](self.context)
        messages = self.ns['SCRIPT_PROMPT'].invoke(values).to_messages()
        self.assertIn('## Evidence', messages[0].content)
        self.assertIn('s1_t2', messages[1].content)
        self.assertIn('s1_i1', messages[1].content)
        self.assertEqual(sum(b.get('type') == 'image_url' for b in messages[-1].content), 1)
        self.assertNotIn(self.image, messages[1].content)

    def test_multiple_quotes_and_excluded_context(self):
        self.state['raw_slides'][0]['texts'] += ['Blends evenly.', 'PRICE $20', '무료 배송']
        self.state['usps'][0]['source_quote'] += '\n\nBlends evenly.'
        context = self.ns['prepare_script_context'](self.state)
        self.assertEqual(context['usps'][0]['evidence_ids'], ['s1_t2', 's1_t4'])
        self.assertNotIn('s1_t5', context['text_map'])
        self.assertNotIn('s1_t6', context['text_map'])

    def test_invalid_plan_cases(self):
        cases = {
            'missing image': lambda p: p['scenes'][1].update(image_id='absent'),
            'missing source': lambda p: p['scenes'][1].update(source_text_ids=['absent']),
            'empty source': lambda p: p['scenes'][1].update(source_text_ids=[]),
            'duplicate source': lambda p: p['scenes'][1].update(source_text_ids=['s1_t2', 's1_t2']),
            'unrelated evidence': lambda p: p['scenes'][1].update(source_text_ids=['s1_t1']),
            'unknown USP': lambda p: p['scenes'][1].update(usp_ids=[99]),
            'duplicate USP': lambda p: p['scenes'][1].update(usp_ids=[1, 1]),
            'missing USP': lambda p: p['scenes'][2].update(purpose='outro', usp_ids=[]),
            'wrong opening': lambda p: p['scenes'][0].update(purpose='usp'),
            'missing identity': lambda p: p['scenes'][0].update(narration='Discover a smooth finish for your daily routine.'),
            'unsupported number': lambda p: p['scenes'][1].update(narration='Lasts 24 hours.'),
            'excluded price': lambda p: p['scenes'][1].update(narration='Buy for $20.'),
            'non-English': lambda p: p['scenes'][1].update(narration='피부에 부드럽게 발립니다.'),
            'overlong narration': lambda p: p['scenes'][1].update(narration=self.texts[1] + ' ' + self.texts[1]),
            'empty narration': lambda p: p['scenes'][1].update(narration=''),
            'too few scenes': lambda p: p['scenes'].pop(),
            'unsupported motion': lambda p: p['scenes'][1].update(motion_effect='spin'),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                plan = copy.deepcopy(self.plan)
                mutate(plan)
                with self.assertRaises(ValueError): self.resolve(plan)

    def make_long_plan(self, extra_words=0):
        self.state['product_info']['how_to_use'] = 'Apply gently across skin.'
        self.state['usps'].append({**self.state['usps'][1], 'usp_id': 3, 'title': 'Comfortable feel'})
        self.context = self.ns['prepare_script_context'](self.state)
        sentences = [
            'Meet NOVA Soft Cream, a cream with a smooth, comfortable, soft finish.',
            'It spreads smoothly across skin for an easy and even application experience.',
            'Enjoy a soft finish that helps skin feel comfortable with daily application.',
            'Soft Cream brings a soft finish that helps skin feel comfortable daily.',
            'Apply Soft Cream gently across skin for a smooth and even application.',
            'Discover NOVA Soft Cream and its smooth application with a soft finish.',
        ]
        plan = copy.deepcopy(self.plan)
        plan['scenes'] = [
            {**self.plan['scenes'][0], 'purpose': purpose, 'narration': text,
             'usp_ids': ids, 'source_text_ids': sources}
            for purpose, text, ids, sources in zip(
                ['hook', 'usp', 'usp', 'usp', 'how_to_use', 'outro'], sentences,
                [[], [1], [2], [3], [], []],
                [['s1_t1', 's1_t2', 's1_t3'], ['s1_t2'], ['s1_t3'], ['s1_t3'], ['s1_t2'], ['s1_t1', 's1_t2', 's1_t3']])
        ]
        for index in range(extra_words):
            plan['scenes'][index]['narration'] += ' Gently.'
        return plan

    def test_72_words_within_duration_is_accepted(self):
        scenes, script, checks = self.resolve(self.make_long_plan())
        self.assertEqual(checks['word_count'], 72)
        self.assertEqual(checks['estimated_duration_sec'], 28.8)
        self.assertEqual(len(checks['warnings']), 1)
        self.assertTrue(all(s['subtitle'] == s['narration'] for s in scenes))

    def test_30_seconds_boundary_is_accepted(self):
        _, _, checks = self.resolve(self.make_long_plan(extra_words=3))
        self.assertEqual(checks['word_count'], 75)
        self.assertEqual(checks['estimated_duration_sec'], 30.0)

    def test_duration_over_30_seconds_is_rejected(self):
        with self.assertRaisesRegex(ValueError, '20~30'):
            self.resolve(self.make_long_plan(extra_words=4))

    def test_short_script_is_advisory_not_a_word_count_failure(self):
        plan = copy.deepcopy(self.plan)
        plan['scenes'][1]['narration'] = 'Smooth application.'
        _, _, checks = self.resolve(plan)
        self.assertLess(checks['word_count'], 45)
        self.assertEqual(checks['estimated_duration_sec'], 25.0)
        self.assertEqual(len(checks['warnings']), 1)

    def make_revision_plans(self):
        long_plan = self.make_long_plan()
        for index in range(17):
            long_plan['scenes'][index % 6]['narration'] += ' Gently.'
        short_plan = copy.deepcopy(long_plan)
        shortened = [
            'Meet NOVA Soft Cream for smooth application and a comfortable finish.',
            'It spreads smoothly across skin for easy, even application.',
            'Enjoy a soft finish that helps skin feel comfortable.',
            'Soft Cream leaves skin feeling comfortable with a soft finish.',
            'Apply gently across skin for a smooth, even finish.',
            'Discover NOVA Soft Cream for smooth application and a soft finish.',
        ]
        for scene, narration in zip(short_plan['scenes'], shortened):
            scene['narration'] = narration
        return long_plan, short_plan

    def fake_revision_chat(self, long_plan, short_plan, calls, invalid_numbering=False):
        ns = self.ns
        class FakeChat:
            def __init__(self, **kwargs):
                assert kwargs['max_retries'] == 0
            def with_structured_output(self, schema, **kwargs):
                def respond(prompt):
                    calls.append(schema.__name__)
                    if schema is ns['StoryboardPlan']:
                        value = schema(**long_plan)
                    else:
                        value = schema(scenes=[{'scene_no': 1 if invalid_numbering else i,
                                                'narration': scene['narration']}
                                               for i, scene in enumerate(short_plan['scenes'], 1)])
                    return {'parsed': value, 'parsing_error': None,
                            'raw': AIMessage(content='', usage_metadata={
                                'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150})}
                return RunnableLambda(respond)
        return FakeChat

    def test_89_words_are_shortened_without_replanning(self):
        long_plan, short_plan = self.make_revision_plans()
        calls = []
        with patch.dict(self.ns, {'ChatOpenAI': self.fake_revision_chat(long_plan, short_plan, calls)}):
            update = self.ns['script_generator'](self.state)
        self.assertEqual(update['status'], 'running', update.get('error_message'))
        self.assertEqual(calls, ['StoryboardPlan', 'NarrationRevision'])
        self.assertEqual(update['retry_count'], 3)  # 기존 2회에서 1회만 증가
        saved = json.loads(Path(update['script_json_path']).read_text(encoding='utf-8'))
        self.assertEqual(saved['revision_history'][0]['before_words'], 89)
        self.assertEqual(saved['model_calls'], 2)
        self.assertEqual(saved['usage']['total_tokens'], 300)
        self.assertTrue(20 <= saved['estimated_duration_sec'] <= 30)
        for original, actual in zip(long_plan['scenes'], update['scenes']):
            for field in ['purpose', 'motion_effect', 'usp_ids', 'source_text_ids']:
                self.assertEqual(actual[field], original[field])
            self.assertEqual(actual['image_path'], self.context['assets'][original['image_id']]['path'])
            self.assertEqual(actual['subtitle'], actual['narration'])

    def test_length_revision_stops_at_shared_retry_limit(self):
        long_plan, _ = self.make_revision_plans()
        self.state.update(retry_count=0, max_retries=3)
        calls = []
        with patch.dict(self.ns, {'ChatOpenAI': self.fake_revision_chat(long_plan, long_plan, calls)}):
            update = self.ns['script_generator'](self.state)
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(update['retry_count'], 3)
        self.assertEqual(len(calls), 4)  # 최초 생성 + 수정 3회
        self.assertIn('상한', update['error_message'])
        self.assertEqual(update['scenes'], [])
        self.assertIsNone(update['script_json_path'])

    def test_exhausted_retry_budget_does_not_call_reviser(self):
        long_plan, short_plan = self.make_revision_plans()
        self.state.update(retry_count=3, max_retries=3)
        calls = []
        with patch.dict(self.ns, {'ChatOpenAI': self.fake_revision_chat(long_plan, short_plan, calls)}):
            update = self.ns['script_generator'](self.state)
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(calls, ['StoryboardPlan'])

    def test_invalid_evidence_is_not_retried_as_a_length_issue(self):
        plan = copy.deepcopy(self.plan)
        plan['scenes'][1]['source_text_ids'] = ['absent']
        calls = []
        with patch.dict(self.ns, {'ChatOpenAI': self.fake_revision_chat(plan, plan, calls)}):
            update = self.ns['script_generator'](self.state)
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(calls, ['StoryboardPlan'])
        self.assertEqual(update['retry_count'], self.state['retry_count'])

    def test_reviser_cannot_change_scene_count_or_numbering(self):
        long_plan, short_plan = self.make_revision_plans()
        calls = []
        with patch.dict(self.ns, {'ChatOpenAI': self.fake_revision_chat(
                long_plan, short_plan, calls, invalid_numbering=True)}):
            update = self.ns['script_generator'](self.state)
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertIn('장면 개수', update['error_message'])
        self.assertEqual(len(calls), 2)

    def test_invalid_source_states(self):
        cases = {
            'failed upstream': lambda s: s.update(status='failed'),
            'missing product': lambda s: s.update(product_info=None),
            'missing raw slides': lambda s: s.update(raw_slides=[]),
            'insufficient USP': lambda s: s['usps'].pop(),
            'duplicate USP IDs': lambda s: s['usps'][1].update(usp_id=1),
            'invented quote': lambda s: s['usps'][0].update(source_quote='Invented claim.'),
            'wrong image': lambda s: s['usps'][0].update(matched_image_path='missing.jpg'),
            'excluded product': lambda s: s['product_info'].update(how_to_use='Price $20'),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                state = copy.deepcopy(self.state)
                mutate(state)
                with self.assertRaises(ValueError): self.ns['prepare_script_context'](state)

    def test_node_output_and_json_without_api(self):
        calls = []
        plan = self.ns['StoryboardPlan'](**self.plan)
        class FakeChat:
            def __init__(self, **kwargs):
                assert kwargs['max_retries'] == 0
            def with_structured_output(self, *args, **kwargs):
                def respond(prompt):
                    calls.append(prompt)
                    return {'parsed': plan, 'parsing_error': None,
                            'raw': AIMessage(content='', usage_metadata={'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150})}
                return RunnableLambda(respond)
        before = copy.deepcopy(self.state)
        with patch.dict(self.ns, {'ChatOpenAI': FakeChat}):
            update = self.ns['script_generator'](self.state)
        self.assertEqual(update['status'], 'running', update.get('error_message'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.state, before)
        merged = {**self.state, **update}
        self.assertEqual(merged['retry_count'], 2)
        self.assertFalse(merged['validation_result']['is_valid'])
        self.assertEqual(merged['audio_path'], '')
        saved = json.loads(Path(merged['script_json_path']).read_text(encoding='utf-8'))
        self.assertEqual(saved['scenes'], merged['scenes'])
        self.assertEqual(saved['full_script'], merged['full_script'])

    def test_failure_clears_previous_storyboard(self):
        self.state.update(status='failed', scenes=[{'old': True}], full_script='stale', script_json_path='old.json')
        update = self.ns['script_generator'](self.state)
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(update['scenes'], [])
        self.assertEqual(update['full_script'], '')
        self.assertIsNone(update['script_json_path'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
