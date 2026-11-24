"use client";

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  Layers,
  Loader2,
  Play,
  Plus,
  RotateCcw,
  Search,
  SearchCheck,
  Sparkles,
} from "lucide-react";
import { JobThumbnail } from "@/components/JobThumbnail";
import { StatusBadge } from "@/components/StatusBadge";
import { fetchDashboardSummary, fetchJobs, getAssetUrl } from "@/lib/api";
import {
  formatDuration,
  formatFileSize,
  formatKSTDateTime,
  formatRelativeTime,
  getJobDisplayName,
  getJobTargetHref,
} from "@/lib/format";
import type { DashboardSummary, JobListItem } from "@/types/job";

const FILTER_TABS = [
  { key: "all", label: "전체" },
  { key: "in_progress", label: "진행 중" },
  { key: "completed", label: "완료" },
  { key: "issue", label: "실패·검토 필요" },
];

function ProjectsContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const statusParam = searchParams.get("status") || "all";
  const searchParam = searchParams.get("search") || "";
  const pageParam = Math.max(1, Number(searchParams.get("page") || "1") || 1);

  const [searchInput, setSearchInput] = useState(searchParam);
  const [sort, setSort] = useState("created_at_desc");
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [items, setItems] = useState<JobListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    setSearchInput(searchParam);
  }, [searchParam]);

  const updateUrl = (next: { status?: string; search?: string; page?: number }) => {
    const qs = new URLSearchParams();
    const s = next.status ?? statusParam;
    const q = next.search ?? searchParam;
    const p = next.page ?? 1;
    if (s && s !== "all") qs.set("status", s);
    if (q.trim()) qs.set("search", q.trim());
    if (p > 1) qs.set("page", String(p));
    const query = qs.toString();
    router.push(`/projects${query ? `?${query}` : ""}`);
  };

  const loadList = useCallback(async () => {
    try {
      const [sumData, listData] = await Promise.all([
        fetchDashboardSummary(),
        fetchJobs({
          status: statusParam,
          search: searchParam || undefined,
          page: pageParam,
          limit: 8,
          sort,
        }),
      ]);
      setSummary(sumData);
      setItems(listData.items);
      setTotal(listData.total);
      setTotalPages(listData.total_pages);
      setErrorMsg(null);
    } catch {
      setErrorMsg("작업 목록을 불러오지 못했습니다. Backend 서버 연결을 확인해 주세요.");
    } finally {
      setLoading(false);
    }
  }, [pageParam, searchParam, sort, statusParam]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  // 진행 중 작업이 있으면 4초마다 자동 갱신
  useEffect(() => {
    const hasActive = items.some((it) => it.status === "queued" || it.status === "running");
    if (!hasActive) return;
    const t = setInterval(() => loadList(), 4000);
    return () => clearInterval(t);
  }, [items, loadList]);

  const handleSearchSubmit = (e: FormEvent) => {
    e.preventDefault();
    updateUrl({ search: searchInput, page: 1 });
  };

  const inProgressCount = (summary?.queued_count || 0) + (summary?.running_count || 0);
  const issueCount = (summary?.failed_count || 0) + (summary?.review_required_count || 0);

  return (
    <div className="space-y-6">
      {/* 상단 배너 */}
      <section className="bf-hero-banner flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[#dfd8fb] p-6">
        <div>
          <h2 className="text-lg font-bold text-[#2b2069] sm:text-xl">내가 생성한 영상들을 한눈에 관리하세요.</h2>
          <p className="mt-1 text-sm text-[#5c5482]">생성 상태 확인, 원문 검증 결과 보기, MP4 다운로드까지 한 곳에서 처리할 수 있습니다.</p>
        </div>
        <Link
          href="/create"
          className="bf-primary-btn inline-flex items-center gap-1.5 rounded-xl px-5 py-2.5 text-sm font-semibold text-white"
        >
          <Plus className="h-4 w-4" />
          새 영상 만들기
        </Link>
      </section>

      {/* 5개 파스텔 KPI 카드 */}
      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {[
          { key: "all", label: "전체 작업", count: summary?.total_count ?? 0, bg: "bg-[#f3f1ff] border-[#e2dcfb]", icon: Layers, iconCls: "text-[#5b4ef5]" },
          { key: "in_progress", label: "진행 중", count: inProgressCount, bg: "bg-[#eef5ff] border-[#d8e8ff]", icon: Loader2, iconCls: "text-blue-600" },
          { key: "completed", label: "완료", count: summary?.completed_count ?? 0, bg: "bg-[#edf9f2] border-[#d3f0df]", icon: CheckCircle2, iconCls: "text-emerald-600" },
          { key: "failed", label: "실패", count: summary?.failed_count ?? 0, bg: "bg-[#fff1f4] border-[#fcdce2]", icon: AlertCircle, iconCls: "text-rose-500" },
          { key: "fallback_review_required", label: "검토 필요", count: summary?.review_required_count ?? 0, bg: "bg-[#fff9eb] border-[#fae8be]", icon: SearchCheck, iconCls: "text-amber-600" },
        ].map((card) => {
          const Icon = card.icon;
          const active = statusParam === card.key;
          return (
            <button
              key={card.key}
              type="button"
              onClick={() => updateUrl({ status: card.key, page: 1 })}
              className={`rounded-2xl border p-4 text-left transition-all ${card.bg} ${
                active ? "ring-2 ring-[#5b4ef5]" : "hover:-translate-y-0.5 hover:shadow-xs"
              }`}
            >
              <div className="flex items-center gap-2 text-xs font-semibold text-[#5a5478]">
                <Icon className={`h-4 w-4 ${card.iconCls}`} />
                {card.label}
              </div>
              <p className="mt-2 text-2xl font-extrabold text-[#1f1b3a]">
                {card.count}
                <span className="ml-0.5 text-sm font-semibold text-[#6e688c]">건</span>
              </p>
            </button>
          );
        })}
      </section>

      {/* 필터 바 + 검색 + 정렬 */}
      <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            {FILTER_TABS.map((tab) => {
              const isSelected = statusParam === tab.key;
              const badgeCount =
                tab.key === "all"
                  ? summary?.total_count ?? 0
                  : tab.key === "in_progress"
                    ? inProgressCount
                    : tab.key === "completed"
                      ? summary?.completed_count ?? 0
                      : issueCount;
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => updateUrl({ status: tab.key, page: 1 })}
                  className={`rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all ${
                    isSelected
                      ? "bg-[#5b4ef5] text-white shadow-xs"
                      : "border border-[#e3dff4] bg-[#f8f7fc] text-[#5c567a] hover:bg-[#efecfb]"
                  }`}
                >
                  {tab.label} ({badgeCount})
                </button>
              );
            })}
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <form onSubmit={handleSearchSubmit} className="relative flex-1 sm:w-64 sm:flex-none">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#918ba9]" />
              <input
                type="text"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder="파일명, 제품명, 작업 ID 검색"
                className="w-full rounded-xl border border-[#e3dff4] bg-[#f8f7fc] py-2 pl-9 pr-3 text-xs text-[#251f47] placeholder:text-[#9893b0] focus:border-[#7c5cfc] focus:bg-white focus:outline-none"
              />
            </form>
            <select
              value={sort}
              onChange={(e) => setSort(e.target.value)}
              className="rounded-xl border border-[#e3dff4] bg-white px-3 py-2 text-xs font-semibold text-[#474166] focus:border-[#7c5cfc] focus:outline-none"
            >
              <option value="created_at_desc">최신순</option>
              <option value="created_at_asc">오래된순</option>
              <option value="updated_at_desc">최근 갱신순</option>
            </select>
          </div>
        </div>

        {errorMsg && (
          <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-xs text-rose-700">
            {errorMsg}
          </div>
        )}

        {/* 작업 목록 테이블 */}
        <div className="mt-5 overflow-x-auto">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-[#5b4ef5]" />
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-[#ded9f4] bg-[#faf9fe] py-14 text-center">
              <Sparkles className="h-8 w-8 text-[#9689f7]" />
              <p className="mt-3 text-sm font-semibold text-[#2d2654]">조건에 맞는 영상 작업이 없습니다.</p>
              <p className="mt-1 text-xs text-[#787296]">PPTX 파일을 업로드해 첫 번째 9:16 숏폼 영상을 만들어 보세요.</p>
              <Link href="/create" className="bf-primary-btn mt-4 rounded-xl px-4 py-2 text-xs font-semibold text-white">
                새 영상 만들기
              </Link>
            </div>
          ) : (
            <table className="w-full min-w-[780px] text-left">
              <thead>
                <tr className="border-b border-[#ece8f7] text-xs font-semibold text-[#777194]">
                  <th className="pb-3 pl-2">프로젝트명</th>
                  <th className="pb-3">요청 시간</th>
                  <th className="pb-3">상태</th>
                  <th className="pb-3">영상 길이 / 결과 정보</th>
                  <th className="pb-3 pr-2 text-right">작업</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#f2effa] text-sm">
                {items.map((job) => {
                  const title = getJobDisplayName(job.file_name, job.product_name);
                  const targetHref = getJobTargetHref(job.job_id, job.status);
                  return (
                    <tr key={job.job_id} className="group transition-colors hover:bg-[#faf9ff]">
                      <td className="py-3.5 pl-2">
                        <Link href={targetHref} className="flex items-center gap-3.5">
                          <JobThumbnail src={job.thumbnail_url} alt={title} sizeClass="h-12 w-16" />
                          <div className="min-w-0">
                            <p className="truncate font-bold text-[#1f1b3a] group-hover:text-[#5b4ef5]">{title}</p>
                            <p className="mt-0.5 text-xs text-[#807a9c]">
                              PPTX · {formatFileSize(job.file_size)} · <span className="font-mono">#{job.job_id}</span>
                            </p>
                          </div>
                        </Link>
                      </td>
                      <td className="py-3.5 text-xs text-[#4b456b]">
                        <p className="font-medium">{formatKSTDateTime(job.created_at)}</p>
                        <p className="mt-0.5 text-[#8a84a6]">({formatRelativeTime(job.created_at)})</p>
                      </td>
                      <td className="py-3.5">
                        <StatusBadge status={job.status} />
                      </td>
                      <td className="py-3.5 text-xs text-[#544e73]">
                        {job.status === "completed" ? (
                          <span className="font-semibold text-[#1f1b3a]">
                            {formatDuration(job.video_duration_sec)} · MP4 (9:16)
                          </span>
                        ) : job.status === "running" || job.status === "queued" ? (
                          <div>
                            <span className="font-semibold text-[#5b4ef5]">
                              {job.current_stage > 0 ? `${job.current_stage}/5 단계` : "대기 중"}
                            </span>
                            <p className="mt-0.5 text-[11px] text-[#7a7496]">
                              {job.current_stage_label || "실행 대기 중"}
                            </p>
                          </div>
                        ) : (
                          <div className="max-w-[230px]">
                            <p className="truncate font-medium text-rose-600">
                              {job.error_message || "오류가 발생했습니다."}
                            </p>
                            {job.error_code && (
                              <p className="mt-0.5 font-mono text-[11px] text-[#8a84a6]">코드: {job.error_code}</p>
                            )}
                          </div>
                        )}
                      </td>
                      <td className="py-3.5 pr-2 text-right">
                        <div className="inline-flex items-center justify-end gap-2">
                          {job.status === "completed" ? (
                            <>
                              <Link
                                href={`/jobs/${encodeURIComponent(job.job_id)}/result`}
                                className="inline-flex items-center gap-1 rounded-lg border border-[#d6cff7] bg-white px-3 py-1.5 text-xs font-semibold text-[#4c3ce8] hover:bg-[#f4f1ff]"
                              >
                                <Play className="h-3.5 w-3.5 fill-current" />
                                결과 보기
                              </Link>
                              <a
                                href={getAssetUrl(`/api/jobs/${encodeURIComponent(job.job_id)}/download`)}
                                download
                                className="inline-flex items-center gap-1 rounded-lg border border-[#dcd8f0] bg-white px-3 py-1.5 text-xs font-semibold text-[#453f64] hover:bg-[#f7f6fc]"
                              >
                                <Download className="h-3.5 w-3.5" />
                                다운로드
                              </a>
                            </>
                          ) : job.status === "running" || job.status === "queued" ? (
                            <Link
                              href={`/jobs/${encodeURIComponent(job.job_id)}`}
                              className="inline-flex items-center gap-1 rounded-lg border border-[#d6cff7] bg-white px-3 py-1.5 text-xs font-semibold text-[#4c3ce8] hover:bg-[#f4f1ff]"
                            >
                              <Play className="h-3.5 w-3.5" />
                              진행 보기
                            </Link>
                          ) : (
                            <>
                              <Link
                                href="/create"
                                className="inline-flex items-center gap-1 rounded-lg border border-[#dcd8f0] bg-white px-3 py-1.5 text-xs font-semibold text-[#453f64] hover:bg-[#f7f6fc]"
                              >
                                <RotateCcw className="h-3.5 w-3.5" />
                                다시 생성
                              </Link>
                              <Link
                                href={`/jobs/${encodeURIComponent(job.job_id)}`}
                                className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-100"
                              >
                                오류 확인
                              </Link>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* 페이지네이션 */}
        {total > 0 && (
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[#f0edf9] pt-4 text-xs text-[#736e91]">
            <span>
              총 <strong>{total}</strong>건 중 {(pageParam - 1) * 8 + 1}–{Math.min(pageParam * 8, total)}건 표시
            </span>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                disabled={pageParam <= 1}
                onClick={() => updateUrl({ page: pageParam - 1 })}
                className="rounded-lg border border-[#e3dff4] p-1.5 disabled:opacity-40 hover:bg-[#f5f3ff]"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <span className="rounded-lg bg-[#5b4ef5] px-3 py-1 font-bold text-white">
                {pageParam} / {totalPages}
              </span>
              <button
                type="button"
                disabled={pageParam >= totalPages}
                onClick={() => updateUrl({ page: pageParam + 1 })}
                className="rounded-lg border border-[#e3dff4] p-1.5 disabled:opacity-40 hover:bg-[#f5f3ff]"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[320px] items-center justify-center rounded-2xl border border-[#e9e6f6] bg-white">
          <Loader2 className="h-6 w-6 animate-spin text-[#5b4ef5]" />
        </div>
      }
    >
      <ProjectsContent />
    </Suspense>
  );
}
