import json
import os
import subprocess
from functools import lru_cache

from app.core import logger
from app.schemas.transcode import VideoCodec, TranscodeConfig, Position

FALLBACK_CODEC = {
    VideoCodec.H264_VIDEOTOOLBOX: VideoCodec.H264,
    VideoCodec.HEVC_VIDEOTOOLBOX: VideoCodec.H265,
    VideoCodec.H264_NVENC: VideoCodec.H264,
    VideoCodec.HEVC_NVENC: VideoCodec.H265,
}

_ENCODER_NAMES = {
    VideoCodec.H264_VIDEOTOOLBOX: "h264_videotoolbox",
    VideoCodec.HEVC_VIDEOTOOLBOX: "hevc_videotoolbox",
    VideoCodec.H264_NVENC: "h264_nvenc",
    VideoCodec.HEVC_NVENC: "hevc_nvenc",
}


@lru_cache(maxsize=1)
def _get_available_encoders() -> set[str]:
    """获取 FFmpeg 支持的硬件编码器列表"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return set()

        encoders = set()
        for encoder_name in _ENCODER_NAMES.values():
            if encoder_name in result.stdout:
                encoders.add(encoder_name)
        return encoders
    except Exception:
        return set()


def is_hw_encoder_available(codec: VideoCodec) -> bool:
    """检测硬件编码器是否可用"""
    if codec not in _ENCODER_NAMES:
        return False
    encoder_name = _ENCODER_NAMES[codec]
    return encoder_name in _get_available_encoders()


def get_video_info(input_path: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-of", "json",
        input_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe error: {result.stderr}")

    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise RuntimeError("No video stream found")

    stream = data["streams"][0]
    fps_str = stream.get("r_frame_rate", "30/1")
    fps_parts = fps_str.split("/")
    fps = int(fps_parts[0]) / int(fps_parts[1]) if len(fps_parts) == 2 else 30

    return {
        "width": stream.get("width", 0),
        "height": stream.get("height", 0),
        "fps": fps,
    }


def _build_video_filters(
        config: TranscodeConfig,
        source_width: int,
        source_height: int,
        source_fps: float,
) -> list[str]:
    filters = []

    short_edge = config.video.short_edge
    if short_edge:
        source_short = min(source_width, source_height)
        if source_short > short_edge:
            if source_width < source_height:
                filters.append(f"scale={short_edge}:-2")
            else:
                filters.append(f"scale=-2:{short_edge}")

    target_fps = None
    if config.video.fps:
        target_fps = config.video.fps
    elif config.video.max_fps and source_fps > config.video.max_fps:
        target_fps = config.video.max_fps

    if target_fps:
        filters.append(f"fps={target_fps}")

    return filters


def _build_overlay_position(config: TranscodeConfig) -> str:
    wm = config.watermark
    position_map = {
        Position.TOP_LEFT: f"{wm.offset_x}:{wm.offset_y}",
        Position.TOP_RIGHT: f"W-w-{wm.offset_x}:{wm.offset_y}",
        Position.BOTTOM_LEFT: f"{wm.offset_x}:H-h-{wm.offset_y}",
        Position.BOTTOM_RIGHT: f"W-w-{wm.offset_x}:H-h-{wm.offset_y}",
        Position.CENTER: "(W-w)/2:(H-h)/2",
    }
    return position_map.get(wm.position, f"{wm.offset_x}:{wm.offset_y}")


def _build_time_filter(config: TranscodeConfig) -> str:
    wm = config.watermark
    if wm.start_time == 0 and wm.end_time == 0:
        return ""

    start_sec = wm.start_time / 1000
    if wm.end_time == 0:
        return f":enable='gte(t,{start_sec})'"

    end_sec = wm.end_time / 1000
    return f":enable='between(t,{start_sec},{end_sec})'"


def quality_to_hw_params(codec: VideoCodec, quality: int) -> list[str]:
    """
    将 quality 值（1-100）映射到硬件编码器的参数
    统一使用 quality 参数，映射到不同编码器的参数
    """
    if codec in (VideoCodec.H264_VIDEOTOOLBOX, VideoCodec.HEVC_VIDEOTOOLBOX):
        # VideoToolbox: quality 1-100，值越高质量越好
        return ["-q:v", str(quality)]
    elif codec in (VideoCodec.H264_NVENC, VideoCodec.HEVC_NVENC):
        # NVENC: quality 1-100 映射到 -cq 0-51，值越小质量越好
        # 映射公式：cq = 51 * (1 - (quality - 1) / 99)
        # quality=100 -> cq=0, quality=1 -> cq=51
        cq = int(51 * (1 - (quality - 1) / 99))
        return ["-cq", str(cq), "-rc", "vbr"]
    else:
        raise ValueError(f"Unsupported hardware codec: {codec}")


def _resolve_codec(config: TranscodeConfig) -> VideoCodec:
    codec = config.video.codec

    if codec in FALLBACK_CODEC and not is_hw_encoder_available(codec):
        fallback = FALLBACK_CODEC[codec]
        logger.warning(f"Hardware encoder {codec.value} unavailable, fallback to {fallback.value}")
        return fallback

    return codec


def build_ffmpeg_command(
        input_path: str,
        output_path: str,
        config: TranscodeConfig,
        codec: VideoCodec,
) -> list[str]:
    info = get_video_info(input_path)
    source_width = info["width"]
    source_height = info["height"]
    source_fps = info["fps"]

    cmd = ["ffmpeg", "-i", input_path]

    if config.watermark_enabled:
        if not os.path.isfile(config.watermark.image_path):
            raise FileNotFoundError(f"Watermark image not found: {config.watermark.image_path}")
        cmd.extend(["-i", config.watermark.image_path])

    cmd.append("-y")

    video_filters = _build_video_filters(config, source_width, source_height, source_fps)

    if config.watermark_enabled:
        wm = config.watermark
        overlay_pos = _build_overlay_position(config)
        time_filter = _build_time_filter(config)

        video_filter_str = ",".join(video_filters) if video_filters else ""
        if video_filter_str:
            filter_complex = f"[0:v]{video_filter_str}[v];[1:v]scale={wm.width}:{wm.height}[wm];[v][wm]overlay={overlay_pos}{time_filter}"
        else:
            filter_complex = f"[1:v]scale={wm.width}:{wm.height}[wm];[0:v][wm]overlay={overlay_pos}{time_filter}"

        cmd.extend(["-filter_complex", filter_complex])
    elif video_filters:
        cmd.extend(["-vf", ",".join(video_filters)])

    cmd.extend(["-c:v", codec.value])

    is_hw = codec in FALLBACK_CODEC
    if is_hw:
        cmd.extend(quality_to_hw_params(codec, config.video.quality))
    else:
        cmd.extend(["-preset", config.video.preset.value])
        cmd.extend(["-crf", str(config.video.crf)])

    if config.video.max_bitrate:
        cmd.extend(["-maxrate", f"{config.video.max_bitrate}k"])
        cmd.extend(["-bufsize", f"{config.video.max_bitrate * 2}k"])

    if not config.audio.enabled:
        cmd.append("-an")
    else:
        cmd.extend(["-c:a", config.audio.codec.value])
        cmd.extend(["-profile:a", config.audio.profile.value])
        cmd.extend(["-ar", str(config.audio.sample_rate.value)])
        cmd.extend(["-b:a", f"{config.audio.bitrate}k"])
        cmd.extend(["-ac", str(config.audio.channels)])

        if config.audio.normalize:
            cmd.extend(["-af", "loudnorm"])

    cmd.append(output_path)
    return cmd


def transcode(
        input_path: str,
        output_path: str,
        config: TranscodeConfig,
) -> None:
    if not os.path.isfile(input_path):
        raise FileNotFoundError(f"Input video not found: {input_path}")

    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    codec = _resolve_codec(config)
    is_hw = codec in FALLBACK_CODEC

    cmd = build_ffmpeg_command(input_path, output_path, config, codec)
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

    if result.returncode != 0:
        if is_hw:
            fallback = FALLBACK_CODEC[codec]
            logger.warning(f"GPU encoding failed, retry with CPU ({fallback.value})")

            cmd = build_ffmpeg_command(input_path, output_path, config, fallback)
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg error: {result.stderr}")
        else:
            raise RuntimeError(f"FFmpeg error: {result.stderr}")

    logger.info(f"transcode completed: {os.path.basename(output_path)}")

