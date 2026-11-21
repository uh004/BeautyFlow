"""분리된 AI/beautyflow Python 패키지의 독립 동작 및 MVP_v2 계약 일치 검증 테스트."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from AI.beautyflow import beautyflow_graph, build_video_graph, run_video_pipeline
from AI.beautyflow.nodes.claim_validator import (
    find_unsupported_cosmetic_claims,
    prepare_claim_context,
    route_after_claim_validation,
)
from AI.beautyflow.nodes.document_parser import document_parser
from AI.beautyflow.nodes.script_generator import (
    derive_badge_label,
    resolve_creative_direction,
)
from AI.beautyflow.nodes.tts_generator import tts_transcript_matches
from AI.beautyflow.nodes.video_qa import qa_pick_sample_local_frame, route_after_video_qa
from AI.beautyflow.nodes.video_renderer import (
    HERO_H,
    HERO_W,
    HERO_Y,
    LAYOUT_VERSION,
    resolve_visual_identity,
    split_subtitle_chunks,
)


class BeautyFlowModuleTests(unittest.TestCase):
    def test_graph_contains_all_eight_nodes(self):
        expected = {
            "DocumentParser",
            "ProductAnalyzer",
            "ScriptGenerator",
            "ClaimValidator",
            "ScriptReviser",
            "TTSGenerator",
            "VideoRenderer",
            "VideoQA",
        }
        self.assertTrue(expected.issubset(set(beautyflow_graph.nodes.keys())))

    def test_document_parser_blocks_url_and_parses_local_pptx(self):
        from pptx import Presentation
        from pptx.util import Inches

        bad = document_parser({"file_path": "https://global.amoremall.com/x", "output_dir": "output"})
        self.assertEqual(bad["status"], "failed")

        # CI 환경(data/ 미포함)에서도 독립 실행되도록 임시 합성 PPTX를 생성해 검증
        with tempfile.TemporaryDirectory(prefix="bf_mod_doc_") as tmp:
            tmp_dir = Path(tmp)
            sample_img = tmp_dir / "sample.png"
            Image.new("RGB", (320, 320), (210, 195, 185)).save(sample_img)
            sample_pptx = tmp_dir / "synthetic_product.pptx"
            prs = Presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = "LUMIA Soft Satin Cushion"
            slide.placeholders[1].text = "Soft satin finish with light coverage."
            slide.shapes.add_picture(str(sample_img), Inches(1), Inches(2), width=Inches(2))
            prs.save(str(sample_pptx))

            ok = document_parser({"file_path": str(sample_pptx), "output_dir": str(tmp_dir / "out")})
            self.assertEqual(ok["status"], "running")
            self.assertEqual(len(ok["raw_slides"]), 1)
            self.assertEqual(len(ok["raw_slides"][0]["image_paths"]), 1)
            self.assertTrue(Path(ok["parsed_json_path"]).is_file())

    def test_creative_direction_respects_brand_guide_override(self):
        resolved = resolve_creative_direction(
            {"concept": "premium_editorial", "background_tone": "deep_dark", "accent_color": "champagne_gold"},
            brand_guide={"background_tone": "soft_light", "accent_color": "ice_blue"},
        )
        self.assertEqual(resolved["background_tone"], "soft_light")
        self.assertEqual(resolved["accent_color"], "ice_blue")
        self.assertEqual(derive_badge_label("usp", {"brand": "LUMIA"}, usp_rank=1), "POINT 01")

    def test_cosmetic_claim_guard_blocks_spf_but_allows_negation(self):
        evidence = "Light serum texture blends smoothly with a natural look."
        found = find_unsupported_cosmetic_claims("Provides SPF 50+ and PA++++ UV protection.", evidence)
        self.assertIn("SPF 50+", found)
        self.assertIn("PA++++", found)
        self.assertIn("UV protection", found)
        self.assertEqual(find_unsupported_cosmetic_claims("No SPF 50+ or PA++++ value is stated in the document.", evidence), [])

    def test_claim_validator_routing_contract(self):
        self.assertEqual(route_after_claim_validation({"status": "running", "validation_result": {"is_valid": True}}), "TTSGenerator")
        self.assertEqual(
            route_after_claim_validation({"status": "running", "retry_count": 0, "max_retries": 3, "validation_result": {"is_valid": False, "error_type": "script_error", "issues": [{"status": "unsupported"}]}}),
            "ScriptReviser",
        )
        self.assertEqual(
            route_after_claim_validation({"status": "running", "retry_count": 0, "max_retries": 3, "validation_result": {"is_valid": False, "error_type": "usp_error", "issues": [{"status": "unsupported"}]}}),
            "ProductAnalyzer",
        )

    def test_tts_article_only_guard(self):
        exact, norm = tts_transcript_matches("Soft satin finish.", "Soft satin finish.", allow_article_only=False)
        self.assertTrue(exact and not norm)
        ok_art, used_art = tts_transcript_matches("without a sticky feel", "without sticky feel", allow_article_only=True)
        self.assertTrue(ok_art and used_art)
        bad, _ = tts_transcript_matches("without any sticky feel", "without sticky feel", allow_article_only=True)
        self.assertFalse(bad)

    def test_video_renderer_minimalist_layout_and_single_line_subtitles(self):
        self.assertEqual(LAYOUT_VERSION, "v2_identity_9x16")
        self.assertEqual((HERO_W, HERO_H, HERO_Y), (980, 940, 390))
        chunks = split_subtitle_chunks("Discover LUMIA Soft Satin Cushion; lightweight feel, soft satin finish.")
        self.assertGreaterEqual(len(chunks), 2)
        for text, _ in chunks:
            self.assertNotIn(r"\N", text)
            self.assertNotIn(";", text)
            self.assertFalse(text.endswith((",", ";", ":", "—")))

    def test_resolve_visual_identity_and_qa_frame_picker(self):
        ident = resolve_visual_identity({"scenes": [], "creative_direction": {"background_tone": "deep_dark"}, "brand_guide": {"background_tone": "warm_neutral"}})
        self.assertEqual(ident["background_tone"], "warm_neutral")
        local_frame = qa_pick_sample_local_frame({
            "start_frame": 0,
            "frame_count": 150,
            "transition_frames": 9,
            "caption_chunks": [{"start_sec": 0.0, "end_sec": 2.5}, {"start_sec": 2.5, "end_sec": 5.0}],
        })
        self.assertTrue(13 <= local_frame <= 136)
        self.assertEqual(route_after_video_qa({"status": "running", "qa_next_node": "VideoRenderer"}), "VideoRenderer")

    def test_prepare_claim_context_flags_bad_creative_direction(self):
        with tempfile.TemporaryDirectory(prefix="bf_mod_claim_") as tmp:
            img = Path(tmp) / "s1.png"
            Image.new("RGB", (200, 200), (100, 100, 100)).save(img)
            state = {
                "status": "running",
                "raw_slides": [{"slide_no": 1, "texts": ["LUMIA Cushion 15g", "Soft satin finish."], "image_paths": [str(img)]}],
                "product_info": {"brand": "LUMIA", "product_name": "Cushion", "category": "Cushion", "volume": "15g", "how_to_use": None},
                "usps": [{"usp_id": 1, "usp_type": "result_finish", "title": "Soft Satin Finish", "description": "Soft satin finish.", "source_slide_no": 1, "source_quote": "Soft satin finish.", "matched_image_path": str(img)}],
                "creative_direction": {"concept": "invalid_concept", "background_tone": "deep_dark", "accent_color": "champagne_gold", "typography_style": "editorial_serif", "motion_pacing": "calm_elegant", "narration_tone": "calm_refined"},
                "scenes": [{"scene_no": 1, "purpose": "hook", "image_path": str(img), "badge_label": "LUMIA", "headline": "Soft Satin", "narration": "Soft satin finish.", "subtitle": "Soft satin finish.", "source_text_ids": ["s1_t2"], "usp_ids": [1]}],
                "full_script": "Soft satin finish.",
            }
            ctx = prepare_claim_context(state)
            self.assertEqual(ctx["code_checks"]["creative_direction"], "failed")


if __name__ == "__main__":
    unittest.main()
