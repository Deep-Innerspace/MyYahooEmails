# Telemetry Spec (deferred)

Status: **Spec only — not implemented.** Drafted 2026-04-19 for future use when the
product has external users. Today there is only one user (the author), so the
only live piece is a local JSONL dump for self-iteration on prompts.

## Goal

Collect enough signal to refine prompts, models, and UX **without ever
exfiltrating corpus content**. The target artifacts are prompt A/B results,
user-correction distributions, and funnel drop-offs — not the emails
themselves.

## Consent model (fails closed)

Three independent toggles in Settings, **all default off**:

| Toggle             | What it sends                                              | Risk   |
|--------------------|------------------------------------------------------------|--------|
| `metrics`          | Counts, timings, scores, booleans — no strings from corpus | Very low |
| `error_reports`    | Stack traces with file:line + scrubbed message             | Low    |
| `redacted_samples` | Prompt/output pairs after NER redaction + thumbs-down text | Medium (explicit opt-in) |

- Env var `TELEMETRY_DISABLED=1` short-circuits the entire module.
- Settings page must have a **"Preview last 24 h of telemetry"** view that dumps
  the local queue as JSON so the user sees exactly what would leave the
  machine. This is the trust feature.

## Event envelope

```json
{
  "event_id": "uuid4",
  "installation_id": "sha256(machine_id + salt)",
  "app_version": "0.9.1",
  "ts": "2026-04-19T12:34:56Z",
  "tier": "metrics | error_reports | redacted_samples",
  "event_type": "...",
  "payload": { ... }
}
```

## Event types

### `prompt_result` (tier: metrics)
One per LLM call. Single highest-value event.

```json
{
  "analysis_type": "tone",
  "provider": "groq", "model_id": "llama-3.3-70b-versatile",
  "prompt_hash": "abc123", "prompt_version": "v4",
  "latency_ms": 1240, "input_tokens": 1500, "output_tokens": 380,
  "parse_success": true, "parse_error_type": null,
  "retry_count": 0, "rate_limited_tpm": false, "rate_limited_tpd": false,
  "confidence_distribution": [0.8, 0.6, 0.9]
}
```

### `user_correction` (tier: metrics)
The gold signal for prompt refinement.

```json
{
  "analysis_type": "manipulation",
  "action": "edited | regenerated | deleted | overridden | accepted",
  "edit_distance_chars": 42,
  "score_delta": -0.5,
  "time_to_action_secs": 15
}
```

### `feature_funnel` (tier: metrics)
```json
{ "feature": "reply_generate", "step": "start|complete|abandon", "duration_secs": 12 }
```

### `corpus_shape` (tier: metrics, once per session, bucketed)
```json
{
  "email_count_bucket": "1000-5000",
  "date_span_years": 12,
  "language_mix": {"fr": 0.98, "en": 0.02},
  "personal_legal_ratio": 0.6,
  "topics_applied_count": 15
}
```

### `error` (tier: error_reports)
```json
{
  "component": "groq_provider",
  "error_class": "TimeoutError",
  "message": "<scrubbed>",
  "stack": ["file.py:42", "..."]
}
```

### `redacted_sample` (tier: redacted_samples — only on thumbs-down or parse failure)
```json
{
  "analysis_type": "manipulation",
  "prompt_hash": "abc123",
  "redacted_input": "Le [DATE] à [TIME], [PERSON_1] a écrit : [REDACTED_SPAN_120]...",
  "redacted_output": "...",
  "user_thumbs": -1,
  "user_comment": "missed passive aggression"
}
```

## Scrubber

Single class, ordered passes. **Fails closed**: unknown string >100 chars →
replaced by `[REDACTED_SPAN_<length>]`.

```python
class Scrubber:
    def __init__(self, conn):
        self.names  = _load_contact_names(conn)
        self.emails = _load_contact_emails(conn)
        self.person_map = {}  # stable [PERSON_1], [PERSON_2] within one event

    PATTERNS = [
        (r"[\w.+-]+@[\w.-]+\.\w+",               "[EMAIL]"),
        (r"\b0[1-9](?:[\s.-]?\d{2}){4}\b",       "[PHONE_FR]"),
        (r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b", "[DATE]"),
        (r"\b\d{1,3}(?:[\s.]\d{3})*(?:,\d+)?\s?€", "[AMOUNT]"),
        (r"\b\d{2}/\d{4,6}\b",                   "[CASENUM]"),
        (r"\biban\s*[:=]?\s*[A-Z0-9 ]{15,34}",   "[IBAN]"),
    ]

    def scrub(self, text: str) -> str:
        for pattern, replacement in self.PATTERNS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        for name in sorted(self.names, key=len, reverse=True):  # longest first
            if name in text:
                token = self.person_map.setdefault(name, f"[PERSON_{len(self.person_map)+1}]")
                text = text.replace(name, token)
        return text
```

## Architecture rules

- `src/telemetry.py` is the **only** module allowed to make outbound HTTP calls
  related to telemetry. Add a CI grep-check: `httpx`/`requests` imports outside
  this module are a violation.
- The scrubber runs **inside** `record()` before any payload is serialized.
- Local SQLite queue table `telemetry_queue (id, payload_json, tier, created_at,
  sent_at)` — lets telemetry survive offline use and gives a single place to
  preview.
- Upload endpoint is config-driven (env var `TELEMETRY_URL`) — point at a local
  dev server first, swap to prod later.

## What gets built today vs. later

**Today (pre-launch, single user):**
- `src/telemetry.py` stub with `record()` that appends to `data/telemetry.jsonl`
  when `TELEMETRY_DEBUG_FILE` env var is set. No-op otherwise.
- One instrumentation point in `src/llm/base.py::complete_with_retry` emitting
  `prompt_result` events.
- This doc saved for reference.

**Deferred until external users exist:**
- Scrubber implementation.
- Consent UI + settings toggles.
- SQLite queue + batch uploader.
- Server-side aggregation.
- `user_correction`, `feature_funnel`, `corpus_shape`, `error`, `redacted_sample`
  event types.

## Rationale

Instrumenting call sites is the expensive part to retrofit (20+ files); the
transport and server are trivial to bolt on later. Ship the hooks; defer the
pipeline until it has a consumer.
