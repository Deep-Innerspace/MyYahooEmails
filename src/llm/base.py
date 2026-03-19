"""Abstract base class for all LLM providers."""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


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
                return self.complete(prompt, system, max_tokens, temperature)
            except Exception as e:
                last_exc = e
                # Don't retry on clear auth/config errors
                msg = str(e).lower()
                if any(k in msg for k in ("auth", "api key", "invalid", "403", "401")):
                    raise
                if attempt < max_retries - 1:
                    wait = retry_delay * (2 ** attempt)
                    time.sleep(wait)
        raise last_exc
