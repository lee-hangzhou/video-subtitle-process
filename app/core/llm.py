from typing import Optional

from openai import AsyncOpenAI

from app.core import settings, logger
from app.schemas.llm import CompletionResponse


class LLMClient(AsyncOpenAI):

    def __init__(
            self,
            api_key: Optional[str] = None,
            base_url: Optional[str] = None,
            **kwargs,
    ):
        super().__init__(
            api_key=api_key or settings.LLM_API_KEY,
            base_url=base_url or settings.LLM_BASE_URI,
            **kwargs,
        )
        self.default_model = settings.DEFAULT_MODEL

    async def create_completion(
            self,
            message: str,
            model: Optional[str] = None,
            system_prompt: Optional[str] = None,
            **kwargs,
    ) -> CompletionResponse:
        model = model or self.default_model

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        kwargs.setdefault("temperature", 0.7)
        kwargs.setdefault("max_tokens", 4096)

        try:
            resp = await self.chat.completions.create(
                messages=messages,
                model=model,
                **kwargs,
            )
        except Exception as e:
            logger.error(f"LLM completion failed: {e}")
            return CompletionResponse(error=str(e))

        content = ""
        if resp.choices:
            content = resp.choices[0].message.content or ""

        return CompletionResponse(
            content=content,
            prompt_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            completion_tokens=resp.usage.completion_tokens if resp.usage else 0,
            total_tokens=resp.usage.total_tokens if resp.usage else 0,
        )
