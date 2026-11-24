"use client";

import { ChangeEvent, DragEvent, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock,
  FileText,
  Film,
  Globe,
  Info,
  Layers,
  Loader2,
  Music,
  Palette,
  Play,
  RefreshCw,
  Smartphone,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { APIRequestError, createVideoJob } from "@/lib/api";
import { formatFileSize } from "@/lib/format";

const MAX_MB = 200;
const MAX_BYTES = MAX_MB * 1024 * 1024;

export default function CreateVideoPage() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [duplicateJobId, setDuplicateJobId] = useState<string | null>(null);

  const acceptFile = (file: File | null | undefined) => {
    setErrorMsg(null);
    setDuplicateJobId(null);
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pptx")) {
      setErrorMsg("지원하지 않는 파일 형식입니다. PPTX 파일만 업로드할 수 있습니다.");
      return;
    }
    if (file.size <= 0) {
      setErrorMsg("비어 있는 파일입니다. 유효한 PPTX 파일을 선택해 주세요.");
      return;
    }
    if (file.size > MAX_BYTES) {
      setErrorMsg(`파일 크기가 허용 한도(${MAX_MB}MB)를 초과했습니다.`);
      return;
    }
    setSelectedFile(file);
  };

  const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    acceptFile(e.target.files?.[0]);
    e.target.value = "";
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(false);
    acceptFile(e.dataTransfer.files?.[0]);
  };

  const handleSubmit = async () => {
    if (!selectedFile || submitting) return;
    setSubmitting(true);
    setErrorMsg(null);
    setDuplicateJobId(null);
    try {
      const created = await createVideoJob(selectedFile);
      router.push(`/jobs/${encodeURIComponent(created.job_id)}`);
    } catch (err) {
      if (err instanceof APIRequestError) {
        setErrorMsg(err.message);
        if (err.errorCode === "DUPLICATE_ACTIVE_JOB" && err.jobId) {
          setDuplicateJobId(err.jobId);
        }
      } else {
        setErrorMsg("서버에 연결할 수 없습니다. Backend API 서버가 실행 중인지 확인해 주세요.");
      }
      setSubmitting(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_320px]">
      {/* 좌측 메인 컬럼 */}
      <div className="space-y-6">
        {/* 상단 배너 */}
        <section className="bf-hero-banner relative overflow-hidden rounded-2xl border border-[#dfd8fb] p-6">
          <div className="max-w-xl">
            <h2 className="text-lg font-bold leading-snug text-[#39299a] sm:text-xl">
              PPTX를 업로드하면,
              <br />
              AI가 뷰티 브랜드에 맞는 영상으로 만들어드려요.
            </h2>
            <p className="mt-2 text-sm text-[#574f7d]">
              제품 소개, 핵심 USP 추출, 원문 팩트체크까지 한 번의 업로드로 9:16 영문 숏폼 영상을 생성하세요.
            </p>
          </div>
          <div className="pointer-events-none absolute right-6 top-1/2 hidden -translate-y-1/2 items-center gap-3 md:flex">
            <div className="flex h-16 w-14 flex-col items-center justify-center rounded-xl bg-white/90 shadow-sm border border-violet-200">
              <span className="rounded bg-orange-500 px-1.5 py-0.5 text-[10px] font-bold text-white">PPTX</span>
              <FileText className="mt-1 h-5 w-5 text-violet-400" />
            </div>
            <ArrowRight className="h-5 w-5 text-violet-500" />
            <div className="flex h-16 w-24 flex-col items-center justify-center rounded-xl bg-gradient-to-br from-[#6d5dfc] to-[#9b7bfd] text-white shadow-md">
              <Sparkles className="h-5 w-5" />
              <span className="mt-1 text-[11px] font-semibold">9:16 MP4</span>
            </div>
          </div>
        </section>

        {/* 파일 업로드 카드 */}
        <section className="rounded-2xl border border-[#e9e6f6] bg-white p-6 shadow-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
              <UploadCloud className="h-5 w-5 text-[#5b4ef5]" />
              파일 업로드
            </h3>
            <span className="inline-flex items-center gap-1.5 text-xs text-[#6f6a89]">
              <Info className="h-3.5 w-3.5 text-[#7c5cfc]" />
              PPTX 파일만 업로드할 수 있습니다. (최대 {MAX_MB}MB)
            </span>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".pptx,application/vnd.openxmlformats-officedocument.presentationml.presentation"
            onChange={handleFileChange}
            className="hidden"
          />

          {/* 드래그 앤 드롭 존 */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`mt-4 flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-all ${
              isDragging
                ? "border-[#5b4ef5] bg-[#f1eeff]"
                : "border-[#d4cdf7] bg-[#f9f8fe] hover:border-[#8d7df8] hover:bg-[#f4f1ff]"
            }`}
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white text-[#6757f6] shadow-xs border border-[#e6e1fa]">
              <UploadCloud className="h-6 w-6" />
            </div>
            <p className="mt-3 text-sm font-medium text-[#2c2749]">파일을 여기로 드래그 앤 드롭하거나,</p>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                fileInputRef.current?.click();
              }}
              className="mt-3 inline-flex items-center gap-2 rounded-xl border border-[#cfc8f4] bg-white px-5 py-2 text-sm font-semibold text-[#4d3df0] shadow-xs hover:bg-[#f5f3ff]"
            >
              파일 선택
            </button>
            <p className="mt-3 text-xs text-[#8a85a4]">지원 형식: PPTX · 최대 용량: {MAX_MB}MB</p>
          </div>

          {/* 오류 배너 */}
          {errorMsg && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
              <span className="flex items-center gap-2">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {errorMsg}
              </span>
              {duplicateJobId && (
                <Link
                  href={`/jobs/${encodeURIComponent(duplicateJobId)}`}
                  className="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700"
                >
                  진행 현황 보기
                </Link>
              )}
            </div>
          )}

          {/* 선택된 파일 카드 */}
          {selectedFile && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50/70 px-4 py-3.5">
              <div className="flex items-center gap-3 min-w-0">
                <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-white border border-orange-200">
                  <span className="text-[10px] font-extrabold text-orange-600">PPTX</span>
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-[#1f1b3a]">{selectedFile.name}</p>
                  <p className="mt-0.5 flex items-center gap-2 text-xs text-[#64607d]">
                    <span>{formatFileSize(selectedFile.size)}</span>
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                      업로드 준비 완료
                    </span>
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={submitting}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#dad5f2] bg-white px-3 py-1.5 text-xs font-semibold text-[#3f3a60] hover:bg-[#f6f4ff]"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  변경
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedFile(null);
                    setErrorMsg(null);
                    setDuplicateJobId(null);
                  }}
                  disabled={submitting}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-50"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  제거
                </button>
              </div>
            </div>
          )}
        </section>

        {/* 입력 및 생성 조건 */}
        <section className="rounded-2xl border border-[#e9e6f6] bg-white p-6 shadow-xs">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-bold text-[#1f1b3a]">입력 및 생성 조건</h3>
            <span className="text-xs text-[#7a7496]">아래 조건으로 영상이 생성됩니다. (MVP 기본값)</span>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
            <div className="rounded-xl bg-[#f3f1ff] p-3.5 text-center">
              <FileText className="mx-auto h-5 w-5 text-[#5b4ef5]" />
              <p className="mt-1.5 text-xs text-[#6e698a]">입력 형식</p>
              <p className="mt-0.5 text-sm font-bold text-[#1f1b3a]">PPTX</p>
            </div>
            <div className="rounded-xl bg-[#eef5ff] p-3.5 text-center">
              <Film className="mx-auto h-5 w-5 text-blue-600" />
              <p className="mt-1.5 text-xs text-[#6e698a]">출력 형식</p>
              <p className="mt-0.5 text-sm font-bold text-[#1f1b3a]">MP4</p>
            </div>
            <div className="rounded-xl bg-[#edf9f2] p-3.5 text-center">
              <Smartphone className="mx-auto h-5 w-5 text-emerald-600" />
              <p className="mt-1.5 text-xs text-[#6e698a]">비율</p>
              <p className="mt-0.5 text-sm font-bold text-[#1f1b3a]">9:16</p>
            </div>
            <div className="rounded-xl bg-[#fff1f4] p-3.5 text-center">
              <Clock className="mx-auto h-5 w-5 text-rose-500" />
              <p className="mt-1.5 text-xs text-[#6e698a]">길이</p>
              <p className="mt-0.5 text-sm font-bold text-[#1f1b3a]">20~30초</p>
            </div>
            <div className="col-span-2 rounded-xl bg-[#f5f1ff] p-3.5 text-center sm:col-span-1">
              <Globe className="mx-auto h-5 w-5 text-violet-600" />
              <p className="mt-1.5 text-xs text-[#6e698a]">언어</p>
              <p className="mt-0.5 text-sm font-bold text-[#1f1b3a]">영어 내레이션·자막</p>
            </div>
          </div>

          {/* 하단 액션 버튼 */}
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 rounded-xl border border-[#dcd8f0] bg-white px-5 py-2.5 text-sm font-semibold text-[#4c476b] hover:bg-[#f7f6fc]"
            >
              <ArrowLeft className="h-4 w-4" />
              취소
            </Link>
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!selectedFile || submitting}
              className="bf-primary-btn inline-flex items-center gap-2 rounded-xl px-7 py-3 text-sm font-semibold text-white transition-all disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  작업 등록 중...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4 fill-current" />
                  영상 생성 시작
                </>
              )}
            </button>
          </div>
        </section>

        {/* 하단 진행 안내 바 */}
        <section className="rounded-2xl border border-[#e5e0fb] bg-[#f2efff] p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="shrink-0">
              <p className="text-sm font-bold text-[#3f319d]">영상 생성 시작 후 이렇게 진행돼요</p>
            </div>
            <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-3">
              {[
                { step: "1", title: "Job ID 생성", desc: "영상 작업이 DB에 등록돼요." },
                { step: "2", title: "AI 처리 시작", desc: "PPTX 분석·팩트체크·렌더링" },
                { step: "3", title: "작업 진행 현황 이동", desc: "5단계 상태를 실시간 확인해요." },
              ].map((s) => (
                <div key={s.step} className="rounded-xl bg-white/90 p-3 shadow-xs border border-[#e7e2fb]">
                  <p className="text-xs font-bold text-[#5b4ef5]">{s.step}. {s.title}</p>
                  <p className="mt-0.5 text-xs text-[#696485]">{s.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>

      {/* 우측 요약 사이드 카드 */}
      <aside className="space-y-5">
        <div className="rounded-2xl border border-[#e9e6f6] bg-white p-5 shadow-xs">
          <h3 className="flex items-center gap-2 text-base font-bold text-[#1f1b3a]">
            <Layers className="h-4 w-4 text-[#5b4ef5]" />
            생성 설정 요약
          </h3>
          <div className="mt-3 rounded-xl border border-[#e6e1fb] bg-[#f5f3ff] p-3 text-xs leading-relaxed text-[#554e7c]">
            현재 MVP에서는 아래 고정 규격으로 영문 제품 소개 숏폼이 생성됩니다.
          </div>

          <dl className="mt-4 divide-y divide-[#f1eef9] text-sm">
            {[
              { label: "입력 형식", value: "PPTX", icon: FileText },
              { label: "출력 형식", value: "MP4 (H.264/AAC)", icon: Film },
              { label: "화면 비율", value: "9:16 (1080×1920)", icon: Smartphone },
              { label: "영상 길이", value: "20~30초", icon: Clock },
              { label: "언어", value: "영어 내레이션·자막", icon: Globe },
            ].map((row) => {
              const Icon = row.icon;
              return (
                <div key={row.label} className="flex items-center justify-between py-3">
                  <dt className="flex items-center gap-2 text-[#6b6687]">
                    <Icon className="h-4 w-4 text-[#7c5cfc]" />
                    {row.label}
                  </dt>
                  <dd className="font-semibold text-[#1f1b3a]">{row.value}</dd>
                </div>
              );
            })}
          </dl>

          <div className="mt-5 border-t border-[#efecf8] pt-4">
            <p className="flex items-center gap-1.5 text-xs font-bold text-[#5d5584]">
              <Sparkles className="h-3.5 w-3.5 text-[#7c5cfc]" />
              추후 지원 예정 (MVP 이후)
            </p>
            <ul className="mt-3 space-y-2.5 text-xs text-[#736e8f]">
              {[
                { label: "브랜드 가이드 적용", icon: Palette },
                { label: "BGM 선택 및 볼륨 조절", icon: Music },
                { label: "언어 변경 (다국어 지원)", icon: Globe },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <li key={item.label} className="flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5 text-[#9892b4]" />
                      {item.label}
                    </span>
                    <span className="rounded-full bg-[#f3f1fa] px-2 py-0.5 text-[11px] font-medium text-[#8a85a4]">
                      추후 지원
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </aside>
    </div>
  );
}
