"use client";

import { FormEvent, ReactNode, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  FolderKanban,
  Home,
  Play,
  Plus,
  Search,
  Settings,
  Video,
} from "lucide-react";

const PAGE_TITLES: Array<{ match: (p: string) => boolean; title: string }> = [
  { match: (p) => p === "/", title: "대시보드" },
  { match: (p) => p.startsWith("/create"), title: "영상 생성" },
  { match: (p) => p.startsWith("/projects"), title: "생성 이력 관리" },
  { match: (p) => p.includes("/result"), title: "영상 결과 상세" },
  { match: (p) => p.startsWith("/jobs/"), title: "작업 진행 현황" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");

  const currentTitle =
    PAGE_TITLES.find((item) => item.match(pathname))?.title || "BeautyFlow";

  const handleGlobalSearch = (e: FormEvent) => {
    e.preventDefault();
    const q = searchQuery.trim();
    router.push(q ? `/projects?search=${encodeURIComponent(q)}` : "/projects");
  };

  const navItems = [
    { href: "/", label: "대시보드", icon: Home, active: pathname === "/" },
    { href: "/create", label: "영상 생성", icon: Video, active: pathname.startsWith("/create") },
    {
      href: "/projects",
      label: "생성 이력 관리",
      icon: FolderKanban,
      active: pathname.startsWith("/projects") || pathname.startsWith("/jobs/"),
    },
  ];

  return (
    <div className="flex min-h-screen bg-[#f6f5fc] text-[#1f1b3a]">
      {/* 좌측 사이드바 */}
      <aside className="bf-sidebar-bg hidden w-60 shrink-0 flex-col border-r border-[#e9e6f6] md:flex">
        <div className="flex h-16 items-center gap-2.5 px-6">
          <Link href="/" className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-[#5b4ef5] via-[#7c5cfc] to-[#a78bfa] text-white shadow-md">
              <Play className="h-4 w-4 fill-current" />
            </span>
            <span className="text-xl font-bold tracking-tight text-[#251f47]">BeautyFlow</span>
          </Link>
        </div>

        <nav className="mt-4 flex flex-1 flex-col gap-1.5 px-3">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-all ${
                  item.active
                    ? "bg-[#ece8ff] font-semibold text-[#5542f6] shadow-xs"
                    : "text-[#4e496a] hover:bg-white/80 hover:text-[#251f47]"
                }`}
              >
                <Icon className={`h-[18px] w-[18px] ${item.active ? "text-[#5542f6]" : "text-[#7a7496]"}`} />
                <span>{item.label}</span>
              </Link>
            );
          })}

          {/* 설정 (추후 확장 비활성 메뉴) */}
          <div
            title="초기 MVP에서는 기본 고정 옵션을 사용합니다"
            className="mt-1 flex cursor-not-allowed items-center justify-between rounded-xl px-4 py-3 text-sm font-medium text-[#9893b0]"
          >
            <span className="flex items-center gap-3">
              <Settings className="h-[18px] w-[18px]" />
              <span>설정</span>
            </span>
            <span className="rounded-full bg-[#eceaf7] px-2 py-0.5 text-[11px] font-semibold text-[#7a7496]">
              추후
            </span>
          </div>
        </nav>

        <div className="p-4">
          <div className="rounded-2xl border border-[#e6e1f9] bg-white/75 p-3.5 text-xs text-[#676186] backdrop-blur-sm">
            <p className="font-semibold text-[#3f3769]">BeautyFlow AI v2.3</p>
            <p className="mt-1 leading-relaxed">9:16 · 20~30초 영문 숏폼 자동 생성 및 원문 팩트체크</p>
          </div>
        </div>
      </aside>

      {/* 우측 메인 영역 */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* 상단 헤더 */}
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-[#e9e6f6] bg-white/85 px-6 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2 md:hidden">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#5b4ef5] text-white">
                <Play className="h-3.5 w-3.5 fill-current" />
              </span>
            </Link>
            <h1 className="text-lg font-bold tracking-tight text-[#1f1b3a] sm:text-xl">{currentTitle}</h1>
          </div>

          <form onSubmit={handleGlobalSearch} className="hidden max-w-md flex-1 sm:block">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#918ba9]" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="프로젝트명, 파일명, 작업 ID로 검색하세요."
                className="w-full rounded-xl border border-[#e5e2f3] bg-[#f8f7fc] py-2 pl-10 pr-4 text-sm text-[#262145] placeholder:text-[#9893b0] focus:border-[#7c5cfc] focus:bg-white focus:outline-none"
              />
            </div>
          </form>

          <Link
            href="/create"
            className="bf-primary-btn inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-all"
          >
            <Plus className="h-4 w-4" />
            <span>새 영상 만들기</span>
          </Link>
        </header>

        {/* 페이지 콘텐츠 */}
        <main className="mx-auto w-full max-w-[1360px] flex-1 p-5 sm:p-7">{children}</main>
      </div>
    </div>
  );
}
