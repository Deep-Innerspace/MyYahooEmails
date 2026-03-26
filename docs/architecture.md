# MyYahooEmails — Architecture Reference

> Last updated: 2026-03-22

## High-Level Data Flow

```
Yahoo IMAP (read-only)
        │
        ▼
  imap_client.py          ← SEARCH by contact address, FETCH RFC822
        │
        ▼
    parser.py             ← MIME parse, bilingual quote strip, delta extraction,
        │                    language detection, delta_hash
        ▼
   threader.py            ← Thread reconstruction, dedup check, store_email()
        │
        ▼
   database.py            ← SQLite: emails, threads, contacts, attachments
        │                    FTS5 index (emails_fts) updated via triggers
        ▼
   analysis/              ← Phase 2+3: LLM analysis pipeline
   classifier.py          ← Topic classification (email_topics table)
   tone.py                ← Tone/aggression/manipulation analysis
   timeline.py            ← Event extraction (timeline_events table)
   contradictions.py      ← Two-pass contradiction detection (Phase 3)
   manipulation.py        ← Per-email manipulation patterns (Phase 3)
   court_correlator.py    ← Court event correlation + narrative (Phase 3)
        │
        ▼
   statistics/            ← Phase 4: SQL aggregation layer
   aggregator.py          ← 10 shared functions (CLI + reports)
        │
        ▼
   reports/               ← Phase 4: Document generation
   charts.py              ← matplotlib PNG charts
   builder.py             ← Report dataclasses + builders
   docx_renderer.py       ← Word output
   pdf_renderer.py        ← PDF output (weasyprint + Jinja2)
        │
        ▼
    search.py             ← FTS5 + metadata filtered queries
        │
        ├──────────────────────┐
        ▼                      ▼
     cli.py               web/           ← Phase 5: FastAPI + HTMX dashboard
                           app.py         ← Application factory
                           deps.py        ← get_conn(), get_perspective()
                           routes/        ← 11 route modules (49+ endpoints)
                           templates/     ← Jinja2 (base + 14 pages + 10+ partials)
                           static/        ← CSS (dual-perspective) + JS
```

## Module Map

| Module | Responsibility |
|--------|---------------|
| `src/config.py` | Load `config.yaml` + `.env`; convenience accessors |
| `src/extraction/imap_client.py` | Yahoo IMAP: connect, search, fetch raw RFC822 |
| `src/extraction/parser.py` | MIME parse, FR/EN quote strip, delta, hash, lang detect |
| `src/extraction/threader.py` | Thread reconstruction, dedup, batch store |
| `src/storage/database.py` | Schema, migrations, FTS5 triggers, seed helpers |
| `src/storage/models.py` | Dataclasses for all DB entities |
| `src/storage/search.py` | Full-text + filtered search; alias-aware |
| `src/llm/base.py` | Abstract `LLMProvider` interface |
| `src/llm/router.py` | Task → provider routing from config |
| `src/llm/claude_provider.py` | Anthropic Claude implementation |
| `src/llm/groq_provider.py` | Groq implementation |
| `src/llm/openai_provider.py` | OpenAI implementation |
| `src/llm/ollama_provider.py` | Ollama (local) implementation |
| `src/analysis/runner.py` | Run lifecycle, batch orchestration, result storage, summaries helper |
| `src/analysis/classifier.py` | Topic classification → `email_topics` |
| `src/analysis/tone.py` | Tone/aggression/manipulation → `analysis_results` |
| `src/analysis/timeline.py` | Event extraction → `timeline_events` |
| `src/analysis/contradictions.py` | Two-pass contradiction detection → `contradictions` |
| `src/analysis/manipulation.py` | Per-email manipulation pattern detection → `analysis_results` |
| `src/analysis/court_correlator.py` | Court event correlation (SQL + optional LLM narrative) |
| `src/analysis/prompts/` | 7 French-legal prompt templates |
| `src/statistics/aggregator.py` | 10 SQL aggregation functions (shared by CLI + reports) |
| `src/reports/charts.py` | matplotlib chart generators (5 chart types) |
| `src/reports/builder.py` | Report dataclasses + 4 builder functions |
| `src/reports/docx_renderer.py` | Word document renderer (python-docx) |
| `src/reports/pdf_renderer.py` | PDF renderer (weasyprint + Jinja2) |
| `src/reports/templates/report.html` | HTML template for PDF generation |
| `src/web/app.py` | FastAPI application factory, static mount, router registration |
| `src/web/deps.py` | `get_conn()` (check_same_thread=False), `get_perspective()` (cookie) |
| `src/web/routes/dashboard.py` | Dashboard + perspective switching (POST /set-perspective) |
| `src/web/routes/emails.py` | Email browser: FTS5 search, multi-topic filter, HTMX detail panel |
| `src/web/routes/notes.py` | Notes CRUD: perspective-aware add/delete with HTMX swap |
| `src/web/routes/charts.py` | 5 chart endpoints streaming matplotlib PNGs |
| `src/web/routes/timeline.py` | Merged timeline (email events + court events) with filters |
| `src/web/routes/analysis.py` | Analysis tabs (tone/topics/response-times) + contradictions + manipulation |
| `src/web/routes/contacts.py` | Contact list + detail with filtered emails |
| `src/web/routes/reports.py` | Report generation hub + download endpoint |
| `src/web/routes/settings.py` | Analysis runs overview, coverage stats, run deletion |
| `src/web/routes/book.py` | Narrative Arc, Chapters CRUD, Quote Bank, Pivotal Moments |
| `src/web/routes/court_events.py` | Court events list |
| `cli.py` | All CLI commands (click groups) + `web` command |

