# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MyYahooEmails is a Python CLI application that extracts, analyzes, and visualizes email conversations from Yahoo Mail via IMAP. The use case: reconstructing the complete timeline and narrative of an international divorce through 10+ years of email exchanges. The ex-wife used **multiple email addresses** (primary + aliases, all tracked in the DB). The system supports multiple LLM providers for cost-optimized AI analysis.

## Tech Stack

- **Python 3.9** (system Python on macOS — no pyenv/conda). Use `.venv/` for isolation.
- **CLI**: `click` + `rich` + `tqdm`
- **IMAP**: `imapclient` (READ-ONLY — never STORE/EXPUNGE/DELETE/MOVE/COPY)
- **Storage**: SQLite with FTS5 (stdlib `sqlite3` — no ORM)
- **Multi-LLM**: Claude, OpenAI, Groq, Ollama via abstract provider layer (`src/llm/`)
- **Web**: FastAPI + Jinja2 + HTMX + dual-perspective dashboard (Phase 5)
- **Reports**: python-docx + weasyprint (Phase 4)

## Environment Setup

```bash
python3 -m venv .venv
.venv/bin/pip install imapclient mail-parser chardet click rich tqdm pyyaml python-dotenv pytest

# Run CLI
.venv/bin/python cli.py <command>

# Run tests
.venv/bin/python -m pytest tests/
.venv/bin/python -m pytest tests/test_parser.py -v
```

Secrets in `.env` (gitignored). Config in `config.yaml` (gitignored).
Templates: `.env.example` and `config.yaml.example` (committed, no secrets).

## Key CLI Commands

