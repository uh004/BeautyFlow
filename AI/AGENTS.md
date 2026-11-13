# BeautyFlow AI Pipeline Harness (`AI/`)

## 1. Input Data Contract (합성 상세페이지 추출 및 필터링)
- **원천 문서 구조**: 제품당 7페이지 비정형 PPTX/PDF (`P.01` 대표정보, `P.02` 특징/목적, `P.03` 피부표현/기능, `P.04` 제형/사용감, `P.05` 주요성분, `P.06` 사용방법, `P.07` 상세정보).
- **필드별 처리 규칙**:

| 구분 | 항목 | 처리 규칙 |
| :--- | :--- | :--- |
| **필수 (Required)** | 브랜드·제품명, 카테고리, 제품 이미지, USP(2~3개) | 반드시 추출. 각 USP는 **원본 근거 문구 및 인접 슬라이드 이미지**와 1:1 매핑 필수 |
| **권장 (Optional)** | 사용 방법(순서·도구), 용량·컬러, 주요 성분 | 장면 구성 및 제품 식별에 필요한 범위 내에서만 선별 반영 |
| **제외 (Excluded)** | 가격·할인율, 리뷰·평점, 재고·배송비 | 상세페이지에 존재하더라도 **영상 대본 및 스토리보드 생성 입력에서 제외** |

## 2. LangGraph 8-Node Contracts
모든 노드는 공유 `State`를 입출력으로 사용하며 단일 책임만 수행한다.

| 순서 | 노드명 | 핵심 역할 및 제약사항 |
| :---: | :--- | :--- |
| 1 | `DocumentParser` | PPTX/PDF 텍스트·이미지 추출 및 페이지별 위치·연관 관계 구조화 (`output/images/` 저장) |
| 2 | `ProductAnalyzer` | 제품 카테고리 식별 및 영상용 핵심 USP 2~3개 선정 + 원본 근거 문구·이미지 매핑 (근거 부족 특징 제외) |
| 3 | `ScriptGenerator` | 20~30초 영문 대본 및 스토리보드(장면별 매칭 이미지, 영어 내레이션, 영어 자막) 생성 |
| 4 | `ClaimValidator` | 원본 문서 대조 검증. 미지원 효능·성분·수치 및 과장 표현 검출. **대본 오류**와 **USP 근거 오류**를 구분 판정 |
| 5 | `ScriptReviser` | 검증 실패 문장 또는 길이 초과 대본만 핀포인트 수정 (검증 통과한 기존 문장은 유지) |
| 6 | `TTSGenerator` | 영문 TTS 오디오 생성 및 전체/장면별 실제 음성 길이(초) 측정 |
| 7 | `VideoRenderer` | FFmpeg 기반 제품 이미지 + TTS 음성 + 영어 자막 합성 (`9:16` 세로형 MP4 렌더링) |
| 8 | `VideoQA` | 영상 길이(20~30초), 해상도(`9:16`), MP4 재생 가능 여부, 음성·자막 싱크 및 이미지 누락 검사 |

## 3. Conditional Routing & Retry Policy
무한 루프 방지를 위해 모든 조건부 루프는 `State` 내 `retry_count`를 추적하며, **`max_retries`(기본 3회) 초과 시 즉시 중단 후 사용자 검토 요청(Fallback) 상태로 종료**한다.

- **정보 검증 통과**: `ClaimValidator` ➔ `TTSGenerator`
- **대본 오류 (원본 불일치/과장 표현)**: `ClaimValidator` ➔ `ScriptReviser` ➔ `ClaimValidator`
- **USP 근거 오류 (원본 근거 부족)**: `ClaimValidator` ➔ `ProductAnalyzer` ➔ `ScriptGenerator` ➔ `ClaimValidator`
- **음성 길이 초과 (> 30초)**: `TTSGenerator` ➔ `ScriptReviser`(대본 축약) ➔ `ClaimValidator` ➔ `TTSGenerator`
- **영상 렌더링/품질 오류**: `VideoQA` ➔ `VideoRenderer` ➔ `VideoQA`

## 4. Verification & Edge Case Checklist (PoC / MVP)
- **PoC (1종)**: 쿠션(`LUMIA.pptx`) 1종으로 End-to-End 파이프라인 및 아래 6대 예외 처리 동작 검증.
- **MVP (3종)**: 쿠션(`LUMIA`), 선세럼(`SOLAIA`), 크림(`DERMERA`) 3종을 제품별 코드 수정 없이 동일 Workflow로 처리 검증.
- **필수 예외 처리(Edge Cases)**:
  1. 잘못된 파일 경로/URL 입력 시 즉시 명확한 에러 메시지 반환
  2. 추출된 제품 이미지가 없거나 부족할 경우 영상 생성 중단 또는 대체 소재 요청
  3. USP 원본 근거 부족 시 근거가 확인된 항목만 사용하거나 생성 중단
  4. 대본에 원본에 없는 효능/수치 등장 시 `ClaimValidator`가 차단 및 수정 루프 실행
  5. TTS 오디오 길이가 30초 초과 시 대본 축약 후 재검증·재생성 루프 실행
  6. FFmpeg 렌더링 실패 시 에러 로깅 후 재시도 또는 안전 중단
- **성능 측정 로깅**: 필수 정보 추출 정확도(목표 100%), USP 근거 연결률(목표 100%), 미지원 주장 수(목표 0건), 영상 규격 준수 여부, 전체 실행 시간 및 API 호출 비용을 기록한다.

