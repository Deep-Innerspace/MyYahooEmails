"""Abstract base class for all LLM providers."""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from src import telemetry


@dataclass
class LLMResponse:
    content: str          # Raw text response from the model
    input_tokens: int     # Tokens consumed in prompt
    output_tokens: int    # Tokens generated
    model_id: str         # Exact model string used
    provider_name: str    # 'claude', 'groq', 'openai', 'ollama'
    latency_ms: int       # Wall-clock time in milliseconds


class LLMProvider(ABC):
    """Unified interface for all LLM providers."""

    name: str = ""   # Override in subclass, e.g. 'groq'

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> LLMResponse:
        """Send a prompt and return the model response."""
        ...

    def complete_with_retry(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ) -> LLMResponse:
        """Retry with exponential backoff on transient errors."""
        last_exc = None
        for attempt in range(max_retries):
            try:
                response = self.complete(prompt, system, max_tokens, temperature)
                telemetry.record("prompt_result", {
                    "provider": response.provider_name,
                    "model_id": response.model_id,
                    "latency_ms": response.latency_ms,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "retry_count": attempt,
                    "success": True,
                })
                return response
            except Exception as e:
                last_exc = e
                # Don't retry on clear auth/config errors
                msg = str(e).lower()
                if any(k in msg for k in ("auth", "api key", "invalid", "403", "401")):
                    telemetry.record("prompt_result", {
                        "provider": self.name,
                        "retry_count": attempt,
                        "success": False,
                        "error_class": type(e).__name__,
                    })
                    raise
                # Don't retry on daily limit exhaustion (retry_after_secs signals
                # GroqDailyLimitError); caller must abort the run and wait for reset
                if hasattr(e, "retry_after_secs"):
                    telemetry.record("prompt_result", {
                        "provider": self.name,
                        "retry_count": attempt,
                        "success": False,
                        "error_class": type(e).__name__,
                        "rate_limited_tpd": True,
                    })
                    raise
                if attempt < max_retries - 1:
                    wait = retry_delay * (2 ** attempt)
                    time.sleep(wait)
        telemetry.record("prompt_result", {
            "provider": self.name,
            "retry_count": max_retries,
            "success": False,
            "error_class": type(last_exc).__name__ if last_exc else "Unknown",
        })
        raise last_exc
