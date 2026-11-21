"""LangGraph 8개 노드가 공유하는 State 및 서브 데이터 스키마."""

from __future__ import annotations

from typing import Any, List, Literal, Optional, TypedDict


class SlideData(TypedDict):
    """슬라이드(페이지)별 텍스트·이미지·위치 추출 데이터."""
    slide_no: int                           # 슬라이드 번호 (1~7)
    title: str                              # 대표 제목
    texts: List[str]                        # 본문 문단 리스트
    image_paths: List[str]                  # 추출 이미지 경로
    all_titles: List[str]                   # 제목 후보 목록
    body_paragraphs: List[str]              # 본문/리스트/표 텍스트
    elements: List[dict[str, Any]]          # Unstructured 원본 요소
    text_blocks: List[dict[str, Any]]       # 원문 및 EMU 좌표 [left, top, width, height]
    image_positions: List[dict[str, Any]]   # 이미지 경로 및 EMU 좌표


class ProductInfo(TypedDict):
    """제품 기본 식별 정보 (가격·리뷰·재고 제외)."""
    brand: str                              # 브랜드명 (예: LUMIA)
    product_name: str                       # 제품명 (예: Soft Satin Cushion)
    category: str                           # 카테고리 (예: Cushion, Sun Serum, Cream)
    volume: Optional[str]                   # 용량/구성
    how_to_use: Optional[str]               # 사용 방법 요약


class AnalysisDimensionSummary(TypedDict):
    """공통 5가지 제품 분석 관점 중 1개 항목의 근거 요약."""
    summary: Optional[str]                  # 원문 기반 요약 (문서에 없으면 None)
    source_text_ids: List[str]              # 근거 원문 ID (예: s2_t1)
    quotes: List[str]                       # 실제 원문 인용


class USPItem(TypedDict):
    """핵심 특장점(USP) 및 원본 근거·이미지 매핑 (중요도 1→3 순위)."""
    usp_id: int
    usp_type: Literal["result_finish", "texture_feel", "functional_benefit"]
    title: str
    description: str
    source_slide_no: int
    source_quote: str
    matched_image_path: str


class CreativeDirectionState(TypedDict):
    """영상 전체 비주얼 아이덴티티 및 내레이션 톤 (렌더링 지원 토큰 고정)."""
    concept: Literal["premium_editorial", "clean_fresh", "clinical_calm"]
    background_tone: Literal["deep_dark", "warm_neutral", "soft_light"]
    accent_color: Literal["champagne_gold", "soft_rose", "ice_blue", "warm_ivory", "charcoal_ink"]
    typography_style: Literal["editorial_serif", "clean_soft", "modern_sans"]
    motion_pacing: Literal["calm_elegant", "fresh_breezy", "steady_clean"]
    narration_tone: Literal["calm_refined", "bright_fresh", "warm_reassuring"]
    rationale: str


class SceneItem(TypedDict):
    """장면별 스토리보드 및 렌더링 명세."""
    scene_no: int
    purpose: str                            # hook, usp, how_to_use, outro
    image_path: str
    badge_label: str                        # 상단 역할 라벨 (메타데이터·브랜드명 보존)
    headline: str                           # 핵심 포인트 카피 (영어 2~5단어, 원문 근거 필수)
    narration: str                          # 영어 TTS 내레이션 문장
    subtitle: str                           # Safe Area 1줄 자막 원문
    motion_effect: str                      # zoom_in, zoom_out, pan_left, pan_right, static
    crop_focus: str                         # center, left, right, closeup
    duration_sec: float                     # 장면 길이(초) — TTS 실측 길이로 갱신
    audio_segment_path: Optional[str]       # 장면별 개별 WAV 경로
    usp_ids: List[int]
    source_text_ids: List[str]
    source_slide_nos: List[int]


class ValidationIssue(TypedDict):
    """ClaimValidator가 탐지한 단일 사실성·규칙 오류."""
    scene_no: Optional[int]
    usp_id: Optional[int]
    target_field: str
    claim: str
    source_text_ids: List[str]
    reason: str
    suggested_action: str
    error_type: Literal["script_error", "usp_error"]
    status: str


class ValidationResult(TypedDict):
    """ClaimValidator 검증 결과 (미지원 주장 0건일 때만 통과)."""
    is_valid: bool
    error_type: Literal["none", "script_error", "usp_error"]
    unsupported_claims: List[str]
    feedback: str
    issues: List[ValidationIssue]


class QAResult(TypedDict):
    """VideoQA 최종 MP4 품질 검사 결과."""
    is_passed: bool
    error_type: Literal["none", "render_error", "duration_error", "sync_error"]
    video_duration_sec: float
    resolution: str                         # 예: 1080x1920
    details: str


class VideoAgentState(TypedDict, total=False):
    """BeautyFlow LangGraph 8노드 공유 State."""
    # 1. 입력 및 문서 파싱 (DocumentParser)
    file_path: str
    output_dir: str
    bgm_path: Optional[str]                 # 선택적 로컬 BGM 경로
    brand_guide: Optional[dict[str, Any]]   # 선택적 공식 브랜드 가이드 (LLM 추론보다 우선)
    pipeline_json_path: Optional[str]
    raw_slides: List[SlideData]
    parsed_json_path: Optional[str]

    # 2. 제품 분석 및 USP 선정 (ProductAnalyzer)
    product_info: Optional[ProductInfo]
    common_analysis: Optional[dict[str, AnalysisDimensionSummary]]
    usps: List[USPItem]
    analysis_json_path: Optional[str]

    # 3. 영상 기획 및 대본 (ScriptGenerator & ScriptReviser)
    creative_direction: Optional[CreativeDirectionState]
    scenes: List[SceneItem]
    full_script: str
    script_json_path: Optional[str]
    revision_json_path: Optional[str]
    revision_history: List[dict[str, Any]]

    # 4. 정보 정확성 검증 (ClaimValidator)
    validation_result: ValidationResult
    validation_json_path: Optional[str]

    # 6. 음성 생성 (TTSGenerator)
    audio_path: str
    tts_duration_sec: float
    tts_json_path: Optional[str]

    # 7 & 8. 영상 렌더링 및 품질 검사 (VideoRenderer & VideoQA)
    video_path: str
    render_json_path: Optional[str]
    qa_result: QAResult
    qa_json_path: Optional[str]
    qa_next_node: Literal["END", "VideoRenderer", "ScriptReviser"]

    # 제어 및 안전장치 (Retry & Safety Valve)
    retry_count: int
    max_retries: int
    status: str                             # running, completed, failed, fallback_review_required
    error_message: Optional[str]
