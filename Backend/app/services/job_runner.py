"""단일 워커 기반 AI LangGraph 실행기, 5단계 진행 상태 계산 및 결과 JSON 조합 서비스."""

from __future__ import annotations

import json
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from AI.beautyflow.graph import run_video_pipeline
from Backend.app.config import NODE_TO_STAGE, STAGE_DEFINITIONS, STAGE_LABELS, BackendSettings
from Backend.app.database import utc_now
from Backend.app.models import Artifact, Job, JobEvent
from Backend.app.schemas import (
    JobLogsResponse,
    JobResultResponse,
    NodeLogItem,
    PublicSceneItem,
    PublicUSPItem,
    StageProgressItem,
    VideoInfoSummary,
)


def generate_job_id() -> str:
    """가독성과 고유성을 모두 만족하는 Job ID(BF-YYYYMMDD-XXXXXX)를 발급한다."""
    stamp = utc_now().strftime("%Y%m%d")
    return f"BF-{stamp}-{uuid4().hex[:6].upper()}"


def compute_stage_progress(job: Job) -> tuple[int, str | None, list[StageProgressItem]]:
    """현재 Job 상태와 current_node를 사용자용 5단계 진행 목록으로 변환한다."""
    current_stage = NODE_TO_STAGE.get(job.current_node or "", 0)
    if job.status == "completed":
        return (
            5,
            STAGE_LABELS[5],
            [StageProgressItem(stage=int(d["stage"]), label=str(d["label"]), status="completed") for d in STAGE_DEFINITIONS],
        )

    if job.status == "queued":
        return (
            0,
            "작업 대기 중",
            [StageProgressItem(stage=int(d["stage"]), label=str(d["label"]), status="pending") for d in STAGE_DEFINITIONS],
        )

    # running / failed / fallback_review_required
    active_stage = current_stage or 1
    terminal_state = "failed" if job.status == "failed" else "review_required" if job.status == "fallback_review_required" else "running"
    stages: list[StageProgressItem] = []
    for defn in STAGE_DEFINITIONS:
        s_num = int(defn["stage"])
        if s_num < active_stage:
            st = "completed"
        elif s_num == active_stage:
            st = terminal_state
        else:
            st = "pending"
        stages.append(StageProgressItem(stage=s_num, label=str(defn["label"]), status=st))  # type: ignore[arg-type]
    return active_stage, STAGE_LABELS.get(active_stage), stages


def aggregate_node_logs(job: Job, events: list[JobEvent]) -> JobLogsResponse:
    """job_events의 시작·종료 이벤트를 node_run_id 기준으로 묶어 노드별 실행 로그를 구성한다."""
    grouped: dict[str, NodeLogItem] = {}
    ordered: list[NodeLogItem] = []

    for ev in events:
        if ev.event_type in {"node_started", "node_completed", "node_failed"} and ev.node_name:
            key = ev.node_run_id or f"ev-{ev.id}"
            if key not in grouped:
                item = NodeLogItem(
                    node_run_id=ev.node_run_id,
                    node_name=ev.node_name,
                    status="running" if ev.event_type == "node_started" else ("failed" if ev.event_type == "node_failed" else "completed"),
                    started_at=ev.created_at,
                    finished_at=None if ev.event_type == "node_started" else ev.created_at,
                    duration_sec=ev.duration_sec,
                    retry_count=ev.retry_count,
                    message=ev.message,
                )
                grouped[key] = item
                ordered.append(item)
            else:
                item = grouped[key]
                item.status = "failed" if ev.event_type == "node_failed" else "completed"
                item.finished_at = ev.created_at
                item.duration_sec = ev.duration_sec
                item.retry_count = ev.retry_count
                item.message = ev.message
        elif ev.event_type in {"retry_scheduled", "job_failed", "review_required"}:
            ordered.append(NodeLogItem(
                node_run_id=ev.node_run_id,
                node_name=ev.node_name or "Pipeline",
                status=ev.event_type,
                started_at=ev.created_at,
                finished_at=ev.created_at,
                duration_sec=ev.duration_sec,
                retry_count=ev.retry_count,
                message=ev.message,
            ))
    return JobLogsResponse(job_id=job.id, status=job.status, logs=ordered)