```bash
python cli.py init                              # Init DB, seed contacts+topics from config.yaml
python cli.py fetch folders                     # List Yahoo IMAP folders with message counts
python cli.py fetch emails --all-folders        # Full import across ALL folders (recommended)
python cli.py fetch emails --all-folders --dry-run  # Count only, no download
python cli.py fetch emails --folder Divorce --folder Avocat  # Specific folders only
python cli.py fetch emails --since 2014-01-01   # Date-filtered fetch
python cli.py fetch status                      # DB stats + resume state per folder
python cli.py fetch conclusions                 # Auto-download MULLER adverse conclusions, create procedure_events
python cli.py fetch conclusions --dry-run       # Preview candidates without downloading
python cli.py fetch conclusions --force         # Re-process already-downloaded attachments

python cli.py contacts list                     # Show contacts with primary email + aliases
python cli.py contacts add --name "..." --email "..." --role ex-wife
python cli.py contacts alias -i <id> --add email@example.com   # Add alias to contact
python cli.py contacts alias -i <id> --remove email@example.com
python cli.py contacts delete <id>              # Deletes contact, keeps emails (unlinked)

python cli.py topics list                       # Topics with email counts
python cli.py topics add --name "..." --description "..."

python cli.py search "garde des enfants"        # FTS5 full-text search
python cli.py search --topic enfants --direction received --from 2018-01-01
python cli.py show <email_id>                   # Show email (delta_text by default)
python cli.py show <email_id> --full            # Show full body

python cli.py stats overview                    # Total counts, date range, language breakdown
python cli.py stats frequency --by month        # Email frequency chart (year/month/week)
python cli.py stats frequency --by year --contact <email>
python cli.py stats response-time               # Response time analysis (your avg vs theirs)
python cli.py stats response-time --contact <email> --by quarter
python cli.py stats tone-trends --by month      # Aggression/manipulation trends over time
python cli.py stats tone-trends --direction sent
python cli.py stats topic-evolution --by quarter # Topic prevalence over time (pivoted table)
python cli.py stats contacts                    # Per-contact activity summary
python cli.py stats contacts --sort count

python cli.py events add --date 2019-03-15 --type hearing --description "..." --jurisdiction "TGI Paris"
python cli.py events list
python cli.py events import court_events.csv    # CSV: date, type, jurisdiction, description, outcome

python cli.py runs list                         # All LLM analysis runs
python cli.py runs delete <run_id>              # Delete run + all its results

python cli.py analyze classify                  # Topic classification (Groq by default)
python cli.py analyze classify --provider claude --limit 10
python cli.py analyze tone                      # Tone/aggression/manipulation analysis
python cli.py analyze timeline                  # Extract dated events (one email at a time)
python cli.py analyze timeline --provider claude --min-significance medium
python cli.py analyze all                       # Run classify + tone + timeline sequentially
python cli.py analyze results <email_id>        # Show all analysis results for one email
python cli.py analyze stats                     # Coverage: how many emails analyzed per type
python cli.py analyze export --type classify --limit 230 --offset 0 --output batch01.xlsx
python cli.py analyze export --type tone --limit 230 --offset 230 --output tone_batch02.xlsx
python cli.py analyze export --type manipulation --limit 230 --offset 0 --output manip_batch01.xlsx
python cli.py analyze export --type contradictions --topic enfants --date-from 2011-01-01 --date-to 2015-12-31 --output contradictions_enfants_1.xlsx
python cli.py analyze import-results batch01.xlsx --type classify --provider openai --model gpt-4o
python cli.py analyze import-results batch01.xlsx --type tone --provider claude --model claude-opus-4
python cli.py analyze import-results manip_batch01.xlsx --type manipulation --provider openai --model gpt-5.4-thinking
python cli.py analyze import-results contradictions_enfants_1.xlsx --type contradictions --provider openai --model gpt-5.4-thinking
python cli.py analyze mark-uncovered                # Tag unclassified emails as trop_court or non_classifiable

# Phase 3 — Deep Analysis
python cli.py analyze contradictions            # Two-pass contradiction detection
python cli.py analyze contradictions --run-id 5 --skip-confirmation
python cli.py analyze contradictions-list       # List detected contradictions
python cli.py analyze manipulation              # Per-email manipulation pattern detection
python cli.py analyze manipulation --min-score 0.3 --direction received
python cli.py analyze court-correlation         # Correlate court events with email patterns
python cli.py analyze court-correlation --narrative  # Include LLM narrative synthesis
python cli.py analyze correlations-list         # List court correlations
python cli.py analyze deep                      # Run all Phase 3 analyses sequentially

# Phase 4 — Reports
python cli.py report timeline --format docx     # Timeline report (Word)
python cli.py report tone --format pdf          # Tone analysis report (PDF, needs brew install pango)
python cli.py report contradictions --format docx
python cli.py report full --format docx         # Complete dossier (all sections)
python cli.py report full --output /path/to/report.docx

# Phase 5 — Web Dashboard
python cli.py web                               # Launch dashboard on http://127.0.0.1:8000
python cli.py web --port 3000 --reload          # Dev mode with auto-reload
```

## Project Structure

