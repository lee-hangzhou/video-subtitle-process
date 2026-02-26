from typing import Optional

from pydantic import BaseModel, Field


class SubtitleEraseRequest(BaseModel):
    """
    字幕擦除请求参数

    box_url: 字幕提取接口返回的 npz 文件地址，包含字幕位置信息
    logo_boxes: 水印位置 [[x0, y0, x1, y1], ...]，左上角和右下角坐标
    subtitle_boxes: 字幕位置 [[x0, y0, x1, y1], ...]，与 box_url 同时存在时失效
    version: 1=老版本，2=新版本（推荐），新版本支持全屏自动擦除
    export_video_quality_type: 0=高清（默认），1=与原视频码率一致

    不传位置信息时，新版本会自动全屏擦除字幕，但可能误擦非字幕文字
    """
    video_url: str = Field(alias="videoUrl")
    box_url: Optional[str] = Field(default=None, alias="boxUrl")
    logo_boxes: Optional[list[list[int]]] = Field(default=None, alias="logoBoxes")
    subtitle_boxes: Optional[list[list[int]]] = Field(default=None, alias="subtitleBoxes")
    version: int = Field(default=2)
    export_video_quality_type: Optional[int] = Field(default=None, alias="exportVideoQualityType")
    callback: Optional[str] = Field(default=None)

    class Config:
        populate_by_name = True


class TaskResult(BaseModel):
    """任务结果，不同接口返回不同字段"""
    video_url: Optional[str] = Field(default=None, alias="videoUrl")
    srt_url: Optional[str] = Field(default=None, alias="srtUrl")
    box_url: Optional[str] = Field(default=None, alias="boxUrl")
    glossary_url: Optional[str] = Field(default=None, alias="glossaryUrl")
    srt_with_role_url: Optional[str] = Field(default=None, alias="srtWithRoleUrl")

    class Config:
        populate_by_name = True


class TaskMeta(BaseModel):
    """任务元数据"""
    video_length: Optional[int] = Field(default=None, alias="videoLength")
    char_count: Optional[int] = Field(default=None, alias="charCount")

    class Config:
        populate_by_name = True


class TaskResultData(BaseModel):
    """
    任务查询结果

    state: 1=进行中，2=已完成，3=失败
    """
    state: int
    task_result: Optional[TaskResult] = Field(default=None, alias="taskResult")
    meta: Optional[TaskMeta] = Field(default=None)
    engine_code: Optional[str] = Field(default=None, alias="engineCode")
    engine_message: Optional[str] = Field(default=None, alias="engineMessage")

    class Config:
        populate_by_name = True

    @property
    def is_running(self) -> bool:
        return self.state == 1

    @property
    def is_completed(self) -> bool:
        return self.state == 2

    @property
    def is_failed(self) -> bool:
        return self.state == 3


class BaseResponse(BaseModel):
    code: int
    success: bool
    message: str


class SubtitleEraseResponse(BaseResponse):
    data: Optional[dict] = None

    @property
    def business_id(self) -> Optional[str]:
        if self.data:
            return self.data.get("businessId")
        return None


class TaskResultResponse(BaseResponse):
    data: Optional[TaskResultData] = None
