"""Backend FastAPI (API-01 ~ API-08) · SQLite ERD · AI 이벤트 훅 통합 테스트."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from pptx import Presentation

from AI.beautyflow.graph import build_video_graph, run_video_pipeline
from Backend.app.config import load_settings
from Backend.app.database import create_db_engine, create_session_factory, init_db, recover_interrupted_jobs, utc_now
from Backend.app.main import create_app
from Backend.app.models import Job


def _make_valid_pptx_bytes(title: str = "LUMIA Soft Satin Cushion") -> bytes:
    buf = BytesIO()
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = "Soft satin finish with natural-looking coverage."
    prs.save(buf)
    return buf.getvalue()


def _make_mock_pipeline(mode: str = "completed"):
    """실제 OpenAI/FFmpeg 호출 없이 pipeline.json · MP4 · 이미지 산출물을 생성하는 Mock 파이프라인."""
    def _pipeline(file_path, output_dir="output", max_retries=3, *, on_event=None, **_kwargs):
        out = Path(output_dir) / "runs" / "mock"
        out.mkdir(parents=True, exist_ok=True)
        img_p = out / "scene_1.png"
        Image.new("RGB", (320, 320), (220, 200, 235)).save(img_p)

        if on_event:
            on_event({"event_type": "node_started", "node_name": "DocumentParser", "node_run_id": "r1", "retry_count": 0, "message": "DocumentParser 시작"})
            on_event({
                "event_type": "node_completed",
                "node_name": "DocumentParser",
                "node_run_id": "r1",
                "retry_count": 0,
                "duration_sec": 0.12,
                "message": "DocumentParser 완료",
                "update": {"raw_slides": [{"slide_no": 1, "image_paths": [str(img_p)]}]},
            })
            on_event({"event_type": "node_started", "node_name": "ProductAnalyzer", "node_run_id": "r2", "retry_count": 0, "message": "ProductAnalyzer 시작"})
            on_event({
                "event_type": "node_completed",
                "node_name": "ProductAnalyzer",
                "node_run_id": "r2",
                "retry_count": 0,
                "duration_sec": 0.25,
                "message": "ProductAnalyzer 완료",
                "product_info": {"brand": "LUMIA", "product_name": "Soft Satin Cushion", "category": "Cushion"},
            })

        if mode == "failed":
            if on_event:
                on_event({"event_type": "node_failed", "node_name": "DocumentParser", "node_run_id": "r1", "retry_count": 0, "duration_sec": 0.1, "message": "DocumentParser: 추출할 이미지가 없습니다."})
            return {"status": "failed", "error_message": "DocumentParser: 추출할 이미지가 없습니다.", "retry_count": 0}

        if mode == "review_required":
            if on_event:
                on_event({"event_type": "retry_scheduled", "node_name": "ClaimValidator", "node_run_id": "r3", "retry_count": 3, "message": "재시도 한도 도달"})
            return {"status": "fallback_review_required", "error_message": "검증 재시도 상한에 도달했습니다.", "retry_count": 3}

        video_p = out / "LUMIA_shortform.mp4"
        video_bytes = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 100
        video_p.write_bytes(video_bytes)

        render_p = out / "render.json"
        render_p.write_text(json.dumps({
            "resolution": "1080x1920",
            "fps": 30,
            "creative_direction": {"concept": "premium_editorial", "background_tone": "warm_neutral", "accent_color": "champagne_gold"},
            "timeline": [{"scene_no": 1, "start_sec": 0.0, "end_sec": 24.5}],
        }), encoding="utf-8")

        val_p = out / "validation.json"
        val_p.write_text(json.dumps({"code_checks": {"cosmetic_claim_guard": "passed", "badge_labels": "passed"}}), encoding="utf-8")

        qa_p = out / "qa.json"
        qa_p.write_text(json.dumps({
            "checks": [
                {"name": "video_file", "passed": True, "details": str(video_p)},
                {"name": "subtitle_single_line", "passed": True, "details": "전부 1줄 정상"},
            ]
        }), encoding="utf-8")

        final_state = {
            "status": "completed",
            "retry_count": 0,
            "product_info": {"brand": "LUMIA", "product_name": "Soft Satin Cushion", "category": "Cushion", "volume": "15g"},
            "common_analysis": {"target_and_usage": {"summary": "Daily natural satin coverage", "source_text_ids": ["s1_t1"], "quotes": ["Daily use"]}},
            "usps": [
                {
                    "usp_id": 1,
                    "usp_type": "result_finish",
                    "title": "Soft Satin Finish",
                    "description": "Natural-looking satin glow.",
                    "source_slide_no": 2,
                    "source_quote": "Soft satin finish with natural-looking coverage.",
                    "matched_image_path": str(img_p),
                }
            ],
            "creative_direction": {"concept": "premium_editorial", "background_tone": "warm_neutral"},
            "scenes": [
                {
                    "scene_no": 1,
                    "purpose": "hook",
                    "image_path": str(img_p),
                    "badge_label": "LUMIA · CUSHION",
                    "headline": "Soft Satin Finish",
                    "narration": "Discover LUMIA Soft Satin Cushion.",
                    "subtitle": "Discover LUMIA Soft Satin Cushion.",
                    "motion_effect": "zoom_in",
                    "duration_sec": 24.5,
                    "audio_segment_path": str(out / "scene_1.wav"),
                    "usp_ids": [1],
                    "source_slide_nos": [1],
                }
            ],
            "full_script": "Discover LUMIA Soft Satin Cushion.",
            "validation_result": {"is_valid": True, "error_type": "none", "unsupported_claims": [], "feedback": "OK", "issues": []},
            "qa_result": {"is_passed": True, "error_type": "none", "video_duration_sec": 24.5, "resolution": "1080x1920", "details": "통과"},
            "video_path": str(video_p),
            "render_json_path": str(render_p),
            "validation_json_path": str(val_p),
            "qa_json_path": str(qa_p),
        }
        pipeline_p = out / "pipeline.json"
        final_state["pipeline_json_path"] = str(pipeline_p)
        pipeline_p.write_text(json.dumps({
            "status": "completed",
            "elapsed_sec": 12.3,
            "known_estimated_cost_usd": 0.019,
            "trace": [],
            "final_state": final_state,
        }), encoding="utf-8")
        return final_state

    return _pipeline


class BackendAPITests(unittest.TestCase):
    def _wait_terminal(self, client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = client.get(f"/api/jobs/{job_id}").json()
            if data["status"] in {"completed", "failed", "fallback_review_required"}:
                return data
            time.sleep(0.05)
        self.fail(f"Job {job_id} did not finish within {timeout}s")

    def test_full_job_lifecycle_api_01_to_08_and_range_streaming(self):
        with tempfile.TemporaryDirectory(prefix="bf_api_") as tmp:
            settings = load_settings(storage_dir=tmp, max_upload_mb=5)
            app = create_app(settings=settings, pipeline_fn=_make_mock_pipeline("completed"))
            with TestClient(app) as client:
                # API-02: 업로드 및 202 반환
                resp = client.post(
                    "/api/jobs",
                    files={"file": ("LUMIA.pptx", _make_valid_pptx_bytes(), "application/octet-stream")},
                )
                self.assertEqual(resp.status_code, 202)
                created = resp.json()
                job_id = created["job_id"]
                self.assertTrue(job_id.startswith("BF-"))

                # API-04: 완료 상태 및 5단계 진행 확인
                final = self._wait_terminal(client, job_id)
                self.assertEqual(final["status"], "completed")
                self.assertEqual(final["current_stage"], 5)
                self.assertEqual(len(final["stages"]), 5)
                self.assertTrue(all(s["status"] == "completed" for s in final["stages"]))
                self.assertEqual(final["product_name"], "LUMIA Soft Satin Cushion")

                # API-05: 노드 실행 로그 확인
                logs_resp = client.get(f"/api/jobs/{job_id}/logs")
                self.assertEqual(logs_resp.status_code, 200)
                node_names = [item["node_name"] for item in logs_resp.json()["logs"]]
                self.assertIn("DocumentParser", node_names)
                self.assertIn("ProductAnalyzer", node_names)

                # API-06: 결과 조회 (서버 내부 파일 경로 미노출 검증)
                res_resp = client.get(f"/api/jobs/{job_id}/result")
                self.assertEqual(res_resp.status_code, 200)
                res_text = res_resp.text
                self.assertNotIn("image_path", res_text)
                self.assertNotIn("audio_segment_path", res_text)
                self.assertNotIn(str(Path(tmp)), res_text)
                res = res_resp.json()
                self.assertEqual(res["video_info"]["resolution"], "1080x1920")
                self.assertEqual(res["scenes"][0]["image_url"], f"/api/jobs/{job_id}/scenes/1/image")

                # 보조 썸네일 & 장면 이미지 응답 확인
                self.assertEqual(client.get(f"/api/jobs/{job_id}/thumbnail").status_code, 200)
                self.assertEqual(client.get(f"/api/jobs/{job_id}/scenes/1/image").status_code, 200)

                # API-07: 영상 스트리밍 (전체 200 + HTTP Range 206)
                v_full = client.get(f"/api/jobs/{job_id}/video")
                self.assertEqual(v_full.status_code, 200)
                self.assertEqual(v_full.headers["accept-ranges"], "bytes")

                v_part = client.get(f"/api/jobs/{job_id}/video", headers={"Range": "bytes=0-9"})
                self.assertEqual(v_part.status_code, 206)
                self.assertEqual(v_part.content, b"0123456789")
                self.assertIn("bytes 0-9/", v_part.headers["content-range"])

                # API-08: MP4 다운로드 헤더 확인
                dl = client.get(f"/api/jobs/{job_id}/download")
                self.assertEqual(dl.status_code, 200)
                self.assertIn("attachment;", dl.headers["content-disposition"])
                self.assertIn("LUMIA_shortform.mp4", dl.headers["content-disposition"])

                # API-03: 검색·필터·페이지네이션
                lst = client.get("/api/jobs", params={"search": "LUMIA", "status": "completed", "page": 1, "limit": 5})
                self.assertEqual(lst.status_code, 200)
                self.assertEqual(lst.json()["total"], 1)
                self.assertEqual(lst.json()["items"][0]["job_id"], job_id)

                # API-01: 대시보드 통계
                summary = client.get("/api/dashboard/summary").json()
                self.assertEqual(summary["total_count"], 1)
                self.assertEqual(summary["completed_count"], 1)
                self.assertEqual(len(summary["recent_activities"]), 1)

    def test_error_codes_415_400_413_404_409_and_review_required(self):
        with tempfile.TemporaryDirectory(prefix="bf_err_") as tmp:
            settings = load_settings(storage_dir=tmp, max_upload_mb=1)
            app = create_app(settings=settings, pipeline_fn=_make_mock_pipeline("review_required"))
            with TestClient(app) as client:
                # 415 Unsupported Media Type
                r415 = client.post("/api/jobs", files={"file": ("doc.pdf", b"%PDF-1.4", "application/pdf")})
                self.assertEqual(r415.status_code, 415)
                self.assertEqual(r415.json()["error_code"], "UNSUPPORTED_FILE_TYPE")

                # 400 Bad Request (손상된 PPTX)
                r400 = client.post("/api/jobs", files={"file": ("broken.pptx", b"not-a-zip", "application/octet-stream")})
                self.assertEqual(r400.status_code, 400)
                self.assertEqual(r400.json()["error_code"], "INVALID_PPTX_FILE")

                # 413 Content Too Large (>1MB)
                r413 = client.post("/api/jobs", files={"file": ("huge.pptx", b"x" * (1024 * 1024 + 10), "application/octet-stream")})
                self.assertEqual(r413.status_code, 413)
                self.assertEqual(r413.json()["error_code"], "FILE_TOO_LARGE")

                # 404 Not Found
                r404 = client.get("/api/jobs/BF-NONEXISTENT")
                self.assertEqual(r404.status_code, 404)
                self.assertEqual(r404.json()["error_code"], "JOB_NOT_FOUND")

                # review_required 완료 시 409 Conflict on /result & /download
                created = client.post("/api/jobs", files={"file": ("SOLAIA.pptx", _make_valid_pptx_bytes("SOLAIA"), "application/octet-stream")}).json()
                final = self._wait_terminal(client, created["job_id"])
                self.assertEqual(final["status"], "fallback_review_required")
                r409 = client.get(f"/api/jobs/{created['job_id']}/result")
                self.assertEqual(r409.status_code, 409)
                self.assertEqual(r409.json()["error_code"], "JOB_NOT_COMPLETED")

    def test_server_restart_recovers_orphaned_running_jobs(self):
        with tempfile.TemporaryDirectory(prefix="bf_rec_") as tmp:
            settings = load_settings(storage_dir=tmp)
            engine = create_db_engine(settings.database_url)
            sf = create_session_factory(engine)
            init_db(engine)
            with sf() as db:
                db.add(Job(id="BF-ORPHAN-1", file_name="DERMERA.pptx", status="running", current_node="VideoRenderer", created_at=utc_now(), updated_at=utc_now()))
                db.commit()
            recovered = recover_interrupted_jobs(sf)
            self.assertEqual(recovered, 1)
            with sf() as db:
                j = db.get(Job, "BF-ORPHAN-1")
                self.assertEqual(j.status, "failed")
                self.assertEqual(j.error_code, "SERVER_RESTARTED")
            engine.dispose()

    def test_ai_graph_on_event_hook_emits_started_and_completed(self):
        events = []
        with tempfile.TemporaryDirectory(prefix="bf_hook_") as tmp:
            g = build_video_graph(
                node_overrides={"DocumentParser": lambda _s: {"status": "failed", "error_message": "DocumentParser: test fail"}},
                on_event=events.append,
            )
            run_video_pipeline("data/LUMIA.pptx", output_dir=tmp, graph=g, verbose=False)
        types = [e["event_type"] for e in events]
        self.assertEqual(types, ["node_started", "node_failed"])
        self.assertEqual(events[0]["node_name"], "DocumentParser")
        self.assertEqual(events[0]["node_run_id"], events[1]["node_run_id"])


if __name__ == "__main__":
    unittest.main()
