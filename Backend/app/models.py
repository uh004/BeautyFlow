"""BeautyFlow ERD 3테이블 ORM 모델 (jobs · artifacts · job_events)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from Backend.app.database import Base, utc_now


class Job(Base):
    """영상 생성 작업 및 현재 상태·결과 요약 테이블 (jobs)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    current_node: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qa_passed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact", back_populates="job", cascade="all, delete-orphan", order_by="Artifact.id"
    )
    events: Mapped[list["JobEvent"]] = relationship(
        "JobEvent", back_populates="job", cascade="all, delete-orphan", order_by="JobEvent.id"
    )


class Artifact(Base):
    """작업별 입력·중간·출력 파일 메타데이터 테이블 (artifacts)."""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    job: Mapped[Job] = relationship("Job", back_populates="artifacts")

    __table_args__ = (Index("ix_artifacts_job_type", "job_id", "artifact_type"),)


class JobEvent(Base):
    """AI 노드별 실행·오류·재시도 이력 테이블 (job_events)."""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    node_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_sec: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    job: Mapped[Job] = relationship("Job", back_populates="events")

    __table_args__ = (Index("ix_job_events_job_created", "job_id", "created_at"),)
