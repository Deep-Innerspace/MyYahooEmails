"""Lightweight telemetry stub.

No-op by default. When env var ``TELEMETRY_DEBUG_FILE`` is set, events are
appended as JSONL to that path for local inspection. There is intentionally no
network transport, no consent UI, and no scrubber yet — see
``docs/telemetry-spec.md`` for the full spec that will be implemented once the
product has external users.

The one value this module provides today is **call-site stability**: adding
``telemetry.record(...)`` hooks now means the future pipeline can plug in
without touching every analysis file again.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_ENV_DEBUG_FILE = "TELEMETRY_DEBUG_FILE"
_ENV_DISABLED = "TELEMETRY_DISABLED"


def _debug_path() -> Optional[Path]:
    if os.environ.get(_ENV_DISABLED) == "1":
        return None
    raw = os.environ.get(_ENV_DEBUG_FILE)
    if not raw:
        return None
    return Path(raw).expanduser()


def record(event_type: str, payload: Dict[str, Any], tier: str = "metrics") -> None:
    """Record a telemetry event. No-op unless TELEMETRY_DEBUG_FILE is set.

    Args:
        event_type: one of the types in docs/telemetry-spec.md
            (prompt_result, user_correction, feature_funnel, corpus_shape,
            error, redacted_sample).
        payload: event-specific fields. See spec for schema.
        tier: consent tier required to transmit (metrics | error_reports |
            redacted_samples). Unused today; preserved for future use.
    """
    path = _debug_path()
    if path is None:
        return
    envelope = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tier": tier,
        "event_type": event_type,
        "payload": payload,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(envelope, ensure_ascii=False) + "\n")
    except Exception:
        # Telemetry must never break the caller.
        pass


class Timer:
    """Context manager for latency measurement.

    Usage:
        with telemetry.Timer() as t:
            result = do_work()
        telemetry.record("prompt_result", {..., "latency_ms": t.ms})
    """

    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.ms = int((time.perf_counter() - self._start) * 1000)
