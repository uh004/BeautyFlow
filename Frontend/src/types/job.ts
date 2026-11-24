/** BeautyFlow Backend API (API-01 ~ API-08) TypeScript 타입 정의. */

export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "fallback_review_required";

export type StageStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "review_required";

export interface RecentActivityItem {
  job_id: string;
  title: string;
  status: JobStatus;
  message: string;
  video_duration_sec: number | null;
  created_at: string;
}

export interface DashboardSummary {
  total_count: number;
  queued_count: number;
  running_count: number;
  completed_count: number;
  failed_count: number;
  review_required_count: number;
  recent_activities: RecentActivityItem[];
}

export interface CreateJobResponse {
  job_id: string;
  file_name: string;
  status: JobStatus;
  created_at: string;
}

export interface JobListItem {
  job_id: string;
  file_name: string;
  file_size: number;
  product_name: string | null;
  status: JobStatus;
  current_node: string | null;
  current_stage: number;
  current_stage_label: string | null;
  retry_count: number;
  error_code: string | null;
  error_message: string | null;
  video_duration_sec: number | null;
  qa_passed: boolean | null;
  has_thumbnail: boolean;
  thumbnail_url: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface JobListResponse {
  items: JobListItem[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

export interface StageProgressItem {
  stage: number;
  label: string;
  status: StageStatus;
}

export interface JobStatusDetail {
  job_id: string;
  file_name: string;
  file_size: number;
  product_name: string | null;
  status: JobStatus;
  current_node: string | null;
  current_stage: number;
  current_stage_label: string | null;
  stages: StageProgressItem[];
  retry_count: number;
  max_retries: number;
  error_code: string | null;
  error_message: string | null;
  video_duration_sec: number | null;
  qa_passed: boolean | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  updated_at: string;
}

export interface NodeLogItem {
  node_run_id: string | null;
  node_name: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_sec: number | null;
  retry_count: number;
  message: string | null;
}

export interface JobLogsResponse {
  job_id: string;
  status: JobStatus;
  logs: NodeLogItem[];
}

export interface PublicUSPItem {
  usp_id: number;
  usp_type: string | null;
  title: string;
  description: string;
  source_slide_no: number;
  source_quote: string;
}

export interface PublicSceneItem {
  scene_no: number;
  purpose: string;
  badge_label: string;
  headline: string;
  narration: string;
  subtitle: string;
  motion_effect: string;
  duration_sec: number;
  start_sec: number;
  end_sec: number;
  usp_ids: number[];
  source_slide_nos: number[];
  image_url: string | null;
}

export interface VideoInfoSummary {
  duration_sec: number;
  resolution: string;
  fps: number;
  video_url: string;
  download_url: string;
  thumbnail_url: string | null;
}

export interface JobResultDetail {
  job_id: string;
  file_name: string;
  created_at: string;
  finished_at: string | null;
  product_info: {
    brand?: string;
    product_name?: string;
    category?: string;
    volume?: string | null;
    how_to_use?: string | null;
  };
  common_analysis: Record<
    string,
    { summary?: string | null; source_text_ids?: string[]; quotes?: string[] }
  >;
  usps: PublicUSPItem[];
  creative_direction: Record<string, string>;
  scenes: PublicSceneItem[];
  full_script: string;
  validation_result: {
    is_valid?: boolean;
    error_type?: string;
    unsupported_claims?: string[];
    feedback?: string;
  };
  code_checks: Record<string, string>;
  qa_result: {
    is_passed?: boolean;
    error_type?: string;
    video_duration_sec?: number;
    resolution?: string;
    details?: string;
  };
  qa_checks: Array<{ name: string; passed: boolean | null; details: unknown }>;
  video_info: VideoInfoSummary;
  elapsed_sec: number | null;
  estimated_cost_usd: number | null;
}
