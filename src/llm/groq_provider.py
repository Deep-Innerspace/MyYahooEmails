"""Groq provider (free/cheap tier — ideal for high-volume classification).

Rate limiting strategy
─────────────────────
Groq free tier for llama-3.3-70b-versatile has TWO independent limits:

  Per-minute limits (TPM):
    • 30 requests / minute
    • ~12 000 tokens / minute  (configurable: config.yaml → rate_limit_tokens_per_min)

  Per-day limit (TPD):
    • 100 000 tokens / day  (rolling 24-hour window)

Proactive throttle — rolling 60-second token bucket (handles TPM):
  - After each successful call we log (timestamp, total_tokens_used).
  - Before the NEXT call we sum tokens used in the last 60 s.
  - If that sum + estimated next call would exceed the per-minute limit, we sleep
    until the oldest bucket entry exits the 60-second window.

Reactive 429 handling (handles both TPM and TPD):
  Two 429 flavours returned by Groq:
    - TPM  429  →  Retry-After is short  (seconds to ~2 minutes)
    - TPD  429  →  Retry-After is long   (up to several hours)

  On RateLimitError:
    1. Parse Retry-After header (seconds).
    2. If Retry-After > _DAILY_LIMIT_THRESHOLD_SECS → raise GroqDailyLimitError
       immediately. Callers should abort the run cleanly instead of retrying.
    3. If Retry-After is short (TPM) → sleep exactly that many seconds, retry.
    4. If Retry-After is absent → exponential back-off with ±50 % jitter.
    5. Max _MAX_RETRIES attempts before re-raising.
"""
import os
import random
import time
from collections import deque
from typing import Deque, Optional, Tuple

from groq import Groq, RateLimitError

from src.config import groq_daily_limit_threshold_secs, groq_token_rate_limit
from src.llm.base import LLMProvider, LLMResponse


# ── constants ────────────────────────────────────────────────────────────────

_WINDOW_SECS              = 60     # rolling per-minute window (seconds)
_MAX_RETRIES              = 5      # maximum TPM 429 retries
_BASE_DELAY               = 2.0    # seconds for first back-off (no Retry-After)
_JITTER                   = 0.5    # ± random jitter fraction
_DAILY_LIMIT_THRESHOLD    = groq_daily_limit_threshold_secs()  # from config.yaml


# ── custom exception ─────────────────────────────────────────────────────────

class GroqDailyLimitError(Exception):
    """Raised when Groq's per-day token limit (TPD) is exhausted.

    The `retry_after_secs` attribute contains the server-suggested wait time.
    Callers should abort the current analysis run gracefully and display this
    value to the user instead of retrying in a tight loop.
    """
    def __init__(self, retry_after_secs: float, original_message: str = ""):
        self.retry_after_secs = retry_after_secs
        mins = int(retry_after_secs // 60)
        secs = int(retry_after_secs % 60)
        super().__init__(
            f"Groq daily token limit (100k/day) exhausted. "
            f"Retry after {mins}m {secs}s. "
            f"Original: {original_message}"
        )


# ── token bucket (module-level so it persists across calls in the same process)

_token_log: Deque[Tuple[float, int]] = deque()   # (monotonic_timestamp, tokens_used)


def _tokens_used_in_window() -> int:
    """Sum tokens consumed in the last 60 seconds, pruning stale entries."""
    cutoff = time.monotonic() - _WINDOW_SECS
    while _token_log and _token_log[0][0] < cutoff:
        _token_log.popleft()
    return sum(t for _, t in _token_log)


def _record_tokens(tokens: int) -> None:
    _token_log.append((time.monotonic(), tokens))


def _throttle_if_needed(estimated_tokens: int, limit: int) -> None:
    """Sleep until sending `estimated_tokens` would stay within `limit`/min."""
    used = _tokens_used_in_window()
    if used + estimated_tokens <= limit:
        return
    # Sleep until the oldest logged entry exits the 60-second window
    if _token_log:
        oldest_ts = _token_log[0][0]
        sleep_secs = (_WINDOW_SECS - (time.monotonic() - oldest_ts)) + 0.5
        if sleep_secs > 0:
            time.sleep(sleep_secs)
    # Prune again after sleeping
    _tokens_used_in_window()


def _parse_retry_after(exc: RateLimitError) -> Optional[float]:
    """Extract the Retry-After value (seconds) from a 429 response header."""
    try:
        header = (
            exc.response.headers.get("retry-after")
            or exc.response.headers.get("Retry-After")
        )
        if header:
            return float(header)
    except Exception:
        pass
    return None


# ── provider ─────────────────────────────────────────────────────────────────

class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise EnvironmentError("GROQ_API_KEY not set in .env")
        self._client = Groq(api_key=api_key)
        self._model  = model
        self._limit  = groq_token_rate_limit()   # per-minute limit from config

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.1,
    ) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        # Estimate tokens before the call:
        #   input  → 1 token ≈ 4 chars (conservative)
        #   output → use half of max_tokens (actual output is well below ceiling)
        estimated = len(prompt) // 4 + max_tokens // 2

        for attempt in range(_MAX_RETRIES + 1):
            # ── proactive per-minute token-bucket throttle ───────────────────
            _throttle_if_needed(estimated, self._limit)

            t0 = time.monotonic()
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except RateLimitError as exc:
                retry_after = _parse_retry_after(exc)

                # ── daily limit hit → abort immediately, don't retry ─────────
                if retry_after is not None and retry_after > _DAILY_LIMIT_THRESHOLD:
                    raise GroqDailyLimitError(
                        retry_after_secs=retry_after,
                        original_message=str(exc),
                    )

                # ── per-minute limit → sleep then retry ─────────────────────
                if attempt >= _MAX_RETRIES:
                    raise
                delay = retry_after if retry_after is not None else (
                    _BASE_DELAY * (2 ** attempt) * (1 + random.uniform(-_JITTER, _JITTER))
                )
                time.sleep(delay)
                continue

            latency = int((time.monotonic() - t0) * 1000)
            usage   = response.usage
            in_tok  = usage.prompt_tokens     if usage else 0
            out_tok = usage.completion_tokens if usage else 0

            # ── record actual token usage for next throttle check ────────────
            _record_tokens(in_tok + out_tok)

            return LLMResponse(
                content=response.choices[0].message.content or "",
                input_tokens=in_tok,
                output_tokens=out_tok,
                model_id=response.model,
                provider_name=self.name,
                latency_ms=latency,
            )

        raise RuntimeError("Groq: exhausted retries without a successful response")
