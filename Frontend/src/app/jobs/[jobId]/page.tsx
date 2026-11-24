"use client";

import { use, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  FileText,
  FolderKanban,
  Loader2,
  RefreshCw,
  RotateCcw,
  Sparkles,
} from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { APIRequestError, fetchJobLogs, fetchJobStatus } from "@/lib/api";
import { formatFileSize, formatKSTDateTime, getJobDisplayName } from "@/lib/format";
import type { JobStatusDetail, NodeLogItem, StageStatus } from "@/types/job";

const STAGE_STATUS_TEXT: Record<StageStatus, { label: string; badge: string }> = {
  completed: { label: "완료", badge: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  running: { label: "진행 중", badge: "bg-violet-50 text-violet-700 border-violet-200" },
  pending: { label: "대기 중", badge: "bg-slate-50 text-slate-500 border-slate-200" },
  failed: { label: "실패", badge: "bg-rose-50 text-rose-700 border-rose-200" },
  review_required: { label: "검토 필요", badge: "bg-amber-50 text-amber-700 border-amber-200" },
};

export default function JobProcessingPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = use(params);
  const router = useRouter();

  const [job, setJob] = useState<JobStatusDetail | null>(null);
  const [logs, setLogs] = useState<NodeLogItem[]>([]);
  const [showLogs, setShowLogs] = useState(false);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  const loadData = useCallback(async () => {
    try {
      const statusData = await fetchJobStatus(jobId);
      setJob(statusData);
      setFetchError(null);
      const logData = await fetchJobLogs(jobId);
      setLogs(logData.logs);
      return statusData;
    } catch (err) {
      if (err instanceof APIRequestError) {
        setFetchError(err.message);
      } else {
        setFetchError("작업 상태를 불러오는 중 오류가 발생했습니다.");
      }
      return null;
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  // 2.5초 간격 Polling (완료·실패·검토 필요 도달 시 중단)
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      const data = await loadData();
      if (!active || !data) return;
      if (data.status === "completed") {
        setRedirecting(true);
        timer = setTimeout(() => {
          if (active) router.push(`/jobs/${encodeURIComponent(jobId)}/result`);
        }, 1200);
        return;
      }
      if (data.status === "queued" || data.status === "running") {
        timer = setTimeout(poll, 2500);
      }
    };

    poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, loadData, router]);

  if (loading) {
    return (
      <div className="flex min-h-[360px] flex-col items-center justify-center rounded-2xl border border-[#e9e6f6] bg-white p-10 text-center">
        <Loader2 className="h-8 w-8 animate-spin text-[#5b4ef5]" />
        <p className="mt-3 text-sm font-medium text-[#5e587d]">작업 진행 상태를 불러오고 있습니다...</p>
      </div>
    );
  }

  if (fetchError || !job) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-white p-8 text-center">
        <AlertCircle className="mx-auto h-10 w-10 text-rose-500" />
        <h2 className="mt-3 text-lg font-bold text-[#1f1b3a]">작업을 찾을 수 없습니다</h2>
        <p className="mt-1 text-sm text-[#6b6687]">{fetchError || "유효하지 않은 Job ID입니다."}</p>
        <div className="mt-5 flex justify-center gap-3">
          <Link href="/projects" className="rounded-xl border border-[#dcd7f2] px-4 py-2 text-sm font-semibold text-[#3f3a60]">
            내 작업으로
          </Link>
          <Link href="/create" className="bf-primary-btn rounded-xl px-4 py-2 text-sm font-semibold text-white">
            새 영상 만들기
          </Link>
        </div>
      </div>
    );
  }

  const displayName = getJobDisplayName(job.file_name, job.product_name);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* 상단 작업 요약 카드 */}
      <section className="rounded-2xl border border-[#e9e6f6] bg-white p-6 shadow-xs">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#f1eeff] text-[#5b4ef5]">
              <FileText className="h-6 w-6" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2.5">
                <h2 className="text-lg font-bold text-[#1f1b3a]">{displayName}</h2>
                <StatusBadge status={job.status} />
              </div>
              <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[#726d8d]">
                <span>파일명: {job.file_name} ({formatFileSize(job.file_size)})</span>
                <span>·</span>
                <span className="font-mono font-semibold text-[#5b4ef5]">{job.job_id}</span>
                <span>·</span>
                <span>요청 시간: {formatKSTDateTime(job.created_at)}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/projects"
              className="inline-flex items-center gap-1.5 rounded-xl border border-[#dcd7f2] bg-white px-4 py-2 text-xs font-semibold text-[#474166] hover:bg-[#f7f6fc]"
            >
              <FolderKanban className="h-4 w-4" />
              내 작업으로
            </Link>
            {job.status === "completed" && (
              <Link
                href={`/jobs/${encodeURIComponent(job.job_id)}/result`}
                className="bf-primary-btn inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-semibold text-white"
              >
                결과 확인
                <ArrowRight className="h-4 w-4" />
              </Link>
            )}
          </div>
        </div>

        {/* 현재 상태 배너 */}
        {job.status === "queued" && (
          <div className="mt-5 flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3.5 text-sm text-slate-700">
            <Clock className="h-5 w-5 shrink-0 text-slate-500" />
            <div>
              <p className="font-semibold">작업 대기 중입니다</p>
              <p className="text-xs text-slate-500">앞선 영상 생성이 끝나면 AI 파이프라인이 자동으로 시작됩니다.</p>
            </div>
          </div>
        )}

        {job.status === "running" && (
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#dfd8fb] bg-[#f4f1ff] px-4 py-3.5 text-sm text-[#39299a]">
            <div className="flex items-center gap-3">
              <Loader2 className="h-5 w-5 shrink-0 animate-spin text-[#5b4ef5]" />
              <div>
                <p className="font-semibold">
                  {job.current_stage}단계 / 5단계 — {job.current_stage_label || "AI 처리 중"}
                </p>
                <p className="text-xs text-[#645c91]">
                  현재 실행 노드: <span className="font-mono font-semibold">{job.current_node || "DocumentParser"}</span>
                  {job.retry_count > 0 && ` · 자동 보정 재시도 ${job.retry_count}회 진행`}
                </p>
              </div>
            </div>
            <span className="rounded-full bg-white px-3 py-1 text-xs font-semibold text-[#5b4ef5] border border-[#ddd5fb]">
              다른 페이지로 이동해도 백그라운드에서 계속 실행됩니다
            </span>
          </div>
        )}

        {job.status === "completed" && (
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3.5 text-sm text-emerald-800">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
              <div>
                <p className="font-semibold">영상 생성 및 최종 품질 검사가 완료되었습니다!</p>
                <p className="text-xs text-emerald-700">
                  {redirecting ? "잠시 후 영상 결과 상세 화면으로 자동 이동합니다..." : "결과 확인 버튼을 눌러 영상을 재생하고 다운로드하세요."}
                </p>
              </div>
            </div>
            <Link
              href={`/jobs/${encodeURIComponent(job.job_id)}/result`}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700"
            >
              결과 확인
            </Link>
          </div>
        )}

        {(job.status === "failed" || job.status === "fallback_review_required") && (
          <div
            className={`mt-5 flex flex-wrap items-start justify-between gap-4 rounded-xl border px-4 py-4 text-sm ${
              job.status === "failed"
                ? "border-rose-200 bg-rose-50 text-rose-800"
                : "border-amber-200 bg-amber-50 text-amber-900"
            }`}
          >
            <div className="flex items-start gap-3">
              {job.status === "failed" ? (
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0 text-rose-600" />
              ) : (
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
              )}
              <div>
                <p className="font-bold">
                  {job.status === "failed" ? "영상 생성에 실패했습니다" : "사용자 검토가 필요한 작업입니다"}
                </p>
                <p className="mt-1 text-xs leading-relaxed">
                  {job.error_message || "원본 PPTX 문서의 텍스트 또는 이미지를 확인한 뒤 다시 시도해 주세요."}
                </p>
                {job.error_code && (
                  <p className="mt-1 font-mono text-[11px] opacity-75">오류 코드: {job.error_code}</p>
                )}
              </div>
            </div>
            <Link
              href="/create"
              className="inline-flex items-center gap-1.5 rounded-xl bg-[#5b4ef5] px-4 py-2 text-xs font-semibold text-white hover:bg-[#4c3ee8]"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              다시 생성하기
            </Link>
          </div>
        )}
      </section>

      {/* 5단계 AI 처리 단계 스테퍼 (임의 % 미사용) */}
      <section className="rounded-2xl border border-[#e9e6f6] bg-white p-6 shadow-xs">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
              <Sparkles className="h-5 w-5 text-[#5b4ef5]" />
              AI 처리 단계
            </h3>
            <p className="mt-0.5 text-xs text-[#797496]">
              검증·품질 검사 결과에 따라 이전 단계가 자동 재실행될 수 있어, 현재 단계와 상태로 정확히 표시합니다.
            </p>
          </div>
          <span className="rounded-full bg-[#f3f1fc] px-3 py-1 text-xs font-semibold text-[#5b4ef5]">
            재시도 {job.retry_count} / {job.max_retries}
          </span>
        </div>

        <ol className="mt-5 space-y-3">
          {job.stages.map((st) => {
            const meta = STAGE_STATUS_TEXT[st.status];
            const isRunning = st.status === "running";
            return (
              <li
                key={st.stage}
                className={`flex items-center justify-between rounded-xl border px-4 py-3.5 transition-all ${
                  isRunning
                    ? "border-[#7c5cfc] bg-[#f7f4ff] shadow-xs"
                    : st.status === "completed"
                      ? "border-emerald-100 bg-emerald-50/40"
                      : st.status === "failed"
                        ? "border-rose-200 bg-rose-50/50"
                        : st.status === "review_required"
                          ? "border-amber-200 bg-amber-50/50"
                          : "border-[#eeebf8] bg-[#faf9fe]"
                }`}
              >
                <div className="flex items-center gap-3.5">
                  <span
                    className={`flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold ${
                      st.status === "completed"
                        ? "bg-emerald-500 text-white"
                        : isRunning
                          ? "bg-[#5b4ef5] text-white"
                          : st.status === "failed"
                            ? "bg-rose-500 text-white"
                            : st.status === "review_required"
                              ? "bg-amber-500 text-white"
                              : "bg-[#e7e4f5] text-[#756f94]"
                    }`}
                  >
                    {st.status === "completed" ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : isRunning ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      st.stage
                    )}
                  </span>
                  <div>
                    <p className="text-sm font-semibold text-[#1f1b3a]">
                      {st.stage}. {st.label}
                    </p>
                    {isRunning && job.current_node && (
                      <p className="text-xs text-[#695ec2]">실행 노드: {job.current_node}</p>
                    )}
                  </div>
                </div>
                <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${meta.badge}`}>
                  {meta.label}
                </span>
              </li>
            );
          })}
        </ol>

        {/* 상세 보기 (API-05 노드별 실행 기록 펼치기) */}
        <div className="mt-5 border-t border-[#efecf8] pt-4">
          <button
            type="button"
            onClick={() => setShowLogs((prev) => !prev)}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#5b4ef5] hover:underline"
          >
            {showLogs ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            {showLogs ? "상세 실행 기록 접기" : `상세 보기 (노드별 실행 기록 ${logs.length}건)`}
          </button>

          {showLogs && (
            <div className="mt-3 overflow-x-auto rounded-xl border border-[#ebe8f7]">
              {logs.length === 0 ? (
                <p className="p-4 text-xs text-[#7d7899]">아직 기록된 노드 실행 이벤트가 없습니다.</p>
              ) : (
                <table className="w-full text-left text-xs">
                  <thead className="bg-[#f7f6fc] text-[#686284]">
                    <tr>
                      <th className="px-3.5 py-2.5 font-semibold">노드</th>
                      <th className="px-3.5 py-2.5 font-semibold">상태</th>
                      <th className="px-3.5 py-2.5 font-semibold">재시도</th>
                      <th className="px-3.5 py-2.5 font-semibold">소요 시간</th>
                      <th className="px-3.5 py-2.5 font-semibold">메시지</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#f1eef9]">
                    {logs.map((lg, idx) => (
                      <tr key={`${lg.node_run_id || idx}-${idx}`} className="bg-white">
                        <td className="px-3.5 py-2.5 font-mono font-semibold text-[#29234a]">{lg.node_name}</td>
                        <td className="px-3.5 py-2.5">
                          <span className="rounded-md bg-[#f3f1fb] px-2 py-0.5 font-medium text-[#5246b5]">
                            {lg.status}
                          </span>
                        </td>
                        <td className="px-3.5 py-2.5 text-[#5c567a]">{lg.retry_count}</td>
                        <td className="px-3.5 py-2.5 text-[#5c567a]">
                          {lg.duration_sec !== null ? `${lg.duration_sec.toFixed(1)}초` : "-"}
                        </td>
                        <td className="px-3.5 py-2.5 text-[#5c567a]">{lg.message || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </section>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => loadData()}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-[#756f94] hover:text-[#5b4ef5]"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          상태 지금 새로고침
        </button>
      </div>
    </div>
  );
}
