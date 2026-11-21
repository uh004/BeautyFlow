"""② AgentEvals 기반 LangGraph 실행 경로(Trajectory) 평가 모듈.

- Exact Match: agentevals의 strict 매처로 1차 직진(retry=0) 경로 일치 여부 판정
- In-Order Match: 재시도가 포함돼도 필수 7단계 순서가 보존됐는지 판정
- Handoff Accuracy: 오류 유도 시 기대 복구 노드로 정확히 분기했는지 판정
"""

from __future__ import annotations

from typing import Any

from agentevals.graph_trajectory.strict import graph_trajectory_strict_match

# 1차 직진(retry=0) 기준 표준 7노드 경로
IDEAL_TRAJECTORY: list[str] = [
    "DocumentParser",
    "ProductAnalyzer",
    "ScriptGenerator",
    "ClaimValidator",
    "TTSGenerator",
    "VideoRenderer",
    "VideoQA",
]


def extract_steps_from_trace(trace: list[dict[str, Any]]) -> list[str]:
    """pipeline.json의 trace 목록에서 실행된 노드 이름 시퀀스를 추출한다."""
    return [str(item["node"]) for item in trace if item.get("node") and item.get("node") != "__error__"]


def evaluate_exact_trajectory(steps: list[str], reference_steps: list[str] | None = None) -> dict[str, Any]:
    """agentevals strict 매처로 실행 경로와 기준 경로의 완전 일치 여부를 판정한다."""
    ref = list(reference_steps or IDEAL_TRAJECTORY)
    result = graph_trajectory_strict_match(
        outputs={"steps": list(steps)},
        reference_outputs={"steps": ref},
    )
    return {
        "key": result.get("key", "graph_trajectory_strict_match"),
        "score": bool(result.get("score")),
        "steps": list(steps),
        "reference_steps": ref,
    }


def evaluate_in_order_trajectory(steps: list[str], required_order: list[str] | None = None) -> bool:
    """재시도 루프가 포함돼도 필수 노드 순서(부분 수열)가 보존됐는지 검사한다."""
    targets = list(required_order or IDEAL_TRAJECTORY)
    cursor = 0
    for node in steps:
        if cursor < len(targets) and node == targets[cursor]:
            cursor += 1
    return cursor == len(targets)


def evaluate_handoff(steps: list[str], expected_transition: tuple[str, str] | None = None, expected_steps: list[str] | None = None) -> bool:
    """오류 유도 시 기대한 조건부 전이(A → B) 또는 전체 복구 경로가 정확히 발생했는지 판정한다."""
    if expected_steps is not None:
        return bool(evaluate_exact_trajectory(steps, expected_steps)["score"])
    if expected_transition is not None:
        src, dst = expected_transition
        return any(steps[i] == src and steps[i + 1] == dst for i in range(len(steps) - 1))
    return False


def evaluate_run_trajectory(trace: list[dict[str, Any]], final_state: dict[str, Any]) -> dict[str, Any]:
    """단일 Golden 실행에 대한 경로 지표(Exact · In-Order · 재시도 횟수)를 요약한다."""
    steps = extract_steps_from_trace(trace)
    exact = evaluate_exact_trajectory(steps, IDEAL_TRAJECTORY)
    in_order = evaluate_in_order_trajectory(steps, IDEAL_TRAJECTORY)
    return {
        "steps": steps,
        "step_count": len(steps),
        "exact_match": exact["score"],
        "in_order_match": in_order,
        "retry_count": int(final_state.get("retry_count", 0) or 0),
    }