```
cli.py                        # All CLI commands (click groups: fetch, contacts, topics,
                              #   search, show, stats, events, runs, init, analyze, report)
tools/
  groq_rate_check.py          # Diagnostic: live Groq quota check via x-ratelimit-* headers
src/
  config.py                   # Load config.yaml + .env; convenience accessors
  extraction/
    imap_client.py            # Yahoo IMAP: connect, search by contact+date, fetch raw
    parser.py                 # MIME parse, bilingual quote strip, delta extraction, lang detect
    threader.py               # Thread reconstruction (References→In-Reply-To→Subject),
                              #   dedup, batch store
  storage/
    models.py                 # Dataclasses for all DB entities
    database.py               # Schema (CREATE TABLE), migrations, FTS5 triggers,
                              #   seed_contacts, seed_topics, get/set_last_uid, dedup checks
    search.py                 # Full-text + filtered search; alias-aware contact matching
  llm/                        # Abstract provider layer (Claude, Groq, OpenAI, Ollama)
  analysis/
    classifier.py             # Topic classification in batches
    tone.py                   # Tone/aggression/manipulation analysis in batches
    timeline.py               # Per-email timeline event extraction
    contradictions.py         # Two-pass contradiction detection (Phase 3)
    manipulation.py           # Per-email manipulation pattern detection (Phase 3)
    court_correlator.py       # Court event correlation — SQL + optional LLM narrative (Phase 3)
    excel_export.py           # Export unanalyzed emails to XLSX for ChatGPT/Claude.ai round-trip
    excel_import.py           # Import LLM-filled XLSX back into DB (classify, tone, timeline)
    runner.py                 # Run lifecycle, batch helpers, result storage, summaries helper
    prompts/                  # 7 prompt templates (classify, tone, timeline, contradictions,
                              #   contradictions_confirm, manipulation, court_correlation)
  statistics/
    aggregator.py             # 10 SQL aggregation functions (shared by CLI + reports)
  reports/
    charts.py                 # matplotlib chart generators (5 chart types)
    builder.py                # Report dataclasses + 4 builder functions
    docx_renderer.py          # Word document renderer (python-docx)
    pdf_renderer.py           # PDF renderer (weasyprint + Jinja2)
    templates/report.html     # HTML template for PDF generation
  web/                        # Phase 5: FastAPI + HTMX dashboard
    app.py                    # Application factory, static mount, router registration
    deps.py                   # get_conn() (check_same_thread=False), get_perspective() (cookie)
    job_manager.py            # Shared background-job store (sync, reply, memory synthesis);
                              #   create_job/get_job/update_job + 30-min TTL cleanup
    routes/                   # 11 route modules: dashboard, emails, notes, charts, timeline,
                              #   analysis, contacts, reports, settings, book, court_events
    templates/
      base.html               # Sidebar layout, perspective toggle, conditional nav
      pages/                  # 14 full-page templates (dashboard, emails, timeline, etc.)
      partials/               # HTMX partials (email_list, email_detail, note_list, etc.)
    static/
      css/style.css           # 600+ lines: dual-perspective CSS variables, responsive layout
      js/app.js               # Perspective switch, quote selection (book mode)
data/                         # Gitignored: emails.db, exports/
tests/
  test_parser.py              # 19 tests for quote stripping, subject normalization, lang detect
```

## Database Schema (Key Tables)

- **contacts** — `id, name, email, aliases (JSON list), role, notes`
- **emails** — `id, message_id (UNIQUE), thread_id, date, from_address, to_addresses (JSON), subject, subject_normalized, body_text, body_html, delta_text, delta_hash, direction, language, has_attachments, contact_id, folder, uid, corpus` ('personal'|'legal')
- **threads** — grouped by subject_normalized + References chain
- **topics** — predefined + AI-discovered; linked via **email_topics** (email_id, topic_id, confidence, run_id)
- **analysis_runs** — `id, analysis_type, provider_name, model_id, prompt_hash, prompt_version, status`
- **analysis_results** — one row per (run, email); stores full LLM JSON output
- **contradictions** — pairs of conflicting emails with severity + explanation
- **timeline_events** — extracted events with date, type, significance
- **procedures** — legal proceedings with type, jurisdiction, case number, parties' lawyers, status
- **procedure_events** — events within procedures (hearings, judgments, filings) with date precision
- **lawyer_invoices** — cost tracking per lawyer per procedure (amount_ht, amount_ttc, tva_rate)
- **attachments** — email attachments with on-demand download support (mime_section, imap_uid, folder, downloaded, download_path, category)
- **schema_version** — migration tracking (migration_id, description, applied_at)
- **fetch_state** — `(folder, contact_email)` → `last_uid` for resumable fetching
- **emails_fts** — FTS5 virtual table mirroring subject + body_text + delta_text + addresses
- **notes** — perspective-aware annotations (`entity_type, entity_id, perspective, category, content`)
- **chapters** — book narrative chapters (`title, order_index, date_from, date_to, summary`)
- **chapter_emails** — many-to-many linking chapters ↔ emails
- **quotes** — saved email excerpts for book (`quote_text, email_id, tags, context`)
- **pivotal_moments** — key turning-point emails (`email_id, significance, description`)
- **bookmarks** — email bookmarks
- **generated_reports** — report generation history (`report_type, format, file_path, perspective`)

## Critical Design Constraints

### IMAP is READ-ONLY
Never use STORE, EXPUNGE, DELETE, MOVE, or COPY. All `select_folder()` calls use `readonly=True`.

