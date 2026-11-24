"""SQLAlchemy SQLite 연결, WAL/FK 설정 및 서버 재시작 중단 작업 복구."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """SQLAlchemy ORM 모델 베이스."""


def utc_now() -> datetime:
    """UTC 기준 현재 시각을 반환한다."""
    return datetime.now(timezone.utc)


def create_db_engine(database_url: str):
    """외래키 제약이 활성화된 SQLite 엔진을 생성한다 (IDE 뷰어 즉시 반영을 위해 기본 DELETE 저널 사용)."""
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=DELETE;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    return engine


def create_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def init_db(engine) -> None:
    """ERD 3개 테이블(jobs, artifacts, job_events)을 생성한다."""
    import Backend.app.models  # noqa: F401 — 메타데이터 등록 보장

    Base.metadata.create_all(bind=engine)


def recover_interrupted_jobs(session_factory) -> int:
    """서버 재시작으로 중단된 queued/running 작업을 failed 상태로 복구한다."""
    from Backend.app.models import Job, JobEvent

    now = utc_now()
    recovered = 0
    with session_factory() as db:
        orphaned = db.query(Job).filter(Job.status.in_(["queued", "running"])).all()
        for job in orphaned:
            job.status = "failed"
            job.error_code = "SERVER_RESTARTED"
            job.error_message = "서버 재시작으로 실행 중이던 작업이 중단되었습니다. 다시 생성해 주세요."
            job.finished_at = now
            job.updated_at = now
            db.add(JobEvent(
                job_id=job.id,
                node_run_id=None,
                node_name=job.current_node,
                event_type="job_failed",
                retry_count=job.retry_count,
                duration_sec=None,
                message=job.error_message,
                created_at=now,
            ))
            recovered += 1
        if recovered:
            db.commit()
    return recovered
