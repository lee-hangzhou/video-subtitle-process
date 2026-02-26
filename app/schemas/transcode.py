from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


@dataclass
class ProcessResult:
    video_name: str
    success: bool
    error: Optional[str] = None


ROOT_DIR = Path(__file__).parent.parent
DEFAULT_WATERMARK = str(ROOT_DIR / "core" / "file" / "mome.png")


class Container(str, Enum):
    MP4 = "mp4"
    MKV = "mkv"
    MOV = "mov"
    AVI = "avi"
    WEBM = "webm"


class VideoCodec(str, Enum):
    """编码器，cpu编码压缩效率最高，编码速度最慢"""
    H264 = "libx264" # cpu编码，编码速度比H265快，压缩效率比H265低，全平台
    H265 = "libx265" # cpu编码，编码速度慢，压缩效率高，全平台
    H264_VIDEOTOOLBOX = "h264_videotoolbox"  # macOS
    HEVC_VIDEOTOOLBOX = "hevc_videotoolbox"  # macOS 压缩效率比H264_VIDEOTOOLBOX高
    H264_NVENC = "h264_nvenc"  # NVIDIA
    HEVC_NVENC = "hevc_nvenc"  # NVIDIA 压缩效率比HEVC_NVENC高


class AudioCodec(str, Enum):
    AAC = "aac"
    MP3 = "libmp3lame"


class AudioProfile(str, Enum):
    AAC_LC = "aac_low"
    AAC_HE = "aac_he"
    AAC_HE_V2 = "aac_he_v2"


class SampleRate(int, Enum):
    HZ_22050 = 22050
    HZ_44100 = 44100
    HZ_48000 = 48000


class Preset(str, Enum):
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    SLOWER = "slower"
    VERYSLOW = "veryslow"


class ScaleMode(str, Enum):
    FIT = "fit"
    FILL = "fill"
    STRETCH = "stretch"


class Position(str, Enum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"
    CENTER = "center"


class WatermarkConfig(BaseModel):
    image_path: str = Field(default=DEFAULT_WATERMARK, description="水印图片路径，仅支持 png 格式")
    start_time: int = Field(default=0, ge=0, description="开始时间 ms，0 表示从视频开始展示")
    end_time: int = Field(default=0, ge=0, description="结束时间 ms，0 表示展示到视频结束")
    position: Position = Field(default=Position.TOP_LEFT, description="水印位置")
    offset_x: int = Field(default=80, ge=0, description="水平偏移 px")
    offset_y: int = Field(default=176, ge=0, description="垂直偏移 px")
    width: int = Field(default=70, ge=1, description="水印宽度 px")
    height: int = Field(default=70, ge=1, description="水印高度 px")


class VideoConfig(BaseModel):
    codec: VideoCodec = Field(default=VideoCodec.H264_NVENC, description="视频编码格式")
    short_edge: Optional[int] = Field(default=720, ge=240, le=2160, description="短边限制，None 表示保持原始，720 对应火山 1080p 档")
    preset: Preset = Field(default=Preset.SLOW, description="编码预设，仅软件编码有效")
    crf: int = Field(default=27, ge=0, le=51, description="恒定质量因子，仅软件编码有效")
    quality: int = Field(default=90, ge=1, le=100, description="硬件编码质量（1-100），VideoToolbox/NVENC 有效，值越高质量越好")
    max_bitrate: Optional[int] = Field(default=5000, ge=100, le=50000, description="最大码率 kbps")
    fps: Optional[int] = Field(default=None, ge=1, le=120, description="输出帧率，None 表示跟随片源")
    max_fps: Optional[int] = Field(default=30, ge=1, le=120, description="最大帧率限制")
    scale_mode: ScaleMode = Field(default=ScaleMode.FIT, description="缩放模式：fit 保持比例，fill 裁剪填充，stretch 拉伸")


class AudioConfig(BaseModel):
    enabled: bool = Field(default=True, description="是否启用音频")
    codec: AudioCodec = Field(default=AudioCodec.AAC, description="音频编码格式")
    profile: AudioProfile = Field(default=AudioProfile.AAC_LC, description="AAC 编码配置")
    sample_rate: SampleRate = Field(default=SampleRate.HZ_44100, description="采样率 Hz")
    bitrate: int = Field(default=64, ge=32, le=320, description="音频码率 kbps")
    channels: int = Field(default=2, ge=1, le=2, description="声道数：1 单声道，2 双声道")
    normalize: bool = Field(default=False, description="音量均衡")


class TranscodeConfig(BaseModel):
    container: Container = Field(default=Container.MP4, description="输出容器格式")
    video: VideoConfig = Field(default_factory=VideoConfig, description="视频配置")
    audio: AudioConfig = Field(default_factory=AudioConfig, description="音频配置")
    watermark_enabled: bool = Field(description="是否添加水印")
    watermark: WatermarkConfig = Field(default_factory=WatermarkConfig, description="水印配置")