### Multi-Address Contacts
The ex-wife used 4 email addresses. Contacts have a `primary email` + `aliases (JSON list)`.
- **Fetch**: `search_uids_by_contact()` is called once per address; UIDs are union-deduplicated before download
- **Storage**: `resolve_contact_id()` in `threader.py` checks primary email then aliases via `json_each()`
- **Search/Stats**: all callers delegate to `expand_contact_addresses(conn, email)` in `database.py` — uses `json_each()` for the alias fallback (no full-table scan + Python loop)
- **Config**: aliases defined in `config.yaml` under `contacts[].aliases[]`; `seed_contacts()` updates aliases on re-run without data loss
- **DO NOT** re-implement alias lookup inline — always call `expand_contact_addresses()`

### Bilingual (French + English)
- Bodies ~99% French; Yahoo-generated headers/metadata in English
- Quote stripping handles both: `"Le DD/MM/YYYY à HH:MM, Nom <email> a écrit :"` and `"On DATE, Name wrote:"`
- Subject normalization strips: `Re:, RE:, Fwd:, Fw:, TR:, Réf:, Ref:`
- All LLM prompts (Phase 2+) must instruct the model to process French legal terminology
- Default language when ambiguous: `fr`

### Analysis Corpus Constraint
classify, tone, and manipulation analysis are **personal corpus only**. These prompts are calibrated for intimate partner conflict and are meaningless on legal correspondence.
- `get_emails_for_analysis()` in `runner.py` hardcodes `e.corpus = 'personal'`
- `export_for_analysis()` in `excel_export.py` hardcodes `e.corpus = 'personal'`
- `mark-uncovered` in `cli.py` filters `corpus = 'personal'`
- Legal corpus uses `legal_analysis` only; `procedure_events` is its authoritative event source
- `timeline_events` table contains personal corpus events only (legal events are in `procedure_events`)
- `email_topics` table contains personal corpus emails only
- `emails.procedure_id` FK is set for legal corpus emails, NULL for personal corpus

### Delta Text & Deduplication
- `delta_text` = email body with all quoted reply sections stripped
- All LLM analysis runs on `delta_text` only (not full body)
- `delta_hash` = SHA256 of lowercased+whitespace-normalized delta_text
- Emails are skipped on insert if `message_id` already exists OR `delta_hash` already exists

### Multi-Model Traceability
- Every analysis result tagged with `provider_name, model_id, prompt_hash, prompt_version`
- Multiple runs from different models coexist; users can compare and delete individual runs
- Each result anchored to `sender_contact_id` (whose perspective the analysis reflects)

### Resumable Fetch
- `fetch_state` table stores `(folder, contact_email) → last_uid`
- `--resume` flag (default: on) skips already-fetched UIDs
- `--no-resume` forces re-scan from the beginning
- `--all-folders` skips system folders: Trash, Draft, Bulk, Spam, Deleted Messages (defined in `_SKIP_FOLDERS` in `cli.py`)

### Groq API Rate Limiting (`src/llm/groq_provider.py`)
Groq free tier has **TWO independent rate limit dimensions** — both must be respected:

| Dimension | Limit | Resets | Config key |
|-----------|-------|--------|------------|
| TPM — tokens/minute | ~12,000 | every 60 s | `rate_limit_tokens_per_min` (default: 10,000) |
| RPM — requests/minute | 30 | every 60 s | `rate_limit_requests_per_min` (default: 30) |
| TPD — tokens/day | 100,000 | rolling 24 h window | `rate_limit_tokens_per_day` (default: 100,000) |
| RPD — requests/day | 1,000 | rolling 24 h window | — |

⚠️ **TPD is a rolling 24-hour window** — it does NOT reset at midnight. If the limit is hit at 9 AM, it won't clear until 9 AM the next day. The `Retry-After` header tells you exactly how long to wait.

Two-layer protection:

**1 — Proactive: rolling token bucket (handles TPM)**
- Module-level `_token_log: deque[(timestamp, tokens)]` persists across all calls in the process
- Before every API call: sum tokens used in last 60 s; if `used + estimated > limit` → sleep until oldest entry exits the window
- Token estimate: `len(prompt) // 4 + max_tokens // 2` (input conservative, output at half ceiling)
- Accessor: `src/config.py::groq_token_rate_limit()`

