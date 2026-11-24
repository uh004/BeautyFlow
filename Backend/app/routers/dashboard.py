"""API-01 대시보드 작업 현황 통계 및 헬스체크 라우터."""

from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func

from AI.beautyflow.config import OPENAI_API_KEY
from Backend.app.models import Job
from Backend.app.schemas import DashboardSummaryResponse, RecentActivityItem

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/health")
def health_check(request: Request) -> dict:
    """서버·DB·OpenAI 설정 상태를 확인한다."""
    return {
        "status": "ok",
        "openai_configured": bool(OPENAI_API_KEY),
        "storage_ready": request.app.state.settings.jobs_dir.is_dir(),
    }


@router.get("/dashboard/summary", response_model=DashboardSummaryResponse)
def get_dashboard_summary(request: Request) -> DashboardSummaryResponse:
    """API-01: 전체 및 상태별 작업 건수와 최근 활동 5건을 집계한다."""
    with request.app.state.session_factory() as db:
        rows = db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
        counts = {status: int(cnt) for status, cnt in rows}
        total = sum(counts.values())

        recent_jobs = db.query(Job).order_by(Job.updated_at.desc()).limit(5).all()
        activities: list[RecentActivityItem] = []
        for job in recent_jobs:
            title = job.product_name or job.file_name.rsplit(".", 1)[0]
            if job.status == "completed":
                msg = f"{title} 영상 생성이 완료되었습니다."
            elif job.status == "failed":
                msg = f"{title} 영상 생성에 실패했습니다."
            elif job.status == "fallback_review_required":
                msg = f"{title} 작업의 사용자 검토가 필요합니다."
            elif job.status == "running":
                msg = f"{title} 영상 생성이 진행 중입니다."
            else:
                msg = f"{title} 작업이 대기열에 등록되었습니다."
            activities.append(RecentActivityItem(
                job_id=job.id,
                title=title,
                status=job.status,
                message=msg,
                video_duration_sec=job.video_duration_sec,
                created_at=job.updated_at,
            ))

        return DashboardSummaryResponse(
            total_count=total,
            queued_count=counts.get("queued", 0),
            running_count=counts.get("running", 0),
            completed_count=counts.get("completed", 0),
            failed_count=counts.get("failed", 0),
            review_required_count=counts.get("fallback_review_required", 0),
            recent_activities=activities,
        )
