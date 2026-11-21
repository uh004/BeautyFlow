"""⑧ 영상 품질 검사 노드 (VideoQA v2.3).

최종 MP4의 해상도(1080×1920)·코덱·길이(20~30초)·오디오 파형 상관도(≥0.90)·
1줄 자막 규칙·브랜드 스타일 일치·장면별 대표 프레임 MAE를 자동 검증하고
qa_preview.jpg와 qa.json을 생성한다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import imageio_ffmpeg
import numpy as np
from PIL import Image

from AI.beautyflow.config import PROJECT_ROOT
from AI.beautyflow.nodes.tts_generator import TTS_RATE, read_tts_wav
from AI.beautyflow.nodes.video_renderer import (
    HERO_X,
    HERO_Y,
    VIDEO_FPS,
    VIDEO_TIMEOUT,
    build_hero_motion_filter,
    compose_scene_assets,
    prepare_video_timeline,
    resolve_visual_identity,
    write_video_subtitles,
)
from AI.beautyflow.state import VideoAgentState

QA_DURATION_TOLERANCE = 0.10
QA_AUDIO_CORRELATION = 0.90
QA_IMAGE_MAE = 4.0
QA_CAPTION_MAE = 8.0


class VideoQAError(ValueError):
    """QA 검사 실패 유형과 복구 대상 노드를 함께 전달하는 예외."""

    def __init__(self, message: str, error_type: str = "render_error", target: str = "VideoRenderer"):
        super().__init__(message)
        self.error_type = error_type
        self.target = target


# ---------------------------------------------------------------------------
# 1. 메타데이터 · 오디오 상관도 · 대표 프레임 비교 헬퍼
# ---------------------------------------------------------------------------
def qa_ffmpeg(arguments: list[str], workdir: Path | None = None) -> bytes:
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", *arguments], cwd=workdir, capture_output=True, timeout=VIDEO_TIMEOUT)
    if result.returncode:
        raise VideoQAError("FFmpeg 검사 실패: " + result.stderr.decode("utf-8", errors="replace")[-1500:])
    return result.stdout


def qa_video_metadata(path: Path) -> dict:
    """ffprobe(우선) 또는 imageio_ffmpeg로 해상도·코덱·FPS·길이를 추출한다."""
    probe = shutil.which("ffprobe")
    if probe:
        result = subprocess.run([probe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        if result.returncode:
            raise VideoQAError("ffprobe가 MP4를 읽지 못했습니다.")
        data = json.loads(result.stdout)
        video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
        audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), {})
        return {
            "size": [video.get("width", 0), video.get("height", 0)],
            "codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name"),
            "pix_fmt": video.get("pix_fmt"),
            "fps": float(Fraction(video.get("avg_frame_rate", "0/1"))),
            "duration": float(data["format"].get("duration", 0)),
            "format": data["format"].get("format_name", ""),
            "video_start": float(video.get("start_time", 0)),
            "audio_start": float(audio.get("start_time", 0)),
            "rotation": [item.get("rotation", 0) for item in video.get("side_data_list", [])],
            "method": "ffprobe",
        }
    reader = imageio_ffmpeg.read_frames(str(path))
    try:
        info = next(reader)
    finally:
        reader.close()
    return {**info, "size": list(info["size"]), "format": "unverified", "method": "imageio_ffmpeg"}


def qa_audio_similarity(reference_pcm: bytes, decoded_pcm: bytes) -> dict:
    """10ms RMS 포락선 교차 상관으로 원본 TTS와 MP4 오디오의 싱크·유사도를 측정한다."""
    def envelope(pcm: bytes) -> np.ndarray:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
        count = len(samples) // 240
        if count < 10:
            raise VideoQAError("비교할 음성이 너무 짧습니다.", "sync_error")
        return np.sqrt(np.mean(samples[:count * 240].reshape(-1, 240) ** 2, axis=1))

    original, decoded = envelope(reference_pcm), envelope(decoded_pcm)
    if max(original.max(), decoded.max()) == 0 or min(original.max(), decoded.max()) < 1:
        return {"correlation": 0.0, "offset_sec": None}
    original -= original.mean()
    decoded -= decoded.mean()
    scale = np.linalg.norm(original) * np.linalg.norm(decoded)
    if scale <= 0:
        return {"correlation": 0.0, "offset_sec": None}
    correlation = np.correlate(decoded, original, mode="full") / scale
    index = int(np.argmax(correlation))
    return {"correlation": float(correlation[index]), "offset_sec": (index - len(original) + 1) * 0.01}


def qa_frame(path: Path, frame: int) -> np.ndarray:
    raw = qa_ffmpeg(["-i", str(path), "-vf", f"select=eq(n\\,{frame}),scale=270:480", "-frames:v", "1", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    if len(raw) != 270 * 480 * 3:
        raise VideoQAError("예상 프레임을 추출하지 못했습니다.", "sync_error")
    return np.frombuffer(raw, dtype=np.uint8).reshape(480, 270, 3)


def qa_pick_sample_local_frame(item: dict) -> int:
    """자막 페이드(0.14s)와 장면 전환(xfade)을 피해 가장 선명한 장면 내부 프레임을 고른다."""
    frame_count = max(1, int(item["frame_count"]))
    start_sec = item["start_frame"] / VIDEO_FPS
    pad = min(max(12, int(item.get("transition_frames", 9)) + 4), max(1, frame_count // 4))
    low, high = pad, max(pad, frame_count - 1 - pad)
    best_frame, best_margin = frame_count // 2, -1.0
    for ch in item.get("caption_chunks") or []:
        c_start, c_end = float(ch.get("start_sec", 0.0)), float(ch.get("end_sec", 0.0))
        if c_end <= c_start:
            continue
        mid_sec = 0.5 * (c_start + c_end)
        local = max(low, min(high, int(round((mid_sec - start_sec) * VIDEO_FPS))))
        actual_sec = start_sec + local / VIDEO_FPS
        margin = min(actual_sec - c_start, c_end - actual_sec)
        if margin > best_margin:
            best_margin = margin
            best_frame = local
    return max(0, min(frame_count - 1, best_frame))


def qa_expected_frame(item: dict, workdir: Path, local_frame: int | None = None) -> np.ndarray:
    """VideoRenderer와 동일한 빌더로 기준 프레임(270×480)을 생성한다."""
    local_frame = item["frame_count"] // 2 if local_frame is None else int(local_frame)
    assets = compose_scene_assets(item, item.get("total_scenes", 5), workdir, prefix="qa")
    effect = item["motion_effect"]
    hero_filter = build_hero_motion_filter(effect, item.get("render_frames", item["frame_count"]), zoom_delta=item.get("zoom_delta", 0.13))
    filter_complex = (
        f"[1:v]{hero_filter},format=rgba[hero];"
        f"[2:v]format=gray[mask];"
        f"[hero][mask]alphamerge[rounded];"
        f"[0:v][rounded]overlay={HERO_X}:{HERO_Y}:shortest=1,"
        f"setpts=PTS+{item['start_frame']}/({VIDEO_FPS}*TB),ass=subtitles.ass,"
        f"select=eq(n\\,{local_frame}),scale=270:480[vout]"
    )
    src_inputs = ["-loop", "1", "-framerate", str(VIDEO_FPS), "-i", assets["src"].name] if effect in {"pan_left", "pan_right"} else ["-i", assets["src"].name]
    raw = qa_ffmpeg([
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", assets["bg"].name,
        *src_inputs,
        "-loop", "1", "-framerate", str(VIDEO_FPS), "-i", assets["mask"].name,
        "-filter_complex", filter_complex, "-map", "[vout]",
        "-frames:v", "1", "-fps_mode", "passthrough",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ], workdir)
    if len(raw) != 270 * 480 * 3:
        raise VideoQAError("비교 기준 화면 생성에 실패했습니다.", target="END")
    return np.frombuffer(raw, dtype=np.uint8).reshape(480, 270, 3)


def route_after_video_qa(state: VideoAgentState) -> str:
    """QA 실패 시 VideoRenderer / ScriptReviser로 복구 분기하고, 통과·종료 시 END를 반환한다."""
    if state.get("status") != "running":
        return "END"
    return state.get("qa_next_node", "END")


# ---------------------------------------------------------------------------
# 2. 노드 진입점
# ---------------------------------------------------------------------------
def video_qa(state: VideoAgentState) -> dict:
    """최종 MP4의 규격·오디오 싱크·1줄 자막·프레임 정합성을 검사하고 qa_preview.jpg를 생성한다."""
    started, checks, metadata = time.perf_counter(), [], {}
    target, error_type, message = "END", "none", ""
    qa_path, reference_duration = None, 0.0

    def check(condition, name: str, details, kind: str = "render_error", next_node: str = "VideoRenderer"):
        checks.append({"name": name, "passed": bool(condition), "details": details})
        if not condition:
            raise VideoQAError(f"{name}: {details}", kind, next_node)

    try:
        # 1) 선행 상태·검증·원본 TTS·타임라인·렌더 리포트 정합성 검사
        check(state.get("status") in {"running", "completed"}, "input_status", state.get("status"), next_node="END")
        validation = state.get("validation_result") or {}
        check(validation.get("is_valid") and not validation.get("issues") and validation.get("error_type") == "none", "claim_validation", "정보 검증 통과 필요", next_node="END")

        audio_path = (PROJECT_ROOT / (state.get("audio_path") or "")).resolve()
        try:
            reference_duration, reference_pcm = read_tts_wav(audio_path)
        except Exception as error:
            raise VideoQAError(f"원본 TTS를 읽을 수 없습니다: {type(error).__name__}", target="END") from error
        check(20 <= reference_duration <= 30, "source_duration", reference_duration, "duration_error", "ScriptReviser")

        try:
            timeline, _, _ = prepare_video_timeline(state)
        except Exception as error:
            raise VideoQAError(f"원본 State/소재 불일치: {error}", target="END") from error

        video_path = (PROJECT_ROOT / (state.get("video_path") or "")).resolve()
        check(video_path.is_file() and video_path.stat().st_size > 0, "video_file", str(video_path))
        qa_path = video_path.parent / "qa.json"

        render_path = (PROJECT_ROOT / (state.get("render_json_path") or "")).resolve()
        check(render_path.is_file(), "render_report", str(render_path))
        report = json.loads(render_path.read_text(encoding="utf-8"))
        check(Path(report["video_path"]).resolve() == video_path and Path(report["audio_path"]).resolve() == audio_path, "report_paths", "렌더링 기록과 현재 State 경로 대조")

        expected_identity = resolve_visual_identity(state)
        if isinstance(report.get("creative_direction"), dict):
            check(report["creative_direction"] == expected_identity, "brand_identity", "현재 State의 브랜드 스타일(creative_direction/brand_guide)과 렌더링 기록 대조")

        expected_keys = ["scene_no", "image_path", "badge_label", "headline", "subtitle", "motion_effect", "crop_focus", "zoom_delta", "start_frame", "end_frame", "frame_count"]
        check(
            len(report["timeline"]) == len(timeline)
            and all(all(saved.get(key) == expected.get(key) for key in expected_keys) for saved, expected in zip(report["timeline"], timeline)),
            "timeline",
            "현재 State로 재계산한 타임라인 대조",
            "sync_error",
        )

        # 2) MP4 메타데이터·전체 디코딩·오디오 파형 상관도 검사
        metadata = qa_video_metadata(video_path)
        check(metadata["size"] == [1080, 1920] and abs(metadata["fps"] - 30) < 0.01 and not any(metadata.get("rotation", [])), "video_spec", metadata)
        check(metadata.get("codec") == "h264" and metadata.get("audio_codec") == "aac" and metadata.get("pix_fmt", "").startswith("yuv420p"), "codecs", "H.264/AAC/yuv420p 필요")
        if metadata.get("method") == "imageio_ffmpeg":
            checks.append({"name": "container_and_stream_start_metadata", "passed": None, "details": "ffprobe가 없어 메타데이터 검사는 생략. 전체 디코딩·파형 검사는 별도로 수행."})
        else:
            check("mp4" in metadata.get("format", ""), "container", metadata.get("format"))

        check(20 <= metadata["duration"] <= 30, "video_duration", metadata["duration"], "duration_error")
        check(abs(metadata["duration"] - reference_duration) <= QA_DURATION_TOLERANCE, "av_duration", {"video": metadata["duration"], "tts": reference_duration}, "sync_error")
        if metadata.get("method") != "imageio_ffmpeg":
            check(abs(metadata.get("video_start", 0) - metadata.get("audio_start", 0)) <= QA_DURATION_TOLERANCE, "stream_start", "영상/음성 시작 위치 비교", "sync_error")

        progress = qa_ffmpeg(["-xerror", "-i", str(video_path), "-map", "0:v:0", "-map", "0:a:0", "-progress", "pipe:1", "-nostats", "-f", "null", "-"]).decode("utf-8")
        frame_counts = re.findall(r"(?m)^frame=(\d+)", progress)
        check(bool(frame_counts) and abs(int(frame_counts[-1]) - timeline[-1]["end_frame"]) <= 1, "full_decode_frames", {"decoded": frame_counts[-1] if frame_counts else None, "expected": timeline[-1]["end_frame"]}, "sync_error")

        decoded_pcm = qa_ffmpeg(["-i", str(video_path), "-map", "0:a:0", "-ac", "1", "-ar", str(TTS_RATE), "-f", "s16le", "pipe:1"])
        check(abs(len(decoded_pcm) / (2 * TTS_RATE) - reference_duration) <= QA_DURATION_TOLERANCE, "decoded_audio_duration", len(decoded_pcm) / (2 * TTS_RATE), "sync_error")

        similarity = qa_audio_similarity(reference_pcm, decoded_pcm)
        check(similarity["correlation"] >= QA_AUDIO_CORRELATION and similarity["offset_sec"] is not None and abs(similarity["offset_sec"]) <= QA_DURATION_TOLERANCE, "audio_similarity", similarity, "sync_error")

        # 3) ASS 1줄 자막 규칙 및 장면별 대표 프레임 MAE 검사 + qa_preview.jpg 생성
        with tempfile.TemporaryDirectory(prefix="beautyflow_qa_") as temporary:
            workdir = Path(temporary)
            write_video_subtitles(timeline, workdir / "subtitles.ass")
            subtitle_path = Path(report["subtitle_path"])
            ass_saved_text = subtitle_path.read_text(encoding="utf-8") if subtitle_path.is_file() else ""
            check(subtitle_path.is_file() and ass_saved_text == (workdir / "subtitles.ass").read_text(encoding="utf-8"), "subtitle_script", "ASS 문구·시점·스타일·Safe Area를 현재 State로 재구성해 대조")

            caption_dialogues = [line.split(",,", 1)[1].split("}", 1)[-1] for line in ass_saved_text.splitlines() if line.startswith("Dialogue: 2,") and ",," in line]
            bad_caption_lines = [t for t in caption_dialogues if r"\N" in t or ";" in t or re.search(r"[,;:—\-]$", t)]
            check(not bad_caption_lines, "subtitle_single_line", f"하단 1줄 자막 규칙 위반: {bad_caption_lines[:3]}" if bad_caption_lines else f"{len(caption_dialogues)}개 토막 전부 1줄·구두점 정상")

            preview = Image.new("RGB", (270 * len(timeline), 480))
            for index, item in enumerate(timeline):
                sample_local = qa_pick_sample_local_frame(item)
                actual = qa_frame(video_path, item["start_frame"] + sample_local)
                expected = qa_expected_frame(item, workdir, sample_local)
                difference = np.abs(actual.astype(float) - expected.astype(float))
                image_mae = float(difference[100:330].mean())
                caption_mae = float(max(difference[58:90].mean(), difference[345:400].mean()))
                preview.paste(Image.fromarray(actual), (index * 270, 0))
                check(image_mae <= QA_IMAGE_MAE, f"scene_{item['scene_no']}_image", {"mae": image_mae, "limit": QA_IMAGE_MAE})
                check(caption_mae <= QA_CAPTION_MAE, f"scene_{item['scene_no']}_caption", {"mae": caption_mae, "limit": QA_CAPTION_MAE})
            preview.save(video_path.parent / "qa_preview.jpg")

        message = "필수 자동 검사 통과. 대표 프레임 비교이며 전체 프레임의 의미·가독성 검증은 아닙니다."
    except VideoQAError as error:
        error_type, target, message = error.error_type, error.target, str(error)
    except Exception as error:
        error_type, target, message = "render_error", "END", f"QA 실행 오류: {type(error).__name__}: {error}"

    passed = error_type == "none"
    exhausted = state.get("retry_count", 0) >= state.get("max_retries", 3)
    if not passed and (target == "END" or exhausted):
        target, status = "END", "fallback_review_required"
    else:
        status = "completed" if passed else "running"

    result = {
        "qa_result": {
            "is_passed": passed,
            "error_type": error_type,
            "video_duration_sec": metadata.get("duration", 0.0),
            "resolution": "x".join(map(str, metadata.get("size", [0, 0]))),
            "details": message,
        },
        "qa_json_path": None,
        "qa_next_node": target,
        "status": status,
        "error_message": None if passed else f"VideoQA: {message}",
    }
    if target == "ScriptReviser":
        result["tts_duration_sec"] = reference_duration
    if qa_path is None:
        output = (PROJECT_ROOT / (state.get("output_dir") or "output")).resolve() / "qa"
        qa_path = output / f"{Path(state.get('file_path') or 'document').stem}_{uuid4().hex[:12]}.json"

    audit = {
        **result,
        "checks": checks,
        "metadata": metadata,
        "video_path": state.get("video_path"),
        "retry_count": state.get("retry_count", 0),
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "thresholds": {
            "duration_sec": QA_DURATION_TOLERANCE,
            "audio_correlation": QA_AUDIO_CORRELATION,
            "image_mae": QA_IMAGE_MAE,
            "caption_mae": QA_CAPTION_MAE,
        },
        "limits": [
            "장면 중앙의 대표 프레임 비교. 전체 프레임·모든 글자의 OCR 검증 아님.",
            "음성은 10ms RMS 파형 비교. 독립 ASR·단어별 자막 정렬 검증 아님.",
            "화면 비교는 현재 렌더링 규칙 기준. 미적 품질·플랫폼 UI 가림 보장 아님.",
        ],
    }
    try:
        qa_path.parent.mkdir(parents=True, exist_ok=True)
        result["qa_json_path"] = str(qa_path)
        audit["qa_json_path"] = str(qa_path)
        qa_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as error:
        result.update(qa_json_path=None, status="failed", qa_next_node="END", error_message=f"VideoQA 기록 저장 실패: {type(error).__name__}")
        result["qa_result"].update(is_passed=False, error_type="render_error", details=result["error_message"])
    return result