**2 — Reactive: 429 retry with `Retry-After` (handles TPM and TPD)**
- On `RateLimitError`: read `response.headers["retry-after"]` first
- `Retry-After ≤ daily_limit_threshold_secs` (default: 300 s) → TPM hit → sleep and retry
- `Retry-After > daily_limit_threshold_secs` → **TPD hit** → raise `GroqDailyLimitError` immediately (do NOT retry in a loop — wait hours)
- If `Retry-After` absent → exponential back-off with ±50% jitter: `2.0 × 2^attempt × (1 ± 0.5)`
- Max 5 retries before re-raising

**Diagnostic tool**: `python tools/groq_rate_check.py` — reads live `x-ratelimit-*` headers on every response. Note: these headers expose TPM/RPM remaining but NOT TPD remaining (only detectable via 429).

**Call chain**: `cli.py` → `classifier/tone/timeline.py` → `provider.complete_with_retry()` (base class, 3 retries) → `GroqProvider.complete()` (rate limiter + 429 retry lives here)

## Implementation Status

All phases are complete. Key facts for new sessions:

- **Personal corpus**: ~3,791 emails; 100% classified, tone-analyzed, manipulation-analyzed
- **Legal corpus**: ~2,743 emails; 100% legal_analysis; 15 procedures tracked; 33 MULLER conclusions downloaded
- **Analysis coverage**: classify/tone/manipulation = personal only; legal_analysis = legal only; timeline_events = personal only (legal events → procedure_events)
- **Migrations**: 24 applied (schema_version table); next ID = 25
- **Procedures**: 15 total, all with date ranges; #14 Révision Pensions Appel + #15 Procédure Lounys Dubai are active

### Excel round-trip pipeline (analyze export/import)
- `--type` accepts: classify | tone | timeline | manipulation | contradictions
- Contradictions export uses TWO sheets; all others use one
- Manipulation: blank `total_score` → stored as 0.0 (NOT skipped — means "reviewed, none detected")
- Optimal batch size: ~230 emails (fits ChatGPT context)
- `analyze mark-uncovered` tags residual unclassified personal emails as "trop_court" or "non_classifiable"

### Reply Command Center (`/reply/`)
- Memory files: `data/memories/*.md` — BM25 chunked retrieval; `party_b_profile.md` always injected
- Background jobs (generate draft, synthesize memory) use `src/web/job_manager.py`
- `reply_memories` table seeded by `seed_memories()` on `init_db()`

### Analysis runner connection pattern
`runner.py` write helpers (`create_run`, `finish_run`, `store_result`, `store_topics_for_email`, `store_timeline_events`, `store_contradictions`) accept an optional `conn` parameter. Pass a connection to share one transaction across a full analysis pass — avoids opening/closing per batch. Omit for standalone/CLI use.

### Web Dashboard Bug Fixes (keep for pattern reference)
- **`sqlite3.Row` has no `.get()`**: convert to `dict(row)` before calling `.get()`, or use `row["col"]` directly.
- **SQLite has no `LEFT()` function**: use Python slicing `str(val)[:N]` in the route layer.
- **Server-side markdown render enforced**: use `POST /memories/_preview` (Python `html.escape()` renderer) — no client-side `innerHTML` with user content.
- **FTS5 rejects email addresses**: `@`, `.`, `+` are syntax tokens — fall back to `LIKE` on `from_address`/`to_addresses`. See `_search_with_filters()` in `src/web/routes/emails.py`.
- **FastAPI commit-before-redirect**: `get_conn()` commits after response. `RedirectResponse` routes must call `conn.commit()` explicitly before returning.
- **HTMX `hx-on::after-swap`** placed directly on the link element, not on a parent — global `htmx:afterSwap` in `app.js` is unreliable inside dynamically-swapped partials.
- **NOT NULL columns with DEFAULT**: `field.strip() or None` converts empty strings to NULL, violating NOT NULL constraint even when DEFAULT '' is set. Use `field.strip()` only.

