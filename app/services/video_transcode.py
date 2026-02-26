import asyncio
from pathlib import Path

from app.core import logger, settings
from app.schemas.transcode import TranscodeConfig, ProcessResult
from app.utils.transcode import transcode
from app.vars.constants import HARDCODE_VIDEO_FORMATS


class VideoTranscodeService:
    def __init__(self, video_formats: list[str] = None):
        self.video_formats = video_formats or HARDCODE_VIDEO_FORMATS

    def _get_video_files(self, directory: Path) -> list[Path]:
        return [
            f for f in directory.iterdir()
            if f.is_file() and f.suffix.lower() in self.video_formats
        ]

    @staticmethod
    async def _process_single(
        video_path: Path,
        output_dir: Path,
        config: TranscodeConfig,
        semaphore: asyncio.Semaphore,
    ) -> ProcessResult:
        """转码单个视频，通过 semaphore 限制并发数。"""
        video_name = video_path.name
        output_path = output_dir / video_name

        async with semaphore:
            try:
                await asyncio.to_thread(
                    transcode,
                    input_path=str(video_path),
                    output_path=str(output_path),
                    config=config,
                )
                return ProcessResult(video_name=video_name, success=True)
            except Exception as e:
                logger.error(f"failed: {video_name}, error: {e}")
                return ProcessResult(video_name=video_name, success=False, error=str(e))

    async def batch_transcode(
        self,
        video_dir: str,
        output_dir: str,
        config: TranscodeConfig,
        max_workers: int = None,
    ) -> list[ProcessResult]:
        """批量转码视频。"""
        video_path = Path(video_dir).resolve()
        output_path = Path(output_dir).resolve()

        if not video_path.is_dir():
            raise ValueError(f"video directory not found: {video_dir}")

        if video_path == output_path:
            output_path = output_path / "output"
            logger.warning(f"input and output are the same, using: {output_path}")

        output_path.mkdir(parents=True, exist_ok=True)

        if max_workers is None:
            max_workers = settings.ffmpeg_workers

        video_files = self._get_video_files(video_path)
        if not video_files:
            logger.warning(f"no video files found in {video_dir}")
            return []

        codec = config.video.codec.value if config else "hevc_nvenc"
        logger.info(f"found {len(video_files)} videos, codec: {codec}, max_workers: {max_workers}")

        semaphore = asyncio.Semaphore(max_workers)
        results = await asyncio.gather(*[
            self._process_single(video, output_path, config, semaphore)
            for video in video_files
        ])

        success_count = sum(1 for r in results if r.success)
        logger.info(f"batch completed: {success_count}/{len(results)} succeeded")

        return list(results)


video_transcode_service = VideoTranscodeService()
