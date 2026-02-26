from enum import IntEnum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class TaskStatus(IntEnum):
    PENDING = 1     # 待处理
    PROCESSING = 2  # 处理中
    SUCCESS = 3     # 成功
    FAILED = 4      # 失败
    CANCELLED = 5   # 已取消


class TaskType(IntEnum):
    EXTRACT = 1    # 字幕提取
    ERASE = 2      # 字幕擦除
    HARDCODE = 3   # 字幕压制
    TRANSCODE = 4  # 视频转码


QUVIDEO_STATUS_MAP = {
    1: TaskStatus.PROCESSING,
    2: TaskStatus.SUCCESS,
    3: TaskStatus.FAILED,
}


class ExtractParams(BaseModel):
    language: str = Field(default="zh", description="提取语言，同时影响 OCR 和 ASR")
    include_secondary_subtitle: bool = Field(default=False, description="是否包含副字幕")


class EraseParams(BaseModel):
    pass


class HardcodeParams(BaseModel):
    subtitle_oss_keys: List[str] = Field(description="字幕文件 OSS key 列表，按文件名数字与 input_files 一一配对")


class TranscodeParams(BaseModel):
    watermark_enabled: bool = Field(default=False, description="是否叠加水印")


TASK_PARAMS_SCHEMA: dict[TaskType, type[BaseModel]] = {
    TaskType.EXTRACT: ExtractParams,
    TaskType.ERASE: EraseParams,
    TaskType.HARDCODE: HardcodeParams,
    TaskType.TRANSCODE: TranscodeParams,
}


class SubmitTaskReq(BaseModel):
    cloud_task_id: int = Field(description="翻译平台任务ID")
    task_type: TaskType = Field(description="任务类型")
    input_files: List[str] = Field(min_length=1, description="输入文件 OSS key 列表")
    params: dict = Field(default_factory=dict, description="任务参数，结构随 task_type 变化")
    callback_url: str = Field(description="任务完成后的回调地址")

    @model_validator(mode="after")
    def validate_params(self) -> "SubmitTaskReq":
        params_schema = TASK_PARAMS_SCHEMA[self.task_type]
        validated = params_schema(**self.params)
        self.params = validated.model_dump()

        if self.task_type == TaskType.HARDCODE:
            subtitle_keys = self.params.get("subtitle_oss_keys", [])
            if len(subtitle_keys) != len(self.input_files):
                raise ValueError(
                    f"HARDCODE 任务的 subtitle_oss_keys 数量（{len(subtitle_keys)}）"
                    f"必须与 input_files 数量（{len(self.input_files)}）一致"
                )
        return self


class SubmitTaskResp(BaseModel):
    local_task_id: int = Field(description="本地任务ID")


class CancelTaskReq(BaseModel):
    cloud_task_id: int = Field(description="翻译平台任务ID")


class TaskDetailReq(BaseModel):
    cloud_task_id: int = Field(description="翻译平台任务ID")


class TaskDetailResp(BaseModel):
    cloud_task_id: int
    task_type: int
    status: int
    input_files: List[str]
    output_files: List[str]
    error_message: Optional[str]
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
