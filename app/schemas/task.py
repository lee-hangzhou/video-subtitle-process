from enum import IntEnum
from typing import List

from pydantic import BaseModel, Field


class TaskStatus(IntEnum):
    SUBMITTED = 1
    RUNNING = 2
    SUCCESS = 3
    FAILED = 4


class TaskSource:
    ALI_CLOUD = "ali_cloud"
    QUVIDEO = "quvideo"


ALI_STATUS_MAP = {
    "Created": TaskStatus.SUBMITTED,
    "Executing": TaskStatus.RUNNING,
    "Finished": TaskStatus.SUCCESS,
    "Failed": TaskStatus.FAILED,
}

QUVIDEO_STATUS_MAP = {
    1: TaskStatus.RUNNING,
    2: TaskStatus.SUCCESS,
    3: TaskStatus.FAILED,
}


class TaskType(IntEnum):
    EXTRACT = 1 # 提取
    ERASE = 2 # 擦除
    HARDCODE = 3 # 压字幕
    TRANSCODE = 4 # 压水印

class InputFile(BaseModel):
    oss_key:str=Field(description="视频oss地址")
    filename:str=Field(description="文件名")


class TaskParams(BaseModel):
    pass


class SubmitTaskReq(BaseModel):
    cloud_task_id:int=Field(description="翻译平台任务id")
    task_type: TaskType = Field(description="任务类别")
    input_files:List[InputFile]=Field(default_factory=list,description="需要处理的视频文件")
    task_params:TaskParams=Field(description="视频处理任务参数")