## Database Schema Summary

### Core tables
- **contacts** — `id, name, email, aliases (JSON), role, notes`
- **emails** — full MIME metadata + `body_text, body_html, delta_text, delta_hash, direction, language`
- **attachments** — binary content linked to emails
- **threads** — grouped by References chain + normalized subject

### Analysis tables
- **topics** — predefined + AI-discovered categories
- **email_topics** — many-to-many (email ↔ topic) with confidence + run_id
- **analysis_runs** — one row per LLM execution (provider, model, prompt_hash, status)
- **analysis_results** — per-email LLM JSON output linked to run + sender perspective
- **contradictions** — conflicting email pairs with severity + explanation
- **timeline_events** — extracted dated events with type + significance

### Context tables
- **court_events** — manually entered hearings, filings, decisions
- **external_events** — other key life dates
- **fetch_state** — `(folder, contact_email) → last_uid` for resumable IMAP fetch

### Web Dashboard (Phase 5)
- **notes** — perspective-aware annotations (`entity_type, entity_id, perspective, category, content`)
- **chapters** — book narrative chapters (`title, order_index, date_from, date_to, summary`)
- **chapter_emails** — many-to-many linking chapters ↔ emails
- **quotes** — saved email excerpts (`quote_text, email_id, tags, context`)
- **pivotal_moments** — key turning-point emails (`email_id, significance, description`)
- **bookmarks** — email bookmarks
- **generated_reports** — report generation history (`report_type, format, file_path, perspective`)

### Search
- **emails_fts** — FTS5 virtual table (subject, body_text, delta_text, from_address, from_name)
- Kept in sync automatically via INSERT/UPDATE/DELETE triggers

## Multi-LLM Provider Architecture

```
        cli.py
           │
     router.py  ←── config.yaml (task_providers mapping)
     /    |    \    \
Claude  Groq  OpenAI  Ollama
```

**Task routing** (from `config.yaml`):
- `classify` → Groq (free, fast, good enough)
- `tone` → Groq
- `timeline` → Groq (switched from Claude for cost)
- `contradictions` → Groq (dev default; switch to Claude for production)
- `manipulation` → Groq (dev default; switch to Claude for production)
- `court_correlation` → Groq (dev default; switch to Claude for production)

**Call chain for analysis tasks**:
```
cli.py
  └─ classifier/tone/timeline.py
       └─ provider.complete_with_retry()   ← base class (3 retries, generic)
            └─ GroqProvider.complete()     ← rate limiter + 429 handling live here
                 └─ Groq SDK API call
```

## Groq Rate Limiting Design

Groq free tier has **two independent rate-limit dimensions** for `llama-3.3-70b-versatile`:

| Dimension | Limit | Reset window | Config key | Accessor |
|-----------|-------|-------------|------------|---------|
| TPM — tokens/min | ~12,000 | Rolling 60 s | `rate_limit_tokens_per_min` | `groq_token_rate_limit()` |
| RPM — requests/min | 30 | Rolling 60 s | `rate_limit_requests_per_min` | `groq_request_rate_limit()` |
| TPD — tokens/day | 100,000 | **Rolling 24 h** | `rate_limit_tokens_per_day` | `groq_daily_token_limit()` |
| RPD — requests/day | 1,000 | Rolling 24 h | — | — |

> ⚠️ **TPD is a rolling 24-hour window** — not a midnight reset. If TPD is exhausted at 9 AM, it won't clear until 9 AM the next day. Plan daily budgets accordingly.

### Layer 1 — Proactive: Rolling Token Bucket (handles TPM)

