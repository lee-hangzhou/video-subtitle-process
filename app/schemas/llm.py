from dataclasses import dataclass
from typing import Optional


@dataclass
class CompletionResponse:
    content: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None
