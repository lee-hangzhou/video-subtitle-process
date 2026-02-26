from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


@dataclass
class ExtractResult:
    video_path: str
    ocr_srt_path: Optional[str] = None
    asr_srt_path: Optional[str] = None
    fused_srt_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class RawSubtitle:
    frame_no: int
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    text: str
    confidence: float


class ExtractMode(str, Enum):
    FPS = "fps"
    DETECT = "detect"


class SubtitleArea(BaseModel):
    y_min: int = Field(ge=0, description="字幕区域上边界")
    y_max: int = Field(ge=0, description="字幕区域下边界")
    x_min: int = Field(ge=0, description="字幕区域左边界")
    x_max: int = Field(ge=0, description="字幕区域右边界")

    @model_validator(mode="after")
    def validate_boundaries(self) -> "SubtitleArea":
        if self.y_min >= self.y_max:
            raise ValueError("y_min must be less than y_max")
        if self.x_min >= self.x_max:
            raise ValueError("x_min must be less than x_max")
        return self


class OCRConfig(BaseModel):
    language: str = Field(default="ch", description="识别语言：ch/en/japan/korean 等")
    extract_mode: ExtractMode = Field(default=ExtractMode.FPS, description="帧提取模式")
    extract_frequency: int = Field(default=3, ge=1, le=30, description="每秒抽帧数")
    subtitle_area: Optional[SubtitleArea] = Field(default=None, description="手动指定的字幕区域")
    similarity_threshold: float = Field(default=0.8, ge=0.5, le=1.0, description="文本相似度阈值，用于去重")
    drop_score: float = Field(default=0.75, ge=0.0, le=1.0, description="OCR 置信度阈值，低于此值丢弃")
    area_deviation_rate: float = Field(default=0.0, ge=0.0, le=0.5, description="字幕区域越界容忍比例，0 表示不允许越界")
    use_gpu: bool = Field(default=False, description="是否使用 GPU 加速")
    filter_watermark: bool = Field(default=False, description="是否过滤水印区域")
    filter_scene_text: bool = Field(default=True, description="是否过滤字幕区域外的文字")
    include_secondary_subtitle: bool = Field(default=False, description="是否包含副字幕")


class ASRConfig(BaseModel):
    model_name: str = Field(default="medium", description="Whisper 模型：tiny/base/small/medium/large-v3")
    language: str = Field(default="Chinese", description="识别语言：Chinese/English/Japanese/Korean 等")
    use_gpu: bool = Field(default=True, description="是否使用 GPU 加速")


class SubtitleSegment(BaseModel):
    index: int = Field(ge=1, description="序号")
    start_time: float = Field(ge=0, description="开始时间（秒）")
    end_time: float = Field(ge=0, description="结束时间（秒）")
    text: str = Field(description="字幕文本")

    @model_validator(mode="after")
    def validate_time(self) -> "SubtitleSegment":
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be less than end_time")
        return self
