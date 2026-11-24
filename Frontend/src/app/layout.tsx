import type { Metadata } from "next";
import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "BeautyFlow — 화장품 상세페이지 AI 숏폼 영상 생성",
  description: "PPTX 업로드부터 AI USP 분석, 원문 팩트체크, 9:16 영문 숏폼 생성 및 다운로드까지",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