def _safe_load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _sanitize_error_message(raw: str | None) -> str:
    """서버 내부 절대경로·스택 정보를 가려 사용자에게 안전한 오류 메시지만 반환한다."""
    if not raw:
        return "영상 생성 처리 중 오류가 발생했습니다."
    cleaned = str(raw).strip()
    # Windows/Unix 절대 경로 패턴 마스킹
    if ":\\" in cleaned or "/storage/" in cleaned:
        parts = cleaned.split(":")
        return parts[0] + ": 입력 문서 또는 산출물 처리 중 오류가 발생했습니다."
    return cleaned[:400]


def register_artifact(db: Session, job_id: str, artifact_type: str, path: str | Path) -> Artifact | None:
    """존재하는 파일의 메타데이터를 artifacts 테이블에 중복 없이 기록한다."""
    p = Path(path)
    if not p.is_file():
        return None
    existing = (
        db.query(Artifact)
        .filter(Artifact.job_id == job_id, Artifact.artifact_type == artifact_type, Artifact.file_path == str(p))
        .first()
    )
    if existing:
        return existing
    mime, _ = mimetypes.guess_type(str(p))
    artifact = Artifact(
        job_id=job_id,
        artifact_type=artifact_type,
        file_name=p.name,
        file_path=str(p),
        file_size=p.stat().st_size,
        mime_type=mime or "application/octet-stream",
        created_at=utc_now(),
    )
    db.add(artifact)
    return artifact


def build_job_result_payload(job: Job, artifacts: list[Artifact]) -> JobResultResponse:
    """pipeline.json 및 보조 JSON에서 내부 파일 경로를 제거한 API-06 응답을 생성한다."""
    by_type = {a.artifact_type: a for a in artifacts}
    pipeline_art = by_type.get("pipeline_json")
    pipeline_data = _safe_load_json(pipeline_art.file_path if pipeline_art else None)
    final_state = pipeline_data.get("final_state") or {}

    render_data = _safe_load_json(final_state.get("render_json_path"))
    val_data = _safe_load_json(final_state.get("validation_json_path"))
    qa_data = _safe_load_json(final_state.get("qa_json_path"))

    # 타임라인 실측 시작/종료 시각 매핑
    timeline_by_scene = {
        int(item["scene_no"]): item
        for item in (render_data.get("timeline") or [])
        if isinstance(item, dict) and "scene_no" in item
    }

    usps = [
        PublicUSPItem(
            usp_id=int(u.get("usp_id", idx)),
            usp_type=u.get("usp_type"),
            title=str(u.get("title") or ""),
            description=str(u.get("description") or ""),
            source_slide_no=int(u.get("source_slide_no", 1)),
            source_quote=str(u.get("source_quote") or ""),
        )
        for idx, u in enumerate(final_state.get("usps") or [], 1)
    ]

    scenes: list[PublicSceneItem] = []
    cursor = 0.0
    for sc in final_state.get("scenes") or []:
        s_no = int(sc.get("scene_no", len(scenes) + 1))
        dur = round(float(sc.get("duration_sec") or 0.0), 2)
        t_item = timeline_by_scene.get(s_no) or {}
        start_sec = round(float(t_item.get("start_sec", cursor)), 2)
        end_sec = round(float(t_item.get("end_sec", start_sec + dur)), 2)
        cursor = end_sec
        has_img = bool(sc.get("image_path") and Path(sc["image_path"]).is_file())
        scenes.append(PublicSceneItem(
            scene_no=s_no,
            purpose=str(sc.get("purpose") or "usp"),
            badge_label=str(sc.get("badge_label") or ""),
            headline=str(sc.get("headline") or ""),
            narration=str(sc.get("narration") or ""),
            subtitle=str(sc.get("subtitle") or ""),
            motion_effect=str(sc.get("motion_effect") or "zoom_in"),
            duration_sec=dur,
            start_sec=start_sec,
            end_sec=end_sec,
            usp_ids=[int(x) for x in (sc.get("usp_ids") or [])],
            source_slide_nos=[int(x) for x in (sc.get("source_slide_nos") or [])],
            image_url=f"/api/jobs/{job.id}/scenes/{s_no}/image" if has_img else None,
        ))

    qa_result = final_state.get("qa_result") or {}
    video_dur = float(qa_result.get("video_duration_sec") or job.video_duration_sec or 0.0)
    resolution = str(qa_result.get("resolution") or render_data.get("resolution") or "1080x1920")
    has_thumb = "image" in by_type

    # QA 체크 목록에서 내부 경로 제외 후 안전한 요약만 반환
    safe_qa_checks = []
    for chk in qa_data.get("checks") or []:
        if not isinstance(chk, dict):
            continue
        name = str(chk.get("name") or "")
        if name in {"video_file", "render_report"}:
            safe_qa_checks.append({"name": name, "passed": chk.get("passed"), "details": "확인 완료" if chk.get("passed") else "파일 확인 필요"})
        else:
            safe_qa_checks.append({"name": name, "passed": chk.get("passed"), "details": chk.get("details")})

    return JobResultResponse(
        job_id=job.id,
        file_name=job.file_name,
        created_at=job.created_at,
        finished_at=job.finished_at,
        product_info=final_state.get("product_info") or {},
        common_analysis=final_state.get("common_analysis") or {},
        usps=usps,
        creative_direction=render_data.get("creative_direction") or final_state.get("creative_direction") or {},
        scenes=scenes,
        full_script=str(final_state.get("full_script") or ""),
        validation_result=final_state.get("validation_result") or {},
        code_checks=val_data.get("code_checks") or {},
        qa_result=qa_result,
        qa_checks=safe_qa_checks,
        video_info=VideoInfoSummary(
            duration_sec=round(video_dur, 2),
            resolution=resolution,
            fps=int(render_data.get("fps") or 30),
            video_url=f"/api/jobs/{job.id}/video",
            download_url=f"/api/jobs/{job.id}/download",
            thumbnail_url=f"/api/jobs/{job.id}/thumbnail" if has_thumb else None,
        ),
        elapsed_sec=pipeline_data.get("elapsed_sec"),
        estimated_cost_usd=pipeline_data.get("known_estimated_cost_usd"),
    )


