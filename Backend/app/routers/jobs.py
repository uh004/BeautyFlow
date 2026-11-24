"""API-02 ~ API-08 영상 생성 작업 등록·조회·로그·결과·영상 스트리밍(Range)·다운로드 라우터."""

from __future__ import annotations

import hashlib
import math
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import quote

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import asc, desc, or_

from Backend.app.database import utc_now
from Backend.app.models import Artifact, Job, JobEvent
from Backend.app.schemas import (
    CreateJobResponse,
    JobListItem,
    JobListResponse,
    JobLogsResponse,
    JobResultResponse,
    JobStatusResponse,
)
from Backend.app.services.job_runner import (
    _safe_load_json,
    aggregate_node_logs,
    build_job_result_payload,
    compute_stage_progress,
    generate_job_id,
)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class APIError(Exception):
    """명세서 공통 오류 형식(error_code, message, job_id)으로 응답하기 위한 예외."""

    def __init__(self, status_code: int, error_code: str, message: str, job_id: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.job_id = job_id


def _sanitize_filename(name: str) -> str:
    base = Path(name or "upload.pptx").name
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip()
    return cleaned or "upload.pptx"


def _validate_pptx_bytes(filename: str, content: bytes, max_bytes: int) -> None:
    """확장자(415) · 용량(413) · 실제 PPTX ZIP 구조(400)를 검증한다."""
    if not filename.lower().endswith(".pptx"):
        raise APIError(415, "UNSUPPORTED_FILE_TYPE", "지원하지 않는 파일 형식입니다. PPTX 파일만 업로드할 수 있습니다.")
    if not content:
        raise APIError(400, "EMPTY_FILE", "비어 있는 파일입니다. 유효한 PPTX 파일을 업로드하세요.")
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise APIError(413, "FILE_TOO_LARGE", f"파일 크기가 허용 한도({limit_mb}MB)를 초과했습니다.")
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            names = set(zf.namelist())
            if "ppt/presentation.xml" not in names:
                raise APIError(400, "INVALID_PPTX_FILE", "유효한 PPTX 문서 구조가 아닙니다.")
    except APIError:
        raise
    except zipfile.BadZipFile:
        raise APIError(400, "INVALID_PPTX_FILE", "손상되었거나 유효하지 않은 PPTX 파일입니다.")


def _get_job_or_404(db, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise APIError(404, "JOB_NOT_FOUND", "존재하지 않는 작업 ID입니다.", job_id=job_id)
    return job


def _get_completed_video_path(db, job_id: str) -> tuple[Job, Path]:
    job = _get_job_or_404(db, job_id)
    if job.status != "completed":
        raise APIError(409, "JOB_NOT_COMPLETED", "작업이 아직 완료되지 않았습니다.", job_id=job_id)
    art = (
        db.query(Artifact)
        .filter(Artifact.job_id == job_id, Artifact.artifact_type == "final_video")
        .order_by(Artifact.id.desc())
        .first()
    )
    if not art or not Path(art.file_path).is_file():
        raise APIError(404, "VIDEO_NOT_FOUND", "생성된 영상 파일을 찾을 수 없습니다.", job_id=job_id)
    return job, Path(art.file_path)


# ---------------------------------------------------------------------------
# API-02: 영상 생성 작업 등록 (202 Accepted)
# ---------------------------------------------------------------------------
@router.post("", response_model=CreateJobResponse, status_code=202)
async def create_job(request: Request, file: UploadFile = File(...)) -> CreateJobResponse:
    """API-02: PPTX 파일을 검증·저장하고 Job ID를 발급해 비동기 AI 실행을 등록한다."""
    settings = request.app.state.settings
    safe_name = _sanitize_filename(file.filename or "")

    # 1) 확장자 1차 검증 후 최대 크기+1바이트까지만 안전하게 읽기
    if not safe_name.lower().endswith(".pptx"):
        raise APIError(415, "UNSUPPORTED_FILE_TYPE", "지원하지 않는 파일 형식입니다. PPTX 파일만 업로드할 수 있습니다.")
    content = await file.read(settings.max_upload_bytes + 1)
    _validate_pptx_bytes(safe_name, content, settings.max_upload_bytes)

    # 2) 동일 파일의 중복 진행 중 요청 방지 (queued/running 상태일 때만 차단)
    content_hash = hashlib.sha256(content).hexdigest()
    with request.app.state.session_factory() as db:
        active_jobs = db.query(Job).filter(Job.status.in_(["queued", "running"]), Job.file_name == safe_name).all()
        for active in active_jobs:
            in_art = db.query(Artifact).filter(Artifact.job_id == active.id, Artifact.artifact_type == "input_pptx").first()
            if in_art and in_art.file_size == len(content) and Path(in_art.file_path).is_file():
                if hashlib.sha256(Path(in_art.file_path).read_bytes()).hexdigest() == content_hash:
                    raise APIError(409, "DUPLICATE_ACTIVE_JOB", "동일한 파일의 영상 생성 작업이 이미 진행 중입니다.", job_id=active.id)

        # 3) Job ID 발급 및 storage/jobs/{job_id}/input, output 디렉터리 생성
        job_id = generate_job_id()
        job_root = settings.jobs_dir / job_id
        input_dir = job_root / "input"
        output_dir = job_root / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_pptx = input_dir / safe_name
        saved_pptx.write_bytes(content)

        now = utc_now()
        job = Job(
            id=job_id,
            file_name=safe_name,
            status="queued",
            retry_count=0,
            max_retries=settings.default_max_retries,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
        db.add(Artifact(
            job_id=job_id,
            artifact_type="input_pptx",
            file_name=safe_name,
            file_path=str(saved_pptx),
            file_size=len(content),
            mime_type=PPTX_MIME,
            created_at=now,
        ))
        db.add(JobEvent(
            job_id=job_id,
            event_type="job_queued",
            retry_count=0,
            message=f"{safe_name} 작업이 등록되었습니다.",
            created_at=now,
        ))
        db.commit()

    # 4) 단일 백그라운드 워커에 AI 실행 위임
    request.app.state.job_runner.submit(job_id, saved_pptx, output_dir, settings.default_max_retries)
    return CreateJobResponse(job_id=job_id, file_name=safe_name, status="queued", created_at=now)


# ---------------------------------------------------------------------------
# API-03: 작업 목록·검색·필터링 조회
# ---------------------------------------------------------------------------
@router.get("", response_model=JobListResponse)
def list_jobs(
    request: Request,
    search: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=50),
    sort: str = Query(default="created_at_desc"),
) -> JobListResponse:
    """API-03: 작업 목록을 검색·상태 필터링·정렬·페이지네이션하여 반환한다."""
    with request.app.state.session_factory() as db:
        q = db.query(Job)

        if search and search.strip():
            term = f"%{search.strip()}%"
            q = q.filter(or_(Job.file_name.ilike(term), Job.product_name.ilike(term), Job.id.ilike(term)))

        if status and status != "all":
            if status == "in_progress":
                q = q.filter(Job.status.in_(["queued", "running"]))
            elif status == "issue":
                q = q.filter(Job.status.in_(["failed", "fallback_review_required"]))
            else:
                q = q.filter(Job.status == status)

        sort_map = {
            "created_at_desc": desc(Job.created_at),
            "created_at_asc": asc(Job.created_at),
            "updated_at_desc": desc(Job.updated_at),
        }
        q = q.order_by(sort_map.get(sort, desc(Job.created_at)))

        total = q.count()
        total_pages = max(1, math.ceil(total / limit))
        rows = q.offset((page - 1) * limit).limit(limit).all()

        # input_pptx 크기 및 썸네일 보유 여부 일괄 조회
        job_ids = [r.id for r in rows]
        file_sizes: dict[str, int] = {}
        thumb_jobs: set[str] = set()
        if job_ids:
            arts = db.query(Artifact).filter(Artifact.job_id.in_(job_ids), Artifact.artifact_type.in_(["input_pptx", "image"])).all()
            for a in arts:
                if a.artifact_type == "input_pptx":
                    file_sizes[a.job_id] = a.file_size
                elif a.artifact_type == "image" and Path(a.file_path).is_file():
                    thumb_jobs.add(a.job_id)

        items = []
        for job in rows:
            stage_num, stage_label, _ = compute_stage_progress(job)
            has_thumb = job.id in thumb_jobs
            items.append(JobListItem(
                job_id=job.id,
                file_name=job.file_name,
                file_size=file_sizes.get(job.id, 0),
                product_name=job.product_name,
                status=job.status,
                current_node=job.current_node,
                current_stage=stage_num,
                current_stage_label=stage_label,
                retry_count=job.retry_count,
                error_code=job.error_code,
                error_message=job.error_message,
                video_duration_sec=job.video_duration_sec,
                qa_passed=job.qa_passed,
                has_thumbnail=has_thumb,
                thumbnail_url=f"/api/jobs/{job.id}/thumbnail" if has_thumb else None,
                created_at=job.created_at,
                finished_at=job.finished_at,
            ))
        return JobListResponse(items=items, total=total, page=page, limit=limit, total_pages=total_pages)


# ---------------------------------------------------------------------------
# API-04: 특정 작업 진행 상태 조회 (Polling 대상)
# ---------------------------------------------------------------------------
@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(request: Request, job_id: str) -> JobStatusResponse:
    """API-04: 특정 작업의 현재 상태, 실행 노드, 5단계 진행 정보를 반환한다."""
    with request.app.state.session_factory() as db:
        job = _get_job_or_404(db, job_id)
        in_art = db.query(Artifact).filter(Artifact.job_id == job_id, Artifact.artifact_type == "input_pptx").first()
        stage_num, stage_label, stages = compute_stage_progress(job)
        return JobStatusResponse(
            job_id=job.id,
            file_name=job.file_name,
            file_size=in_art.file_size if in_art else 0,
            product_name=job.product_name,
            status=job.status,
            current_node=job.current_node,
            current_stage=stage_num,
            current_stage_label=stage_label,
            stages=stages,
            retry_count=job.retry_count,
            max_retries=job.max_retries,
            error_code=job.error_code,
            error_message=job.error_message,
            video_duration_sec=job.video_duration_sec,
            qa_passed=job.qa_passed,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
            updated_at=job.updated_at,
        )


# ---------------------------------------------------------------------------
# API-05: AI 노드별 실행 기록 조회
# ---------------------------------------------------------------------------
@router.get("/{job_id}/logs", response_model=JobLogsResponse)
def get_job_logs(request: Request, job_id: str) -> JobLogsResponse:
    """API-05: 작업의 노드별 실행 시작·종료·소요 시간·재시도 기록을 반환한다."""
    with request.app.state.session_factory() as db:
        job = _get_job_or_404(db, job_id)
        events = db.query(JobEvent).filter(JobEvent.job_id == job_id).order_by(JobEvent.id.asc()).all()
        return aggregate_node_logs(job, events)


# ---------------------------------------------------------------------------
# API-06: 영상 생성 및 검증 결과 조회
# ---------------------------------------------------------------------------
@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(request: Request, job_id: str) -> JobResultResponse:
    """API-06: 완료된 작업의 제품 분석·USP·원문 근거·대본·검증·QA 결과를 반환한다."""
    with request.app.state.session_factory() as db:
        job = _get_job_or_404(db, job_id)
        if job.status != "completed":
            raise APIError(409, "JOB_NOT_COMPLETED", "영상이 아직 완료되지 않아 결과를 조회할 수 없습니다.", job_id=job_id)
        artifacts = db.query(Artifact).filter(Artifact.job_id == job_id).all()
        return build_job_result_payload(job, artifacts)


# ---------------------------------------------------------------------------
# API-07: 영상 미리보기 스트리밍 (HTTP Range 206 지원)
# ---------------------------------------------------------------------------
@router.get("/{job_id}/video")
def stream_job_video(request: Request, job_id: str):
    """API-07: 브라우저 재생 및 탐색(Seek)을 위한 HTTP Range 지원 MP4 스트리밍."""
    with request.app.state.session_factory() as db:
        _, video_path = _get_completed_video_path(db, job_id)

    file_size = video_path.stat().st_size
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(path=str(video_path), media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

    match = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not match:
        raise APIError(400, "INVALID_RANGE", "유효하지 않은 Range 요청입니다.", job_id=job_id)

    start_s, end_s = match.groups()
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else file_size - 1
    if start >= file_size or end < start:
        raise APIError(416, "RANGE_NOT_SATISFIABLE", "요청한 바이트 범위가 영상 크기를 벗어났습니다.", job_id=job_id)
    end = min(end, file_size - 1)
    chunk_len = end - start + 1

    def iter_file(path: Path, offset: int, length: int) -> Iterator[bytes]:
        with path.open("rb") as fh:
            fh.seek(offset)
            remaining = length
            while remaining > 0:
                buf = fh.read(min(256 * 1024, remaining))
                if not buf:
                    break
                remaining -= len(buf)
                yield buf

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_len),
    }
    return StreamingResponse(iter_file(video_path, start, chunk_len), status_code=206, media_type="video/mp4", headers=headers)


# ---------------------------------------------------------------------------
# API-08: 최종 MP4 다운로드
# ---------------------------------------------------------------------------
@router.get("/{job_id}/download")
def download_job_video(request: Request, job_id: str):
    """API-08: 완료된 작업의 최종 MP4를 첨부 파일로 다운로드한다."""
    with request.app.state.session_factory() as db:
        job, video_path = _get_completed_video_path(db, job_id)

    stem = Path(job.file_name).stem or job.id
    download_name = f"{stem}_shortform.mp4"
    encoded = quote(download_name)
    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        headers={"Content-Disposition": f"attachment; filename=\"{download_name}\"; filename*=UTF-8''{encoded}"},
    )


