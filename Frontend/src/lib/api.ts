/** BeautyFlow Backend REST API (API-01 ~ API-08) 클라이언트. */

import type {
  CreateJobResponse,
  DashboardSummary,
  JobListResponse,
  JobLogsResponse,
  JobResultDetail,
  JobStatusDetail,
} from "@/types/job";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/+$/, "") || "http://localhost:8000";

export class APIRequestError extends Error {
  status: number;
  errorCode: string;
  jobId: string | null;

  constructor(status: number, errorCode: string, message: string, jobId: string | null = null) {
    super(message);
    this.status = status;
    this.errorCode = errorCode;
    this.jobId = jobId;
  }
}

export function getAssetUrl(path: string | null | undefined): string {
  if (!path) return "";
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    cache: "no-store",
  });
  if (!res.ok) {
    let errorCode = "REQUEST_FAILED";
    let message = `요청 처리 중 오류가 발생했습니다. (HTTP ${res.status})`;
    let jobId: string | null = null;
    try {
      const body = await res.json();
      if (body?.error_code) errorCode = body.error_code;
      if (body?.message) message = body.message;
      if (body?.job_id) jobId = body.job_id;
    } catch {
      // JSON 본문이 없는 오류는 기본 메시지 유지
    }
    throw new APIRequestError(res.status, errorCode, message, jobId);
  }
  return (await res.json()) as T;
}

/** API-01: 대시보드 현황 통계 및 최근 활동 조회. */
export function fetchDashboardSummary(): Promise<DashboardSummary> {
  return requestJson<DashboardSummary>("/api/dashboard/summary");
}

/** API-02: PPTX 파일 업로드 및 영상 생성 작업 등록. */
export function createVideoJob(file: File): Promise<CreateJobResponse> {
  const form = new FormData();
  form.append("file", file);
  return requestJson<CreateJobResponse>("/api/jobs", {
    method: "POST",
    body: form,
  });
}

/** API-03: 작업 목록 · 검색 · 필터 · 페이지네이션 조회. */
export function fetchJobs(params?: {
  search?: string;
  status?: string;
  page?: number;
  limit?: number;
  sort?: string;
}): Promise<JobListResponse> {
  const qs = new URLSearchParams();
  if (params?.search) qs.set("search", params.search);
  if (params?.status && params.status !== "all") qs.set("status", params.status);
  if (params?.page) qs.set("page", String(params.page));
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.sort) qs.set("sort", params.sort);
  const query = qs.toString();
  return requestJson<JobListResponse>(`/api/jobs${query ? `?${query}` : ""}`);
}

/** API-04: 특정 작업 진행 상태 조회 (Polling). */
export function fetchJobStatus(jobId: string): Promise<JobStatusDetail> {
  return requestJson<JobStatusDetail>(`/api/jobs/${encodeURIComponent(jobId)}`);
}

/** API-05: AI 노드별 실행 기록 조회. */
export function fetchJobLogs(jobId: string): Promise<JobLogsResponse> {
  return requestJson<JobLogsResponse>(`/api/jobs/${encodeURIComponent(jobId)}/logs`);
}

/** API-06: 완료된 작업의 영상 생성 및 검증 결과 조회. */
export function fetchJobResult(jobId: string): Promise<JobResultDetail> {
  return requestJson<JobResultDetail>(`/api/jobs/${encodeURIComponent(jobId)}/result`);
}
