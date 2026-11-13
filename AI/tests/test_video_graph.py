"""실제 LangGraph 엔진으로 8개 노드의 연결·분기·공유 재시도 계약을 검사한다."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import test_script_generator as script_tests
import test_video_qa as qa_tests
from notebook_loader import load_definitions


class VideoGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        qa_tests.VideoQATests.setUpClass()
        cls.ns = dict(qa_tests.VideoQATests.ns)
        cls.node_names = {'DocumentParser': 'document_parser', 'ProductAnalyzer': 'product_analyzer',
                         'ScriptGenerator': 'script_generator', 'ClaimValidator': 'claim_validator',
                         'ScriptReviser': 'script_reviser', 'TTSGenerator': 'tts_generator',
                         'VideoRenderer': 'video_renderer', 'VideoQA': 'video_qa'}
        cls.ns['document_parser'] = lambda s: {'status': 'running'}
        load_definitions(cls.ns, 'build_video_graph', 'run_video_pipeline')

    def setUp(self):
        self.visited, self.counts = [], {}

    def make_graph(self, scenario='normal'):
        def make_node(name):
            def node(state):
                self.visited.append(name)
                self.counts[name] = self.counts.get(name, 0) + 1
                count = self.counts[name]
                result = {'status': 'running', 'error_message': None}
                if scenario == 'parser_failure' and name == 'DocumentParser':
                    return {'status': 'failed', 'error_message': 'missing file'}
                if scenario == 'premature_completion' and name == 'DocumentParser':
                    return {'status': 'completed'}
                if scenario == 'unexpected_error' and name == 'ProductAnalyzer':
                    raise RuntimeError('simulated provider exception')
                if name == 'DocumentParser': result['raw_slides'] = [{'slide_no': 1}]
                if name == 'ProductAnalyzer':
                    if (state.get('validation_result') or {}).get('error_type') == 'usp_error':
                        result['retry_count'] = state.get('retry_count', 0) + 1
                    result['product_info'] = {'brand': 'NOVA'}
                if name == 'ScriptGenerator':
                    result.update(full_script='NOVA script', scenes=[], validation_result={
                        'is_valid': False, 'error_type': 'none', 'issues': []})
                if name == 'ClaimValidator':
                    invalid = count == 1 and scenario in {'script_error', 'usp_error'} or scenario == 'exhausted'
                    kind = 'usp_error' if scenario in {'usp_error', 'exhausted'} else 'script_error'
                    result['validation_result'] = {'is_valid': not invalid, 'error_type': kind if invalid else 'none',
                                                   'issues': [{'status': 'unsupported'}] if invalid else []}
                    if invalid and state.get('retry_count', 0) >= state.get('max_retries', 3):
                        result['status'] = 'fallback_review_required'
                if name == 'ScriptReviser':
                    result.update(retry_count=state.get('retry_count', 0) + 1, revision_json_path='revision.json',
                                  tts_duration_sec=0, validation_result={'is_valid': False, 'error_type': 'none', 'issues': []},
                                  qa_result={'is_passed': False, 'error_type': 'none'})
                if name == 'TTSGenerator':
                    result.update(audio_path='voice.wav', tts_duration_sec=35 if scenario == 'tts_length' and count == 1 else 25,
                                  qa_result={'is_passed': False, 'error_type': 'none'})
                    if result['tts_duration_sec'] > 30 and state.get('retry_count', 0) >= state.get('max_retries', 3):
                        result['status'] = 'fallback_review_required'
                if name == 'VideoRenderer':
                    if (state.get('qa_result') or {}).get('error_type') in {'render_error', 'sync_error', 'duration_error'}:
                        result['retry_count'] = state.get('retry_count', 0) + 1
                    result.update(video_path='video.mp4', qa_result={'is_passed': False, 'error_type': 'none'})
                if name == 'VideoQA':
                    if scenario in {'qa_render', 'qa_source_length'} and count == 1:
                        result.update(qa_next_node='VideoRenderer' if scenario == 'qa_render' else 'ScriptReviser',
                                      qa_result={'is_passed': False, 'error_type': 'render_error'})
                        if scenario == 'qa_source_length': result['tts_duration_sec'] = 35
                        if state.get('retry_count', 0) >= state.get('max_retries', 3):
                            result.update(status='fallback_review_required', qa_next_node='END')
                    else:
                        result.update(status='completed', qa_next_node='END', qa_result={'is_passed': True, 'error_type': 'none'})
                return result
            return node
        replacements = {identifier: make_node(name) for name, identifier in self.node_names.items()}
        with patch.dict(self.ns, replacements):
            return self.ns['build_video_graph']()

    def invoke(self, scenario='normal', max_retries=3):
        return self.make_graph(scenario).invoke({'file_path': 'data/NOVA.pptx', 'status': 'running',
                                                'retry_count': 0, 'max_retries': max_retries},
                                               config={'recursion_limit': 40})

    def test_normal_path_and_state_merge(self):
        result = self.invoke()
        self.assertEqual(self.visited, ['DocumentParser', 'ProductAnalyzer', 'ScriptGenerator', 'ClaimValidator',
                                        'TTSGenerator', 'VideoRenderer', 'VideoQA'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['raw_slides'], [{'slide_no': 1}])
        self.assertEqual(result['retry_count'], 0)

    def test_each_correction_route_returns_and_counts_once(self):
        for scenario, repeated, corrected in [('script_error', 'ClaimValidator', 'ScriptReviser'),
                                               ('usp_error', 'ProductAnalyzer', 'ProductAnalyzer'),
                                               ('tts_length', 'TTSGenerator', 'ScriptReviser'),
                                               ('qa_render', 'VideoQA', 'VideoRenderer'),
                                               ('qa_source_length', 'TTSGenerator', 'ScriptReviser')]:
            with self.subTest(scenario=scenario):
                self.visited, self.counts = [], {}
                result = self.invoke(scenario)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(result['retry_count'], 1)
                self.assertEqual(self.counts[repeated], 2)
                self.assertIn(corrected, self.visited)

    def test_parser_failure_never_calls_paid_nodes(self):
        result = self.invoke('parser_failure')
        self.assertEqual(self.visited, ['DocumentParser'])
        self.assertEqual(result['status'], 'failed')

    def test_shared_retry_budget_stops_repeated_usp_failure(self):
        result = self.invoke('exhausted')
        self.assertEqual(result['status'], 'fallback_review_required')
        self.assertEqual(result['retry_count'], 3)
        self.assertEqual(self.counts['ProductAnalyzer'], 4)
        self.assertNotIn('TTSGenerator', self.visited)

    def test_no_retry_budget_still_allows_first_success(self):
        self.assertEqual(self.invoke(max_retries=0)['status'], 'completed')
        self.visited, self.counts = [], {}
        result = self.invoke('tts_length', max_retries=0)
        self.assertEqual(result['status'], 'fallback_review_required')
        self.assertNotIn('ScriptReviser', self.visited)

    def test_runner_records_trace_and_isolates_each_run(self):
        with TemporaryDirectory() as temporary:
            paths = []
            for _ in range(2):
                graph = self.make_graph()
                with patch.dict(self.ns, {'beautyflow_graph': graph}), contextlib.redirect_stdout(io.StringIO()):
                    result = self.ns['run_video_pipeline']('data/NOVA.pptx', temporary)
                paths.append(result['pipeline_json_path'])
                report = json.loads(Path(paths[-1]).read_text(encoding='utf-8'))
                self.assertEqual(report['status'], 'completed')
                self.assertEqual(len(report['trace']), 7)
                self.assertEqual(report['final_state']['video_path'], 'video.mp4')
            self.assertNotEqual(paths[0], paths[1])

    def test_runner_preserves_last_state_on_unexpected_exception(self):
        with TemporaryDirectory() as temporary:
            graph = self.make_graph('unexpected_error')
            with patch.dict(self.ns, {'beautyflow_graph': graph}), contextlib.redirect_stdout(io.StringIO()):
                result = self.ns['run_video_pipeline']('data/NOVA.pptx', temporary)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['raw_slides'], [{'slide_no': 1}])
            self.assertIn('RuntimeError', result['error_message'])
            report = json.loads(Path(result['pipeline_json_path']).read_text(encoding='utf-8'))
            self.assertIsNone(report['estimated_cost_usd'])

    def test_runner_never_accepts_completion_without_final_qa(self):
        with TemporaryDirectory() as temporary:
            graph = self.make_graph('premature_completion')
            with patch.dict(self.ns, {'beautyflow_graph': graph}), contextlib.redirect_stdout(io.StringIO()):
                result = self.ns['run_video_pipeline']('data/NOVA.pptx', temporary)
            self.assertEqual(result['status'], 'fallback_review_required')

    def test_graph_recursion_guard_returns_review_status(self):
        ns = self.ns
        class LimitedGraph:
            def stream(self, state, **kwargs):
                yield 'values', state
                raise ns['GraphRecursionError']('simulated graph limit')
        with TemporaryDirectory() as temporary:
            with patch.dict(ns, {'beautyflow_graph': LimitedGraph()}):
                result = ns['run_video_pipeline']('data/NOVA.pptx', temporary)
            self.assertEqual(result['status'], 'fallback_review_required')
            self.assertIn('한도', result['error_message'])

    def test_invalid_retry_setting_is_rejected(self):
        for value in [-1, True, 1.5]:
            with self.assertRaises(ValueError): self.ns['run_video_pipeline']('data/NOVA.pptx', max_retries=value)


if __name__ == '__main__':
    unittest.main()
