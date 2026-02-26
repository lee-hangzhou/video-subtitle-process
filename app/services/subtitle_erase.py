import os
import tempfile
from pathlib import Path

import httpx

from app.core import logger
from app.core.oss import oss_client
from app.core.quvideo.client import quvideo
from app.core.quvideo.schema import SubtitleEraseRequest
from app.utils.retry import retry
from app.vars.constants import CHUNK_SIZE


class SubtitleEraseService:

    @retry()
    async def upload_and_submit(self, local_path: Path, oss_key: str) -> str:
        """上传视频到 OSS 并提交 QuVideo 字幕擦除，返回 business_id。"""
        await oss_client.upload_file(str(local_path), oss_key)
        video_url = await oss_client.sign_url(oss_key)
        request = SubtitleEraseRequest(videoUrl=video_url)
        response = await quvideo.erase_subtitle(request)
        logger.info(f"submitted erase job: {local_path.name}, business_id: {response.business_id}")
        return response.business_id

    @retry()
    async def get_result(self, job_id: str):
        """查询 QuVideo 擦除任务结果，返回原始 response.data。"""
        response = await quvideo.get_task_result(job_id)
        return response.data

    @retry()
    async def download_result(self, url: str, local_path: Path) -> None:
        """从 URL 下载处理完成的视频到本地路径。"""
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                with open(local_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=CHUNK_SIZE):
                        f.write(chunk)
        logger.info(f"downloaded erase result: {local_path.name}")


subtitle_erase_service = SubtitleEraseService()
