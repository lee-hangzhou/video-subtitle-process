import os
import platform
import subprocess
import tempfile
from typing import Optional

import pysubs2

from app.core import logger
from app.schemas.hardcode import SubtitleStyle, QualityConfig
from app.schemas.transcode import VideoCodec
from app.utils.format import video_validation, subtitle_validation
from app.utils.transcode import FALLBACK_CODEC, is_hw_encoder_available, quality_to_hw_params


def _detect_subtitle_encoding(file_path: str) -> str:
    """检测字幕文件编码"""
    encodings = ["utf-8", "gbk", "gb2312", "latin1", "cp1252"]
    for enc in encodings:
        try:
            with open(file_path, "r", encoding=enc) as f:
                f.read()
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "utf-8"


def hardcode_subtitle(
        video_path: str,
        subtitle_path: str,
        output_path: str,
        style: Optional[SubtitleStyle] = None,
        quality: Optional[QualityConfig] = None,
) -> None:
    """将字幕硬编码到视频中，SRT 应用完整样式，ASS 仅覆盖用户指定的样式"""
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if not os.path.isfile(subtitle_path):
        raise FileNotFoundError(f"Subtitle file not found: {subtitle_path}")
    if not video_validation(video_path):
        raise ValueError(f"Unsupported video format: {video_path}")
    if not subtitle_validation(subtitle_path):
        raise ValueError(f"Unsupported subtitle format: {subtitle_path}")

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    quality = quality or QualityConfig()

    encoding = _detect_subtitle_encoding(subtitle_path)
    subs = pysubs2.load(subtitle_path, encoding=encoding)

    is_srt = subtitle_path.lower().endswith(".srt")
    if is_srt:
        _apply_full_style(subs, style or SubtitleStyle())
    elif style is not None:
        _apply_partial_style(subs, style)

    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as tmp:
        tmp_path = tmp.name
        subs.save(tmp_path)

    try:
        codec = _resolve_codec(quality)
        is_hw = codec in FALLBACK_CODEC

        cmd = _build_ffmpeg_command(video_path, tmp_path, output_path, quality, codec)
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

        if result.returncode != 0:
            if is_hw:
                fallback = FALLBACK_CODEC[codec]
                logger.warning(f"GPU encoding failed, retry with CPU ({fallback.value})")

                cmd = _build_ffmpeg_command(video_path, tmp_path, output_path, quality, fallback)
                result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')

                if result.returncode != 0:
                    raise RuntimeError(f"FFmpeg error: {result.stderr}")
            else:
                raise RuntimeError(f"FFmpeg error: {result.stderr}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _resolve_codec(quality: QualityConfig) -> VideoCodec:
    codec = quality.codec

    if codec in FALLBACK_CODEC and not is_hw_encoder_available(codec):
        fallback = FALLBACK_CODEC[codec]
        logger.warning(f"Hardware encoder {codec.value} unavailable, fallback to {fallback.value}")
        return fallback

    return codec


def _apply_full_style(subs: pysubs2.SSAFile, style: SubtitleStyle) -> None:
    """应用完整样式到字幕，用于 SRT 格式"""
    ssa_style = pysubs2.SSAStyle()
    for field, value in style.model_dump(by_alias=True).items():
        setattr(ssa_style, field, value)
    subs.styles["Default"] = ssa_style

    for event in subs.events:
        event.style = "Default"


def _apply_partial_style(subs: pysubs2.SSAFile, style: SubtitleStyle) -> None:
    """仅覆盖用户明确设置的样式字段，用于 ASS 格式"""
    fields = style.model_dump(by_alias=True, exclude_unset=True)
    if not fields:
        return

    default_style = subs.styles.get("Default", pysubs2.SSAStyle())
    for field, value in fields.items():
        setattr(default_style, field, value)
    subs.styles["Default"] = default_style


def _build_ffmpeg_command(
        video_path: str,
        subtitle_path: str,
        output_path: str,
        quality: QualityConfig,
        codec: VideoCodec,
) -> list[str]:
    if platform.system() == 'Windows':
        subtitle_path_escaped = subtitle_path.replace('\\', '\\\\\\\\').replace(':', '\\\\:')
        vf_parts = [f"subtitles={subtitle_path_escaped}"]
    else:
        subtitle_path_escaped = subtitle_path.replace(':', '\\:')
        vf_parts = [f"subtitles={subtitle_path_escaped}"]

    if quality.resolution:
        vf_parts.insert(0, f"scale={quality.resolution}")

    vf = ",".join(vf_parts)

    is_hw = codec in FALLBACK_CODEC

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", vf,
        "-c:v", codec.value,
    ]

    if is_hw:
        cmd.extend(quality_to_hw_params(codec, quality.quality))
    else:
        cmd.extend(["-crf", str(quality.crf)])
        cmd.extend(["-preset", quality.preset.value])

    cmd.extend(["-c:a", "aac", output_path])

    return cmd
