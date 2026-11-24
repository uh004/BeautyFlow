"""API-01 ~ API-08 Pydantic 요청·응답 스키마 및 공통 오류 모델."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# 공통 오류 응답
# ---------------------------------------------------------------------------
class ErrorResponse(BaseModel):
    error_code: str
    message: str
    job_id: Optional[str] = None


# ---------------------------------------------------------------------------
# API-01: 대시보드 작업 현황 통계
# ---------------------------------------------------------------------------
class RecentActivityItem(BaseModel):
    job_id: str
    title: str
    status: str
    message: str
    video_duration_sec: Optional[float] = None
    created_at: datetime


class DashboardSummaryResponse(BaseModel):
    total_count: int
    queued_count: int
    running_count: int
    completed_count: int
    failed_count: int
    review_required_count: int
    recent_activities: list[RecentActivityItem] = []


# ---------------------------------------------------------------------------
# API-02: 영상 생성 작업 등록
# ---------------------------------------------------------------------------
class CreateJobResponse(BaseModel):
    job_id: str
    file_name: str
    status: str
    created_at: datetime


# ---------------------------------------------------------------------------
# API-03: 작업 목록 조회
# ---------------------------------------------------------------------------
class JobListItem(BaseModel):
    job_id: str
    file_name: str
    file_size: int = 0
    product_name: Optional[str] = None
    status: str
    current_node: Optional[str] = None
    current_stage: int = 0
    current_stage_label: Optional[str] = None
    retry_count: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    video_duration_sec: Optional[float] = None
    qa_passed: Optional[bool] = None
    has_thumbnail: bool = False
    thumbnail_url: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


class JobListResponse(BaseModel):
    items: list[JobListItem]
    total: int
    page: int
    limit: int
    total_pages: int


# ---------------------------------------------------------------------------
# API-04: 특정 작업 진행 상태 조회
# ---------------------------------------------------------------------------
class StageProgressItem(BaseModel):
    stage: int
    label: str
    status: Literal["pending", "running", "completed", "failed", "review_required"]


class JobStatusResponse(BaseModel):
    job_id: str
    file_name: str
    file_size: int = 0
    product_name: Optional[str] = None
    status: str
    current_node: Optional[str] = None
    current_stage: int = 0
    current_stage_label: Optional[str] = None
    stages: list[StageProgressItem] = []
    retry_count: int = 0
    max_retries: int = 3
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    video_duration_sec: Optional[float] = None
    qa_passed: Optional[bool] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime


# ---------------------------------------------------------------------------
# API-05: AI 노드별 실행 기록 조회
# ---------------------------------------------------------------------------
class NodeLogItem(BaseModel):
    node_run_id: Optional[str] = None
    node_name: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    duration_sec: Optional[float] = None
    retry_count: int = 0
    message: Optional[str] = None


class JobLogsResponse(BaseModel):
    job_id: str
    status: str
    logs: list[NodeLogItem]


# ---------------------------------------------------------------------------
# API-06: 영상 생성 및 검증 결과 조회 (서버 내부 경로 제외)
# ---------------------------------------------------------------------------
class PublicUSPItem(BaseModel):
    usp_id: int
    usp_type: Optional[str] = None
    title: str
    description: str
    source_slide_no: int
    source_quote: str


class PublicSceneItem(BaseModel):
    scene_no: int
    purpose: str
    badge_label: str = ""
    headline: str = ""
    narration: str
    subtitle: str
    motion_effect: str
    duration_sec: float
    start_sec: float = 0.0
    end_sec: float = 0.0
    usp_ids: list[int] = []
    source_slide_nos: list[int] = []
    image_url: Optional[str] = None


class VideoInfoSummary(BaseModel):
    duration_sec: float
    resolution: str
    fps: int = 30
    video_url: str
    download_url: str
    thumbnail_url: Optional[str] = None


class JobResultResponse(BaseModel):
    job_id: str
    file_name: str
    created_at: datetime
    finished_at: Optional[datetime] = None
    product_info: dict[str, Any]
    common_analysis: dict[str, Any] = {}
    usps: list[PublicUSPItem]
    creative_direction: dict[str, Any] = {}
    scenes: list[PublicSceneItem]
    full_script: str
    validation_result: dict[str, Any]
    code_checks: dict[str, str] = {}
    qa_result: dict[str, Any]
    qa_checks: list[dict[str, Any]] = []
    video_info: VideoInfoSummary
    elapsed_sec: Optional[float] = None
    estimated_cost_usd: Optional[float] = None
