import asyncio
import os
from typing import Optional

from app.core import logger
from app.core.extractors import OCRExtractor, ASRExtractor
from app.core.llm import LLMClient
from app.schemas.subtitle_extract import OCRConfig, ASRConfig, ExtractResult
from app.vars.promtps import SUBTITLE_FUSION_USER, SUBTITLE_FUSION_SYSTEM


class SubtitleExtractService:

    def __init__(
            self,
            ocr_config: Optional[OCRConfig] = None,
            asr_config: Optional[ASRConfig] = None,
    ):
        self.ocr_config = ocr_config
        self.asr_config = asr_config
        self._ocr_extractor = None
        self._asr_extractor = None
        self._llm_client = None

    @property
    def ocr_extractor(self) -> OCRExtractor:
        if self._ocr_extractor is None:
            self._ocr_extractor = OCRExtractor(self.ocr_config)
        return self._ocr_extractor

    @property
    def asr_extractor(self) -> ASRExtractor:
        if self._asr_extractor is None:
            self._asr_extractor = ASRExtractor(self.asr_config)
        return self._asr_extractor

    @property
    def llm_client(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    async def extract(
            self,
            video_path: str,
            output_dir: Optional[str] = None,
    ) -> ExtractResult:
        """
        标准字幕提取流程：OCR + ASR + LLM 融合

        Args:
            video_path: 视频文件路径
            output_dir: 输出目录，默认为视频所在目录

        Returns:
            ExtractResult: 包含所有生成文件路径的结果对象
        """
        if output_dir is None:
            output_dir = os.path.dirname(video_path)

        process_dir = os.path.join(output_dir, "process_file")
        os.makedirs(process_dir, exist_ok=True)

        base_name = os.path.splitext(os.path.basename(video_path))[0]
        ocr_output = os.path.join(process_dir, f"{base_name}_ocr.srt")
        asr_output = os.path.join(process_dir, f"{base_name}_asr.srt")

        result = ExtractResult(video_path=video_path)

        # 并行执行 OCR 和 ASR
        outcomes = await asyncio.gather(
            self._run_ocr(video_path, ocr_output),
            self._run_asr(video_path, asr_output),
            return_exceptions=True,
        )

        errors = [str(r) for r in outcomes if isinstance(r, Exception)]
        if errors:
            result.error = "; ".join(errors)
            return result

        result.ocr_srt_path = ocr_output
        result.asr_srt_path = asr_output

        # LLM 融合
        try:
            fused_path = await self._fuse_subtitles(ocr_output, asr_output, output_dir)
            result.fused_srt_path = fused_path
        except Exception as e:
            logger.error(f"LLM fusion failed: {e}")
            result.error = f"LLM fusion failed: {e}"

        return result

    async def _run_ocr(self, video_path: str, output_path: str) -> None:
        """执行 OCR 提取"""
        try:
            await asyncio.to_thread(self.ocr_extractor.extract, video_path, output_path)
            logger.info(f"OCR extraction completed: {output_path}")
        except Exception as e:
            logger.error(f"OCR extraction failed for {video_path}: {e}")
            raise RuntimeError(f"OCR extraction failed: {e}")

    async def _run_asr(self, video_path: str, output_path: str) -> None:
        """执行 ASR 提取"""
        try:
            await asyncio.to_thread(self.asr_extractor.extract, video_path, output_path)
            logger.info(f"ASR extraction completed: {output_path}")
        except Exception as e:
            logger.error(f"ASR extraction failed for {video_path}: {e}")
            raise RuntimeError(f"ASR extraction failed: {e}")

    async def _fuse_subtitles(
            self,
            ocr_srt_path: str,
            asr_srt_path: str,
            output_dir: str,
    ) -> str:
        """用 LLM 融合 OCR 和 ASR 字幕"""
        with open(ocr_srt_path, "r", encoding="utf-8") as f:
            ocr_content = f.read()
        with open(asr_srt_path, "r", encoding="utf-8") as f:
            asr_content = f.read()

        message = SUBTITLE_FUSION_USER.format(
            ocr_content=ocr_content,
            asr_content=asr_content,
        )

        response = await self.llm_client.create_completion(
            message=message,
            system_prompt=SUBTITLE_FUSION_SYSTEM,
        )

        if not response.success:
            raise RuntimeError(f"LLM fusion failed: {response.error}")

        fused_content = self._extract_srt_content(response.content)

        base_name = os.path.splitext(os.path.basename(ocr_srt_path))[0]
        base_name = base_name.replace("_ocr", "")
        fused_path = os.path.join(output_dir, f"{base_name}.srt")

        with open(fused_path, "w", encoding="utf-8") as f:
            f.write(fused_content)

        logger.info(f"Subtitle fusion completed: {fused_path}")
        return fused_path

    @staticmethod
    def _extract_srt_content(llm_output: str) -> str:
        """从 LLM 输出中提取 SRT 内容"""
        content = llm_output.strip()

        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        return content.strip()


subtitle_extract_service = SubtitleExtractService()