## Configuration Reference

`config.yaml` (gitignored — use `config.yaml.example` as template):
```yaml
imap:
  server: imap.mail.yahoo.com
  port: 993
  ssl: true

llm:
  default_provider: groq
  task_providers:
    classify: groq
    tone: groq
    timeline: groq
    contradictions: groq          # switch to claude for production
    manipulation: groq            # switch to claude for production
    court_correlation: groq       # switch to claude for production
  providers:
    claude:
      model: claude-sonnet-4-6
    groq:
      model: llama-3.3-70b-versatile
      rate_limit_tokens_per_min: 10000   # TPM ceiling (free tier ~12K/min)
      rate_limit_tokens_per_day: 100000  # TPD ceiling — run aborts cleanly when hit
      rate_limit_requests_per_min: 30    # RPM ceiling (informational)
      daily_limit_threshold_secs: 300    # Retry-After > this → treat as daily limit hit

contacts:
  - name: Moi
    email: myaddress@yahoo.com
    role: me
  - name: Ex-femme
    email: primary@example.com
    role: ex-wife
    aliases:
      - old@hotmail.fr
      - work@company.com

topics:
  - name: logement
    description: Appartement, loyer, charges, déménagement
  - name: enfants
    description: Garde, pension alimentaire, école, vacances

database:
  path: data/emails.db

analysis:
  batch_size: 20
  contradiction_batch_size: 50
  court_correlation_window: 14
  skip_if_analyzed: true

reports:
  output_dir: data/exports
  language: fr
  page_size: A4
```

## IMAP Gotchas

### Yahoo UIDs are folder-specific — stale after email move
IMAP UIDs (RFC 3501) are assigned per-folder. When a user moves an email from one Yahoo folder to another, the UID in the source folder is invalidated and a new UID is assigned in the destination folder. Any stored `(folder, uid)` pair pointing to the old location will silently return empty content on `BODY.PEEK[]` fetch.

**Symptom**: `fetch_mime_part()` returns `None`; attachment download shows "IMAP returned empty content".

**Fix**: `_find_email_imap_location()` in `src/web/routes/attachments.py` — two-pass fallback when IMAP returns empty:
1. **Pass 1**: Searches all legal-corpus folders (known in DB) for `HEADER Message-ID <value>` (fast, exact)
2. **Pass 2** *(if Pass 1 fails)*: Searches ALL current Yahoo IMAP folders via `client.list_folders()` — catches folders created after the initial fetch (e.g. `vclavocat`). Skip set: trash/spam/bulk/draft/deleted.
3. Uses `SENTON <date> FROM <address>` search when Message-ID not found (Yahoo strips it on move)
4. **`_pick_uid_by_subject()`**: when SENTON+FROM returns multiple UIDs (two emails from same sender on same day), fetches `ENVELOPE` for each and matches subject against `subject_normalized` to pick the correct one
5. On success, updates both `attachments` and `emails` tables with corrected folder+UID

**`[UNAVAILABLE]` = "not found here"**: Yahoo returns `[UNAVAILABLE]` both for transient server errors AND for non-existent UIDs (email moved). Do NOT retry `[UNAVAILABLE]` — return `None` immediately and let `_find_email_imap_location()` handle recovery. Retrying burns 21+ seconds for no benefit.

**Reuse**: Any future feature storing `imap_uid + folder` for on-demand fetch must use this same fallback.

### Yahoo IMAP search misses emails in large folders
Yahoo's IMAP search (`SEARCH FROM/TO/CC`) does not reliably index all messages in very large folders (e.g. Inbox with 49,000+ messages). Emails can exist in Yahoo webmail but not be returned by IMAP search.

**Pattern seen twice**: Valérie's received emails (2014–2016) were in `vclavocat` folder; Hélène's (2017–2023) were in `Onyx` folder — both created by the user to organise mail, neither indexed by the original `--all-folders` fetch.

**Diagnosis**: When a lawyer's received count is suspiciously low vs sent count, check Yahoo webmail for dedicated folders and run:
```bash
python cli.py fetch emails --folder <folder_name> --corpus legal
```
Or to fetch all UIDs in a folder regardless of contact match:
```python
# Direct script using search_all_uids() — not yet a CLI flag
```