class JobRunner:
    """단일 백그라운드 워커로 LangGraph 파이프라인을 실행하고 DB를 실시간 갱신한다."""

    def __init__(
        self,
        settings: BackendSettings,
        session_factory,
        pipeline_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.pipeline_fn = pipeline_fn or run_video_pipeline
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="beautyflow-worker")

    def submit(self, job_id: str, input_pptx_path: Path, output_dir: Path, max_retries: int) -> None:
        """작업을 단일 실행 큐에 등록한다."""
        self._executor.submit(self._execute, job_id, input_pptx_path, output_dir, max_retries)

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _execute(self, job_id: str, input_pptx_path: Path, output_dir: Path, max_retries: int) -> None:
        now = utc_now()
        with self.session_factory() as db:
            job = db.get(Job, job_id)
            if not job:
                return
            job.status = "running"
            job.current_node = "DocumentParser"
            job.started_at = now
            job.updated_at = now
            db.add(JobEvent(
                job_id=job_id,
                event_type="job_started",
                retry_count=0,
                message="AI 영상 생성 워크플로우를 시작합니다.",
                created_at=now,
            ))
            db.commit()

        def on_event(payload: dict[str, Any]) -> None:
            ev_now = utc_now()
            ev_type = str(payload.get("event_type") or "")
            node_name = payload.get("node_name")
            retry_cnt = int(payload.get("retry_count") or 0)
            with self.session_factory() as db:
                job = db.get(Job, job_id)
                if not job:
                    return
                if node_name:
                    job.current_node = str(node_name)
                job.retry_count = retry_cnt
                job.updated_at = ev_now

                # ProductAnalyzer 완료 시 제품명 즉시 반영
                p_info = payload.get("product_info")
                if isinstance(p_info, dict):
                    brand = str(p_info.get("brand") or "").strip()
                    pname = str(p_info.get("product_name") or "").strip()
                    full_name = f"{brand} {pname}".strip() if brand and brand.lower() not in pname.lower() else (pname or brand)
                    if full_name:
                        job.product_name = full_name

                # DocumentParser 완료 시 첫 번째 추출 이미지를 썸네일 artifact로 조기 등록
                upd = payload.get("update")
                if node_name == "DocumentParser" and ev_type == "node_completed" and isinstance(upd, dict):
                    for slide in upd.get("raw_slides") or []:
                        imgs = slide.get("image_paths") or []
                        if imgs:
                            register_artifact(db, job_id, "image", imgs[0])
                            break

                db.add(JobEvent(
                    job_id=job_id,
                    node_run_id=payload.get("node_run_id"),
                    node_name=node_name,
                    event_type=ev_type,
                    retry_count=retry_cnt,
                    duration_sec=payload.get("duration_sec"),
                    message=_sanitize_error_message(payload.get("message")) if ev_type == "node_failed" else payload.get("message"),
                    created_at=ev_now,
                ))
                db.commit()

        try:
            final_state = self.pipeline_fn(
                str(input_pptx_path),
                output_dir=str(output_dir),
                max_retries=max_retries,
                on_event=on_event,
                run_name=f"BeautyFlow-Web:{job_id}",
                tags=["beautyflow-web", job_id],
                metadata={"job_id": job_id},
                verbose=False,
            )
            self._finalize_job(job_id, final_state)
        except Exception as exc:
            err_now = utc_now()
            with self.session_factory() as db:
                job = db.get(Job, job_id)
                if job:
                    job.status = "failed"
                    job.error_code = "AI_EXECUTION_ERROR"
                    job.error_message = f"AI 실행 오류: {type(exc).__name__}"
                    job.finished_at = err_now
                    job.updated_at = err_now
                    db.add(JobEvent(
                        job_id=job_id,
                        node_name=job.current_node,
                        event_type="job_failed",
                        retry_count=job.retry_count,
                        message=job.error_message,
                        created_at=err_now,
                    ))
                    db.commit()

    def _finalize_job(self, job_id: str, final_state: dict[str, Any]) -> None:
        done_now = utc_now()
        with self.session_factory() as db:
            job = db.get(Job, job_id)
            if not job:
                return

            # 제품명 최종 보강
            p_info = final_state.get("product_info") or {}
            if isinstance(p_info, dict) and not job.product_name:
                brand = str(p_info.get("brand") or "").strip()
                pname = str(p_info.get("product_name") or "").strip()
                full_name = f"{brand} {pname}".strip() if brand and brand.lower() not in pname.lower() else (pname or brand)
                if full_name:
                    job.product_name = full_name

            # 산출물 artifacts 등록
            artifact_map = [
                ("pipeline_json", final_state.get("pipeline_json_path")),
                ("final_video", final_state.get("video_path")),
                ("analysis_json", final_state.get("analysis_json_path")),
                ("script_json", final_state.get("script_json_path")),
                ("validation_json", final_state.get("validation_json_path")),
                ("qa_json", final_state.get("qa_json_path")),
                ("audio", final_state.get("audio_path")),
            ]
            for art_type, art_path in artifact_map:
                if art_path:
                    register_artifact(db, job_id, art_type, art_path)

            # 썸네일 미등록 시 첫 슬라이드/장면 이미지 등록
            for sc in final_state.get("scenes") or []:
                if sc.get("image_path"):
                    register_artifact(db, job_id, "image", sc["image_path"])
                    break

            qa_res = final_state.get("qa_result") or {}
            qa_passed = bool(qa_res.get("is_passed"))
            video_path = final_state.get("video_path") or ""
            video_exists = bool(video_path and Path(video_path).is_file())
            raw_status = str(final_state.get("status") or "failed")

            job.retry_count = int(final_state.get("retry_count") or job.retry_count or 0)
            job.qa_passed = qa_passed
            if qa_res.get("video_duration_sec"):
                job.video_duration_sec = round(float(qa_res["video_duration_sec"]), 2)

            # 최종 MP4 저장 및 QA 통과 시에만 completed 확정
            if raw_status == "completed" and qa_passed and video_exists:
                job.status = "completed"
                job.current_node = "VideoQA"
                job.error_code = None
                job.error_message = None
                ev_type = "job_completed"
                ev_msg = "영상 생성 및 품질 검사가 완료되었습니다."
            elif raw_status == "fallback_review_required":
                job.status = "fallback_review_required"
                job.error_code = "REVIEW_REQUIRED"
                job.error_message = _sanitize_error_message(final_state.get("error_message") or "자동 복구 한도를 초과하여 사용자 검토가 필요합니다.")
                ev_type = "review_required"
                ev_msg = job.error_message
            else:
                job.status = "failed"
                job.error_code = "PIPELINE_FAILED"
                job.error_message = _sanitize_error_message(final_state.get("error_message"))
                ev_type = "job_failed"
                ev_msg = job.error_message

            job.finished_at = done_now
            job.updated_at = done_now
            db.add(JobEvent(
                job_id=job_id,
                node_name=job.current_node,
                event_type=ev_type,
                retry_count=job.retry_count,
                message=ev_msg,
                created_at=done_now,
            ))
            db.commit()
