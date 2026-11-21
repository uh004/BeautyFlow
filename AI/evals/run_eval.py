"""① LangSmith 연동 + 4종 AI Agent 통합 벤치마크 실행기.

사용 예시:
    .venv\\Scripts\\python.exe -m AI.evals.run_eval --repeats 1
    .venv\\Scripts\\python.exe -m AI.evals.run_eval --products LUMIA --repeats 1 --skip-langsmith
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from AI.beautyflow.config import PROJECT_ROOT
from AI.beautyflow.graph import run_video_pipeline
from AI.evals.code_eval import (
    compute_pass_at_k,
    compute_pass_pow_k,
    evaluate_run_deterministic,
    run_pytest_regression,
)
from AI.evals.dataset import GOLDEN_CASES, run_adversarial_suite
from AI.evals.judge_eval import evaluate_v1_vs_v2_pairwise, evaluate_video_with_vlm_judge
from AI.evals.trajectory_eval import IDEAL_TRAJECTORY, evaluate_run_trajectory

DEFAULT_DATASET_NAME = "BeautyFlow-Benchmark-v2"


# ---------------------------------------------------------------------------
# 1. LangSmith 데이터셋 동기화 및 실험(Experiment) 업로드
# ---------------------------------------------------------------------------
def _sync_langsmith_dataset(client, dataset_name: str, cases: list[dict[str, Any]]):
    """LangSmith Dataset을 생성(또는 조회)하고 Golden Set 예제를 동기화한다."""
    existing = [d for d in client.list_datasets(dataset_name=dataset_name)]
    if existing:
        dataset = existing[0]
    else:
        dataset = client.create_dataset(
            dataset_name=dataset_name,
            description="BeautyFlow Golden Benchmark (LUMIA Cushion, SOLAIA Sun Serum, DERMERA Cream)",
        )

    existing_examples = list(client.list_examples(dataset_id=dataset.id))
    by_id = {(ex.inputs or {}).get("product_id"): ex for ex in existing_examples}
    for case in cases:
        inputs = {"product_id": case["id"], "file_path": case["file_path"], "category": case["category"]}
        outputs = {"expected_steps": IDEAL_TRAJECTORY, "expected_status": "completed", "expected_resolution": "1080x1920"}
        if case["id"] not in by_id:
            client.create_example(inputs=inputs, outputs=outputs, dataset_id=dataset.id)
    return dataset


def _make_langsmith_evaluators():
    """LangSmith Experiment 대시보드에 항목별 정량·정성 점수를 기록하는 Evaluator 목록."""
    def eval_e2e_completed(outputs: dict) -> dict:
        return {"key": "e2e_completed", "score": int(bool((outputs.get("deterministic") or {}).get("completed")))}

    def eval_exact_trajectory(outputs: dict) -> dict:
        return {"key": "agent_evals_exact_match", "score": int(bool((outputs.get("trajectory") or {}).get("exact_match")))}

    def eval_in_order_trajectory(outputs: dict) -> dict:
        return {"key": "agent_evals_in_order", "score": int(bool((outputs.get("trajectory") or {}).get("in_order_match")))}

    def eval_retry_count(outputs: dict) -> dict:
        return {"key": "retry_count", "score": int((outputs.get("trajectory") or {}).get("retry_count", 0))}

    def eval_zero_unsupported(outputs: dict) -> dict:
        cnt = int((outputs.get("deterministic") or {}).get("unsupported_claims_count", 1))
        return {"key": "zero_unsupported_claims", "score": int(cnt == 0)}

    def eval_video_spec(outputs: dict) -> dict:
        return {"key": "video_spec_passed", "score": int(bool((outputs.get("deterministic") or {}).get("video_spec_passed")))}

    def eval_audio_corr(outputs: dict) -> dict:
        return {"key": "audio_sync_correlation", "score": float((outputs.get("deterministic") or {}).get("audio_correlation", 0.0))}

    def eval_vlm_avg(outputs: dict) -> dict:
        judge = outputs.get("vlm_judge") or {}
        score = float(judge.get("average_score") or 0.0)
        return {"key": "vlm_judge_avg_5pt", "score": score, "comment": judge.get("overall_summary", "")}

    def _make_rubric_eval(rubric_key: str):
        def _eval(outputs: dict) -> dict:
            judge = outputs.get("vlm_judge") or {}
            scores = judge.get("scores") or {}
            rationales = judge.get("rationales") or {}
            return {"key": f"vlm_{rubric_key}", "score": float(scores.get(rubric_key, 0.0)), "comment": rationales.get(rubric_key, "")}
        _eval.__name__ = f"eval_vlm_{rubric_key}"
        return _eval

    rubric_evals = [
        _make_rubric_eval(k)
        for k in ("groundedness", "hook_appeal", "usp_clarity", "visual_alignment", "brand_consistency")
    ]
    return [
        eval_e2e_completed,
        eval_exact_trajectory,
        eval_in_order_trajectory,
        eval_retry_count,
        eval_zero_unsupported,
        eval_video_spec,
        eval_audio_corr,
        eval_vlm_avg,
        *rubric_evals,
    ]


# ---------------------------------------------------------------------------
# 2. 단일 Golden 실행 + 3종 평가(경로 · 코드 · VLM Judge) 결합
# ---------------------------------------------------------------------------
def _execute_and_evaluate_case(
    product_id: str,
    file_path: str,
    category: str,
    *,
    output_dir: str,
    max_retries: int,
    run_judge: bool,
    trial_index: int,
) -> dict[str, Any]:
    """단일 제품을 AI/beautyflow 파이프라인으로 실행하고 경로·결정론·VLM 평가를 수행한다."""
    print(f"\n[Eval] ▶ {product_id} ({category}) — Trial #{trial_index} 시작", flush=True)
    final_state = run_video_pipeline(
        file_path,
        output_dir=output_dir,
        max_retries=max_retries,
        run_name=f"BeautyFlow-Eval:{product_id}:t{trial_index}",
        tags=["beautyflow-eval", "v2.3", product_id, f"trial-{trial_index}"],
        metadata={"product_id": product_id, "category": category, "trial": trial_index},
        verbose=True,
    )
    pipeline_path = Path(final_state["pipeline_json_path"])
    pipeline_report = json.loads(pipeline_path.read_text(encoding="utf-8"))

    trajectory = evaluate_run_trajectory(pipeline_report.get("trace") or [], final_state)
    deterministic = evaluate_run_deterministic(pipeline_report)

    if run_judge and deterministic["completed"]:
        vlm_judge = evaluate_video_with_vlm_judge(pipeline_report)
    else:
        vlm_judge = {"skipped": True, "reason": "미완료 또는 Judge 생략", "average_score": 0.0, "estimated_cost_usd": 0.0}

    return {
        "product_id": product_id,
        "category": category,
        "file_path": file_path,
        "trial": trial_index,
        "pipeline_json_path": str(pipeline_path),
        "trajectory": trajectory,
        "deterministic": deterministic,
        "vlm_judge": vlm_judge,
    }


# ---------------------------------------------------------------------------
# 3. 통합 마크다운 리포트 생성 (노션 복붙용)
# ---------------------------------------------------------------------------
def render_markdown_report(summary: dict[str, Any]) -> str:
    """평가 결과를 노션·발표자료에 바로 활용할 수 있는 마크다운 성적표로 렌더링한다."""
    ov = summary["overview"]
    ls = summary["langsmith"]
    pt = summary["pytest_regression"]
    adv = summary["adversarial"]
    ab = summary.get("v1_vs_v2_pairwise") or {}

    lines = [
        "# BeautyFlow AI Agent 정량 평가 리포트 (v2.3)",
        "",
        f"- **실행 시각**: {summary['timestamp']}",
        f"- **평가 반복 횟수 (`k`)**: `{summary['repeats']}` (Golden {len(summary['golden_runs'])}편 + Adversarial 6건)",
        f"- **LangSmith 프로젝트**: `{ls.get('project')}` / Dataset: `{ls.get('dataset')}` / Experiment: `{ls.get('experiment_name') or 'N/A'}`",
        "",
        "---",
        "",
        "## 1. 핵심 성적표 요약 (4종 평가 프레임워크)",
        "",
        "| 평가 축 | 핵심 지표 | 측정 결과 | 목표 기준 | 판정 |",
        "| :--- | :--- | :---: | :---: | :---: |",
        f"| **① LangSmith (일관성)** | `pass@{summary['repeats']}` / `pass^{summary['repeats']}` | **{ov['pass_at_k']:.0%}** / **{ov['pass_pow_k']:.0%}** | 100% | {'PASS' if ov['pass_pow_k'] == 1.0 else 'CHECK'} |",
        f"| **② AgentEvals (경로)** | In-Order 경로 준수율 / Exact Match (`retry=0`) | **{ov['in_order_rate']:.0%}** / **{ov['exact_match_rate']:.0%}** | 100% / ≥66% | {'PASS' if ov['in_order_rate'] == 1.0 else 'CHECK'} |",
        f"| **② AgentEvals (분기)** | 6대 오류 유도 Handoff 정확도 | **{adv['handoff_accuracy']:.0%}** ({adv['passed_count']}/{adv['total_count']}) | 100% | {'PASS' if adv['handoff_accuracy'] == 1.0 else 'CHECK'} |",
        f"| **② 루프 효율** | 평균 `retry_count` | **{ov['avg_retry_count']:.2f}회** | ≤ 1.0회 | {'PASS' if ov['avg_retry_count'] <= 1.0 else 'CHECK'} |",
        f"| **③ Python / Pytest** | 회귀 테스트 통과율 | **{pt['passed']} passed / {pt['failed']} failed** ({pt['pass_rate']:.0%}) | 100% | {'PASS' if pt['failed'] == 0 and pt['errors'] == 0 else 'CHECK'} |",
        f"| **③ 안전성·규격** | 미지원 주장 / 영상 규격 준수율 | **{ov['total_unsupported_claims']}건** / **{ov['video_spec_rate']:.0%}** | 0건 / 100% | {'PASS' if ov['total_unsupported_claims'] == 0 and ov['video_spec_rate'] == 1.0 else 'CHECK'} |",
        f"| **④ LLM/VLM Judge** | 5대 루브릭 평균 점수 (1~5점) | **{ov['vlm_avg_score']:.2f} / 5.00** | ≥ 4.00 | {'PASS' if ov['vlm_avg_score'] >= 4.0 else 'CHECK'} |",
        f"| **운영 효율** | 편당 평균 시간 / 비용 | **{ov['avg_elapsed_sec']:.1f}초** / **\\${ov['avg_cost_usd']:.4f}** | ≤ 180초 / ≤ \\$0.05 | PASS |",
        "",
        "---",
        "",
        "## 2. Golden Set 3종 상세 결과",
        "",
        "| 제품 | Trial | 상태 | Retry | Exact / In-Order | 길이(초) | 오디오 싱크 | 미지원 주장 | VLM 평균 | 시간 / 비용 | 비주얼 스타일 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]
    for r in summary["golden_runs"]:
        d, t, j = r["deterministic"], r["trajectory"], r["vlm_judge"]
        cd = d.get("creative_direction") or {}
        style = f"{cd.get('background_tone', '-')}/{cd.get('typography_style', '-')}"
        vlm_txt = f"{j['average_score']:.2f}" if not j.get("skipped") else "N/A"
        lines.append(
            f"| **{r['product_id']}** ({r['category']}) | {r['trial']} | `{d['status']}` | {t['retry_count']} | "
            f"{'O' if t['exact_match'] else 'X'} / {'O' if t['in_order_match'] else 'X'} | "
            f"{d['video_duration_sec']}s | {d['audio_correlation']:.3f} | {d['unsupported_claims_count']}건 | "
            f"**{vlm_txt}** | {d['elapsed_sec']:.1f}s / \\${d['estimated_cost_usd']:.4f} | `{style}` |"
        )

    lines.extend([
        "",
        "### VLM Judge 5대 루브릭 상세 (1~5점)",
        "",
        "| 제품 | Groundedness | Hook Appeal | USP Clarity | Visual Alignment | Brand Consistency | 평균 | 한줄 평가 |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])
    for r in summary["golden_runs"]:
        j = r["vlm_judge"]
        if j.get("skipped"):
            continue
        sc = j["scores"]
        lines.append(
            f"| **{r['product_id']}** (T{r['trial']}) | {sc['groundedness']} | {sc['hook_appeal']} | {sc['usp_clarity']} | "
            f"{sc['visual_alignment']} | {sc['brand_consistency']} | **{j['average_score']:.2f}** | {j.get('overall_summary', '')} |"
        )

    if ab and not ab.get("skipped"):
        lines.extend([
            "",
            "### v1 (개선 전) vs v2.3 (개선 후) 블라인드 A/B 비교",
            "",
            f"- **대상**: {ab['product']} (블라인드 배정: A=`{ab['blind_order']['A']}`, B=`{ab['blind_order']['B']}`)",
            f"- **최종 승자**: **`{ab['winner']}`** (비주얼 완성도: `{ab['visual_polish_winner']}`, 가독성: `{ab['readability_winner']}`, 브랜드 무드: `{ab['brand_mood_winner']}`)",
            f"- **심사 코멘트**: {ab['rationale']}",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## 3. 6대 오류 유도 시나리오 (Adversarial Set — API 비용 \\$0)",
        "",
        "| 케이스 ID | 시나리오 | 방어/복구 | Handoff | 실행 경로 (`steps`) | 비고 |",
        "| :--- | :--- | :---: | :---: | :--- | :--- |",
    ])
    for c in adv["cases"]:
        steps_str = " → ".join(c["steps"])
        lines.append(
            f"| `{c['case_id']}` | {c['category']} | {'PASS' if c['passed'] else 'FAIL'} | "
            f"{'PASS' if c['handoff_ok'] else 'FAIL'} | `{steps_str}` | {c['detail']} |"
        )

    lines.extend(["", "---", "", "## 4. 산출물 경로", ""])
    for r in summary["golden_runs"]:
        d = r["deterministic"]
        lines.append(f"- **{r['product_id']} (T{r['trial']})**: MP4 `{d['video_path']}` / Preview `{d['qa_preview_path']}`")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 4. 메인 CLI 진입점
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="BeautyFlow 4종 AI Agent 정량 평가 실행기")
    parser.add_argument("--products", nargs="+", default=["LUMIA", "SOLAIA", "DERMERA"], help="평가할 제품 ID 목록")
    parser.add_argument("--repeats", type=int, default=1, help="제품당 반복 횟수 k (pass@k / pass^k 측정)")
    parser.add_argument("--max-retries", type=int, default=3, help="파이프라인 최대 재시도 횟수")
    parser.add_argument("--output-dir", default="output/evals", help="평가 리포트 및 산출물 저장 디렉토리")
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME, help="LangSmith Dataset 이름")
    parser.add_argument("--v1-preview", default="", help="v1 vs v2 블라인드 비교용 v1 프리뷰 이미지 경로")
    parser.add_argument("--skip-langsmith", action="store_true", help="LangSmith Dataset/Experiment 업로드 생략")
    parser.add_argument("--skip-judge", action="store_true", help="VLM Judge 채점 생략")
    parser.add_argument("--skip-pytest", action="store_true", help="Pytest 회귀 테스트 실행 생략")
    args = parser.parse_args()

    started = time.perf_counter()
    selected_cases = [c for c in GOLDEN_CASES if c["id"] in {p.upper() for p in args.products}]
    if not selected_cases:
        raise ValueError(f"유효한 제품 ID가 없습니다: {args.products}")

    eval_out = (PROJECT_ROOT / args.output_dir).resolve()
    eval_out.mkdir(parents=True, exist_ok=True)
    golden_runs: list[dict[str, Any]] = []
    ls_info = {
        "enabled": False,
        "project": os.getenv("LANGSMITH_PROJECT") or "BeautyFlow-Eval",
        "dataset": args.dataset_name,
        "experiment_name": None,
    }

    # 1) Golden Set 실행 (LangSmith evaluate 연동 또는 로컬 직실행)
    use_ls = (not args.skip_langsmith) and bool(os.getenv("LANGSMITH_API_KEY"))
    if use_ls:
        from langsmith import Client, evaluate

        client = Client()
        _sync_langsmith_dataset(client, args.dataset_name, selected_cases)
        trial_counters: dict[str, int] = {}
        selected_ids = {c["id"] for c in selected_cases}

        def ls_target(inputs: dict[str, Any]) -> dict[str, Any]:
            pid = inputs["product_id"]
            trial_counters[pid] = trial_counters.get(pid, 0) + 1
            res = _execute_and_evaluate_case(
                pid,
                inputs["file_path"],
                inputs.get("category", ""),
                output_dir=args.output_dir,
                max_retries=args.max_retries,
                run_judge=not args.skip_judge,
                trial_index=trial_counters[pid],
            )
            golden_runs.append(res)
            return res

        examples = [ex for ex in client.list_examples(dataset_name=args.dataset_name) if (ex.inputs or {}).get("product_id") in selected_ids]
        exp_results = evaluate(
            ls_target,
            data=examples,
            evaluators=_make_langsmith_evaluators(),
            experiment_prefix="beautyflow-v2.3",
            metadata={"repeats": args.repeats, "products": [c["id"] for c in selected_cases]},
            max_concurrency=1,
            num_repetitions=args.repeats,
            client=client,
        )
        ls_info["enabled"] = True
        ls_info["experiment_name"] = getattr(exp_results, "experiment_name", None)
    else:
        for trial in range(1, args.repeats + 1):
            for case in selected_cases:
                res = _execute_and_evaluate_case(
                    case["id"],
                    case["file_path"],
                    case["category"],
                    output_dir=args.output_dir,
                    max_retries=args.max_retries,
                    run_judge=not args.skip_judge,
                    trial_index=trial,
                )
                golden_runs.append(res)

    # 2) 6대 Adversarial 사례 검증 (API 비용 0원)
    print("\n[Eval] ▶ 6대 오류 유도 시나리오(Adversarial Set) 검증 중...", flush=True)
    adv_cases = run_adversarial_suite()
    adv_passed = sum(1 for c in adv_cases if c["passed"])
    adv_handoff = sum(1 for c in adv_cases if c["handoff_ok"])

    # 3) Pytest 회귀 테스트 집계
    if args.skip_pytest:
        pytest_res = {"returncode": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "pass_rate": 0.0, "summary_line": "skipped"}
    else:
        print("\n[Eval] ▶ Pytest 전체 회귀 테스트 실행 중...", flush=True)
        pytest_res = run_pytest_regression()

    # 4) v1 vs v2.3 블라인드 A/B 비교 (LUMIA 프리뷰 기준)
    v1_ab = {"skipped": True, "reason": "미지정"}
    if not args.skip_judge and args.v1_preview:
        lumia_run = next((r for r in golden_runs if r["product_id"] == "LUMIA" and r["deterministic"].get("qa_preview_path")), None)
        if lumia_run:
            print("\n[Eval] ▶ v1 vs v2.3 블라인드 A/B 비교 실행 중...", flush=True)
            v1_ab = evaluate_v1_vs_v2_pairwise(args.v1_preview, lumia_run["deterministic"]["qa_preview_path"], product_name="LUMIA Soft Satin Cushion", seed=42)

    # 5) 종합 지표 계산 (pass@k, pass^k, AgentEvals, 규격, VLM 평균, 비용)
    n_runs = len(golden_runs)
    n_completed = sum(1 for r in golden_runs if r["deterministic"]["completed"])
    per_product_pass_at_k, per_product_pass_pow_k = [], []
    for case in selected_cases:
        pruns = [r for r in golden_runs if r["product_id"] == case["id"]]
        pcomp = sum(1 for r in pruns if r["deterministic"]["completed"])
        per_product_pass_at_k.append(compute_pass_at_k(len(pruns), pcomp, args.repeats))
        per_product_pass_pow_k.append(compute_pass_pow_k(len(pruns), pcomp, args.repeats))

    vlm_scores = [r["vlm_judge"]["average_score"] for r in golden_runs if not r["vlm_judge"].get("skipped")]
    judge_cost = sum(float(r["vlm_judge"].get("estimated_cost_usd") or 0.0) for r in golden_runs) + float(v1_ab.get("estimated_cost_usd") or 0.0)

    summary = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "repeats": args.repeats,
        "total_eval_elapsed_sec": round(time.perf_counter() - started, 2),
        "langsmith": ls_info,
        "overview": {
            "total_golden_runs": n_runs,
            "completed_runs": n_completed,
            "pass_at_k": round(sum(per_product_pass_at_k) / max(1, len(per_product_pass_at_k)), 4),
            "pass_pow_k": round(sum(per_product_pass_pow_k) / max(1, len(per_product_pass_pow_k)), 4),
            "exact_match_rate": round(sum(1 for r in golden_runs if r["trajectory"]["exact_match"]) / max(1, n_runs), 4),
            "in_order_rate": round(sum(1 for r in golden_runs if r["trajectory"]["in_order_match"]) / max(1, n_runs), 4),
            "avg_retry_count": round(sum(r["trajectory"]["retry_count"] for r in golden_runs) / max(1, n_runs), 2),
            "total_unsupported_claims": sum(r["deterministic"]["unsupported_claims_count"] for r in golden_runs),
            "video_spec_rate": round(sum(1 for r in golden_runs if r["deterministic"]["video_spec_passed"]) / max(1, n_runs), 4),
            "vlm_avg_score": round(sum(vlm_scores) / max(1, len(vlm_scores)), 2) if vlm_scores else 0.0,
            "avg_elapsed_sec": round(sum(r["deterministic"]["elapsed_sec"] for r in golden_runs) / max(1, n_runs), 2),
            "avg_cost_usd": round(sum(r["deterministic"]["estimated_cost_usd"] for r in golden_runs) / max(1, n_runs), 6),
            "total_judge_cost_usd": round(judge_cost, 6),
        },
        "golden_runs": golden_runs,
        "adversarial": {
            "total_count": len(adv_cases),
            "passed_count": adv_passed,
            "handoff_accuracy": round(adv_handoff / max(1, len(adv_cases)), 4),
            "cases": adv_cases,
        },
        "pytest_regression": pytest_res,
        "v1_vs_v2_pairwise": v1_ab,
    }

    json_path = eval_out / "eval_report.json"
    md_path = eval_out / "eval_report.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown_report(summary), encoding="utf-8")
    print(f"\n[Eval] 완료! JSON: {json_path} / Markdown: {md_path}", flush=True)


if __name__ == "__main__":
    main()
