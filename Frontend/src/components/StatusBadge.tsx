"use client";

import { AlertCircle, CheckCircle2, Clock, Loader2, SearchCheck } from "lucide-react";
import type { JobStatus } from "@/types/job";

const STATUS_META: Record<
  JobStatus,
  { label: string; className: string; icon: "clock" | "spin" | "check" | "alert" | "review" }
> = {
  queued: {
    label: "대기 중",
    className: "bg-slate-100 text-slate-600 border border-slate-200",
    icon: "clock",
  },
  running: {
    label: "진행 중",
    className: "bg-blue-50 text-blue-600 border border-blue-200",
    icon: "spin",
  },
  completed: {
    label: "완료",
    className: "bg-emerald-50 text-emerald-600 border border-emerald-200",
    icon: "check",
  },
  failed: {
    label: "실패",
    className: "bg-rose-50 text-rose-600 border border-rose-200",
    icon: "alert",
  },
  fallback_review_required: {
    label: "검토 필요",
    className: "bg-amber-50 text-amber-700 border border-amber-200",
    icon: "review",
  },
};

export function StatusBadge({ status }: { status: JobStatus }) {
  const meta = STATUS_META[status] || STATUS_META.queued;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold whitespace-nowrap ${meta.className}`}
    >
      {meta.icon === "clock" && <Clock className="h-3.5 w-3.5" />}
      {meta.icon === "spin" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {meta.icon === "check" && <CheckCircle2 className="h-3.5 w-3.5" />}
      {meta.icon === "alert" && <AlertCircle className="h-3.5 w-3.5" />}
      {meta.icon === "review" && <SearchCheck className="h-3.5 w-3.5" />}
      {meta.label}
    </span>
  );
}