## Web Layer Gotchas

### FastAPI commit-before-redirect race condition
`get_conn()` commits AFTER the HTTP response is sent. Any route returning `RedirectResponse` MUST call `conn.commit()` explicitly before returning — otherwise the browser follows the redirect before the INSERT/UPDATE is persisted.

### FTS5 rejects email addresses
SQLite FTS5 treats `@`, `.`, `+` as syntax tokens. Any search query containing these chars must fall back to `LIKE` on `from_address`/`to_addresses` instead of `emails_fts MATCH`. See `_search_with_filters()` in `src/web/routes/emails.py` for the pattern.

### Silent error swallowing
Several routes use bare `except Exception: return []` (e.g. `_get_chapters()`). This hides schema mismatches entirely. When a page returns empty data unexpectedly, check for swallowed exceptions first.

### HTMX scan workspace: OOB swap exclusion pattern
`_build_scan_action_response()` returns `detail_html + "\n" + list_html (OOB)`. Two `htmx:afterSwap` events fire — one for the main detail swap and one for the OOB list swap. The `htmx:afterSwap` handler for `#scan-list` must skip the auto-detail-load for OOB updates (which already carry the correct next-email detail in the main response). Detection: `evt.detail.elt.getAttribute('hx-post')?.includes('/invoices/scan/')`.

### Jinja2 `{% from "X" import name %}` only works for macros
Using `{% from "partial.html" import _ with context %}` raises `ImportError` if the template file doesn't define a macro named `_`. This causes a 500 that HTMX silently swallows (no visible error in the browser). Symptom: clicking a row in a list does nothing; detail panel never updates. Check server logs for Jinja2 ImportError before debugging HTMX.

### NOT NULL columns with DEFAULT: explicit NULL still violates
SQL `DEFAULT ''` only fires when the column is OMITTED from the INSERT. If you pass `None` (Python `None` → SQL `NULL`) explicitly via a parameter, the NOT NULL constraint fires even though a DEFAULT exists. Pattern: use `field.strip()` (returns empty string `""`) NOT `field.strip() or None` when the column is NOT NULL.

## Database / Schema Gotchas

### Migration authoring
Migrations live in `_MIGRATIONS` list in `database.py` as `(id, description, sql)` tuples. Each is wrapped in a **SAVEPOINT** — the SQL and the `schema_version` INSERT commit atomically or roll back together. A module-level `_migration_lock` prevents concurrent startup races. Rules:
- Never skip a migration ID (gaps cause ordering bugs)
- Use `executescript`-style multi-statement SQL (semicolon-separated); `_split_sql()` handles the splitting
- `OperationalError` containing "duplicate column" or "already exists" is tolerated and the migration is recorded as applied — all other errors propagate and abort startup

### WAL connection settings
`_connect()` sets `journal_size_limit=67108864` (64 MB cap) and `wal_autocheckpoint=1000` to prevent the WAL file from growing unboundedly under concurrent writes. Do not remove these without understanding the implications.

### Always verify column names before writing queries
Use `PRAGMA table_info(table)` to confirm actual column names — multiple schema/route mismatches found (chapters used `date_from` but schema has `date_start`; `court_events` was dropped in migration 9 but CLI still referenced it).

### Changing NOT NULL constraints in SQLite
SQLite has no `ALTER COLUMN`. To make a column nullable: CREATE new table, INSERT SELECT, DROP old, RENAME new. See migration 14 (`procedure_id` on `procedure_events`) for the pattern.

### Alias backfill
When adding an alias to a contact (or creating a new contact), always backfill: `UPDATE emails SET contact_id = ? WHERE from_address = ? AND contact_id IS NULL`. Without this, existing emails from that address stay unlinked and don't appear in stats.

### contradictions.topic vs topic_id
The `contradictions` table has BOTH `topic` (TEXT, Excel-import path) and `topic_id` (FK, automated pipeline). Always use `COALESCE(c.topic, t.name)` when querying topic names.
