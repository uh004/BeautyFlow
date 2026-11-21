"""BeautyFlow 공통 환경 설정, 경로, 모델·단가·필터 상수."""

from __future__ import annotations

import os
import re
import warnings
from pathlib import Path

from dotenv import load_dotenv

# Pydantic v2 직렬화 경고 숨김 (LangChain structured_output 호환)
warnings.filterwarnings("ignore", message="Pydantic serializer warnings:", category=UserWarning)


def _find_project_root() -> Path:
    """저장소 루트(AI/AGENTS.md + data/ 위치)를 탐색한다."""
    candidates = [Path(__file__).resolve().parents[2], Path.cwd(), *Path.cwd().parents]
    for path in candidates:
        if (path / "AI" / "AGENTS.md").is_file() and (path / "data").is_dir():
            return path
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT: Path = _find_project_root()

# .env 명시 로드 (OpenAI / LangSmith 키)
load_dotenv(PROJECT_ROOT / ".env")

# OPENAI_API_KEY 또는 OPEN_API_KEY 둘 다 지원
OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY")
if OPENAI_API_KEY and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# 공통 모델 및 표준 단가 (USD / 100만 토큰, 2026-11-12 공식 문서 기준)
DEFAULT_LLM_MODEL = "gpt-6-luna"
PRODUCT_TOKEN_RATES: dict[str, float] = {
    "input": 0.10,
    "cached_input": 0.01,
    "cache_write": 0.125,
    "output": 0.50,
}

# 분석·기획·검증에서 제외할 상업 정보 패턴 (가격·할인·리뷰·재고·배송)
EXCLUDED_INFO = re.compile(
    r"\b(price|discount|reviews?|ratings?|in stock|out of stock|shipping|delivery fee)\b"
    r"|\$|\u20AC|\u20A9|가격|할인|리뷰|평점|재고|배송",
    re.IGNORECASE,
)


def estimate_llm_cost(usage: dict | None, rates: dict[str, float] = PRODUCT_TOKEN_RATES) -> float:
    """LangChain usage_metadata로부터 예상 USD 비용을 계산한다."""
    usage = usage or {}
    details = usage.get("input_token_details") or {}
    cached = details.get("cache_read", 0)
    written = details.get("cache_creation", 0)
    uncached = max(0, usage.get("input_tokens", 0) - cached - written)
    cost = (
        uncached * rates["input"]
        + cached * rates["cached_input"]
        + written * rates["cache_write"]
        + usage.get("output_tokens", 0) * rates["output"]
    ) / 1_000_000
    return round(cost, 8)
