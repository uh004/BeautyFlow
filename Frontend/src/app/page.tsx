"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  Bell,
  CheckCircle2,
  ChevronRight,
  Clock,
  FileText,
  FolderKanban,
  Layers,
  Loader2,
  Play,
  RotateCcw,
  Sparkles,
  Zap,
} from "lucide-react";
import { JobThumbnail } from "@/components/JobThumbnail";
import { StatusBadge } from "@/components/StatusBadge";
import { fetchDashboardSummary, fetchJobs } from "@/lib/api";
import {
  formatDuration,
  formatFileSize,
  formatKSTDateTime,
  formatKSTTime,
  getJobDisplayName,
  getJobTargetHref,
} from "@/lib/format";
import type { DashboardSummary, JobListItem } from "@/types/job";

export default function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    try {
      const [sumData, listData] = await Promise.all([
        fetchDashboardSummary(),
        fetchJobs({ page: 1, limit: 5, sort: "created_at_desc" }),
      ]);
      setSummary(sumData);
      setRecentJobs(listData.items);
      setErrorMsg(null);
    } catch {
      setErrorMsg("Backend API(localhost:8000)에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  // 진행 중 작업이 있으면 4초마다 자동 갱신
  useEffect(() => {
    const hasActive = (summary?.queued_count || 0) + (summary?.running_count || 0) > 0;
    if (!hasActive) return;
    const t = setInterval(() => loadDashboard(), 4000);
    return () => clearInterval(t);
  }, [loadDashboard, summary]);

  const inProgressCount = (summary?.queued_count || 0) + (summary?.running_count || 0);
  const issueCount = (summary?.failed_count || 0) + (summary?.review_required_count || 0);

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_320px]">
      {/* 좌측 메인 영역 */}
      <div className="space-y-6">
        {/* 웰컴 히어로 배너 */}
        <section className="bf-hero-banner relative overflow-hidden rounded-2xl border border-[#dfd8fb] p-6 sm:p-7">
          <div className="max-w-lg">
            <p className="text-sm font-bold text-[#5b4ef5]">BeautyFlow에 오신 것을 환영합니다!</p>
            <h2 className="mt-1.5 text-xl font-extrabold leading-snug text-[#1f1b3a] sm:text-2xl">
              PPTX 업로드부터 AI 영상 생성,
              <br />
              검증, 다운로드까지 한 번에 관리
            </h2>
            <p className="mt-2.5 text-xs leading-relaxed text-[#57507d] sm:text-sm">
              화장품 상세페이지(PPTX)를 업로드하면 AI가 핵심 USP를 분석하고 원문 팩트체크를 거쳐 9:16 영문 숏폼을 자동으로 완성합니다.
            </p>
          </div>
          <div className="pointer-events-none absolute right-6 top-1/2 hidden -translate-y-1/2 items-center gap-3 md:flex">
            <div className="flex h-20 w-16 flex-col items-center justify-center rounded-2xl border border-violet-200 bg-white/90 shadow-sm">
              <span className="rounded bg-orange-500 px-1.5 py-0.5 text-[10px] font-bold text-white">PPTX</span>
              <FileText className="mt-1.5 h-6 w-6 text-violet-400" />
            </div>
            <ArrowRight className="h-5 w-5 text-violet-500" />
            <div className="flex h-20 w-28 flex-col items-center justify-center rounded-2xl bg-gradient-to-br from-[#5b4ef5] to-[#9874ff] text-white shadow-md">
              <Sparkles className="h-5 w-5" />
              <span className="mt-1 text-xs font-bold">AI 숏폼 영상</span>
            </div>
          </div>
        </section>

        {errorMsg && (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs font-medium text-rose-700">
            {errorMsg}
          </div>
        )}

        {/* 4개 작업 현황 KPI 카드 (클릭 시 상태 필터링된 생성 이력으로 이동) */}
        <section className="grid grid-cols-2 gap-3.5 sm:grid-cols-4">
          {[
            { href: "/projects", label: "전체 작업", count: summary?.total_count ?? 0, bg: "bg-[#f3f1ff] border-[#e2dcfb]", icon: Layers, iconCls: "text-[#5b4ef5]" },
            { href: "/projects?status=in_progress", label: "생성 중", count: inProgressCount, bg: "bg-[#eef5ff] border-[#d8e8ff]", icon: Loader2, iconCls: "text-blue-600" },
            { href: "/projects?status=completed", label: "완료", count: summary?.completed_count ?? 0, bg: "bg-[#edf9f2] border-[#d3f0df]", icon: CheckCircle2, iconCls: "text-emerald-600" },
            { href: "/projects?status=issue", label: "실패·검토", count: issueCount, bg: "bg-[#fff1f4] border-[#fcdce2]", icon: AlertCircle, iconCls: "text-rose-500" },
          ].map((card) => {
            const Icon = card.icon;
            return (
              <Link
                key={card.label}
                href={card.href}
                className={`rounded-2xl border p-4 transition-all hover:-translate-y-0.5 hover:shadow-xs ${card.bg}`}
              >
                <div className="flex items-center gap-2 text-xs font-semibold text-[#5a5478]">
                  <Icon className={`h-4 w-4 ${card.iconCls}`} />
                  {card.label}
                </div>
                <p className="mt-2.5 text-2xl font-extrabold text-[#1f1b3a]">
                  {card.count}
                  <span className="ml-0.5 text-sm font-semibold text-[#6e688c]">건</span>
                </p>
              </Link>
            );
          })}
        </section>

        {/* 최근 생성 작업 5건 */}
        <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
              <Clock className="h-4 w-4 text-[#5b4ef5]" />
              최근 작업
            </h3>
            <Link
              href="/projects"
              className="inline-flex items-center gap-1 text-xs font-semibold text-[#5b4ef5] hover:underline"
            >
              전체 보기
              <ChevronRight className="h-3.5 w-3.5" />
            </Link>
          </div>

          {loading ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-[#5b4ef5]" />
            </div>
          ) : recentJobs.length === 0 ? (
            <div className="mt-4 flex flex-col items-center justify-center rounded-xl border border-dashed border-[#ded9f4] bg-[#faf9fe] py-12 text-center">
              <Sparkles className="h-8 w-8 text-[#9689f7]" />
              <p className="mt-2.5 text-sm font-semibold text-[#2d2654]">아직 생성된 영상 작업이 없습니다.</p>
              <p className="mt-1 text-xs text-[#787296]">상단의 &apos;+ 새 영상 만들기&apos; 버튼으로 첫 PPTX를 업로드해 보세요.</p>
              <Link href="/create" className="bf-primary-btn mt-4 rounded-xl px-4 py-2 text-xs font-semibold text-white">
                + 새 영상 만들기
              </Link>
            </div>
          ) : (
            <div className="mt-4 divide-y divide-[#f1eef9]">
              {recentJobs.map((job) => {
                const title = getJobDisplayName(job.file_name, job.product_name);
                const href = getJobTargetHref(job.job_id, job.status);
                return (
                  <div
                    key={job.job_id}
                    className="flex flex-wrap items-center justify-between gap-3 py-3.5 first:pt-1 last:pb-1"
                  >
                    <Link href={href} className="flex min-w-0 flex-1 items-center gap-3.5 group">
                      <JobThumbnail src={job.thumbnail_url} alt={title} sizeClass="h-14 w-20" />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-bold text-[#1f1b3a] group-hover:text-[#5b4ef5]">{title}</p>
                        <p className="mt-0.5 text-xs text-[#807a9c]">
                          PPTX · {formatFileSize(job.file_size)} · {formatKSTDateTime(job.created_at)}
                        </p>
                      </div>
                    </Link>

                    <div className="flex items-center gap-3">
                      <StatusBadge status={job.status} />

                      {job.status === "completed" ? (
                        <>
                          <span className="hidden font-mono text-xs font-semibold text-[#5e587d] sm:inline">
                            {formatDuration(job.video_duration_sec)}
                          </span>
                          <Link
                            href={`/jobs/${encodeURIComponent(job.job_id)}/result`}
                            className="inline-flex items-center gap-1 rounded-lg border border-[#d6cff7] bg-white px-3 py-1.5 text-xs font-semibold text-[#4c3ce8] hover:bg-[#f4f1ff]"
                          >
                            <Play className="h-3 w-3 fill-current" />
                            결과 보기
                          </Link>
                        </>
                      ) : job.status === "running" || job.status === "queued" ? (
                        <Link
                          href={`/jobs/${encodeURIComponent(job.job_id)}`}
                          className="inline-flex items-center gap-1 rounded-lg bg-[#f3f0ff] px-3 py-1.5 text-xs font-semibold text-[#5342f0] hover:bg-[#e8e3ff]"
                        >
                          {job.current_stage > 0 ? `${job.current_stage}/5 단계` : "대기 중"}
                          <ChevronRight className="h-3.5 w-3.5" />
                        </Link>
                      ) : (
                        <Link
                          href={`/jobs/${encodeURIComponent(job.job_id)}`}
                          className="inline-flex items-center gap-1 rounded-lg border border-[#dcd8f0] bg-white px-3 py-1.5 text-xs font-semibold text-[#453f64] hover:bg-[#f7f6fc]"
                        >
                          <RotateCcw className="h-3 w-3" />
                          상세 확인
                        </Link>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* 우측 보조 사이드 컬럼 */}
      <aside className="space-y-5">
        {/* 빠른 시작 */}
        <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
          <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
            <Zap className="h-4 w-4 text-[#5b4ef5]" />
            빠른 시작
          </h3>
          <p className="mt-1 text-xs text-[#756f94]">지금 바로 영상을 만들거나 내 작업을 확인해 보세요.</p>

          <div className="mt-4 space-y-2.5">
            <Link
              href="/create"
              className="bf-cta-gradient flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-bold text-white transition-all"
            >
              <Play className="h-4 w-4 fill-current" />
              영상 생성
              <ChevronRight className="h-4 w-4" />
            </Link>
            <Link
              href="/projects"
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-[#dfd9f7] bg-[#f8f7fe] py-2.5 text-sm font-semibold text-[#3f3769] hover:bg-[#f0ecfd]"
            >
              <FolderKanban className="h-4 w-4 text-[#5b4ef5]" />
              내 작업 보기
              <ChevronRight className="h-4 w-4" />
            </Link>
          </div>
        </section>

        {/* 최근 활동 */}
        <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
              <Bell className="h-4 w-4 text-[#5b4ef5]" />
              최근 활동
            </h3>
            <Link href="/projects" className="text-xs font-semibold text-[#5b4ef5] hover:underline">
              전체 보기
            </Link>
          </div>

          {!summary || summary.recent_activities.length === 0 ? (
            <p className="mt-4 text-xs text-[#8a85a4]">최근 작업 활동 내역이 아직 없습니다.</p>
          ) : (
            <ul className="mt-4 space-y-3">
              {summary.recent_activities.map((act) => (
                <li key={act.job_id}>
                  <Link
                    href={getJobTargetHref(act.job_id, act.status)}
                    className="flex items-start justify-between gap-2 rounded-xl p-2 transition-colors hover:bg-[#f8f7fe]"
                  >
                    <div className="flex items-start gap-2.5 min-w-0">
                      {act.status === "completed" ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
                      ) : act.status === "failed" || act.status === "fallback_review_required" ? (
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-500" />
                      ) : (
                        <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-blue-500" />
                      )}
                      <div className="min-w-0">
                        <p className="truncate text-xs font-semibold text-[#231e42]">{act.message}</p>
                        <p className="mt-0.5 text-[11px] text-[#837da0]">
                          {act.title}
                          {act.video_duration_sec ? ` · ${formatDuration(act.video_duration_sec)}` : ""}
                        </p>
                      </div>
                    </div>
                    <span className="shrink-0 text-[11px] text-[#9690b2]">{formatKSTTime(act.created_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* 상태별 바로가기 */}
        <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
          <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
            <Layers className="h-4 w-4 text-[#5b4ef5]" />
            상태별 바로가기
          </h3>
          <p className="mt-1 text-xs text-[#756f94]">원하는 상태의 작업만 모아서 확인하세요.</p>

          <div className="mt-4 grid grid-cols-4 gap-2 text-center">
            {[
              { href: "/projects", label: "전체", count: summary?.total_count ?? 0, cls: "bg-[#f3f1ff] text-[#4c3ce8]" },
              { href: "/projects?status=in_progress", label: "생성 중", count: inProgressCount, cls: "bg-[#eef5ff] text-blue-600" },
              { href: "/projects?status=completed", label: "완료", count: summary?.completed_count ?? 0, cls: "bg-[#edf9f2] text-emerald-600" },
              { href: "/projects?status=issue", label: "실패", count: issueCount, cls: "bg-[#fff1f4] text-rose-600" },
            ].map((item) => (
              <Link
                key={item.label}
                href={item.href}
                className={`rounded-xl py-2.5 transition-transform hover:-translate-y-0.5 ${item.cls}`}
              >
                <p className="text-[11px] font-semibold opacity-85">{item.label}</p>
                <p className="mt-1 text-sm font-extrabold">{item.count}건</p>
              </Link>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}
