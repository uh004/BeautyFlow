"""벤치마크 데이터셋 정의: Golden 3종(LUMIA·SOLAIA·DERMERA) + 6대 오류 유도 사례(Adversarial Set).

AI/AGENTS.md Section 4의 6대 예외 케이스를 실제 AI/beautyflow LangGraph 경로로 검증하며
API 비용 0원으로 100% 결정론적 방어·복구 정확도를 측정한다.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from pptx import Presentation

from AI.beautyflow.config import PROJECT_ROOT
from AI.beautyflow.graph import build_video_graph, run_video_pipeline
from AI.beautyflow.nodes import (
    claim_validator,
    document_parser,
    product_analyzer,
    script_reviser,
    video_qa,
)
from AI.evals.trajectory_eval import evaluate_handoff, extract_steps_from_trace

# Golden Set (카테고리 3종: 쿠션 · 선세럼 · 크림)
GOLDEN_CASES: list[dict[str, Any]] = [
    {"id": "LUMIA", "file_path": "data/LUMIA.pptx", "category": "Cushion"},
    {"id": "SOLAIA", "file_path": "data/SOLAIA.pptx", "category": "Sun Serum"},
    {"id": "DERMERA", "file_path": "data/DERMERA.pptx", "category": "Cream"},
]


def _make_base_state(workdir: Path) -> dict[str, Any]:
    """오류 주입 시나리오에서 공유하는 최소 유효 State(로컬 이미지 1장 포함)를 생성한다."""
    from PIL import Image

    img_path = workdir / "slide_1_img_1.png"
    Image.new("RGB", (600, 600), (220, 210, 200)).save(img_path)
    slides = [
        {
            "slide_no": 1,
            "title": "LUMIA Soft Satin Cushion",
            "texts": [
                "LUMIA Soft Satin Cushion 15g Cushion",
                "Helps even the appearance of skin tone with a soft satin finish.",
                "Light texture blends smoothly for comfortable wear.",
                "Press puff lightly and pat evenly onto skin.",
            ],
            "image_paths": [str(img_path)],
            "all_titles": ["LUMIA Soft Satin Cushion"],
            "body_paragraphs": [],
            "elements": [],
            "text_blocks": [],
            "image_positions": [],
        }
    ]
    usps = [
        {
            "usp_id": 1,
            "usp_type": "result_finish",
            "title": "Soft Satin Finish",
            "description": "Helps even the appearance of skin tone with a soft satin finish.",
            "source_slide_no": 1,
            "source_quote": "Helps even the appearance of skin tone with a soft satin finish.",
            "matched_image_path": str(img_path),
        },
        {
            "usp_id": 2,
            "usp_type": "texture_feel",
            "title": "Light Smooth Texture",
            "description": "Light texture blends smoothly for comfortable wear.",
            "source_slide_no": 1,
            "source_quote": "Light texture blends smoothly for comfortable wear.",
            "matched_image_path": str(img_path),
        },
    ]
    scenes = [
        {
            "scene_no": 1,
            "purpose": "hook",
            "image_path": str(img_path),
            "badge_label": "LUMIA · CUSHION",
            "headline": "Soft Satin Finish",
            "narration": "Discover LUMIA Soft Satin Cushion for a soft satin finish.",
            "subtitle": "Discover LUMIA Soft Satin Cushion for a soft satin finish.",
            "motion_effect": "zoom_in",
            "crop_focus": "center",
            "duration_sec": 6.0,
            "audio_segment_path": None,
            "usp_ids": [],
            "source_text_ids": ["s1_t1", "s1_t2"],
            "source_slide_nos": [1],
        },
        {
            "scene_no": 2,
            "purpose": "usp",
            "image_path": str(img_path),
            "badge_label": "POINT 01",
            "headline": "Even Skin Tone",
            "narration": "It helps even the appearance of skin tone cleanly.",
            "subtitle": "It helps even the appearance of skin tone cleanly.",
            "motion_effect": "pan_left",
            "crop_focus": "left",
            "duration_sec": 6.5,
            "audio_segment_path": None,
            "usp_ids": [1],
            "source_text_ids": ["s1_t2"],
            "source_slide_nos": [1],
        },
        {
            "scene_no": 3,
            "purpose": "usp",
            "image_path": str(img_path),
            "badge_label": "POINT 02",
            "headline": "Light Smooth Wear",
            "narration": "The light texture blends smoothly for comfortable wear.",
            "subtitle": "The light texture blends smoothly for comfortable wear.",
            "motion_effect": "zoom_out",
            "crop_focus": "right",
            "duration_sec": 6.5,
            "audio_segment_path": None,
            "usp_ids": [2],
            "source_text_ids": ["s1_t3"],
            "source_slide_nos": [1],
        },
        {
            "scene_no": 4,
            "purpose": "outro",
            "image_path": str(img_path),
            "badge_label": "LUMIA · 15g",
            "headline": "LUMIA Soft Satin Cushion",
            "narration": "LUMIA Soft Satin Cushion, for a soft satin finish.",
            "subtitle": "LUMIA Soft Satin Cushion, for a soft satin finish.",
            "motion_effect": "pan_right",
            "crop_focus": "center",
            "duration_sec": 6.0,
            "audio_segment_path": None,
            "usp_ids": [],
            "source_text_ids": ["s1_t1", "s1_t2"],
            "source_slide_nos": [1],
        },
    ]
    return {
        "raw_slides": slides,
        "product_info": {
            "brand": "LUMIA",
            "product_name": "Soft Satin Cushion",
            "category": "Cushion",
            "volume": "15g",
            "how_to_use": "Press puff lightly and pat evenly onto skin.",
        },
        "usps": usps,
        "creative_direction": {
            "concept": "premium_editorial",
            "background_tone": "deep_dark",
            "accent_color": "champagne_gold",
            "typography_style": "editorial_serif",
            "motion_pacing": "calm_elegant",
            "narration_tone": "calm_refined",
            "rationale": "Synthetic test identity.",
        },
        "scenes": scenes,
        "full_script": " ".join(s["narration"] for s in scenes),
    }


def run_adversarial_suite() -> list[dict[str, Any]]:
    """AI/AGENTS.md 6대 필수 예외 시나리오를 LangGraph 실제 분기로 검증한다 (API 비용 0원)."""
    results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="beautyflow_adv_") as tmp:
        tmp_dir = Path(tmp)
        base = _make_base_state(tmp_dir)
        out_root = tmp_dir / "out"

        # ------------------------------------------------------------------
        # Case 1: 외부 URL / 미지원 경로 차단 (DocumentParser → END)
        # ------------------------------------------------------------------
        g1 = build_video_graph({"DocumentParser": document_parser})
        s1 = run_video_pipeline("https://global.amoremall.com/product/123", output_dir=out_root, graph=g1, verbose=False)
        t1 = json.loads(Path(s1["pipeline_json_path"]).read_text(encoding="utf-8"))["trace"]
        steps1 = extract_steps_from_trace(t1)
        ok1 = s1["status"] == "failed" and evaluate_handoff(steps1, expected_steps=["DocumentParser"])
        results.append({
            "case_id": "adv_1_invalid_url",
            "category": "입력 보안/경로 차단",
            "passed": ok1,
            "handoff_ok": evaluate_handoff(steps1, expected_steps=["DocumentParser"]),
            "steps": steps1,
            "final_status": s1["status"],
            "detail": s1.get("error_message") or "",
        })

        # ------------------------------------------------------------------
        # Case 2: 이미지 없는 PPTX 중단 (DocumentParser → END)
        # ------------------------------------------------------------------
        no_img_pptx = tmp_dir / "text_only.pptx"
        prs = Presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "Text Only Product"
        slide.placeholders[1].text = "No images in this document."
        prs.save(str(no_img_pptx))

        s2 = run_video_pipeline(no_img_pptx, output_dir=out_root, graph=g1, verbose=False)
        t2 = json.loads(Path(s2["pipeline_json_path"]).read_text(encoding="utf-8"))["trace"]
        steps2 = extract_steps_from_trace(t2)
        ok2 = s2["status"] == "failed" and "이미지가 없습니다" in (s2.get("error_message") or "") and evaluate_handoff(steps2, expected_steps=["DocumentParser"])
        results.append({
            "case_id": "adv_2_no_images_pptx",
            "category": "이미지 부재 중단",
            "passed": ok2,
            "handoff_ok": evaluate_handoff(steps2, expected_steps=["DocumentParser"]),
            "steps": steps2,
            "final_status": s2["status"],
            "detail": s2.get("error_message") or "",
        })

        # ------------------------------------------------------------------
        # Case 3: USP 근거 부족/원문 부재 차단 (ProductAnalyzer → END)
        # ------------------------------------------------------------------
        def fake_empty_slides(state):
            return {"raw_slides": [{"slide_no": 1, "title": "", "texts": ["   "], "image_paths": [], "all_titles": [], "body_paragraphs": [], "elements": [], "text_blocks": [], "image_positions": []}], "status": "running", "error_message": None}

        g3 = build_video_graph({"DocumentParser": fake_empty_slides, "ProductAnalyzer": product_analyzer})
        s3 = run_video_pipeline("data/LUMIA.pptx", output_dir=out_root, graph=g3, verbose=False)
        t3 = json.loads(Path(s3["pipeline_json_path"]).read_text(encoding="utf-8"))["trace"]
        steps3 = extract_steps_from_trace(t3)
        ok3 = s3["status"] == "fallback_review_required" and evaluate_handoff(steps3, expected_steps=["DocumentParser", "ProductAnalyzer"])
        results.append({
            "case_id": "adv_3_insufficient_usp_evidence",
            "category": "USP 근거 부족 차단",
            "passed": ok3,
            "handoff_ok": evaluate_handoff(steps3, expected_steps=["DocumentParser", "ProductAnalyzer"]),
            "steps": steps3,
            "final_status": s3["status"],
            "detail": s3.get("error_message") or "",
        })

        # ------------------------------------------------------------------
        # Case 4: 원문 외 SPF 50+ & 24시간 과장 주입 → ClaimValidator → ScriptReviser → 복구
        # ------------------------------------------------------------------
        bad_scenes = [dict(sc) for sc in base["scenes"]]
        bad_scenes[1] = {
            **bad_scenes[1],
            "narration": "It delivers SPF 50+ protection for 24 hours.",
            "subtitle": "It delivers SPF 50+ protection for 24 hours.",
        }
        claim_calls = {"n": 0}

        def stub_doc(_):
            return {"raw_slides": base["raw_slides"], "status": "running", "error_message": None}

        def stub_prod(_):
            return {"product_info": base["product_info"], "usps": base["usps"], "status": "running", "error_message": None}

        def stub_script_bad(_):
            return {
                "creative_direction": base["creative_direction"],
                "scenes": bad_scenes,
                "full_script": " ".join(s["narration"] for s in bad_scenes),
                "status": "running",
                "error_message": None,
            }

        def claim_guard_wrapper(state):
            claim_calls["n"] += 1
            if claim_calls["n"] == 1:
                # 실제 claim_validator 1차 파이썬 가드가 SPF 50+ / 24 수치를 차단하고 LLM 호출 없이 script_error 반환
                return claim_validator(state)
            # 수정 후 2회차는 통과 판정
            return {
                "validation_result": {"is_valid": True, "error_type": "none", "unsupported_claims": [], "feedback": "OK", "issues": []},
                "status": "running",
                "error_message": None,
            }

        def stub_reviser_fix(state):
            fixed = [dict(sc) for sc in base["scenes"]]
            return {
                "scenes": fixed,
                "full_script": " ".join(s["narration"] for s in fixed),
                "revision_json_path": str(tmp_dir / "rev4.json"),
                "retry_count": state.get("retry_count", 0) + 1,
                "validation_result": {"is_valid": False, "error_type": "none", "unsupported_claims": [], "feedback": "recheck", "issues": []},
                "status": "running",
                "error_message": None,
            }

        def stub_tts_ok(state):
            return {"audio_path": str(tmp_dir / "ok.wav"), "tts_duration_sec": 25.0, "status": "running", "error_message": None}

        def stub_render_ok(state):
            return {"video_path": str(tmp_dir / "ok.mp4"), "status": "running", "error_message": None}

        def stub_qa_ok(state):
            return {
                "qa_result": {"is_passed": True, "error_type": "none", "video_duration_sec": 25.0, "resolution": "1080x1920", "details": "OK"},
                "qa_next_node": "END",
                "status": "completed",
                "error_message": None,
            }

        g4 = build_video_graph({
            "DocumentParser": stub_doc,
            "ProductAnalyzer": stub_prod,
            "ScriptGenerator": stub_script_bad,
            "ClaimValidator": claim_guard_wrapper,
            "ScriptReviser": stub_reviser_fix,
            "TTSGenerator": stub_tts_ok,
            "VideoRenderer": stub_render_ok,
            "VideoQA": stub_qa_ok,
        })
        s4 = run_video_pipeline("data/LUMIA.pptx", output_dir=out_root, graph=g4, verbose=False)
        t4 = json.loads(Path(s4["pipeline_json_path"]).read_text(encoding="utf-8"))["trace"]
        steps4 = extract_steps_from_trace(t4)
        exp4 = ["DocumentParser", "ProductAnalyzer", "ScriptGenerator", "ClaimValidator", "ScriptReviser", "ClaimValidator", "TTSGenerator", "VideoRenderer", "VideoQA"]
        ok4 = s4["status"] == "completed" and evaluate_handoff(steps4, expected_steps=exp4)
        results.append({
            "case_id": "adv_4_hallucinated_spf_and_number",
            "category": "미지원 SPF·수치 1차 차단 및 교정 루프",
            "passed": ok4,
            "handoff_ok": evaluate_handoff(steps4, expected_steps=exp4),
            "steps": steps4,
            "final_status": s4["status"],
            "detail": f"retry={s4.get('retry_count')} / 1차 가드 차단 후 ScriptReviser→ClaimValidator 복구",
        })

        # ------------------------------------------------------------------
        # Case 5: TTS 실측 33.5초 초과 → ScriptReviser 축약 → ClaimValidator → TTS(25.0s) 복구
        # ------------------------------------------------------------------
        tts_calls = {"n": 0}

        def stub_script_ok(_):
            return {
                "creative_direction": base["creative_direction"],
                "scenes": base["scenes"],
                "full_script": base["full_script"],
                "status": "running",
                "error_message": None,
            }

        def stub_claim_ok(_):
            return {
                "validation_result": {"is_valid": True, "error_type": "none", "unsupported_claims": [], "feedback": "OK", "issues": []},
                "status": "running",
                "error_message": None,
            }

        def stub_tts_over_then_ok(_):
            tts_calls["n"] += 1
            dur = 33.5 if tts_calls["n"] == 1 else 25.0
            return {"audio_path": str(tmp_dir / f"tts_{tts_calls['n']}.wav"), "tts_duration_sec": dur, "status": "running", "error_message": None}

        g5 = build_video_graph({
            "DocumentParser": stub_doc,
            "ProductAnalyzer": stub_prod,
            "ScriptGenerator": stub_script_ok,
            "ClaimValidator": stub_claim_ok,
            "ScriptReviser": stub_reviser_fix,
            "TTSGenerator": stub_tts_over_then_ok,
            "VideoRenderer": stub_render_ok,
            "VideoQA": stub_qa_ok,
        })
        s5 = run_video_pipeline("data/LUMIA.pptx", output_dir=out_root, graph=g5, verbose=False)
        t5 = json.loads(Path(s5["pipeline_json_path"]).read_text(encoding="utf-8"))["trace"]
        steps5 = extract_steps_from_trace(t5)
        exp5 = ["DocumentParser", "ProductAnalyzer", "ScriptGenerator", "ClaimValidator", "TTSGenerator", "ScriptReviser", "ClaimValidator", "TTSGenerator", "VideoRenderer", "VideoQA"]
        ok5 = s5["status"] == "completed" and evaluate_handoff(steps5, expected_steps=exp5)
        results.append({
            "case_id": "adv_5_tts_duration_over_30s",
            "category": "30초 초과 축약 루프 복구",
            "passed": ok5,
            "handoff_ok": evaluate_handoff(steps5, expected_steps=exp5),
            "steps": steps5,
            "final_status": s5["status"],
            "detail": f"33.5s → ScriptReviser → ClaimValidator → 25.0s 복구 (retry={s5.get('retry_count')})",
        })

        # ------------------------------------------------------------------
        # Case 6: VideoQA 렌더링/자막 오류 탐지 → VideoRenderer 재렌더링 → VideoQA 통과
        # ------------------------------------------------------------------
        qa_calls = {"n": 0}

        def stub_render_count(state):
            qa = state.get("qa_result") or {}
            rc = state.get("retry_count", 0) + (1 if qa.get("error_type") == "render_error" else 0)
            return {"video_path": str(tmp_dir / f"v_{rc}.mp4"), "retry_count": rc, "status": "running", "error_message": None}

        def stub_qa_fail_then_ok(state):
            qa_calls["n"] += 1
            if qa_calls["n"] == 1:
                return {
                    "qa_result": {"is_passed": False, "error_type": "render_error", "video_duration_sec": 25.0, "resolution": "1080x1920", "details": "subtitle_single_line mismatch"},
                    "qa_next_node": "VideoRenderer",
                    "status": "running",
                    "error_message": "VideoQA: subtitle_single_line mismatch",
                }
            return stub_qa_ok(state)

        g6 = build_video_graph({
            "DocumentParser": stub_doc,
            "ProductAnalyzer": stub_prod,
            "ScriptGenerator": stub_script_ok,
            "ClaimValidator": stub_claim_ok,
            "ScriptReviser": script_reviser,
            "TTSGenerator": stub_tts_ok,
            "VideoRenderer": stub_render_count,
            "VideoQA": stub_qa_fail_then_ok,
        })
        s6 = run_video_pipeline("data/LUMIA.pptx", output_dir=out_root, graph=g6, verbose=False)
        t6 = json.loads(Path(s6["pipeline_json_path"]).read_text(encoding="utf-8"))["trace"]
        steps6 = extract_steps_from_trace(t6)
        exp6 = ["DocumentParser", "ProductAnalyzer", "ScriptGenerator", "ClaimValidator", "TTSGenerator", "VideoRenderer", "VideoQA", "VideoRenderer", "VideoQA"]
        ok6 = s6["status"] == "completed" and evaluate_handoff(steps6, expected_steps=exp6)
        results.append({
            "case_id": "adv_6_video_qa_render_recovery",
            "category": "VideoQA 오류 탐지 및 재렌더링 복구",
            "passed": ok6,
            "handoff_ok": evaluate_handoff(steps6, expected_steps=exp6),
            "steps": steps6,
            "final_status": s6["status"],
            "detail": f"VideoQA→VideoRenderer→VideoQA 자동 복구 (retry={s6.get('retry_count')})",
        })

    return results
