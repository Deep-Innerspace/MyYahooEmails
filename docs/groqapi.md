## Groq API Rate Limiting — Findings & Patterns (empirically validated)

### Two independent rate-limit dimensions

Groq free tier enforces **two completely separate dimensions** simultaneously. Both must be handled:

| Dimension | Limit | Resets | Exposed in headers? |
|-----------|-------|--------|-------------------|
| TPM — tokens/minute | ~12,000 | Rolling 60 s | ✅ Yes |
| RPM — requests/minute | 30 | Rolling 60 s | ✅ Yes |
| TPD — tokens/day | 100,000 | **Rolling 24 h** | ❌ No |
| RPD — requests/day | 1,000 | Rolling 24 h | ✅ Yes |

### Critical: TPD is a rolling 24-hour window
The daily token limit does **not** reset at midnight. It resets on a sliding 24-hour window from when the tokens were consumed. If you hit TPD at 9 AM, quota won't clear until 9 AM the next day. Plan batch schedules accordingly.

### Critical: TPD is invisible in response headers
The `x-ratelimit-*` headers returned on every successful response expose TPM and RPD remaining — but **NOT TPD remaining**. TPD exhaustion is only detectable by receiving a 429 with a long `Retry-After` header (typically thousands of seconds).

### Recommended two-layer protection

**Layer 1 — Proactive rolling token bucket (handles TPM)**
```python
from collections import deque
import time

_token_log = deque()  # module-level: persists across instances in the same process
_WINDOW = 60          # seconds
_TPM_LIMIT = 10000    # set conservatively below the 12K ceiling

def _throttle(estimated_tokens):
    cutoff = time.monotonic() - _WINDOW
    while _token_log and _token_log[0][0] < cutoff:
        _token_log.popleft()
    used = sum(t for _, t in _token_log)
    if used + estimated_tokens > _TPM_LIMIT:
        sleep_secs = (_WINDOW - (time.monotonic() - _token_log[0][0])) + 0.5
        if sleep_secs > 0:
            time.sleep(sleep_secs)

def _record(tokens):
    _token_log.append((time.monotonic(), tokens))

# Token estimation (conservative):
estimated = len(prompt) // 4 + max_tokens // 2
```

**Layer 2 — Reactive 429 handler (handles both TPM and TPD)**
```python
from groq import RateLimitError

DAILY_THRESHOLD = 300  # seconds — separates TPM (~10-120s) from TPD (~3000-86400s)

except RateLimitError as exc:
    retry_after = None
    try:
        ra = exc.response.headers.get("retry-after") or exc.response.headers.get("Retry-After")
        retry_after = float(ra) if ra else None
    except Exception:
        pass

    if retry_after and retry_after > DAILY_THRESHOLD:
        # Daily limit hit — abort cleanly, do NOT retry
        raise DailyLimitError(f"TPD exhausted. Retry after {retry_after:.0f}s (~{retry_after/3600:.1f}h)")

    # Per-minute limit — sleep and retry
    delay = retry_after if retry_after else BASE_DELAY * (2 ** attempt) * (1 + random.uniform(-0.5, 0.5))
    time.sleep(delay)
```

### Reading live quota headers
Use `with_raw_response` to read rate-limit headers on every successful call:
```python
from groq import Groq

client = Groq(api_key=...)
raw = client.with_raw_response.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": prompt}],
    max_tokens=max_tokens,
)
# Read quota before parsing response
remaining_tokens   = raw.headers.get("x-ratelimit-remaining-tokens")   # TPM remaining
remaining_requests = raw.headers.get("x-ratelimit-remaining-requests") # RPD remaining
reset_tokens       = raw.headers.get("x-ratelimit-reset-tokens")       # e.g. "215ms"
reset_requests     = raw.headers.get("x-ratelimit-reset-requests")     # e.g. "1m26s"
# Then get the actual response
parsed = raw.parse()
content = parsed.choices[0].message.content
```

### Diagnostic probe (minimal cost: ~44 tokens)
```python
raw = client.with_raw_response.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": "Reply with the single word: OK"}],
    max_tokens=5,
    temperature=0.0,
)
# Check headers — but remember: a passing probe does NOT guarantee a full batch won't hit TPD
```

### Config keys to expose (recommended)
```yaml
groq:
  model: llama-3.3-70b-versatile
  rate_limit_tokens_per_min: 10000   # TPM ceiling — tune below the 12K hard limit
  rate_limit_tokens_per_day: 100000  # TPD ceiling — used to size daily batches
  rate_limit_requests_per_min: 30    # RPM (informational — rarely the bottleneck)
  daily_limit_threshold_secs: 300    # Retry-After above this = TPD hit, abort
```

### Groq Python SDK notes
- Model tested: `llama-3.3-70b-versatile` — handles French legal text fluently
- SDK: `groq` PyPI package — mirrors OpenAI SDK structure; `RateLimitError` has `.response.headers`
- `with_raw_response` gives direct access to the underlying `httpx` response object
- Token bucket must be **module-level** (not instance-level) to persist across multiple provider instances in the same process

---