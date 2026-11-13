# BeautyFlow — Root Agent Harness

## 1. Project Overview
화장품 상세페이지(7p PPTX/PDF 합성데이터)에서 텍스트·이미지를 추출해 핵심 특장점(USP)을 분석하고, 원본 근거 검증(Fact-Check)을 거쳐 **20~30초 분량의 9:16 영문 제품 소개 숏폼 영상(MP4)**을 자동 생성하는 AI Agent 시스템.

## 2. Tech Stack & Environment
- **Runtime**: Windows PowerShell, Python 3.11 (`.venv\Scripts\python.exe` 필수 사용, 전역 `pip install` 금지)
- **Core Stack**: FastAPI (단일 백엔드, 내부 LangGraph 통합), LangGraph, PyMuPDF / python-pptx / Unstructured, LLM, TTS API, FFmpeg, Next.js

## 3. Repository Map
- `data/`: 합성 원천데이터 7페이지 PPTX (`LUMIA.pptx` 쿠션, `SOLAIA.pptx` 선세럼, `DERMERA.pptx` 크림)
- `AI/`: 노트북(`AI/notebooks/MVP.ipynb`) 및 LangGraph 파이프라인 모듈 (**작업 시 `AI/AGENTS.md` 필독**)
- `Backend/`: FastAPI 서버 및 API 엔드포인트
- `Frontend/`: Next.js 웹 클라이언트
- `output/`: 추출된 이미지(`output/images/`), 파싱된 JSON, 최종 렌더링된 MP4 결과물

## 4. Global Guardrails (절대 준수 규칙)
1. **외부 쇼핑몰 크롤링 금지**: `global.amoremall.com` 등 실제 외부 사이트 크롤링·스크래핑 코드 작성 절대 금지(약관 제12조 위배). 반드시 `data/` 내 합성 문서(PPTX/PDF) 또는 자체 제작 가상 상세페이지만 입력으로 사용한다.
2. **Hallucination & 과장 광고 차단**: 원본 문서에 명시되지 않은 효능·성분·임상 수치를 생성하거나 과장하지 않는다 (미지원 주장 **0건** 필수).
3. **최종 영상 규격 고정**:
   - 화면 비율: `9:16` 세로형 (Instagram Reels / YouTube Shorts 규격, Safe Area 내 자막 배치)
   - 영상 길이: `20~30초`
   - 언어: **영어 내레이션(TTS) + 영어 자막** 고정
4. **카테고리 하드코딩 금지**: 특정 제품(쿠션 등)에만 동작하는 분기 로직 작성을 피하고, 쿠션·선세럼·크림 등 다양한 카테고리에 범용 동작하도록 설계한다.

## 5. Sub-Harness Pointers
- **AI 파이프라인 / 노트북 / 프롬프트 / 렌더링 작업 시**: 반드시 [`AI/AGENTS.md`](./AI/AGENTS.md)의 데이터 계약 및 LangGraph 노드 명세를 따른다.

