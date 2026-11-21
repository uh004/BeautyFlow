"""ProductAnalyzer(2번 노드) 공통 5가지 분석·3유형 USP·우선순위·근거/이미지 검증 계약 검사. API 호출 없음."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

import test_script_generator as script_tests


class ProductAnalyzerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script_tests.ScriptGeneratorTests.setUpClass()
        cls.ns = dict(script_tests.ScriptGeneratorTests.ns)
        if 'CommonProductAnalysis' not in cls.ns:
            raise unittest.SkipTest('v2 ProductAnalyzer(MVP_v2.ipynb)에서만 실행되는 테스트입니다.')

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.img1 = str(Path(self.temp.name) / 'slide_1_img_1.jpg')
        self.img2 = str(Path(self.temp.name) / 'slide_2_img_1.jpg')
        self.img3 = str(Path(self.temp.name) / 'slide_3_img_1.jpg')
        Image.new('RGB', (1200, 1200), (235, 220, 210)).save(self.img1)
        Image.new('RGB', (1800, 866), (225, 200, 185)).save(self.img2)
        Image.new('RGB', (1400, 1100), (210, 215, 225)).save(self.img3)
        self.state = {
            'file_path': 'data/NOVA.pptx',
            'output_dir': self.temp.name,
            'status': 'running',
            'retry_count': 0,
            'max_retries': 3,
            'raw_slides': [
                {
                    'slide_no': 1,
                    'texts': ['NOVA', 'Soft Velvet Cream', 'Moisturizing cream', '50 mL', 'Price $30'],
                    'image_paths': [self.img1],
                    'text_blocks': [],
                    'image_positions': [],
                },
                {
                    'slide_no': 2,
                    'texts': ['Delivers natural-looking radiance with a soft finish.', 'Apply after serum gently.'],
                    'image_paths': [self.img2],
                    'text_blocks': [],
                    'image_positions': [],
                },
                {
                    'slide_no': 3,
                    'texts': ['A lightweight, creamy texture spreads evenly without stickiness.', 'Contains Ceramide NP for barrier comfort.'],
                    'image_paths': [self.img3],
                    'text_blocks': [],
                    'image_positions': [],
                },
            ],
        }
        self.payload = {
            'brand': {'value': 'NOVA', 'source_text_ids': ['s1_t1']},
            'product_name': {'value': 'Soft Velvet Cream', 'source_text_ids': ['s1_t2']},
            'category': {'value': 'Moisturizing cream', 'source_text_ids': ['s1_t3']},
            'volume': {'value': '50 mL', 'source_text_ids': ['s1_t4']},
            'how_to_use': {'value': 'Apply after serum gently.', 'source_text_ids': ['s2_t2']},
            'common_analysis': {
                'result_effect': {'summary': 'Natural-looking radiance with a soft finish.', 'source_text_ids': ['s2_t1']},
                'texture_feel': {'summary': 'Lightweight creamy texture that spreads evenly without stickiness.', 'source_text_ids': ['s3_t1']},
                'function_performance': {'summary': 'Supports a comfortable barrier feel.', 'source_text_ids': ['s3_t2']},
                'target_and_usage': {'summary': 'Apply gently after serum.', 'source_text_ids': ['s2_t2']},
                'ingredients_and_evidence': {'summary': None, 'source_text_ids': []},
            },
            'usps': [
                {
                    'usp_type': 'texture_feel',
                    'priority': 2,
                    'title': 'Lightweight Non-Sticky Texture',
                    'description': 'Creamy texture spreads evenly without stickiness.',
                    'source_text_ids': ['s3_t1'],
                    'image_id': 's3_i1',
                    'selection_reason': 'Highlights sensory feel with texture visual.',
                },
                {
                    'usp_type': 'result_finish',
                    'priority': 1,
                    'title': 'Natural-Looking Soft Radiance',
                    'description': 'Delivers natural-looking radiance with a soft finish.',
                    'source_text_ids': ['s2_t1'],
                    'image_id': 's2_i1',
                    'selection_reason': 'Hero visible result on a distinct slide.',
                },
            ],
        }
        self.prompts = []

    def run_node(self, payload=None):
        ns = self.ns
        prompts = self.prompts
        data = copy.deepcopy(payload or self.payload)

        class FakeChat:
            def __init__(self, **kwargs):
                assert kwargs['max_retries'] == 0

            def with_structured_output(self, schema, **kwargs):
                def respond(prompt):
                    prompts.append(prompt)
                    parsed = schema(**data)
                    return {
                        'parsed': parsed,
                        'parsing_error': None,
                        'raw': AIMessage(content='', usage_metadata={
                            'input_tokens': 500, 'output_tokens': 200, 'total_tokens': 700,
                        }),
                    }
                return RunnableLambda(respond)

        with patch.dict(ns['product_analyzer'].__globals__, {'ChatOpenAI': FakeChat}):
            return ns['product_analyzer'](self.state)

    def test_common_analysis_priority_sorting_and_image_metadata(self):
        update = self.run_node()
        self.assertEqual(update['status'], 'running', update)
        # priority=1(result_finish)이 usp_id=1로 먼저 정렬돼야 함
        self.assertEqual([u['usp_id'] for u in update['usps']], [1, 2])
        self.assertEqual([u['usp_type'] for u in update['usps']], ['result_finish', 'texture_feel'])
        self.assertEqual(update['usps'][0]['title'], 'Natural-Looking Soft Radiance')
        # 5가지 공통 분석이 State와 JSON에 모두 저장되며 null 항목도 허용됨
        ca = update['common_analysis']
        self.assertEqual(set(ca.keys()), set(self.ns['COMMON_ANALYSIS_FIELDS']))
        self.assertIsNone(ca['ingredients_and_evidence']['summary'])
        self.assertEqual(ca['ingredients_and_evidence']['source_text_ids'], [])
        # 이미지 해상도·비율 정보가 프롬프트에 전달되고 제외 정보(Price $30)는 필터링됨
        messages = self.prompts[0].to_messages()
        self.assertIn('1800x866', str(messages[-1].content))
        self.assertIn('ratio=2.08', str(messages[-1].content))
        self.assertNotIn('Price $30', messages[1].content)
        saved = json.loads(Path(update['analysis_json_path']).read_text(encoding='utf-8'))
        self.assertEqual(saved['common_analysis'], ca)
        self.assertEqual(saved['usps'], update['usps'])

    def test_rejects_invalid_common_analysis_and_usp_contracts(self):
        cases = {
            'common_analysis invented number': lambda d: d['common_analysis']['result_effect'].update(
                summary='Delivers 24 hour radiance.'
            ),
            'common_analysis excluded price': lambda d: d['common_analysis']['result_effect'].update(
                summary='Great value discount finish.'
            ),
            'common_analysis null with ids': lambda d: d['common_analysis']['ingredients_and_evidence'].update(
                summary=None, source_text_ids=['s3_t2']
            ),
            'common_analysis invalid id': lambda d: d['common_analysis']['result_effect'].update(
                source_text_ids=['s9_t9']
            ),
            'duplicate priority': lambda d: d['usps'][0].update(priority=1),
            'non-sequential priority': lambda d: d['usps'][0].update(priority=3),
            'cross-slide image': lambda d: d['usps'][0].update(image_id='s2_i1'),
            'usp invented number': lambda d: d['usps'][1].update(title='SPF 50 Soft Radiance'),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                payload = copy.deepcopy(self.payload)
                mutate(payload)
                update = self.run_node(payload)
                self.assertEqual(update['status'], 'fallback_review_required', update)
                self.assertIsNone(update['common_analysis'])
                self.assertEqual(update['usps'], [])

    def test_usp_error_retry_increments_and_respects_budget(self):
        self.state['validation_result'] = {'error_type': 'usp_error', 'feedback': 'Fix USP 1'}
        update = self.run_node()
        self.assertEqual(update['status'], 'running', update)
        self.assertEqual(update['retry_count'], 1)
        self.state['retry_count'] = 3
        blocked = self.run_node()
        self.assertEqual(blocked['status'], 'fallback_review_required')
        self.assertEqual(blocked['retry_count'], 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
