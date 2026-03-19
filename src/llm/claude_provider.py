"""Anthropic Claude provider."""
import os
import time
from typing import Optional

import anthropic

from src.llm.base import LLMProvider, LLMResponse


class ClaudeProvider(LLMProvider):
    name = "claude"

    def __init__(self, model: str = "claude-sonnet-4-6"):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY not set in .env")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> LLMResponse:
        t0 = time.monotonic()
        kwargs = dict(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        if system:
            kwargs["system"] = system

        response = self._client.messages.create(**kwargs)
        latency = int((time.monotonic() - t0) * 1000)

        return LLMResponse(
            content=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model_id=response.model,
            provider_name=self.name,
            latency_ms=latency,
        )
