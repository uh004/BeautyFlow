"""BeautyFlow LangGraph 8노드 그래프 조립 및 파이프라인 실행기."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph

from AI.beautyflow.config import PROJECT_ROOT
from AI.beautyflow.nodes import (
    claim_validator,
    document_parser,
    product_analyzer,
    route_after_claim_validation,
    route_after_script_revision,
    route_after_tts,
    route_after_video_qa,
    route_after_video_render,
    script_generator,
    script_reviser,
    tts_generator,
    video_qa,
    video_renderer,
)
from AI.beautyflow.state import VideoAgentState

# 노드별 결과 JSON 경로 키 및 API 과금 노드 집합
NODE_REPORT_KEYS: dict[str, str] = {
    "DocumentParser": "parsed_json_path",
    "ProductAnalyzer": "analysis_json_path",
    "ScriptGenerator": "script_json_path",
    "ClaimValidator": "validation_json_path",
    "ScriptReviser": "revision_json_path",
    "TTSGenerator": "tts_json_path",
    "VideoRenderer": "render_json_path",
    "VideoQA": "qa_json_path",
}
API_NODES: frozenset[str] = frozenset({
    "ProductAnalyzer",
    "ScriptGenerator",
    "ClaimValidator",
    "ScriptReviser",
    "TTSGenerator",
})


def build_video_graph(node_overrides: dict[str, Any] | None = None):
    """8개 노드와 조건부 라우팅 엣지를 연결한 LangGraph를 컴파일한다.

    Args:
        node_overrides: 테스트·오류 주입 평가용 노드 함수 치환 맵(선택).
    """
    nodes = {
        "DocumentParser": document_parser,
        "ProductAnalyzer": product_analyzer,
        "ScriptGenerator": script_generator,
        "ClaimValidator": claim_validator,
        "ScriptReviser": script_reviser,
        "TTSGenerator": tts_generator,
        "VideoRenderer": video_renderer,
        "VideoQA": video_qa,
    }
    if node_overrides:
        nodes.update(node_overrides)

    graph = StateGraph(VideoAgentState)
    for name, fn in nodes.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "DocumentParser")

    def continue_to(target: str):
        def route(state: VideoAgentState) -> str:
            return target if state.get("status") == "running" else "END"
        return route

    # 1~3번 노드: 정상(running)일 때만 다음 단계로 직진
    for source, target in [
        ("DocumentParser", "ProductAnalyzer"),
        ("ProductAnalyzer", "ScriptGenerator"),
        ("ScriptGenerator", "ClaimValidator"),
    ]:
        graph.add_conditional_edges(source, continue_to(target), {target: target, "END": END})

    # 4~8번 노드: 검증·길이·QA 결과에 따른 조건부 복구 루프
    routes = {
        "ClaimValidator": (route_after_claim_validation, ["TTSGenerator", "ProductAnalyzer", "ScriptReviser"]),
        "ScriptReviser": (route_after_script_revision, ["ClaimValidator", "ProductAnalyzer", "TTSGenerator"]),
        "TTSGenerator": (route_after_tts, ["VideoRenderer", "ScriptReviser"]),
        "VideoRenderer": (route_after_video_render, ["VideoQA"]),
        "VideoQA": (route_after_video_qa, ["VideoRenderer", "ScriptReviser"]),
    }
    for source, (route_fn, destinations) in routes.items():
        graph.add_conditional_edges(source, route_fn, {**{d: d for d in destinations}, "END": END})

    return graph.compile()


beautyflow_graph = build_video_graph()


def run_video_pipeline(
    file_path: str | Path,
    output_dir: str | Path = "output",
    max_retries: int = 3,
    *,
    brand_guide: dict[str, Any] | None = None,
    bgm_path: str | Path | None = None,
    graph=None,
    run_name: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """단일 PPTX에 대해 8노드 숏폼 생성 파이프라인을 실행하고 pipeline.json에 기록한다."""
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError("max_retries는 0 이상의 정수여야 합니다.")

    stem = Path(str(file_path)).stem or "invalid_input"
    run_dir = (PROJECT_ROOT / output_dir / "runs" / stem / uuid4().hex[:12]).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = run_dir / "pipeline.json"

    state: dict[str, Any] = {
        "file_path": str(file_path),
        "output_dir": str(run_dir),
        "retry_count": 0,
        "max_retries": max_retries,
        "status": "running",
        "error_message": None,
        "pipeline_json_path": str(manifest),
    }
    if brand_guide is not None:
        state["brand_guide"] = brand_guide
    if bgm_path is not None:
        state["bgm_path"] = str(bgm_path)

    trace: list[dict[str, Any]] = []
    started = time.perf_counter()
    step_started = started

    def save() -> None:
        costs = [item["estimated_cost_usd"] for item in trace]
        known = round(sum(c for c in costs if c is not None), 8)
        report = {
            "status": state.get("status"),
            "error_message": state.get("error_message"),
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "trace": trace,
            "estimated_cost_usd": known if all(c is not None for c in costs) else None,
            "known_estimated_cost_usd": known,
            "final_state": state,
        }
        tmp = manifest.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(manifest)

    compiled = graph or beautyflow_graph
    run_config: dict[str, Any] = {
        "recursion_limit": 16 + 6 * max_retries,
        "run_name": run_name or f"BeautyFlow:{stem}",
        "tags": tags or ["beautyflow", "v2.3", stem],
        "metadata": {"file_path": str(file_path), "max_retries": max_retries, **(metadata or {})},
    }

    save()
    try:
        for mode, event in compiled.stream(state, stream_mode=["updates", "values"], config=run_config):
            if mode == "values":
                state = dict(event)
                continue
            for node, update in event.items():
                if not isinstance(update, dict):
                    continue
                state.update(update)
                report_path = update.get(NODE_REPORT_KEYS.get(node, ""))
                cost: float | None = 0.0
                if node in API_NODES:
                    cost = None if update.get("status") in {"failed", "fallback_review_required"} else 0.0
                    if report_path:
                        try:
                            recorded = json.loads(Path(report_path).read_text(encoding="utf-8"))
                            if node == "ScriptReviser":
                                cost = recorded["revision_history"][-1].get("estimated_cost_usd")
                            else:
                                cost = recorded.get("estimated_cost_usd")
                        except (OSError, ValueError, KeyError, IndexError):
                            cost = None
                trace.append({
                    "node": node,
                    "status": state.get("status"),
                    "retry_count": state.get("retry_count", 0),
                    "elapsed_sec": round(time.perf_counter() - step_started, 3),
                    "estimated_cost_usd": cost,
                    "report_path": report_path,
                    "error_message": state.get("error_message"),
                })
                if verbose:
                    print(f"{node}: {state.get('status')} / retry={state.get('retry_count', 0)}", flush=True)
                save()
                step_started = time.perf_counter()

        if state.get("status") == "running" or (
            state.get("status") == "completed"
            and (not (state.get("qa_result") or {}).get("is_passed") or not state.get("video_path"))
        ):
            state.update(status="fallback_review_required", error_message="LangGraph가 완료 판정 없이 종료됐습니다.")
    except GraphRecursionError:
        state.update(status="fallback_review_required", error_message="LangGraph 실행 단계 한도에 도달했습니다.")
    except Exception as error:
        state.update(status="failed", error_message=f"LangGraph 실행 오류: {type(error).__name__}")
        trace.append({
            "node": "__error__",
            "status": "failed",
            "retry_count": state.get("retry_count", 0),
            "elapsed_sec": round(time.perf_counter() - step_started, 3),
            "estimated_cost_usd": None,
            "report_path": None,
            "error_message": state["error_message"],
        })

    state["pipeline_json_path"] = str(manifest)
    save()
    return state
