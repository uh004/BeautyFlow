"""정보 검증 노드의 코드 검사·모델 응답 계약·분기 검사. API 호출 없음."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
import test_script_generator as script_tests
from notebook_loader import load_definitions


class ClaimValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        script_tests.ScriptGeneratorTests.setUpClass()
        cls.ns = dict(script_tests.ScriptGeneratorTests.ns)
        load_definitions(cls.ns, 'claim_validator')

    def setUp(self):
        fixture = script_tests.ScriptGeneratorTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.state = fixture.state
        scenes, script, _ = fixture.resolve()
        self.state.update(scenes=scenes, full_script=script)
        self.calls = []

    def fake_chat(self, change=None, api_failure=False):
        ns, calls = self.ns, self.calls
        class FakeChat:
            def __init__(self, **kwargs):
                assert kwargs['model'] == 'gpt-6-luna' and kwargs['max_retries'] == 0
            def with_structured_output(self, schema, **kwargs):
                assert schema == ns['ClaimReview'].model_json_schema()
                def respond(prompt):
                    calls.append(prompt)
                    if api_failure:
                        raise RuntimeError('simulated API failure')
                    human = prompt.to_messages()[1].content
                    sources_text, candidates_text = human.split('## Candidates to validate\n', 1)
                    sources = json.loads(sources_text.split('## Original document\n', 1)[1].strip())
                    candidates = json.loads(candidates_text)
                    verdicts = [{'candidate_id': c['candidate_id'], 'status': 'supported',
                                 'source_text_ids': c['evidence_ids'] or [sources[0]['id']],
                                 'problematic_claims': [], 'reason': 'Supported paraphrase.', 'suggested_action': ''}
                                for c in candidates]
                    if change:
                        change(verdicts, candidates)
                    return {'parsed': ns['ClaimReview'](verdicts=verdicts).model_dump(), 'parsing_error': None,
                            'raw': AIMessage(content='', usage_metadata={
                                'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150})}
                return RunnableLambda(respond)
        return FakeChat

    def validate(self, change=None, api_failure=False):
        with patch.dict(self.ns, {'ChatOpenAI': self.fake_chat(change, api_failure)}):
            return self.ns['claim_validator'](self.state)

    def next_node(self, update):
        return self.ns['route_after_claim_validation']({**self.state, **update})

    @staticmethod
    def reject(verdicts, candidates, key, status='unsupported'):
        index = next(i for i, v in enumerate(verdicts) if v['candidate_id'] == key)
        verdicts[index].update(status=status, problematic_claims=[candidates[index]['text']],
                               reason='The cited wording does not establish this claim.',
                               suggested_action='Remove or weaken the unsupported statement.')

    def change_narration(self, text):
        self.state['scenes'][1].update(narration=text, subtitle=text)
        self.state['full_script'] = ' '.join(s['narration'] for s in self.state['scenes'])

    def test_supported_result_and_report(self):
        before = copy.deepcopy(self.state)
        update = self.validate()
        self.assertTrue(update['validation_result']['is_valid'])
        self.assertEqual(update['validation_result']['issues'], [])
        self.assertEqual(self.next_node(update), 'TTSGenerator')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.state, before)
        report = json.loads(Path(update['validation_json_path']).read_text(encoding='utf-8'))
        self.assertTrue(report['semantic_review_completed'])
        self.assertEqual(report['checked_candidates'], len(report['verdicts']))

    def test_json_schema_rejects_unknown_fields_at_every_object(self):
        schema = self.ns['ClaimReview'].model_json_schema()
        self.assertIs(schema['additionalProperties'], False)
        self.assertIs(schema['$defs']['ClaimVerdict']['additionalProperties'], False)

    def test_subtitle_only_error_is_blocked_without_api(self):
        self.state['scenes'][1]['subtitle'] = 'Repairs damaged skin.'
        update = self.validate()
        self.assertFalse(update['validation_result']['is_valid'])
        self.assertEqual(update['validation_result']['error_type'], 'script_error')
        self.assertEqual(self.next_node(update), 'ScriptReviser')
        self.assertEqual(self.calls, [])

    def test_unsupported_number_is_blocked_without_api(self):
        self.change_narration('Lasts 24 hours.')
        update = self.validate()
        self.assertFalse(update['validation_result']['is_valid'])
        self.assertEqual(self.calls, [])
        self.assertTrue(any('수치' in i['reason'] for i in update['validation_result']['issues']))

    def test_full_script_mismatch_is_blocked(self):
        self.state['full_script'] = 'Unrelated stale script.'
        update = self.validate()
        self.assertEqual(self.next_node(update), 'ScriptReviser')
        self.assertEqual(self.calls, [])

    def test_unsupported_semantic_claim_routes_to_reviser(self):
        self.change_narration('Repairs damaged skin.')
        update = self.validate(lambda v, c: self.reject(v, c, 'scene:2:narration'))
        self.assertFalse(update['validation_result']['is_valid'])
        self.assertEqual(self.next_node(update), 'ScriptReviser')
        self.assertEqual(update['validation_result']['issues'][0]['scene_no'], 2)

    def test_numbers_with_wrong_units_require_semantic_review(self):
        self.state['raw_slides'][0]['texts'].append('Volume: 24 mL.')
        self.state['scenes'][1]['source_text_ids'].append('s1_t4')
        self.change_narration('Lasts 24 hours.')
        update = self.validate(lambda v, c: self.reject(v, c, 'scene:2:narration'))
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(update['validation_result']['is_valid'])

    def test_usp_semantic_error_has_priority_over_script_error(self):
        def change(v, c):
            self.reject(v, c, 'scene:2:narration')
            self.reject(v, c, 'usp:1:title')
        update = self.validate(change)
        self.assertEqual(update['validation_result']['error_type'], 'usp_error')
        self.assertEqual(self.next_node(update), 'ProductAnalyzer')

    def test_invalid_usp_reference_has_priority(self):
        self.state['usps'][0]['source_quote'] = 'Invented source.'
        self.state['scenes'][1]['subtitle'] = 'Changed subtitle.'
        update = self.validate()
        self.assertEqual(update['validation_result']['error_type'], 'usp_error')
        self.assertEqual(self.next_node(update), 'ProductAnalyzer')

    def test_uncertain_verdict_requires_review(self):
        update = self.validate(lambda v, c: self.reject(v, c, 'scene:2:narration', 'uncertain'))
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertFalse(update['validation_result']['is_valid'])
        self.assertEqual(self.next_node(update), 'END')

    def test_last_retry_can_still_pass_validation(self):
        self.state.update(retry_count=3, max_retries=3)
        update = self.validate()
        self.assertTrue(update['validation_result']['is_valid'])
        self.assertEqual(self.next_node(update), 'TTSGenerator')
        self.assertNotIn('retry_count', update)

    def test_failed_last_retry_stops(self):
        self.state.update(retry_count=3, max_retries=3)
        update = self.validate(lambda v, c: self.reject(v, c, 'scene:2:narration'))
        self.assertEqual(update['status'], 'fallback_review_required')
        self.assertEqual(self.next_node(update), 'END')

    def test_missing_duplicate_or_extra_model_verdict_fails_closed(self):
        for mutate in [lambda v: v.pop(), lambda v: v.append(copy.deepcopy(v[0])),
                       lambda v: v[0].update(candidate_id='invented')]:
            with self.subTest(mutate=mutate):
                update = self.validate(lambda v, c: mutate(v))
                self.assertEqual(update['status'], 'fallback_review_required')
                self.assertFalse(update['validation_result']['is_valid'])

    def test_invented_evidence_or_error_phrase_fails_closed(self):
        def invalid_phrase(v, c):
            self.reject(v, c, 'scene:2:narration')
            next(x for x in v if x['candidate_id'] == 'scene:2:narration')['problematic_claims'] = ['not in the candidate']
        for change in [lambda v, c: v[0].update(source_text_ids=['invented']),
                       lambda v, c: v[0].update(source_text_ids=[]), invalid_phrase]:
            with self.subTest(change=change):
                update = self.validate(change)
                self.assertFalse(update['validation_result']['is_valid'])
                self.assertEqual(self.next_node(update), 'END')

    def test_api_or_upstream_failure_never_passes(self):
        update = self.validate(api_failure=True)
        self.assertEqual(update['status'], 'failed')
        self.assertFalse(update['validation_result']['is_valid'])
        self.state['status'] = 'failed'
        update = self.validate()
        self.assertFalse(update['validation_result']['is_valid'])
        self.assertEqual(self.next_node(update), 'END')


if __name__ == '__main__':
    unittest.main(verbosity=2)
