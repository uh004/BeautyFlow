"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowLeft,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Copy,
  Download,
  FileText,
  FolderKanban,
  Loader2,
  MonitorSmartphone,
  Plus,
  ShieldCheck,
  Sparkles,
  Target,
} from "lucide-react";
import { JobThumbnail } from "@/components/JobThumbnail";
import { APIRequestError, fetchJobResult, getAssetUrl } from "@/lib/api";
import { formatDuration, formatKSTDateTime, getJobDisplayName } from "@/lib/format";
import type { JobResultDetail } from "@/types/job";

const USP_CARD_STYLES = [
  "bg-[#f3f0ff] border-[#e2dcff] text-[#4c3bd6]",
  "bg-[#eef5ff] border-[#d9e8ff] text-[#2b60c9]",
  "bg-[#f8f0ff] border-[#ead8ff] text-[#7e3bc9]",
];

const PURPOSE_LABELS: Record<string, string> = {
  hook: "오프닝 & 제품 소개",
  usp: "핵심 USP",
  how_to_use: "사용 방법",
  outro: "엔딩 & 브랜드 마무리",
};

export default function JobResultPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = use(params);
  const [result, setResult] = useState<JobResultDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [openUspIds, setOpenUspIds] = useState<Record<number, boolean>>({});
  const [openSection, setOpenSection] = useState<"quotes" | "validation" | "qa" | null>(null);
  const [bottomTab, setBottomTab] = useState<"scenes" | "script">("scenes");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const data = await fetchJobResult(jobId);
        if (active) setResult(data);
      } catch (err) {
        if (!active) return;
        if (err instanceof APIRequestError) {
          setErrorMsg(err.message);
        } else {
          setErrorMsg("영상 결과를 불러올 수 없습니다.");
        }
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [jobId]);

  const toggleUspQuote = (uspId: number) => {
    setOpenUspIds((prev) => ({ ...prev, [uspId]: !prev[uspId] }));
  };

  const handleCopyScript = async () => {
    if (!result?.full_script) return;
    await navigator.clipboard.writeText(result.full_script);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };

  if (loading) {
    return (
      <div className="flex min-h-[380px] flex-col items-center justify-center rounded-2xl border border-[#e9e6f6] bg-white p-10">
        <Loader2 className="h-8 w-8 animate-spin text-[#5b4ef5]" />
        <p className="mt-3 text-sm font-medium text-[#666086]">영상 결과와 검증 리포트를 불러오는 중입니다...</p>
      </div>
    );
  }

  if (errorMsg || !result) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-white p-8 text-center">
        <AlertCircle className="mx-auto h-10 w-10 text-rose-500" />
        <h2 className="mt-3 text-lg font-bold text-[#1f1b3a]">영상 결과를 조회할 수 없습니다</h2>
        <p className="mt-1 text-sm text-[#6b6687]">{errorMsg}</p>
        <div className="mt-5 flex justify-center gap-3">
          <Link
            href={`/jobs/${encodeURIComponent(jobId)}`}
            className="rounded-xl border border-[#dcd7f2] px-4 py-2 text-sm font-semibold text-[#3f3a60]"
          >
            진행 현황 보기
          </Link>
          <Link href="/projects" className="bf-primary-btn rounded-xl px-4 py-2 text-sm font-semibold text-white">
            내 작업으로
          </Link>
        </div>
      </div>
    );
  }

  const brand = result.product_info?.brand || "";
  const productName = result.product_info?.product_name || getJobDisplayName(result.file_name);
  const fullTitle = brand && !productName.toLowerCase().includes(brand.toLowerCase()) ? `${brand} ${productName}` : productName;
  const unsupportedCount = (result.validation_result?.unsupported_claims || []).length;
  const videoSrc = getAssetUrl(result.video_info.video_url);
  const downloadHref = getAssetUrl(result.video_info.download_url);
  const posterSrc = result.video_info.thumbnail_url ? getAssetUrl(result.video_info.thumbnail_url) : undefined;
  const targetSummary = result.common_analysis?.target_and_usage?.summary || result.product_info?.how_to_use || "원문 기반 제품 소개 및 사용 안내";
  const styleTokens = [
    result.creative_direction?.concept,
    result.creative_direction?.background_tone,
    result.creative_direction?.typography_style,
  ].filter(Boolean);

  return (
    <div className="space-y-6">
      {/* 상단 액션 바 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/projects"
          className="inline-flex items-center gap-1.5 rounded-xl border border-[#dcd7f2] bg-white px-4 py-2 text-sm font-semibold text-[#453f64] hover:bg-[#f7f6fc]"
        >
          <ArrowLeft className="h-4 w-4" />
          목록으로
        </Link>

        <div className="flex flex-wrap items-center gap-2.5">
          <a
            href={downloadHref}
            download
            className="bf-primary-btn inline-flex items-center gap-1.5 rounded-xl px-5 py-2.5 text-sm font-semibold text-white"
          >
            <Download className="h-4 w-4" />
            MP4 다운로드
          </a>
          <Link
            href="/create"
            className="inline-flex items-center gap-1.5 rounded-xl border border-[#dcd7f2] bg-white px-4 py-2.5 text-sm font-semibold text-[#3f3a60] hover:bg-[#f7f6fc]"
          >
            <Plus className="h-4 w-4" />
            새 영상 만들기
          </Link>
          <Link
            href="/projects"
            className="inline-flex items-center gap-1.5 rounded-xl border border-[#dcd7f2] bg-white px-4 py-2.5 text-sm font-semibold text-[#3f3a60] hover:bg-[#f7f6fc]"
          >
            <FolderKanban className="h-4 w-4" />
            내 작업으로
          </Link>
        </div>
      </div>

      {/* 상단 메인 2열: 좌측 9:16 영상 플레이어 + 우측 제품 정보/USP/검증 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[310px_1fr]">
        {/* 9:16 세로형 MP4 플레이어 */}
        <div className="flex flex-col items-center">
          <div className="w-full max-w-[310px] overflow-hidden rounded-2xl border border-[#ddd7f5] bg-[#141122] shadow-lg">
            <video
              src={videoSrc}
              poster={posterSrc}
              controls
              playsInline
              preload="metadata"
              className="aspect-[9/16] w-full bg-black object-contain"
            />
          </div>
          <p className="mt-2.5 text-xs text-[#7c7699]">
            {result.video_info.resolution} · {formatDuration(result.video_info.duration_sec)} · 영문 내레이션·자막
          </p>
        </div>

        {/* 우측 상세 패널 */}
        <div className="space-y-5">
          {/* 제품 헤더 카드 */}
          <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex items-center gap-4">
                <JobThumbnail src={result.video_info.thumbnail_url} alt={fullTitle} sizeClass="h-16 w-16" />
                <div>
                  <h2 className="text-xl font-bold text-[#1f1b3a]">{fullTitle}</h2>
                  <p className="mt-0.5 text-sm text-[#6b6687]">
                    {result.product_info?.category || "Cosmetics"}
                    {result.product_info?.volume ? ` · ${result.product_info.volume}` : ""}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[#756f94]">
                    <span className="inline-flex items-center gap-1">
                      <MonitorSmartphone className="h-3.5 w-3.5 text-[#7c5cfc]" />
                      {result.video_info.resolution} (세로 9:16)
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5 text-[#7c5cfc]" />
                      {formatDuration(result.video_info.duration_sec)} ({result.video_info.duration_sec}s)
                    </span>
                    <span className="inline-flex items-center gap-1">
                      <Calendar className="h-3.5 w-3.5 text-[#7c5cfc]" />
                      {formatKSTDateTime(result.finished_at || result.created_at)}
                    </span>
                  </div>
                </div>
              </div>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1 text-xs font-bold text-emerald-700">
                <CheckCircle2 className="h-3.5 w-3.5" />
                완료
              </span>
            </div>
          </section>

          {/* USP 요약 카드 2~3개 + 개별 근거 보기 */}
          <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
                <Sparkles className="h-4 w-4 text-[#5b4ef5]" />
                USP 요약 (핵심 특장점 {result.usps.length}건)
              </h3>
              <span className="text-xs text-[#847ea1]">중요도 순위 · 원문 인용 기반</span>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
              {result.usps.map((usp, idx) => {
                const style = USP_CARD_STYLES[idx % USP_CARD_STYLES.length];
                const isOpen = !!openUspIds[usp.usp_id];
                return (
                  <div key={usp.usp_id} className={`flex flex-col justify-between rounded-xl border p-4 ${style}`}>
                    <div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-bold uppercase tracking-wide opacity-80">
                          POINT 0{usp.usp_id}
                        </span>
                        <span className="rounded-full bg-white/80 px-2 py-0.5 text-[10px] font-semibold">
                          Slide {usp.source_slide_no}
                        </span>
                      </div>
                      <h4 className="mt-1.5 text-sm font-bold text-[#1f1b3a]">{usp.title}</h4>
                      <p className="mt-1 text-xs leading-relaxed text-[#575276]">{usp.description}</p>
                    </div>

                    <div className="mt-3 border-t border-black/5 pt-2.5">
                      <button
                        type="button"
                        onClick={() => toggleUspQuote(usp.usp_id)}
                        className="inline-flex items-center gap-1 text-xs font-semibold hover:underline"
                      >
                        {isOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
                        {isOpen ? "근거 닫기" : "근거 보기"}
                      </button>
                      {isOpen && (
                        <blockquote className="mt-2 rounded-lg bg-white/90 p-2.5 text-[11px] leading-relaxed text-[#3f3a60] border border-white">
                          “{usp.source_quote}”
                        </blockquote>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* 검증 및 품질 결과 아코디언 */}
          <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
            <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
              <ShieldCheck className="h-5 w-5 text-[#5b4ef5]" />
              검증 및 품질 결과
            </h3>

            <div className="mt-3 divide-y divide-[#efecf8] rounded-xl border border-[#eeebf8]">
              {/* 1) 원문 근거 보기 */}
              <div>
                <button
                  type="button"
                  onClick={() => setOpenSection(openSection === "quotes" ? null : "quotes")}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left hover:bg-[#faf9fe]"
                >
                  <div className="flex items-center gap-3">
                    <FileText className="h-4 w-4 text-[#5b4ef5]" />
                    <div>
                      <p className="text-sm font-semibold text-[#1f1b3a]">원문 근거 보기</p>
                      <p className="text-xs text-[#736e91]">영상에 사용된 USP와 원본 PPTX 슬라이드 인용 문구를 확인하세요.</p>
                    </div>
                  </div>
                  {openSection === "quotes" ? <ChevronUp className="h-4 w-4 text-[#7c769a]" /> : <ChevronDown className="h-4 w-4 text-[#7c769a]" />}
                </button>
                {openSection === "quotes" && (
                  <div className="space-y-2 border-t border-[#f1eef9] bg-[#faf9fe] px-4 py-3 text-xs">
                    {result.usps.map((u) => (
                      <div key={u.usp_id} className="rounded-lg bg-white p-3 border border-[#eae6f7]">
                        <p className="font-semibold text-[#2a2352]">
                          [Slide {u.source_slide_no}] {u.title}
                        </p>
                        <p className="mt-1 text-[#5c567a]">“{u.source_quote}”</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 2) 정보 검증 결과 */}
              <div>
                <button
                  type="button"
                  onClick={() => setOpenSection(openSection === "validation" ? null : "validation")}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left hover:bg-[#faf9fe]"
                >
                  <div className="flex items-center gap-3">
                    <ShieldCheck className="h-4 w-4 text-emerald-600" />
                    <div>
                      <p className="text-sm font-semibold text-[#1f1b3a]">정보 검증 결과</p>
                      <p className="text-xs text-[#736e91]">
                        미지원 주장 <strong>{unsupportedCount}건</strong> · 원문 대비 사실성·수치·규제 검증 완료
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700 border border-emerald-200">
                      {result.validation_result?.is_valid ? "검증 완료" : "확인 필요"}
                    </span>
                    {openSection === "validation" ? <ChevronUp className="h-4 w-4 text-[#7c769a]" /> : <ChevronDown className="h-4 w-4 text-[#7c769a]" />}
                  </div>
                </button>
                {openSection === "validation" && (
                  <div className="border-t border-[#f1eef9] bg-[#faf9fe] px-4 py-3 text-xs space-y-2">
                    <p className="text-[#453f64]">{result.validation_result?.feedback || "미지원 주장이 발견되지 않았습니다."}</p>
                    {Object.keys(result.code_checks || {}).length > 0 && (
                      <div className="flex flex-wrap gap-2 pt-1">
                        {Object.entries(result.code_checks).map(([k, v]) => (
                          <span key={k} className="rounded-lg bg-white px-2.5 py-1 border border-[#e6e1f7] font-mono text-[11px] text-[#4b446c]">
                            {k}: <strong className={v === "passed" ? "text-emerald-600" : "text-slate-500"}>{v}</strong>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* 3) 영상 QA 결과 */}
              <div>
                <button
                  type="button"
                  onClick={() => setOpenSection(openSection === "qa" ? null : "qa")}
                  className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left hover:bg-[#faf9fe]"
                >
                  <div className="flex items-center gap-3">
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                    <div>
                      <p className="text-sm font-semibold text-[#1f1b3a]">영상 QA 결과</p>
                      <p className="text-xs text-[#736e91]">해상도, 길이(20~30초), 1줄 자막, 오디오 싱크 자동 품질 검사</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700 border border-emerald-200">
                      {result.qa_result?.is_passed ? "QA 통과" : "미통과"}
                    </span>
                    {openSection === "qa" ? <ChevronUp className="h-4 w-4 text-[#7c769a]" /> : <ChevronDown className="h-4 w-4 text-[#7c769a]" />}
                  </div>
                </button>
                {openSection === "qa" && (
                  <div className="border-t border-[#f1eef9] bg-[#faf9fe] px-4 py-3 text-xs space-y-2">
                    <p className="text-[#453f64]">{result.qa_result?.details}</p>
                    <div className="flex flex-wrap gap-2">
                      {result.qa_checks.slice(0, 12).map((chk, idx) => (
                        <span key={`${chk.name}-${idx}`} className="rounded-lg bg-white px-2.5 py-1 border border-[#e6e1f7] font-mono text-[11px]">
                          {chk.name}:{" "}
                          <strong className={chk.passed === false ? "text-rose-600" : "text-emerald-600"}>
                            {chk.passed === false ? "FAIL" : "PASS"}
                          </strong>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* 하단 2열: 씬(장면) 요약 / 스크립트 요약 + 영상 한눈에 보기 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
        {/* 좌측 탭 카드 */}
        <section className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
          <div className="inline-flex rounded-xl bg-[#f3f1fb] p-1">
            <button
              type="button"
              onClick={() => setBottomTab("scenes")}
              className={`rounded-lg px-4 py-2 text-xs font-bold transition-all ${
                bottomTab === "scenes" ? "bg-[#5b4ef5] text-white shadow-xs" : "text-[#635e82] hover:text-[#1f1b3a]"
              }`}
            >
              씬(장면) 요약 ({result.scenes.length})
            </button>
            <button
              type="button"
              onClick={() => setBottomTab("script")}
              className={`rounded-lg px-4 py-2 text-xs font-bold transition-all ${
                bottomTab === "script" ? "bg-[#5b4ef5] text-white shadow-xs" : "text-[#635e82] hover:text-[#1f1b3a]"
              }`}
            >
              스크립트 요약
            </button>
          </div>

          {bottomTab === "scenes" ? (
            <div className="mt-4 divide-y divide-[#f1eef9]">
              {result.scenes.map((sc) => (
                <div key={sc.scene_no} className="flex items-start gap-3.5 py-3.5 first:pt-1 last:pb-1">
                  <JobThumbnail src={sc.image_url} alt={`Scene ${sc.scene_no}`} sizeClass="h-14 w-20" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-md bg-[#ede9ff] px-2 py-0.5 text-[11px] font-bold text-[#5342f0]">
                        {String(sc.scene_no).padStart(2, "0")}
                      </span>
                      <span className="font-mono text-xs text-[#7c769a]">
                        {formatDuration(sc.start_sec)} – {formatDuration(sc.end_sec)}
                      </span>
                      <span className="text-xs font-semibold text-[#5b4ef5]">
                        {PURPOSE_LABELS[sc.purpose] || sc.purpose}
                      </span>
                    </div>
                    <p className="mt-1 text-sm font-bold text-[#1f1b3a]">{sc.headline || sc.badge_label}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-[#5e587d]">{sc.narration}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-[#eae6f8] bg-[#faf9fe] p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-[#4e4577]">전체 영문 내레이션 스크립트</span>
                <button
                  type="button"
                  onClick={handleCopyScript}
                  className="inline-flex items-center gap-1 rounded-lg border border-[#dad5f2] bg-white px-3 py-1 text-xs font-semibold text-[#4c42a8] hover:bg-[#f4f1ff]"
                >
                  <Copy className="h-3.5 w-3.5" />
                  {copied ? "복사 완료" : "복사"}
                </button>
              </div>
              <p className="mt-3 text-sm leading-7 text-[#251f47]">{result.full_script}</p>
            </div>
          )}
        </section>

        {/* 우측: 영상 한눈에 보기 */}
        <aside className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
          <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
            <Target className="h-4 w-4 text-[#5b4ef5]" />
            영상 한눈에 보기
          </h3>
          <div className="mt-3 rounded-xl border border-[#e6e0fb] bg-[#f5f2ff] p-3.5 text-xs leading-relaxed text-[#453d6c]">
            <strong>{fullTitle}</strong>의 핵심 특장점 {result.usps.length}가지를{" "}
            <strong>{Math.round(result.video_info.duration_sec)}초</strong> 세로형 영문 숏폼으로 구성한 제품 소개 영상입니다.
          </div>

          <dl className="mt-4 space-y-3 text-xs">
            <div className="flex justify-between gap-3">
              <dt className="shrink-0 text-[#7c769a]">카테고리</dt>
              <dd className="text-right font-semibold text-[#1f1b3a]">{result.product_info?.category || "-"}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="shrink-0 text-[#7c769a]">타깃·사용법</dt>
              <dd className="text-right font-medium text-[#3c365c]">{targetSummary}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="shrink-0 text-[#7c769a]">영상 스타일</dt>
              <dd className="flex flex-wrap justify-end gap-1">
                {styleTokens.length > 0 ? (
                  styleTokens.map((t) => (
                    <span key={t} className="rounded-full bg-[#f1eeff] px-2 py-0.5 text-[11px] font-semibold text-[#5b4ef5]">
                      #{t}
                    </span>
                  ))
                ) : (
                  <span>-</span>
                )}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="shrink-0 text-[#7c769a]">영상 길이</dt>
              <dd className="font-semibold text-[#1f1b3a]">{formatDuration(result.video_info.duration_sec)}</dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="shrink-0 text-[#7c769a]">해상도 / 비율</dt>
              <dd className="font-semibold text-[#1f1b3a]">{result.video_info.resolution} (9:16)</dd>
            </div>
            {result.elapsed_sec !== null && (
              <div className="flex justify-between gap-3">
                <dt className="shrink-0 text-[#7c769a]">생성 소요 시간</dt>
                <dd className="font-semibold text-[#1f1b3a]">{result.elapsed_sec.toFixed(1)}초</dd>
              </div>
            )}
          </dl>
        </aside>
      </div>
    </div>
  );
}
