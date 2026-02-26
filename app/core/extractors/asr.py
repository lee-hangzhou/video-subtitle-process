import os
from typing import Optional

import torch
import whisper
from whisper.transcribe import transcribe

from app.core import logger
from app.schemas.subtitle_extract import ASRConfig, SubtitleSegment
from app.utils.retry import retry
from app.utils.str import write_srt
from app.vars.constants import VIDEO_FORMATS, AUDIO_FORMATS


class ASRExtractor:

    def __init__(self, config: Optional[ASRConfig] = None):
        self.config = config or ASRConfig()
        self._model: Optional[whisper.Whisper] = None
        self._device: Optional[str] = None

    @property
    def device(self) -> str:
        if self._device is None:
            if self.config.use_gpu and torch.cuda.is_available():
                self._device = "cuda"
            else:
                self._device = "cpu"
                if self.config.use_gpu:
                    logger.warning("CUDA not available, falling back to CPU for ASR")
        return self._device

    @property
    def model(self) -> whisper.Whisper:
        if self._model is None:
            logger.info(f"Loading Whisper model: {self.config.model_name} on {self.device}")
            self._model = whisper.load_model(self.config.model_name, device=self.device)
        return self._model

    def extract(self, input_path: str, output_path: Optional[str] = None) -> str:
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"Input file not found: {input_path}")

        ext = os.path.splitext(input_path)[1].lower()
        if ext not in VIDEO_FORMATS | AUDIO_FORMATS:
            raise ValueError(f"Unsupported file format: {ext}")

        if output_path is None:
            output_path = os.path.splitext(input_path)[0] + "_asr.srt"

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        segments = self._transcribe(input_path)
        write_srt(segments, output_path)

        return output_path

    @retry(max_retries=3, exceptions=(RuntimeError, Exception), delay_base=1)
    def _transcribe(self, input_path: str) -> list[SubtitleSegment]:
        result = transcribe(
            model=self.model,
            audio=input_path,
            language=self.config.language,  # type:ignore
            condition_on_previous_text=False,
            verbose=False,
        )

        segments = []
        for idx, seg in enumerate(result.get("segments", []), start=1):
            text = seg.get("text", "").strip()
            if not text:
                continue

            start_time = seg.get("start", 0.0)
            end_time = seg.get("end", 0.0)

            if start_time >= end_time:
                continue

            segments.append(SubtitleSegment(
                index=idx,
                start_time=start_time,
                end_time=end_time,
                text=text,
            ))

        return segments