# ---------------------------------------------------------------------------
# 보조 자산 API: 서버 내부 경로를 숨기고 썸네일·장면 이미지를 안전 제공
# ---------------------------------------------------------------------------
@router.get("/{job_id}/thumbnail")
def get_job_thumbnail(request: Request, job_id: str):
    """작업 대표 제품 썸네일 이미지를 반환한다."""
    with request.app.state.session_factory() as db:
        _get_job_or_404(db, job_id)
        art = db.query(Artifact).filter(Artifact.job_id == job_id, Artifact.artifact_type == "image").order_by(Artifact.id.asc()).first()
        if not art or not Path(art.file_path).is_file():
            raise APIError(404, "THUMBNAIL_NOT_FOUND", "썸네일 이미지가 없습니다.", job_id=job_id)
        return FileResponse(path=art.file_path, media_type=art.mime_type)


@router.get("/{job_id}/scenes/{scene_no}/image")
def get_scene_image(request: Request, job_id: str, scene_no: int):
    """결과 상세의 씬(장면) 요약 썸네일 이미지를 반환한다."""
    with request.app.state.session_factory() as db:
        job = _get_job_or_404(db, job_id)
        if job.status != "completed":
            raise APIError(409, "JOB_NOT_COMPLETED", "완료된 작업의 장면 이미지만 조회할 수 있습니다.", job_id=job_id)
        p_art = db.query(Artifact).filter(Artifact.job_id == job_id, Artifact.artifact_type == "pipeline_json").first()
        data = _safe_load_json(p_art.file_path if p_art else None)
        scenes = (data.get("final_state") or {}).get("scenes") or []
        scene = next((s for s in scenes if int(s.get("scene_no", -1)) == scene_no), None)
        if not scene or not scene.get("image_path") or not Path(scene["image_path"]).is_file():
            raise APIError(404, "SCENE_IMAGE_NOT_FOUND", "해당 장면 이미지를 찾을 수 없습니다.", job_id=job_id)
        return FileResponse(path=scene["image_path"])
