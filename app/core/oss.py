import asyncio
import atexit
from concurrent.futures import ThreadPoolExecutor

import oss2

from app.core import settings


class OssClient:
    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="oss_",
        )
        auth = oss2.Auth(
            settings.ALIBABA.access_key_id,
            settings.ALIBABA.access_key_secret,
        )
        self.bucket = oss2.Bucket(
            auth,
            settings.ALIBABA.oss_endpoint,
            settings.ALIBABA.oss_bucket_name,
        )
        atexit.register(self._shutdown)

    async def upload_file(self, local_path: str, oss_key: str) -> None:
        """将本地文件上传到 OSS。"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self._executor,
            lambda: self.bucket.put_object_from_file(oss_key, local_path),
        )

    async def download_file(self, oss_key: str, local_path: str) -> None:
        """从 OSS 下载文件到本地路径。"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            self._executor,
            lambda: self.bucket.get_object_to_file(oss_key, local_path),
        )

    async def sign_url(self, oss_key: str, expires: int = 3600) -> str:
        """生成带时效的 GET 签名 URL。"""
        return self.bucket.sign_url("GET", oss_key, expires)

    async def aclose(self) -> None:
        """关闭专用线程池，供 lifespan 或 Worker shutdown 调用。"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._executor.shutdown, True)

    def _shutdown(self) -> None:
        self._executor.shutdown(wait=False)


oss_client = OssClient()
