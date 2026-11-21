"""③ Python / Pytest 기반 결정론적 규격·안전성·일관성 평가 모듈.

미지원 주장 0건, code_checks 5종, 9:16·20~30초·1줄 자막·오디오 싱크(≥0.90),
Anthropic pass@k / pass^k 일관성 지표, Pytest 회귀 테스트 결과를 집계한다.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from AI.beautyflow.config import PROJECT_ROOT


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def evaluate_run_deterministic(pipeline_report: dict[str, Any]) -> dict[str, Any]:
    """pipeline.json 리포트로부터 규격·사실성·안전성·비용·시간 지표를 결정론적으로 계산한다."""
    final_state = pipeline_report.get("final_state") or {}
    val_result = final_state.get("validation_result") or {}
    qa_result = final_state.get("qa_result") or {}

    val_report = _load_json(final_state.get("validation_json_path"))
    qa_report = _load_json(final_state.get("qa_json_path"))
    render_report = _load_json(final_state.get("render_json_path"))

    # 1) 사실성 · 1차 코드 가드
    unsupported = list(val_result.get("unsupported_claims") or [])
    code_checks = dict(val_report.get("code_checks") or {})
    code_checks_passed = bool(code_checks) and all(v in {"passed", "skipped"} for v in code_checks.values()) and any(v == "passed" for v in code_checks.values())

    # 2) 영상 규격 · 1줄 자막 · 오디오 싱크
    checks_by_name = {c["name"]: c for c in (qa_report.get("checks") or []) if isinstance(c, dict) and "name" in c}
    audio_sim = (checks_by_name.get("audio_similarity") or {}).get("details") or {}
    audio_corr = float(audio_sim.get("correlation", 0.0)) if isinstance(audio_sim, dict) else 0.0
    single_line_ok = bool((checks_by_name.get("subtitle_single_line") or {}).get("passed"))

    duration = float(qa_result.get("video_duration_sec") or 0.0)
    resolution = str(qa_result.get("resolution") or "")
    video_spec_ok = (
        bool(qa_result.get("is_passed"))
        and resolution == "1080x1920"
        and 20.0 <= duration <= 30.0
        and single_line_ok
        and audio_corr >= 0.90
    )

    completed = final_state.get("status") == "completed" and bool(final_state.get("video_path")) and video_spec_ok and len(unsupported) == 0
    return {
        "completed": completed,
        "status": final_state.get("status"),
        "unsupported_claims_count": len(unsupported),
        "validation_passed": bool(val_result.get("is_valid")),
        "code_checks": code_checks,
        "code_checks_passed": code_checks_passed,
        "video_spec_passed": video_spec_ok,
        "resolution": resolution,
        "video_duration_sec": round(duration, 2),
        "subtitle_single_line": single_line_ok,
        "audio_correlation": round(audio_corr, 4),
        "creative_direction": render_report.get("creative_direction") or final_state.get("creative_direction") or {},
        "elapsed_sec": float(pipeline_report.get("elapsed_sec") or 0.0),
        "estimated_cost_usd": float(pipeline_report.get("known_estimated_cost_usd") or 0.0),
        "video_path": final_state.get("video_path") or "",
        "qa_preview_path": str(Path(final_state["video_path"]).parent / "qa_preview.jpg") if final_state.get("video_path") else "",
    }


def compute_pass_at_k(total_trials: int, passed_trials: int, k: int) -> float:
    """Anthropic/OpenAI 표준 pass@k: k회 시도 중 최소 1회 성공 확률."""
    if total_trials <= 0 or k <= 0:
        return 0.0
    k = min(k, total_trials)
    if total_trials - passed_trials < k:
        return 1.0
    return round(1.0 - math.comb(total_trials - passed_trials, k) / math.comb(total_trials, k), 4)


def compute_pass_pow_k(total_trials: int, passed_trials: int, k: int) -> float:
    """Anthropic pass^k: k회 연속 모두 성공할 신뢰성(일관성) 확률."""
    if total_trials <= 0 or k <= 0:
        return 0.0
    p = passed_trials / total_trials
    return round(p ** k, 4)


def run_pytest_regression(notebook_path: str = "AI/notebooks/MVP_v2.ipynb") -> dict[str, Any]:
    """AI/tests 전체 Pytest 회귀 테스트를 실행하고 통과 건수를 요약한다."""
    env = {**os.environ, "BEAUTYFLOW_NOTEBOOK": notebook_path}
    default_render_state = PROJECT_ROOT / "output" / "v2_minimal_verify" / "lumia_minimal_state.json"
    if "BEAUTYFLOW_RENDER_STATE" not in env and default_render_state.is_file():
        env["BEAUTYFLOW_RENDER_STATE"] = str(default_render_state)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "AI/tests", "-ra", "--tb=short"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    # 마지막 요약 줄("111 passed, 1 warning in 14.2s")에서 집계 추출
    summary_line = next(
        (ln.strip() for ln in reversed(output.splitlines()) if re.search(r"\b(?:passed|failed|error)\b", ln)),
        "",
    )
    passed = sum(int(m) for m in re.findall(r"(\d+)\s+passed", summary_line))
    failed = sum(int(m) for m in re.findall(r"(\d+)\s+failed", summary_line))
    skipped = sum(int(m) for m in re.findall(r"(\d+)\s+skipped", summary_line))
    errors = sum(int(m) for m in re.findall(r"(\d+)\s+errors?", summary_line))
    total = passed + failed + errors
    return {
        "returncode": proc.returncode,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "summary_line": summary_line,
    }
