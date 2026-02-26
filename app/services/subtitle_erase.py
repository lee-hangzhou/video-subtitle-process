import asyncio
import time
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

from app.core import logger
from app.core.oss import OssClient
from app.core.quvideo.client import quvideo
from app.core.quvideo.schema import SubtitleEraseRequest
from app.models.task import Task
from app.repositories.task import TaskRepository
from app.schemas.task import TaskSource, QUVIDEO_STATUS_MAP, TaskStatus
from app.utils.retry import retry
from app.vars.constants import HARDCODE_VIDEO_FORMATS, CHUNK_SIZE


class BaseVideoService(ABC):
    source: str
    video_formats: list[str]

    def __init__(self):

        self.oss_client = OssClient()
        self.task_repo = TaskRepository()

    async def submit(self, directory: str) -> None:
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            logger.error(f"directory not exists: {directory}")
            return

        timestamp = int(time.time())
        task_name = f"{dir_path.name}-{timestamp}"
        video_files = await self._get_video_files(dir_path)

        if not video_files:
            logger.warning(f"no video files found in {directory}")
            return

        logger.info(f"found {len(video_files)} videos, task_name: {task_name}")

        for video in video_files:
            await self._process_video(video, task_name)

    async def query(self) -> None:
        tasks = await self.task_repo.get_pending(source=self.source)
        if not tasks:
            logger.info("no pending tasks")
            return

        logger.info(f"found {len(tasks)} pending tasks")

        for task in tasks:
            await self._query_single_task(task)

    async def download(self, task_name: str, output_dir: str) -> None:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        tasks = await self.task_repo.get_success_by_task_name(task_name)
        if not tasks:
            logger.warning(f"no success tasks for: {task_name}")
            return

        logger.info(f"downloading {len(tasks)} videos")

        for task in tasks:
            await self._download_single_video(task, output_path)

        await self._post_download(output_path)

    async def _get_video_files(self, directory: Path) -> list[Path]:
        return [
            f for f in directory.iterdir()
            if f.is_file() and f.suffix.lower() in self.video_formats
        ]

    @retry()
    async def _upload_video(self, video_path: Path, oss_key: str) -> str:
        await asyncio.to_thread(self.oss_client.upload_file, str(video_path), oss_key)
        return await asyncio.to_thread(self.oss_client.sign_url, oss_key)

    @retry()
    async def _download_from_url(self, url: str, local_path: Path) -> None:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                        f.write(chunk)
        logger.info(f"downloaded: {local_path.name}")

    async def _post_download(self, output_path: Path) -> None:
        pass

    @abstractmethod
    async def _process_video(self, video_path: Path, task_name: str) -> None:
        pass

    @abstractmethod
    async def _query_single_task(self, task: Task) -> None:
        pass

    @abstractmethod
    async def _download_single_video(self, task: Task, output_dir: Path) -> None:
        pass


class SubtitleEraseService(BaseVideoService):
    source = TaskSource.QUVIDEO
    video_formats = HARDCODE_VIDEO_FORMATS

    @retry()
    async def _call_erase_api(self, video_url: str) -> str:
        request = SubtitleEraseRequest(videoUrl=video_url)
        response = await quvideo.erase_subtitle(request)
        return response.business_id

    async def _process_video(self, video_path: Path, task_name: str) -> None:
        video_stem = video_path.stem
        oss_key = f"quvideo/input/{task_name}/{video_path.name}"
        title = f"{task_name}-{video_stem}"

        try:
            video_url = await self._upload_video(video_path, oss_key)
        except Exception as e:
            logger.error(f"upload failed: {video_path}, error: {e}")
            return

        params = {"videoUrl": video_url, "version": 2}

        task = await self.task_repo.create_task(
            source=self.source,
            task_name=task_name,
            input_url=oss_key,
            title=title,
            params=params,
        )

        try:
            business_id = await self._call_erase_api(video_url)
            await self.task_repo.update(task.id, job_id=business_id, status=TaskStatus.RUNNING.value)
            logger.info(f"task {task.id} submitted, business_id: {business_id}")
        except Exception as e:
            logger.error(f"api call failed: {video_path}, error: {e}")
            await self.task_repo.update_status(task.id, TaskStatus.FAILED)

    async def _query_single_task(self, task: Task) -> None:
        try:
            if not task.job_id:
                return

            response = await quvideo.get_task_result(task.job_id)
            if not response.data:
                return

            state = response.data.state
            new_status = QUVIDEO_STATUS_MAP.get(state, TaskStatus.RUNNING)

            if task.status != new_status.value:
                update_data = {"status": new_status.value}

                if response.data.is_completed and response.data.task_result:
                    update_data["output_url"] = response.data.task_result.video_url

                await self.task_repo.update(task.id, **update_data)
                logger.info(f"task {task.id} status: {state}")

        except Exception as e:
            logger.error(f"query task {task.id} failed: {e}")

    async def _download_single_video(self, task: Task, output_dir: Path) -> None:
        try:
            if not task.output_url:
                logger.warning(f"task {task.id} has no output_url")
                return

            filename = f"{task.title.split('-')[-1]}.mp4"
            local_path = output_dir / filename
            await self._download_from_url(task.output_url, local_path)
        except Exception as e:
            logger.error(f"download task {task.id} failed: {e}")


subtitle_erase_service = SubtitleEraseService()
