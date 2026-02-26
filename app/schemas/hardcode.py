from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.transcode import VideoCodec, Preset


class SubtitleStyle(BaseModel):
    fontname: Optional[str] = Field(default="Montserrat SemiBold / Bold")
    fontsize: Optional[int] = Field(default=14)
    primary_colour: Optional[str] = Field(default="&H00FFFFFF", alias="primarycolour")
    outline_colour: Optional[str] = Field(default="&H00000000", alias="outlinecolour")
    back_colour: Optional[str] = Field(default="&H80000000", alias="backcolour")
    bold: Optional[bool] = Field(default=False)
    italic: Optional[bool] = Field(default=False)
    underline: Optional[bool] = Field(default=False)
    outline: Optional[float] = Field(default=0.2)
    shadow: Optional[float] = Field(default=1.0)
    alignment: Optional[int] = Field(default=2)
    margin_l: Optional[int] = Field(default=10, alias="marginl")
    margin_r: Optional[int] = Field(default=10, alias="marginr")
    margin_v: Optional[int] = Field(default=50, alias="marginv")
    scale_x: Optional[int] = Field(default=100, alias="scalex")
    scale_y: Optional[int] = Field(default=100, alias="scaley")


class QualityConfig(BaseModel):
    codec: VideoCodec = Field(default=VideoCodec.H264, description="视频编码格式")
    crf: int = Field(default=18, ge=0, le=51, description="恒定质量因子，仅软件编码有效")
    quality: int = Field(default=65, ge=1, le=100,
                         description="硬件编码质量（1-100），VideoToolbox/NVENC 有效，值越高质量越好")
    preset: Preset = Field(default=Preset.MEDIUM, description="编码预设，仅软件编码有效")
    resolution: Optional[str] = Field(default=None, description="输出分辨率，如 1920:1080")
