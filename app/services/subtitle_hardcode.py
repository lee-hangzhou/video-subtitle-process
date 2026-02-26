import asyncio
from pathlib import Path
from typing import Optional

from app.core import logger, settings
from app.schemas.hardcode import SubtitleStyle, QualityConfig
from app.schemas.transcode import ProcessResult
from app.utils.file import extract_number_from_filename
from app.utils.hardcode import hardcode_subtitle
from app.vars.constants import HARDCODE_VIDEO_FORMATS, ALLOWED_SUBTITLE_FORMATS


class SubtitleHardcodeService:
    @staticmethod
    def _collect_files(directory: Path, extensions: set[str]) -> dict[int, Path]:
        """收集文件，用文件名中的数字作为 key"""
        result = {}
        for file in directory.iterdir():
            if file.is_file() and file.suffix.lower() in extensions:
                num = extract_number_from_filename(file.stem)
                if num is not None:
                    result[num] = file
        return result

    def _match_files(
            self,
            video_dir: Path,
            subtitle_dir: Path,
    ) -> list[tuple[Path, Path, int]]:
        """匹配视频和字幕，返回 (视频路径, 字幕路径, 数字编号)"""
        videos = self._collect_files(video_dir, HARDCODE_VIDEO_FORMATS)
        subtitles = self._collect_files(subtitle_dir, ALLOWED_SUBTITLE_FORMATS)

        matched = []
        for num, video_path in videos.items():
            if num in subtitles:
                matched.append((video_path, subtitles[num], num))

        return matched

    @staticmethod
    async def _process_single(
            video_path: Path,
            subtitle_path: Path,
            output_dir: Path,
            output_num: int,
            style: Optional[SubtitleStyle],
            quality: Optional[QualityConfig],
            semaphore: asyncio.Semaphore,
    ) -> ProcessResult:
        """压制单个视频，通过 semaphore 限制并发数。"""
        video_name = video_path.name
        output_path = output_dir / f"{output_num}{video_path.suffix}"

        async with semaphore:
            try:
                await asyncio.to_thread(
                    hardcode_subtitle,
                    video_path=str(video_path),
                    subtitle_path=str(subtitle_path),
                    output_path=str(output_path),
                    style=style,
                    quality=quality,
                )
                logger.info(f"completed: {video_name}")
                return ProcessResult(video_name=video_name, success=True)
            except Exception as e:
                logger.error(f"failed: {video_name}, error: {e}")
                return ProcessResult(video_name=video_name, success=False, error=str(e))

    async def batch_hardcode(
            self,
            video_dir: str,
            subtitle_dir: str,
            output_dir: str,
            style: Optional[SubtitleStyle] = None,
            quality: Optional[QualityConfig] = None,
            max_workers: int = None,
    ) -> list[ProcessResult]:
        """批量压制字幕，通过文件名匹配视频和字幕。"""
        video_path = Path(video_dir)
        subtitle_path = Path(subtitle_dir)
        output_path = Path(output_dir)

        if not video_path.is_dir():
            raise ValueError(f"video directory not found: {video_dir}")
        if not subtitle_path.is_dir():
            raise ValueError(f"subtitle directory not found: {subtitle_dir}")

        output_path.mkdir(parents=True, exist_ok=True)

        if max_workers is None:
            max_workers = settings.ffmpeg_workers

        matched = self._match_files(video_path, subtitle_path)
        if not matched:
            logger.warning("no matched video-subtitle pairs found")
            return []

        logger.info(f"found {len(matched)} matched pairs")

        semaphore = asyncio.Semaphore(max_workers)
        results = await asyncio.gather(*[
            self._process_single(video, subtitle, output_path, num, style, quality, semaphore)
            for video, subtitle, num in matched
        ])

        success_count = sum(1 for r in results if r.success)
        logger.info(f"batch completed: {success_count}/{len(results)} succeeded")

        return list(results)


subtitle_hardcode_service = SubtitleHardcodeService()