Implemented in `src/llm/groq_provider.py` as a module-level `deque`.

```
_token_log: deque[(monotonic_timestamp, tokens_used)]
```

**Before each API call**:
1. Prune entries older than 60 seconds from the deque
2. Sum remaining entries → `used`
3. Estimate next call cost: `len(prompt) // 4 + max_tokens // 2`
   - Input: 1 token ≈ 4 chars (conservative for French text)
   - Output: half of `max_tokens` ceiling (actual output << max in practice)
4. If `used + estimated > limit` → sleep until `oldest_entry_age` exits the 60s window

**After each successful call**: record `(now, actual_input_tokens + actual_output_tokens)` in the deque.

Typical throughput: ~1 batch (20 emails) per minute.

### Layer 2 — Reactive: 429 Retry with Retry-After (handles TPM and TPD)

When Groq returns a `RateLimitError` (HTTP 429):

```python
retry_after = exc.response.headers.get("retry-after")

if retry_after > daily_limit_threshold_secs:   # default 300 s
    raise GroqDailyLimitError(retry_after)     # abort — don't retry for hours
elif retry_after:
    sleep(float(retry_after))                  # TPM hit — short wait
else:
    sleep(BASE_DELAY * 2^attempt * (1 ± 0.5_jitter))   # exponential back-off
```

- **`GroqDailyLimitError`** custom exception: callers catch it, save partial run, and exit gracefully
- Max 5 retries before re-raising (TPM path only)
- `Retry-After` always takes precedence over computed back-off
- Back-off baseline: 2.0s × 2^attempt ± 50% jitter

### Header Visibility

The `x-ratelimit-*` headers returned on **every** response (readable via `client.with_raw_response`):

| Header | Meaning |
|--------|---------|
| `x-ratelimit-limit-tokens` | TPM cap |
| `x-ratelimit-remaining-tokens` | TPM remaining this minute |
| `x-ratelimit-reset-tokens` | Time until TPM resets |
| `x-ratelimit-limit-requests` | RPD cap |
| `x-ratelimit-remaining-requests` | RPD remaining today |
| `x-ratelimit-reset-requests` | Time until RPD resets |

> ⚠️ **TPD (tokens/day) quota is NOT exposed in these headers.** It is only detectable by receiving a 429 with a long `Retry-After`. Use `tools/groq_rate_check.py` to check TPM/RPD; if the check passes but a full call 429s, it's a TPD hit.

### Diagnostic Tool

```bash
.venv/bin/python tools/groq_rate_check.py           # show live quota
.venv/bin/python tools/groq_rate_check.py --verbose  # + raw headers
```

Exit code: 0 = API available, 1 = rate limited. Scriptable.

### Configuration

```yaml
# config.yaml
llm:
  providers:
    groq:
      model: llama-3.3-70b-versatile
      rate_limit_tokens_per_min: 10000   # Conservative TPM ceiling (free tier ~12K/min)
      rate_limit_tokens_per_day: 100000  # TPD ceiling — run aborts cleanly when hit
      rate_limit_requests_per_min: 30    # RPM (informational — rarely binding)
      daily_limit_threshold_secs: 300    # Retry-After > this → treat as daily-limit hit
```

Config accessors in `src/config.py`:
- `groq_token_rate_limit()` → TPM ceiling
- `groq_daily_token_limit()` → TPD ceiling
- `groq_request_rate_limit()` → RPM ceiling
- `groq_daily_limit_threshold_secs()` → TPM vs TPD threshold

## Key Design Constraints

1. **IMAP is READ-ONLY** — only FETCH and SEARCH; never STORE/EXPUNGE/DELETE
2. **Multi-address contacts** — primary email + aliases JSON; all expanded in search
3. **Delta text** — all LLM analysis on `delta_text` (quote-stripped), not full body
4. **Bilingual** — French bodies + English Yahoo headers; both handled throughout
5. **Resumable fetch** — `fetch_state` tracks last UID per (folder, contact_email)
6. **Multi-run coexistence** — multiple model runs per email; compare/delete independently

## Tools

| Script | Purpose |
|--------|---------|
| `tools/groq_rate_check.py` | Live Groq quota check — reads `x-ratelimit-*` headers; shows TPM and RPD quota bars; handles 429 |

## Scheduled Tasks

| Task ID | Schedule | Purpose |
|---------|----------|---------|
| `groq-classify-resume` | One-time (fires once then disables) | Resume classify → tone → timeline after TPD reset |
| `groq-daily-analysis` | Daily at 8:00 AM | Auto-run full analysis pipeline every morning |
