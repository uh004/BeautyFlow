"""Backend 환경 설정, 저장소 경로 및 AI 노드 → 사용자 5단계 매핑 상수."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from AI.beautyflow.config import PROJECT_ROOT

# 사용자 화면에 표시할 5개 AI 처리 단계 (명세서 기준 고정)
STAGE_DEFINITIONS: tuple[dict[str, object], ...] = (
    {"stage": 1, "label": "문서 분석", "nodes": ("DocumentParser",)},
    {"stage": 2, "label": "제품 정보 및 USP 분석", "nodes": ("ProductAnalyzer",)},
    {"stage": 3, "label": "대본 생성 및 정보 검증", "nodes": ("ScriptGenerator", "ClaimValidator", "ScriptReviser")},
    {"stage": 4, "label": "음성·영상 제작", "nodes": ("TTSGenerator", "VideoRenderer")},
    {"stage": 5, "label": "최종 품질 검사", "nodes": ("VideoQA",)},
)

NODE_TO_STAGE: dict[str, int] = {
    node: int(defn["stage"])
    for defn in STAGE_DEFINITIONS
    for node in defn["nodes"]  # type: ignore[union-attr]
}

STAGE_LABELS: dict[int, str] = {int(defn["stage"]): str(defn["label"]) for defn in STAGE_DEFINITIONS}


@dataclass(frozen=True)
class BackendSettings:
    """FastAPI 백엔드 런타임 설정."""
    storage_dir: Path
    jobs_dir: Path
    db_path: Path
    max_upload_bytes: int
    cors_origins: tuple[str, ...]
    default_max_retries: int = 3

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


def load_settings(
    storage_dir: str | Path | None = None,
    db_path: str | Path | None = None,
    max_upload_mb: int | None = None,
) -> BackendSettings:
    """환경변수 또는 테스트 인자에서 BackendSettings를 생성한다."""
    raw_storage = storage_dir or os.getenv("BEAUTYFLOW_STORAGE_DIR") or "storage"
    resolved_storage = Path(raw_storage)
    if not resolved_storage.is_absolute():
        resolved_storage = (PROJECT_ROOT / resolved_storage).resolve()

    raw_db = db_path or os.getenv("BEAUTYFLOW_DB_PATH") or (resolved_storage / "beautyflow.db")
    resolved_db = Path(raw_db)
    if not resolved_db.is_absolute():
        resolved_db = (PROJECT_ROOT / resolved_db).resolve()

    limit_mb = max_upload_mb if max_upload_mb is not None else int(os.getenv("BEAUTYFLOW_MAX_UPLOAD_MB") or "200")
    raw_cors = os.getenv("BEAUTYFLOW_CORS_ORIGINS") or "http://localhost:3000,http://127.0.0.1:3000"
    origins = tuple(item.strip() for item in raw_cors.split(",") if item.strip())

    resolved_storage.mkdir(parents=True, exist_ok=True)
    jobs_dir = resolved_storage / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    resolved_db.parent.mkdir(parents=True, exist_ok=True)

    return BackendSettings(
        storage_dir=resolved_storage,
        jobs_dir=jobs_dir,
        db_path=resolved_db,
        max_upload_bytes=limit_mb * 1024 * 1024,
        cors_origins=origins,
    )
