"use client";

import { useState } from "react";
import { Sparkles } from "lucide-react";
import { getAssetUrl } from "@/lib/api";

interface JobThumbnailProps {
  src?: string | null;
  alt: string;
  sizeClass?: string;
}

/** 실제 추출 제품 이미지를 표시하고, 미추출·오류 시 라벤더 플레이스홀더로 안전 대체한다. */
export function JobThumbnail({ src, alt, sizeClass = "h-14 w-20" }: JobThumbnailProps) {
  const [failed, setFailed] = useState(false);
  const resolved = src ? getAssetUrl(src) : "";

  if (!resolved || failed) {
    return (
      <div
        className={`${sizeClass} flex shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-100 via-indigo-50 to-purple-100 text-violet-500 border border-violet-200/70`}
      >
        <Sparkles className="h-5 w-5" />
      </div>
    );
  }

  return (
    <img
      src={resolved}
      alt={alt}
      onError={() => setFailed(true)}
      className={`${sizeClass} shrink-0 rounded-xl object-cover border border-violet-100 bg-violet-50`}
    />
  );
}
