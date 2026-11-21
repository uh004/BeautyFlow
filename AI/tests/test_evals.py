"""4종 AI Agent 평가 모듈(AgentEvals · Python/Pytest · Adversarial 6종 · 리포트) 단위 테스트."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from AI.evals.code_eval import compute_pass_at_k, compute_pass_pow_k, evaluate_run_deterministic
from AI.evals.dataset import run_adversarial_suite
from AI.evals.judge_eval import (
    PairwiseJudgment,
    RubricScore,
    VideoQualityJudgment,
    evaluate_v1_vs_v2_pairwise,
    evaluate_video_with_vlm_judge,
)
from AI.evals.run_eval import _make_langsmith_evaluators, render_markdown_report
from AI.evals.trajectory_eval import (
    IDEAL_TRAJECTORY,
    evaluate_exact_trajectory,
    evaluate_handoff,
    evaluate_in_order_trajectory,
    evaluate_run_trajectory,
)


class BeautyFlowEvalsTests(unittest.TestCase):
    def test_agentevals_exact_and_in_order_match(self):
        # 1차 직진(retry=0) → Exact True, In-Order True
        res = evaluate_exact_trajectory(IDEAL_TRAJECTORY)
        self.assertTrue(res["score"])
        self.assertTrue(evaluate_in_order_trajectory(IDEAL_TRAJECTORY))

        # 1회 수정 루프 포함 → Exact False, In-Order True
        with_retry = [
            "DocumentParser",
            "ProductAnalyzer",
            "ScriptGenerator",
            "ClaimValidator",
            "ScriptReviser",
            "ClaimValidator",
            "TTSGenerator",
            "VideoRenderer",
            "VideoQA",
        ]
        self.assertFalse(evaluate_exact_trajectory(with_retry)["score"])
        self.assertTrue(evaluate_in_order_trajectory(with_retry))
        self.assertTrue(evaluate_handoff(with_retry, expected_transition=("ClaimValidator", "ScriptReviser")))

        summary = evaluate_run_trajectory([{"node": n} for n in with_retry], {"retry_count": 1})
        self.assertEqual(summary["retry_count"], 1)
        self.assertFalse(summary["exact_match"])
        self.assertTrue(summary["in_order_match"])

    def test_pass_at_k_and_pass_pow_k(self):
        self.assertEqual(compute_pass_at_k(3, 3, 3), 1.0)
        self.assertEqual(compute_pass_pow_k(3, 3, 3), 1.0)
        self.assertAlmostEqual(compute_pass_pow_k(2, 1, 2), 0.25)
        self.assertEqual(compute_pass_at_k(2, 1, 2), 1.0)

    def test_adversarial_six_mandatory_cases_all_pass(self):
        cases = run_adversarial_suite()
        self.assertEqual(len(cases), 6)
        for case in cases:
            self.assertTrue(case["passed"], f"Failed adversarial case: {case}")
            self.assertTrue(case["handoff_ok"], f"Handoff mismatch: {case}")

    def test_render_markdown_report_contains_core_sections(self):
        dummy = {
            "timestamp": "2026-11-20T15:50:00",
            "repeats": 1,
            "langsmith": {"project": "BeautyFlow-Eval", "dataset": "BeautyFlow-Benchmark-v2", "experiment_name": "exp-1"},
            "overview": {
                "pass_at_k": 1.0,
                "pass_pow_k": 1.0,
                "in_order_rate": 1.0,
                "exact_match_rate": 1.0,
                "avg_retry_count": 0.0,
                "total_unsupported_claims": 0,
                "video_spec_rate": 1.0,
                "vlm_avg_score": 4.6,
                "avg_elapsed_sec": 95.0,
                "avg_cost_usd": 0.018,
            },
            "golden_runs": [
                {
                    "product_id": "LUMIA",
                    "category": "Cushion",
                    "trial": 1,
                    "trajectory": {"retry_count": 0, "exact_match": True, "in_order_match": True},
                    "deterministic": {
                        "status": "completed",
                        "video_duration_sec": 24.5,
                        "audio_correlation": 0.991,
                        "unsupported_claims_count": 0,
                        "elapsed_sec": 95.0,
                        "estimated_cost_usd": 0.018,
                        "creative_direction": {"background_tone": "deep_dark", "typography_style": "editorial_serif"},
                        "video_path": "LUMIA.mp4",
                        "qa_preview_path": "qa_preview.jpg",
                    },
                    "vlm_judge": {
                        "skipped": False,
                        "average_score": 4.6,
                        "scores": {"groundedness": 5, "hook_appeal": 5, "usp_clarity": 5, "visual_alignment": 4, "brand_consistency": 4},
                        "overall_summary": "Clean editorial luxury short-form.",
                    },
                }
            ],
            "adversarial": {"total_count": 6, "passed_count": 6, "handoff_accuracy": 1.0, "cases": []},
            "pytest_regression": {"passed": 110, "failed": 0, "errors": 0, "pass_rate": 1.0},
            "v1_vs_v2_pairwise": {"skipped": False, "product": "LUMIA", "blind_order": {"A": "v2", "B": "v1"}, "winner": "v2", "visual_polish_winner": "v2", "readability_winner": "v2", "brand_mood_winner": "v2", "rationale": "Cleaner layout."},
        }
        md = render_markdown_report(dummy)
        self.assertIn("BeautyFlow AI Agent 정량 평가 리포트", md)
        self.assertIn("AgentEvals", md)
        self.assertIn("v1 (개선 전) vs v2.3 (개선 후)", md)

    def test_deterministic_code_eval_pass_and_fail(self):
        with tempfile.TemporaryDirectory(prefix="eval_det_") as tmp:
            tdir = Path(tmp)
            val_p = tdir / "val.json"
            qa_p = tdir / "qa.json"
            ren_p = tdir / "render.json"
            vid_p = tdir / "demo.mp4"
            vid_p.write_bytes(b"mp4")
            val_p.write_text(json.dumps({"code_checks": {"cosmetic_claim_guard": "passed", "badge_labels": "passed"}}), encoding="utf-8")
            qa_p.write_text(json.dumps({"checks": [
                {"name": "subtitle_single_line", "passed": True},
                {"name": "audio_similarity", "passed": True, "details": {"correlation": 0.995}},
            ]}), encoding="utf-8")
            ren_p.write_text(json.dumps({"creative_direction": {"background_tone": "deep_dark"}}), encoding="utf-8")

            report = {
                "elapsed_sec": 120.5,
                "known_estimated_cost_usd": 0.02,
                "final_state": {
                    "status": "completed",
                    "video_path": str(vid_p),
                    "validation_json_path": str(val_p),
                    "qa_json_path": str(qa_p),
                    "render_json_path": str(ren_p),
                    "validation_result": {"is_valid": True, "unsupported_claims": []},
                    "qa_result": {"is_passed": True, "resolution": "1080x1920", "video_duration_sec": 25.4},
                },
            }
            ok = evaluate_run_deterministic(report)
            self.assertTrue(ok["completed"])
            self.assertTrue(ok["video_spec_passed"])
            self.assertTrue(ok["code_checks_passed"])
            self.assertEqual(ok["unsupported_claims_count"], 0)

            # 규격 위반(35초) + 미지원 주장 1건 -> completed=False
            report["final_state"]["qa_result"]["video_duration_sec"] = 35.0
            report["final_state"]["validation_result"]["unsupported_claims"] = ["SPF 50+"]
            bad = evaluate_run_deterministic(report)
            self.assertFalse(bad["completed"])
            self.assertFalse(bad["video_spec_passed"])
            self.assertEqual(bad["unsupported_claims_count"], 1)

    def test_vlm_judge_and_blind_pairwise_mocked(self):
        class FakeRaw:
            usage_metadata = {"input_tokens": 1000, "output_tokens": 200}

        class FakeStructured:
            def __init__(self, parsed_obj):
                self._obj = parsed_obj

            def invoke(self, _messages):
                return {"parsing_error": None, "parsed": self._obj, "raw": FakeRaw()}

        class FakeChat:
            parsed_obj = None

            def __init__(self, **kwargs):
                pass

            def with_structured_output(self, *_args, **_kwargs):
                return FakeStructured(self.parsed_obj)

        with tempfile.TemporaryDirectory(prefix="eval_vlm_") as tmp:
            tdir = Path(tmp)
            v1_img = tdir / "v1.jpg"
            v2_img = tdir / "qa_preview.jpg"
            vid = tdir / "demo.mp4"
            Image.new("RGB", (540, 480), (40, 40, 40)).save(v1_img)
            Image.new("RGB", (540, 480), (200, 180, 170)).save(v2_img)
            vid.write_bytes(b"mp4")

            FakeChat.parsed_obj = VideoQualityJudgment(
                groundedness=RubricScore(score=5, rationale="Faithful."),
                hook_appeal=RubricScore(score=4, rationale="Clear hook."),
                usp_clarity=RubricScore(score=5, rationale="Sharp USPs."),
                visual_alignment=RubricScore(score=4, rationale="Aligned."),
                brand_consistency=RubricScore(score=5, rationale="Cohesive."),
                overall_summary="Strong ad.",
            )
            with patch("AI.evals.judge_eval.ChatOpenAI", FakeChat), patch("AI.evals.judge_eval.OPENAI_API_KEY", "test-key"):
                res = evaluate_video_with_vlm_judge({
                    "final_state": {"video_path": str(vid), "scenes": [], "raw_slides": [], "product_info": {}}
                })
                self.assertFalse(res["skipped"])
                self.assertEqual(res["average_score"], 4.6)
                self.assertEqual(res["scores"]["groundedness"], 5)

                # 블라인드 A/B 매핑 검증 (winner='A'가 실제 배정된 v1/v2로 정확히 역매핑되는지)
                FakeChat.parsed_obj = PairwiseJudgment(
                    winner="A",
                    visual_polish_winner="A",
                    readability_winner="tie",
                    brand_mood_winner="A",
                    rationale="A is cleaner.",
                )
                ab = evaluate_v1_vs_v2_pairwise(v1_img, v2_img, seed=42)
                self.assertFalse(ab["skipped"])
                self.assertEqual(ab["winner"], ab["blind_order"]["A"])
                self.assertEqual(ab["readability_winner"], "tie")

    def test_langsmith_evaluators_all_13_keys(self):
        evaluators = _make_langsmith_evaluators()
        self.assertEqual(len(evaluators), 13)
        sample_out = {
            "trajectory": {"exact_match": True, "in_order_match": True, "retry_count": 0},
            "deterministic": {"completed": True, "unsupported_claims_count": 0, "video_spec_passed": True, "audio_correlation": 0.998},
            "vlm_judge": {
                "average_score": 4.4,
                "overall_summary": "Good",
                "scores": {"groundedness": 5, "hook_appeal": 4, "usp_clarity": 4, "visual_alignment": 4, "brand_consistency": 5},
                "rationales": {"groundedness": "ok", "hook_appeal": "ok", "usp_clarity": "ok", "visual_alignment": "ok", "brand_consistency": "ok"},
            },
        }
        keys = [fn(sample_out)["key"] for fn in evaluators]
        self.assertIn("vlm_groundedness", keys)
        self.assertIn("vlm_brand_consistency", keys)
        self.assertIn("retry_count", keys)
        self.assertIn("audio_sync_correlation", keys)


if __name__ == "__main__":
    unittest.main()
