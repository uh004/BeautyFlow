"""⑦ 영상 합성 노드 (VideoRenderer v2.3 미니멀 9:16).

비주얼 아이덴티티(배경 3종·글꼴 3종·포인트 색 5종·모션 템포 3종)를 반영해
상단 헤드라인 + 64px 포인트 선 + 라운드 히어로 카드 + 하단 1줄 중앙 자막의
1080×1920 30fps MP4(H.264/AAC)를 FFmpeg로 렌더링한다.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from AI.beautyflow.config import EXCLUDED_INFO, PROJECT_ROOT
from AI.beautyflow.nodes.script_generator import derive_badge_label, derive_fallback_headline
from AI.beautyflow.nodes.tts_generator import TTS_RATE, read_tts_wav, tts_text_key
from AI.beautyflow.state import VideoAgentState

# ---------------------------------------------------------------------------
# 1. 영상 규격 및 비주얼 아이덴티티 프리셋
# ---------------------------------------------------------------------------
LAYOUT_VERSION = "v2_identity_9x16"
VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS = 1080, 1920, 30
HERO_X, HERO_Y, HERO_W, HERO_H, HERO_RADIUS = 50, 390, 980, 940, 36
TRANSITION_FRAMES = 9  # 기본 0.30초 (30fps)
TRANSITION_SEQUENCE = ("fade", "smoothleft", "fade", "dissolve", "smoothup")
VIDEO_FONT = Path("C:/Windows/Fonts/arialbd.ttf")
VIDEO_HEADLINE_FONT = Path("C:/Windows/Fonts/bahnschrift.ttf") if Path("C:/Windows/Fonts/bahnschrift.ttf").is_file() else VIDEO_FONT
VIDEO_FONT_NAME = "Arial"
VIDEO_HEADLINE_FONT_NAME = "Bahnschrift" if VIDEO_HEADLINE_FONT.name.lower() == "bahnschrift.ttf" else "Arial"
VIDEO_TIMEOUT = 240

TYPOGRAPHY_PRESETS = {
    "editorial_serif": {"path": Path("C:/Windows/Fonts/georgiab.ttf"), "name": "Georgia", "size": 56},
    "clean_soft": {"path": Path("C:/Windows/Fonts/corbelb.ttf"), "name": "Corbel", "size": 58},
    "modern_sans": {"path": Path("C:/Windows/Fonts/bahnschrift.ttf"), "name": "Bahnschrift", "size": 58},
}

ACCENT_PRESETS = {
    "champagne_gold": {"rgb": (236, 214, 174), "light_rgb": (152, 118, 66), "ass_dark": "&H00AED6EC", "ass_light": "&H00F2E4CC"},
    "soft_rose":      {"rgb": (246, 206, 216), "light_rgb": (176, 98, 118), "ass_dark": "&H00D8CEF6", "ass_light": "&H00EAE2F8"},
    "ice_blue":       {"rgb": (192, 226, 248), "light_rgb": (48, 102, 144), "ass_dark": "&H00F8E2C0", "ass_light": "&H00FAF0E2"},
    "warm_ivory":     {"rgb": (246, 240, 230), "light_rgb": (96, 86, 76),   "ass_dark": "&H00E6F0F6", "ass_light": "&H00FFFFFF"},
    "charcoal_ink":   {"rgb": (228, 232, 238), "light_rgb": (38, 44, 52),   "ass_dark": "&H00EEE8E4", "ass_light": "&H00FFFFFF"},
}

PACING_PRESETS = {
    "calm_elegant": {"zoom_delta": 0.11, "transition_frames": 11, "transitions": ("fade", "dissolve", "fade", "dissolve", "fade")},
    "fresh_breezy": {"zoom_delta": 0.16, "transition_frames": 8,  "transitions": ("smoothleft", "fade", "smoothleft", "smoothup", "fade")},
    "steady_clean": {"zoom_delta": 0.13, "transition_frames": 9,  "transitions": ("dissolve", "fade", "smoothleft", "dissolve", "fade")},
}


# ---------------------------------------------------------------------------
# 2. 아이덴티티 해석 · 타임라인 준비 · 1줄 자막 분할 · ASS 생성
# ---------------------------------------------------------------------------
def resolve_visual_identity(state_or_cd: dict | None) -> dict:
    """State 또는 creative_direction에서 안전한 비주얼 아이덴티티 6종을 해석한다 (brand_guide 최우선)."""
    is_state = isinstance(state_or_cd, dict) and "scenes" in state_or_cd
    raw = state_or_cd.get("creative_direction") if is_state else state_or_cd
    raw = dict(raw) if isinstance(raw, dict) else {}
    if is_state and isinstance(state_or_cd.get("brand_guide"), dict):
        guide = state_or_cd["brand_guide"]
        for key in ("concept", "background_tone", "accent_color", "typography_style", "motion_pacing", "narration_tone"):
            if key in guide and guide[key] is not None:
                raw[key] = guide[key]
    return {
        "concept": raw.get("concept") if raw.get("concept") in {"premium_editorial", "clean_fresh", "clinical_calm"} else "premium_editorial",
        "background_tone": raw.get("background_tone") if raw.get("background_tone") in {"deep_dark", "warm_neutral", "soft_light"} else "deep_dark",
        "accent_color": raw.get("accent_color") if raw.get("accent_color") in ACCENT_PRESETS else "champagne_gold",
        "typography_style": raw.get("typography_style") if raw.get("typography_style") in TYPOGRAPHY_PRESETS else "modern_sans",
        "motion_pacing": raw.get("motion_pacing") if raw.get("motion_pacing") in PACING_PRESETS else "steady_clean",
        "narration_tone": raw.get("narration_tone") if raw.get("narration_tone") in {"calm_refined", "bright_fresh", "warm_reassuring"} else "calm_refined",
    }


def _resolve_headline_font(typography_style: str) -> tuple[Path, str, int]:
    preset = TYPOGRAPHY_PRESETS.get(typography_style, TYPOGRAPHY_PRESETS["modern_sans"])
    if preset["path"].is_file():
        return preset["path"], preset["name"], preset["size"]
    return VIDEO_HEADLINE_FONT, VIDEO_HEADLINE_FONT_NAME, 56


def run_video_ffmpeg(arguments: list[str], workdir: Path) -> None:
    """FFmpeg 명령을 실행하고 실패 시 stderr 말미를 포함해 RuntimeError를 발생시킨다."""
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", *arguments]
    result = subprocess.run(command, cwd=workdir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=VIDEO_TIMEOUT)
    if result.returncode:
        raise RuntimeError(f"FFmpeg 실패: {result.stderr[-2000:]}")


def _resolve_scene_overlay_meta(scene: dict, state: VideoAgentState, usp_rank: int) -> tuple[str, str, str]:
    """장면의 badge_label, headline, crop_focus를 v1/v2 호환으로 안전하게 해석한다."""
    product = state.get("product_info") or {}
    usps_by_id = {u["usp_id"]: u for u in (state.get("usps") or []) if isinstance(u, dict) and "usp_id" in u}
    purpose = scene.get("purpose") or "usp"
    badge = (scene.get("badge_label") or "").strip() or derive_badge_label(purpose, product, usp_rank if purpose == "usp" else None)
    headline = (scene.get("headline") or "").strip()
    if not headline:
        usp = usps_by_id.get((scene.get("usp_ids") or [None])[0]) if purpose == "usp" else None
        headline = derive_fallback_headline(purpose, product, usp)
    crop_focus = scene.get("crop_focus") if scene.get("crop_focus") in {"center", "left", "right", "closeup"} else "center"
    return badge, headline, crop_focus


def prepare_video_timeline(state: VideoAgentState):
    """검증 통과 State와 실제 WAV 길이를 대조해 프레임 단위 장면 타임라인을 구성한다."""
    if state.get("status") in {"failed", "fallback_review_required"}:
        raise ValueError("이전 단계의 실패·검토 대기 상태를 먼저 해결하세요.")
    validation = state.get("validation_result") or {}
    if not validation.get("is_valid") or validation.get("issues") or validation.get("error_type") != "none":
        raise ValueError("정보 검증을 통과한 대본이 필요합니다.")
    scenes = state.get("scenes") or []
    if not 4 <= len(scenes) <= 6 or [s.get("scene_no") for s in scenes] != list(range(1, len(scenes) + 1)):
        raise ValueError("순서가 연속된 4~6개 장면이 필요합니다.")
    if state.get("full_script") != " ".join(s["narration"] for s in scenes):
        raise ValueError("전체 대본과 장면별 내레이션이 다릅니다.")

    audio_path = (PROJECT_ROOT / (state.get("audio_path") or "")).resolve()
    total, merged_pcm = read_tts_wav(audio_path)
    expected_total = state.get("tts_duration_sec", 0)
    if (
        not isinstance(expected_total, (int, float))
        or not math.isfinite(expected_total)
        or not 20 <= total <= 30
        or abs(total - expected_total) > 1 / TTS_RATE
    ):
        raise ValueError("실제 음성 길이 20~30초 및 State의 실측 시간을 확인하세요.")

    identity = resolve_visual_identity(state)
    pacing = PACING_PRESETS[identity["motion_pacing"]]
    timeline, sample_count, previous_frame, segment_pcm, usp_rank = [], 0, 0, [], 0

    for scene in scenes:
        image_path = (PROJECT_ROOT / scene["image_path"]).resolve()
        with Image.open(image_path) as image:
            image.verify()
        if scene["subtitle"] != scene["narration"] or not tts_text_key(scene["subtitle"]) or EXCLUDED_INFO.search(scene["subtitle"]):
            raise ValueError("검증된 영문 내레이션과 동일한 자막이 필요합니다.")
        if scene["motion_effect"] not in {"static", "zoom_in", "zoom_out", "pan_left", "pan_right"}:
            raise ValueError("지원하지 않는 모션 효과입니다.")
        segment = (PROJECT_ROOT / (scene.get("audio_segment_path") or "")).resolve()
        duration, pcm = read_tts_wav(segment)
        expected = scene.get("duration_sec", 0)
        if not isinstance(expected, (int, float)) or not math.isfinite(expected) or abs(duration - expected) > 1 / TTS_RATE:
            raise ValueError("장면의 실제 음성 길이가 State와 다릅니다.")

        segment_pcm.append(pcm)
        start = sample_count / TTS_RATE
        sample_count += len(pcm) // 2
        elapsed = sample_count / TTS_RATE
        boundary = (sample_count * VIDEO_FPS * 2 + TTS_RATE) // (2 * TTS_RATE)
        if boundary <= previous_frame:
            raise ValueError("한 프레임보다 짧은 장면은 렌더링할 수 없습니다.")
        if scene.get("purpose") == "usp":
            usp_rank += 1
        badge_label, headline, crop_focus = _resolve_scene_overlay_meta(scene, state, usp_rank)
        if timeline and timeline[-1]["image_path"] == str(image_path) and timeline[-1]["crop_focus"] == crop_focus:
            crop_focus = "right" if crop_focus in {"center", "left"} else "closeup"

        timeline.append({
            "scene_no": scene["scene_no"],
            "purpose": scene.get("purpose", "usp"),
            "image_path": str(image_path),
            "badge_label": badge_label,
            "headline": headline,
            "subtitle": scene["subtitle"],
            "motion_effect": scene["motion_effect"],
            "crop_focus": crop_focus,
            "creative_direction": identity,
            "zoom_delta": pacing["zoom_delta"],
            "start_sec": start,
            "end_sec": elapsed,
            "start_frame": previous_frame,
            "end_frame": boundary,
            "frame_count": boundary - previous_frame,
        })
        previous_frame = boundary

    if b"".join(segment_pcm) != merged_pcm:
        raise ValueError("전체 음성이 현재 장면별 음성과 다릅니다. TTS를 다시 확인하세요.")

    min_frames = min(item["frame_count"] for item in timeline)
    overlap = min(pacing["transition_frames"], max(0, min_frames // 4))
    transitions = pacing["transitions"]
    for index, item in enumerate(timeline):
        item["total_scenes"] = len(timeline)
        item["transition_frames"] = overlap if index < len(timeline) - 1 else 0
        item["render_frames"] = item["frame_count"] + item["transition_frames"]
        item["transition_name"] = transitions[index % len(transitions)] if index < len(timeline) - 1 else None
    return timeline, audio_path, total


def _wrap_text_lines(text: str, font_path: Path, max_width: int, sizes, max_lines: int) -> tuple[list[str], int]:
    if any(c in text for c in "{}\\\r\n"):
        raise ValueError("자막/텍스트에 허용되지 않는 제어 문자가 있습니다.")
    words = text.split()
    if not words:
        raise ValueError("빈 자막/텍스트입니다.")
    for size in sizes:
        font = ImageFont.truetype(str(font_path), size)
        lines = []
        for word in words:
            if font.getlength(word) > max_width:
                break
            if lines and font.getlength(lines[-1] + " " + word) <= max_width:
                lines[-1] += " " + word
            else:
                lines.append(word)
        else:
            if len(lines) <= max_lines:
                return lines, size
    raise ValueError("텍스트가 Safe Area의 허용 줄 수를 초과합니다.")


def video_caption(text: str) -> tuple[str, int]:
    """단일 자막 문구를 Safe Area(폭 760px, 최대 3줄) 기준으로 줄바꿈 검사한다."""
    lines, size = _wrap_text_lines(text, VIDEO_FONT, 760, range(46, 37, -2), 3)
    return r"\N".join(lines), size


def _clean_subtitle_display(text: str) -> str:
    """1줄 자막에서 세미콜론·대시·끝 구두점을 정리한다 (단어 누락 0)."""
    cleaned = re.sub(r"\s*[;—]\s*", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return re.sub(r"[,;:—\-]+$", "", cleaned).strip()


def split_subtitle_chunks(text: str, max_width: int = 820, font_size: int = 42) -> list[tuple[str, int]]:
    """내레이션을 항상 깔끔한 1줄(max_width 이하, 끝 구두점 정리) 청크로 단어 누락 없이 분할한다."""
    if any(c in text for c in "{}\\\r\n"):
        raise ValueError("자막에 허용되지 않는 제어 문자가 있습니다.")
    words = re.sub(r"\s*([;—])\s*", r"\1 ", text).strip().split()
    if not words:
        raise ValueError("빈 자막입니다.")

    raw_phrases, buf = [], []
    for word in words:
        buf.append(word)
        if re.search(r"[,;:—.!?]$", word):
            raw_phrases.append(buf)
            buf = []
    if buf:
        raw_phrases.append(buf)

    base_font = ImageFont.truetype(str(VIDEO_FONT), font_size)
    phrases = []
    for phrase in raw_phrases:
        if phrases and len(phrase) <= 2:
            merged = phrases[-1] + phrase
            merged_disp = _clean_subtitle_display(" ".join(merged))
            if base_font.getlength(merged_disp) <= max_width and len(merged) <= 6:
                phrases[-1] = merged
                continue
        phrases.append(phrase)

    chunks = []
    for phrase in phrases:
        disp = _clean_subtitle_display(" ".join(phrase))
        if not disp:
            continue
        if base_font.getlength(disp) <= max_width and len(phrase) <= 6:
            chunks.append((disp, font_size))
            continue

        placed = False
        for parts_count in range(2, len(phrase) + 1):
            step = math.ceil(len(phrase) / parts_count)
            groups = [phrase[i:i + step] for i in range(0, len(phrase), step)]
            cleaned_groups = [c for c in (_clean_subtitle_display(" ".join(g)) for g in groups if g) if c]
            for try_size in (font_size, 40, 38):
                try_font = ImageFont.truetype(str(VIDEO_FONT), try_size)
                if all(try_font.getlength(c) <= max_width for c in cleaned_groups):
                    chunks.extend((c, try_size) for c in cleaned_groups)
                    placed = True
                    break
            if placed:
                break
        if not placed:
            for try_size in (36, 34, 32, 28):
                if ImageFont.truetype(str(VIDEO_FONT), try_size).getlength(disp) <= max_width:
                    chunks.append((disp, try_size))
                    placed = True
                    break
            if not placed:
                chunks.append((disp, 28))
    return chunks


def ass_timestamp(seconds: float) -> str:
    ticks = math.floor(max(0.0, seconds) * 100 + 0.5)
    return f"{ticks // 360000}:{ticks // 6000 % 60:02d}:{ticks // 100 % 60:02d}.{ticks % 100:02d}"


def write_video_subtitles(timeline: list[dict], path: Path) -> None:
    """상단 헤드라인 + 하단 1줄 중앙 청크 자막을 ASS 파일로 저장한다."""
    identity = resolve_visual_identity(timeline[0].get("creative_direction") if timeline else None)
    bg_tone = identity["background_tone"]
    hl_font_path, hl_font_name, hl_base_size = _resolve_headline_font(identity["typography_style"])

    if bg_tone == "soft_light":
        hl_primary, hl_outline, hl_shadow = "&H00382B22", "&HD8FFFFFF", "&HB8FFFFFF"
        hl_out_w, hl_sh_w, sub_box = 0.7, 1.2, "&H322C221A"
    elif bg_tone == "warm_neutral":
        hl_primary, hl_outline, hl_shadow = "&H00FFFFFF", "&H88261A18", "&H72241816"
        hl_out_w, hl_sh_w, sub_box = 1.0, 3.2, "&H48261B1A"
    else:
        hl_primary, hl_outline, hl_shadow = "&H00FFFFFF", "&H99000000", "&H78000000"
        hl_out_w, hl_sh_w, sub_box = 1.2, 3.5, "&H50141414"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Headline,{hl_font_name},{hl_base_size},{hl_primary},{hl_primary},{hl_outline},{hl_shadow},-1,0,0,0,100,100,0.4,0,1,{hl_out_w},{hl_sh_w},5,60,60,60,1
Style: Default,{VIDEO_FONT_NAME},42,&H00FFFFFF,&H00FFFFFF,{sub_box},&H88141414,-1,0,0,0,100,100,0,0,3,13,0,2,80,80,380,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for item in timeline:
        scene_start = item["start_frame"] / VIDEO_FPS
        scene_end = item["end_frame"] / VIDEO_FPS
        scene_dur = max(0.2, scene_end - scene_start)

        headline_raw = item.get("headline", "").strip()
        if headline_raw:
            hl_lines, hl_size = _wrap_text_lines(headline_raw, hl_font_path, 900, range(hl_base_size, 37, -2), 2)
            hl_y = 286 if len(hl_lines) == 1 else 282
            events.append(
                f"Dialogue: 1,{ass_timestamp(scene_start)},{ass_timestamp(scene_end)},Headline,,0,0,0,,"
                + r"{\an5\pos(540," + str(hl_y) + r")\fs" + str(hl_size) + r"\fad(220,140)}" + r"\N".join(hl_lines)
            )
            item["headline_lines"] = hl_lines
            item["headline_font_size"] = hl_size

        chunks = split_subtitle_chunks(item["subtitle"])
        weights = [max(1, len(c[0].replace(r"\N", " "))) for c in chunks]
        total_weight = sum(weights)
        cursor, chunk_records = scene_start, []
        for idx, ((chunk_text, size), weight) in enumerate(zip(chunks, weights)):
            chunk_end = scene_end if idx == len(chunks) - 1 else min(scene_end, cursor + scene_dur * (weight / total_weight))
            tags = r"{\an2\pos(540,1510)\fs" + str(size) + r"\fad(140,100)}"
            events.append(f"Dialogue: 2,{ass_timestamp(cursor)},{ass_timestamp(chunk_end)},Default,,0,0,0,,{tags}{chunk_text}")
            chunk_records.append({"text": chunk_text, "start_sec": round(cursor, 3), "end_sec": round(chunk_end, 3), "font_size": size})
            cursor = chunk_end

        item.update(
            caption_chunks=chunk_records,
            caption_lines=[line for c, _ in chunks for line in c.split(r"\N")],
            caption_font_size=min(size for _, size in chunks),
        )
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. 캔버스 합성 · 모션 필터 · FFmpeg 인자 빌더 · 라우팅
# ---------------------------------------------------------------------------
def _build_rounded_mask(width: int, height: int, radius: int) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    return mask


def _crop_focus_centering(crop_focus: str) -> tuple[float, float]:
    return {"center": (0.5, 0.5), "left": (0.18, 0.5), "right": (0.82, 0.5), "closeup": (0.5, 0.45)}.get(crop_focus, (0.5, 0.5))


def compose_scene_assets(item: dict, total_scenes: int, workdir: Path, prefix: str = "scene") -> dict[str, Path]:
    """배경 톤별 블러 캔버스·64px 브랜드 포인트 선·2x 히어로 소스·라운드 마스크를 생성한다."""
    number = item["scene_no"]
    bg_path = workdir / f"{prefix}_{number}_bg.png"
    src_path = workdir / f"{prefix}_{number}_src.png"
    mask_path = workdir / f"{prefix}_hero_mask.png"

    identity = resolve_visual_identity(item.get("creative_direction"))
    bg_tone = identity["background_tone"]
    accent = ACCENT_PRESETS[identity["accent_color"]]

    with Image.open(item["image_path"]) as raw_img:
        rgb = ImageOps.exif_transpose(raw_img).convert("RGB")
        orig_w, orig_h = rgb.size
        orig_ratio = orig_w / max(1, orig_h)

        # 1) 배경 톤별 적응형 블러 백드롭
        blur_r = 48 if bg_tone == "soft_light" else 42
        backdrop = ImageOps.fit(rgb, (VIDEO_WIDTH, VIDEO_HEIGHT), method=Image.Resampling.LANCZOS)
        arr = np.asarray(backdrop.filter(ImageFilter.GaussianBlur(radius=blur_r)), dtype=np.float32)
        y_norm = np.linspace(0.0, 1.0, VIDEO_HEIGHT, dtype=np.float32)[:, None, None]

        if bg_tone == "soft_light":
            light_tint = np.array([246.0, 249.0, 252.0], dtype=np.float32)[None, None, :]
            alpha = np.clip(0.64 + np.clip((0.25 - y_norm) / 0.25, 0.0, 1.0) * 0.14 + np.clip((y_norm - 0.68) / 0.32, 0.0, 1.0) * 0.10, 0.0, 0.86)
            bg = Image.fromarray(np.clip(arr * (1.0 - alpha) + light_tint * alpha, 0, 255).astype(np.uint8)).convert("RGBA")
            shadow_rgba, border_rgba, bar_active = (36, 52, 72, 56), (255, 255, 255, 225), (*accent["light_rgb"], 245)
        elif bg_tone == "warm_neutral":
            warm_lift = np.array([248.0, 238.0, 232.0], dtype=np.float32)[None, None, :]
            warm_scrim = np.array([72.0, 50.0, 48.0], dtype=np.float32)[None, None, :]
            lifted = arr * 0.82 + warm_lift * 0.18
            scrim_a = np.clip(0.10 + np.clip((0.27 - y_norm) / 0.27, 0.0, 1.0) ** 1.25 * 0.50 + np.clip((y_norm - 0.65) / 0.35, 0.0, 1.0) ** 1.15 * 0.54, 0.0, 0.68)
            bg = Image.fromarray(np.clip(lifted * (1.0 - scrim_a) + warm_scrim * scrim_a, 0, 255).astype(np.uint8)).convert("RGBA")
            shadow_rgba, border_rgba, bar_active = (42, 24, 22, 92), (255, 246, 240, 140), (*accent["rgb"], 250)
        else:
            darken = np.clip(0.26 + np.clip((0.26 - y_norm) / 0.26, 0.0, 1.0) ** 1.4 * 0.54 + np.clip((y_norm - 0.64) / 0.36, 0.0, 1.0) ** 1.2 * 0.60, 0.0, 0.82)
            bg = Image.fromarray(np.clip(arr * (1.0 - darken), 0, 255).astype(np.uint8)).convert("RGBA")
            shadow_rgba, border_rgba, bar_active = (0, 0, 0, 120), (*accent["rgb"], 115), (*accent["rgb"], 250)

        # 2) 히어로 카드 소프트 드롭 섀도 + 상단 64px 포인트 선 + 외곽 헤어라인 보더
        shadow_layer = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        ImageDraw.Draw(shadow_layer).rounded_rectangle((HERO_X - 6, HERO_Y + 14, HERO_X + HERO_W + 6, HERO_Y + HERO_H + 22), radius=HERO_RADIUS + 4, fill=shadow_rgba)
        bg = Image.alpha_composite(bg, shadow_layer.filter(ImageFilter.GaussianBlur(radius=22)))

        bar_layer = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        bdraw = ImageDraw.Draw(bar_layer)
        bdraw.rounded_rectangle((508, 342, 572, 346), radius=2, fill=bar_active)
        bdraw.rounded_rectangle((HERO_X - 2, HERO_Y - 2, HERO_X + HERO_W + 2, HERO_Y + HERO_H + 2), radius=HERO_RADIUS + 2, outline=border_rgba, width=2)
        Image.alpha_composite(bg, bar_layer).convert("RGB").save(bg_path)

        # 3) 2x 고해상도 히어로 소스 생성
        effect, focus = item["motion_effect"], item.get("crop_focus", "center")
        centering = _crop_focus_centering(focus)
        target_w, target_h = HERO_W * 2, HERO_H * 2
        if effect in {"pan_left", "pan_right"}:
            pan_h = target_h
            pan_w = max(2280, int(round(pan_h * orig_ratio)))
            hero_src = ImageOps.fit(rgb, (pan_w, pan_h), method=Image.Resampling.LANCZOS, centering=centering) if orig_ratio < pan_w / pan_h else rgb.resize((pan_w, pan_h), Image.Resampling.LANCZOS)
            hero_src = hero_src.crop((0, 0, pan_w - (pan_w % 2), pan_h))
        elif focus == "closeup":
            crop_w, crop_h = int(orig_w * 0.78), int(orig_h * 0.78)
            left, top = (orig_w - crop_w) // 2, (orig_h - crop_h) // 2
            hero_src = ImageOps.fit(rgb.crop((left, top, left + crop_w, top + crop_h)), (target_w, target_h), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        else:
            hero_src = ImageOps.fit(rgb, (target_w, target_h), method=Image.Resampling.LANCZOS, centering=centering)
        hero_src.save(src_path)

    if not mask_path.is_file():
        _build_rounded_mask(HERO_W, HERO_H, HERO_RADIUS).save(mask_path)
    return {"bg": bg_path, "src": src_path, "mask": mask_path}


def video_motion_filter(effect: str, frames: int, zoom_delta: float = 0.14) -> str:
    """Smoothstep 이징 Ken Burns 모션 필터 문자열을 생성한다 (단독 테스트 호환용)."""
    denom = max(1, frames - 1)
    p = f"(on/{denom})"
    ease = f"({p}*{p}*(3-2*{p}))"
    if effect == "static":
        zoom, x = "1", "(iw-iw/zoom)/2"
    elif effect == "zoom_in":
        zoom, x = f"1+{zoom_delta:.2f}*{ease}", "(iw-iw/zoom)/2"
    elif effect == "zoom_out":
        zoom, x = f"{1 + zoom_delta:.2f}-{zoom_delta:.2f}*{ease}", "(iw-iw/zoom)/2"
    elif effect == "pan_left":
        zoom, x = f"{1 + zoom_delta + 0.01:.2f}", f"(iw-iw/zoom)*{ease}"
    elif effect == "pan_right":
        zoom, x = f"{1 + zoom_delta + 0.01:.2f}", f"(iw-iw/zoom)*(1-{ease})"
    else:
        raise ValueError(f"지원하지 않는 모션 효과입니다: {effect}")
    return f"scale=2160:3840,zoompan=z='{zoom}':x='{x}':y='(ih-ih/zoom)/2':d={frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS},setsar=1,format=yuv420p"


def build_hero_motion_filter(effect: str, frames: int, zoom_delta: float = 0.13) -> str:
    """히어로 카드(980×940) 전용 Smoothstep 모션 필터를 생성한다."""
    denom = max(1, frames - 1)
    if effect in {"pan_left", "pan_right"}:
        p = f"min(1\\,n/{denom})"
        ease = f"({p}*{p}*(3-2*{p}))"
        x_expr = f"(iw-{HERO_W * 2})*{ease}" if effect == "pan_left" else f"(iw-{HERO_W * 2})*(1-{ease})"
        return f"crop=w={HERO_W * 2}:h={HERO_H * 2}:x='{x_expr}':y='(ih-{HERO_H * 2})/2',scale={HERO_W}:{HERO_H}:flags=lanczos,setsar=1"
    p = f"(on/{denom})"
    ease = f"({p}*{p}*(3-2*{p}))"
    zoom = f"1+{zoom_delta:.2f}*{ease}" if effect == "zoom_in" else f"{1 + zoom_delta:.2f}-{zoom_delta:.2f}*{ease}" if effect == "zoom_out" else "1"
    return f"zoompan=z='{zoom}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={frames}:s={HERO_W}x{HERO_H}:fps={VIDEO_FPS},setsar=1"


def build_scene_ffmpeg_args(assets: dict, effect: str, frames: int, output_name: str, encoding: list[str], zoom_delta: float = 0.13) -> list[str]:
    """배경·모션 히어로·라운드 마스크 합성용 FFmpeg 인자를 조립한다."""
    hero_filter = build_hero_motion_filter(effect, frames, zoom_delta=zoom_delta)
    filter_complex = (
        f"[1:v]{hero_filter},format=rgba[hero];"
        f"[2:v]format=gray[mask];"
        f"[hero][mask]alphamerge[rounded];"
        f"[0:v][rounded]overlay={HERO_X}:{HERO_Y}:shortest=1,format=yuv420p[vout]"
    )
    src_inputs = ["-loop", "1", "-framerate", str(VIDEO_FPS), "-i", assets["src"].name] if effect in {"pan_left", "pan_right"} else ["-i", assets["src"].name]
    return [
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", assets["bg"].name,
        *src_inputs,
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", assets["mask"].name,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-frames:v", str(frames), "-r", str(VIDEO_FPS), "-an",
        *encoding, output_name,
    ]


def build_xfade_filter_complex(timeline: list[dict], bgm_enabled: bool = False, total_sec: float = 0.0) -> str:
    """장면 클립들을 xfade로 연결하고 ASS 자막(및 선택 BGM 덕킹)을 입히는 filter_complex를 생성한다."""
    parts = []
    if len(timeline) == 1:
        parts.append("[0:v]ass=subtitles.ass,format=yuv420p[vfinal]")
    else:
        prev = "[0:v]"
        for idx in range(len(timeline) - 1):
            overlap_sec = timeline[idx]["transition_frames"] / VIDEO_FPS
            offset_sec = timeline[idx]["end_frame"] / VIDEO_FPS
            trans = timeline[idx].get("transition_name") or "fade"
            out_label = f"[vx{idx + 1}]"
            if overlap_sec > 0:
                parts.append(f"{prev}[{idx + 1}:v]xfade=transition={trans}:duration={overlap_sec:.6f}:offset={offset_sec:.6f}{out_label}")
            else:
                parts.append(f"{prev}[{idx + 1}:v]concat=n=2:v=1:a=0{out_label}")
            prev = out_label
        parts.append(f"{prev}ass=subtitles.ass,format=yuv420p[vfinal]")

    audio_idx = len(timeline)
    if bgm_enabled:
        bgm_idx = audio_idx + 1
        fade_start = max(0.0, total_sec - 1.2)
        parts.append(f"[{bgm_idx}:a]volume=-22dB,afade=t=out:st={fade_start:.3f}:d=1.2[bgm];[{audio_idx}:a][bgm]amix=inputs=2:duration=first:normalize=0[afinal]")
    return ";".join(parts)


def route_after_video_render(state: VideoAgentState) -> str:
    """렌더링 성공 시 VideoQA로 이동한다."""
    return "VideoQA" if state.get("status") == "running" and state.get("video_path") else "END"


# ---------------------------------------------------------------------------
# 4. 노드 진입점
# ---------------------------------------------------------------------------
def video_renderer(state: VideoAgentState) -> dict:
    """장면별 클립 합성·xfade 전환·ASS 자막·TTS 오디오를 합쳐 최종 MP4를 렌더링한다."""
    retry_count = state.get("retry_count", 0)
    reset = {
        "video_path": "",
        "render_json_path": None,
        "qa_json_path": None,
        "qa_next_node": "END",
        "qa_result": {"is_passed": False, "error_type": "none", "video_duration_sec": 0.0, "resolution": "", "details": "VideoQA에서 검사하세요."},
    }
    report_path, timeline, started = None, [], time.perf_counter()
    try:
        timeline, audio_path, total = prepare_video_timeline(state)
        identity = resolve_visual_identity(state)
        hl_font_path, hl_font_name, _ = _resolve_headline_font(identity["typography_style"])

        qa = state.get("qa_result") or {}
        if not qa.get("is_passed", False) and qa.get("error_type") in {"render_error", "duration_error", "sync_error"}:
            if retry_count >= state.get("max_retries", 3):
                return {**reset, "retry_count": retry_count, "status": "fallback_review_required", "error_message": "VideoRenderer: 재렌더링 한도에 도달했습니다."}
            retry_count += 1

        if not VIDEO_FONT.is_file():
            raise ValueError(f"자막 글꼴이 없습니다: {VIDEO_FONT}")

        bgm_path = None
        if state.get("bgm_path"):
            candidate_bgm = (PROJECT_ROOT / state["bgm_path"]).resolve()
            if not candidate_bgm.is_file():
                raise ValueError(f"BGM 파일이 없습니다: {candidate_bgm}")
            bgm_path = candidate_bgm

        output = (PROJECT_ROOT / (state.get("output_dir") or "output")).resolve()
        stem = Path(state.get("file_path") or "document").stem
        run_dir = output / "video" / stem / uuid4().hex[:12]
        run_dir.mkdir(parents=True, exist_ok=False)
        report_path = run_dir / "render.json"

        # 1) 자막 ASS 생성 및 장면별 모션 MP4 렌더링
        write_video_subtitles(timeline, run_dir / "subtitles.ass")
        encoding = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", "-threads", "2"]
        total_scenes = len(timeline)
        for item in timeline:
            assets = compose_scene_assets(item, total_scenes, run_dir, prefix="scene")
            clip_args = build_scene_ffmpeg_args(assets, item["motion_effect"], item["render_frames"], f"scene_{item['scene_no']}.mp4", encoding, zoom_delta=item.get("zoom_delta", 0.13))
            run_video_ffmpeg(clip_args, run_dir)

        (run_dir / "clips.txt").write_text("".join(f"file 'scene_{s['scene_no']}.mp4'\n" for s in timeline), encoding="utf-8")

        # 2) 전체 장면 xfade 결합 + ASS 번인 + 오디오(TTS/BGM) 믹싱
        video_path = run_dir / f"{stem}_shortform.mp4"
        combine_inputs = []
        for item in timeline:
            combine_inputs.extend(["-i", f"scene_{item['scene_no']}.mp4"])
        combine_inputs.extend(["-i", str(audio_path)])
        if bgm_path:
            combine_inputs.extend(["-stream_loop", "-1", "-i", str(bgm_path)])

        filter_complex = build_xfade_filter_complex(timeline, bgm_enabled=bool(bgm_path), total_sec=total)
        audio_map = "[afinal]" if bgm_path else f"{len(timeline)}:a:0"
        run_video_ffmpeg([
            *combine_inputs,
            "-filter_complex", filter_complex,
            "-map", "[vfinal]", "-map", audio_map,
            *encoding, "-r", str(VIDEO_FPS),
            "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.8f}",
            "-movflags", "+faststart", video_path.name,
        ], run_dir)

        if not video_path.is_file() or not video_path.stat().st_size:
            raise ValueError("출력 MP4가 없거나 비어 있습니다.")

        report = {
            "status": "running",
            "layout_version": LAYOUT_VERSION,
            "creative_direction": identity,
            "video_path": str(video_path),
            "audio_path": str(audio_path),
            "bgm_path": str(bgm_path) if bgm_path else None,
            "tts_duration_sec": total,
            "timeline": timeline,
            "resolution": "1080x1920",
            "fps": VIDEO_FPS,
            "frame_count": timeline[-1]["end_frame"],
            "video_codec": "h264",
            "audio_codec": "aac",
            "subtitle_path": str(run_dir / "subtitles.ass"),
            "font_path": str(VIDEO_FONT),
            "headline_font_path": str(hl_font_path),
            "headline_font_name": hl_font_name,
            "safe_area": {
                "headline_y": 286,
                "accent_line_y": 344,
                "hero_box": [HERO_X, HERO_Y, HERO_W, HERO_H],
                "caption_center_x": 540,
                "caption_bottom_y": 1510,
                "max_text_width": 820,
                "max_chunk_lines": 1,
            },
            "retry_count": retry_count,
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "requires_video_qa": True,
            "next_node": "VideoQA",
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {**reset, "video_path": str(video_path), "render_json_path": str(report_path), "retry_count": retry_count, "status": "running", "error_message": None}
    except Exception as error:
        result = {**reset, "retry_count": retry_count, "status": "failed", "error_message": f"VideoRenderer: {error}"}
        if report_path:
            try:
                report_path.write_text(json.dumps({"status": "failed", "layout_version": LAYOUT_VERSION, "error_message": result["error_message"], "timeline": timeline, "retry_count": retry_count, "next_node": "END"}, ensure_ascii=False, indent=2), encoding="utf-8")
                result["render_json_path"] = str(report_path)
            except OSError:
                pass
        return result
