import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

import httpx

from app.core.celery_app import celery_app, run_in_worker
from app.core.config import settings
from app.core.oss import oss_client
from app.models.task import Task
from app.repositories.task import TaskRepository
from app.schemas.task import QUVIDEO_STATUS_MAP, TaskStatus, TaskType
from app.schemas.subtitle_extract import OCRConfig, ASRConfig, ExtractMode
from app.schemas.transcode import TranscodeConfig
from app.services.subtitle_erase import subtitle_erase_service, SubtitleEraseService
from app.services.subtitle_extract import SubtitleExtractService
from app.services.subtitle_hardcode import SubtitleHardcodeService
from app.services.video_transcode import VideoTranscodeService


class TaskProcessor:
    """处理单个视频任务：下载输入 → 执行处理 → 上传输出 → 回调。"""

    def __init__(self, task_id: Optional[int] = None):
        self.task_id = task_id
        self.task_repo = TaskRepository()
        self.subtitle_erase_service = SubtitleEraseService()
        self.oss_client = oss_client

    async def execute_task(self) -> None:
        """任务主入口。"""
        if self.task_id is None:
            raise RuntimeError("task id must be set")
        task = await self.task_repo.get_by_id(self.task_id)
        if not task:
            return
        await self.task_repo.update(task.id, status=TaskStatus.PROCESSING)
        await self._execute(task)

    async def _execute(self, task: Task) -> None:
        """下载 → 路由到对应处理器 → 上传 → 回调。"""
        work_dir = Path(settings.TMP_DIR) / str(task.cloud_task_id)
        input_dir = work_dir / "input"
        output_dir = work_dir / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            await self._download_inputs(task.input_files, input_dir)

            if task.task_type == TaskType.ERASE:
                await self._process_erase(task, list(input_dir.iterdir()))
                return

            handler = {
                TaskType.EXTRACT: self._process_extract,
                TaskType.HARDCODE: self._process_hardcode,
                TaskType.TRANSCODE: self._process_transcode,
            }[task.task_type]

            output_files = await handler(task, input_dir, output_dir)
            output_oss_keys = await self._upload_outputs(output_files, task.cloud_task_id)

            await self.task_repo.update(task.id, status=TaskStatus.SUCCESS, output_files=output_oss_keys)
            await self.send_callback(task, TaskStatus.SUCCESS, output_oss_keys)

        except Exception as e:
            await self.task_repo.update(task.id, status=TaskStatus.FAILED, error_message=str(e))
            await self.send_callback(task, TaskStatus.FAILED, [], str(e))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    @staticmethod
    async def _process_extract(task: Task, input_dir: Path, output_dir: Path) -> list[Path]:
        """字幕提取：OCR + ASR + LLM 融合，返回 SRT 文件路径列表。"""
        params = task.params or {}
        language = params.get("language", "zh")
        include_secondary = params.get("include_secondary_subtitle", False)

        service = SubtitleExtractService(
            ocr_config=OCRConfig(
                language="ch" if language == "zh" else language,
                extract_mode=ExtractMode.FPS,
                include_secondary_subtitle=include_secondary,
            ),
            asr_config=ASRConfig(
                language="Chinese" if language == "zh" else language,
            ),
        )

        output_files = []
        for video_path in input_dir.iterdir():
            if not video_path.is_file():
                continue
            result = await service.extract(str(video_path), str(output_dir))
            if result.fused_srt_path:
                output_files.append(Path(result.fused_srt_path))
        return output_files

    @staticmethod
    async def _process_hardcode(task: Task, input_dir: Path, output_dir: Path) -> list[Path]:
        """字幕压制：下载字幕文件后烧录到视频，返回输出视频路径列表。"""
        params = task.params or {}
        subtitle_oss_keys: list[str] = params.get("subtitle_oss_keys", [])

        subtitle_dir = input_dir / "subtitles"
        subtitle_dir.mkdir()
        for oss_key in subtitle_oss_keys:
            await oss_client.download_file(oss_key, str(subtitle_dir / os.path.basename(oss_key)))

        results = await SubtitleHardcodeService().batch_hardcode(
            video_dir=str(input_dir),
            subtitle_dir=str(subtitle_dir),
            output_dir=str(output_dir),
            max_workers=settings.FFMPEG_WORKERS,
        )
        return [output_dir / r.video_name for r in results if r.success]

    @staticmethod
    async def _process_transcode(task: Task, input_dir: Path, output_dir: Path) -> list[Path]:
        """视频转码，返回输出视频路径列表。"""
        params = task.params or {}
        config = TranscodeConfig(watermark_enabled=params.get("watermark_enabled", False))

        results = await VideoTranscodeService().batch_transcode(
            video_dir=str(input_dir),
            output_dir=str(output_dir),
            config=config,
            max_workers=settings.FFMPEG_WORKERS,
        )
        return [output_dir / r.video_name for r in results if r.success]

    async def _process_erase(self, task: Task, local_paths: list[Path]) -> None:
        """字幕擦除：提交所有视频到 QuVideo，将 job_id 列表写回 params。"""
        job_ids = []
        for local_path in local_paths:
            oss_key = f"{settings.alibaba.oss_input_prefix}/{task.cloud_task_id}/{local_path.name}"
            job_id = await subtitle_erase_service.upload_and_submit(local_path, oss_key)
            job_ids.append(job_id)

        params = dict(task.params or {})
        params["job_ids"] = job_ids
        await self.task_repo.update(task.id, params=params)

    @staticmethod
    async def _download_inputs(oss_keys: list[str], input_dir: Path) -> None:
        """从 OSS 批量下载输入文件到本地目录。"""
        for oss_key in oss_keys:
            await oss_client.download_file(oss_key, str(input_dir / os.path.basename(oss_key)))

    @staticmethod
    async def _upload_outputs(local_paths: list[Path], cloud_task_id: int) -> list[str]:
        """将本地输出文件上传到 OSS，返回 OSS key 列表。"""
        oss_keys = []
        for local_path in local_paths:
            oss_key = f"{settings.alibaba.oss_output_prefix}/{cloud_task_id}/{local_path.name}"
            await oss_client.upload_file(str(local_path), oss_key)
            oss_keys.append(oss_key)
        return oss_keys

    @staticmethod
    async def send_callback(task: Task, status: TaskStatus, output_files: list[str], error: str | None = None) -> None:
        """向翻译平台发送任务结果回调。"""
        if not task.callback_url:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(task.callback_url, json={
                "cloud_task_id": task.cloud_task_id,
                "status": status,
                "output_files": output_files,
                "error_message": error,
            })

    async def polling(self):
        tasks = await self.task_repo.get_processing_erase_tasks()
        for task in tasks:
            try:
                await self._poll_single(task)
            except Exception as e:
                await self.task_repo.update(task.id, status=TaskStatus.FAILED, error_message=str(e))
                await self.send_callback(task, TaskStatus.FAILED, [], str(e))

    async def _poll_single(self, task: Task) -> None:
        job_ids: List[str] = (task.params or {}).get("job_ids", [])
        if not job_ids:
            return
        output_oss_keys = []
        all_done = True

        for job_id in job_ids:
            data = await self.subtitle_erase_service.get_result(job_id)
            if not data:
                all_done = False
                continue

            new_status = QUVIDEO_STATUS_MAP.get(data.state)
            if new_status == TaskStatus.FAILED:
                raise RuntimeError(f"QuVideo job {job_id} failed: {data.engine_message}")
            if new_status != TaskStatus.SUCCESS:
                all_done = False
                continue

            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            await self.subtitle_erase_service.download_result(data.task_result.video_url, tmp_path)

            oss_key = f"{settings.alibaba.oss_output_prefix}/{task.cloud_task_id}/{job_id}.mp4"
            await self.oss_client.upload_file(str(tmp_path), oss_key)
            os.remove(tmp_path)
            output_oss_keys.append(oss_key)

        if not all_done:
            return

        await self.task_repo.update(task.id, status=TaskStatus.SUCCESS, output_files=output_oss_keys)
        await self.send_callback(task, TaskStatus.SUCCESS, output_oss_keys)


@celery_app.task(name="app.tasks.process.process_video_task")
def process_video_task(task_id: int) -> None:
    """接收任务 ID，驱动完整的视频处理流水线。"""
    run_in_worker(TaskProcessor(task_id).execute_task())


@celery_app.task(name="app.tasks.process.poll_erase_tasks")
def poll_erase_tasks() -> None:
    """定时轮询 QuVideo，处理完成的擦除任务并回调翻译平台。"""
    run_in_worker(TaskProcessor().polling())
