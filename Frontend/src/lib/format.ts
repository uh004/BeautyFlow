/** 날짜(KST 변환), 파일 크기, 영상 길이 및 경로 헬퍼. */

import type { JobStatus } from "@/types/job";

/** UTC ISO 문자열을 한국 시간(YYYY.MM.DD HH:mm)으로 변환한다. */
export function formatKSTDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const normalized = iso.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return "-";
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(d);
  const map = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${map.year}.${map.month}.${map.day} ${map.hour}:${map.minute}`;
}

/** UTC ISO 문자열을 한국 시간 시:분(HH:mm)으로 변환한다. */
export function formatKSTTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const normalized = iso.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

/** 상대 시간 표시 (방금 전 / 약 N분 전 / 약 N시간 전 / 약 N일 전). */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const normalized = iso.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const diffSec = Math.max(0, Math.floor((Date.now() - new Date(normalized).getTime()) / 1000));
  if (diffSec < 60) return "방금 전";
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `약 ${mins}분 전`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `약 ${hrs}시간 전`;
  return `약 ${Math.floor(hrs / 24)}일 전`;
}

/** 바이트 크기를 보기 쉬운 단위로 변환한다. */
export function formatFileSize(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return "-";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

/** 초 단위 길이를 MM:SS 포맷으로 변환한다. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "00:00";
  const total = Math.max(0, Math.round(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

/** 작업 상태에 따라 이동해야 할 상세 페이지 경로를 반환한다. */
export function getJobTargetHref(jobId: string, status: JobStatus): string {
  if (status === "completed") return `/jobs/${encodeURIComponent(jobId)}/result`;
  return `/jobs/${encodeURIComponent(jobId)}`;
}

/** 파일명에서 확장자를 제외한 표시용 작업명을 추출한다. */
export function getJobDisplayName(fileName: string, productName?: string | null): string {
  if (productName && productName.trim()) return productName.trim();
  return fileName.replace(/\.pptx$/i, "") || fileName;
}
