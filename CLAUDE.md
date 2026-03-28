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
- **Storage**: `resolve_contact_id()` checks both primary email and aliases
- **Search**: `all_addresses_for_contact()` expands to all known addresses in WHERE clauses
- **Config**: aliases defined in `config.yaml` under `contacts[].aliases[]`; `seed_contacts()` updates aliases on re-run without data loss

### Bilingual (French + English)
- Bodies ~99% French; Yahoo-generated headers/metadata in English
- Quote stripping handles both: `"Le DD/MM/YYYY à HH:MM, Nom <email> a écrit :"` and `"On DATE, Name wrote:"`
- Subject normalization strips: `Re:, RE:, Fwd:, Fw:, TR:, Réf:, Ref:`
- All LLM prompts (Phase 2+) must instruct the model to process French legal terminology
- Default language when ambiguous: `fr`

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

## Current Implementation Status

### ✅ Phase 1 — Foundation (COMPLETE)
- IMAP client with read-only contact+date search across all/specific folders
- `--all-folders` flag fetches every folder except system ones (Trash/Draft/Bulk/Spam/Deleted Messages)
- Multi-address fetch: all aliases of a contact are searched and UIDs union-deduplicated per folder
- MIME parser with bilingual quote stripping and delta extraction
- Thread reconstruction (References → In-Reply-To → normalized subject fallback)
- SQLite schema with FTS5, all tables, indexes, and triggers
- Full CLI: fetch (with --all-folders), contacts (with alias management), topics, search, show, stats, events, runs
- 19 passing tests for parser
- First real fetch completed: ~2,676 emails found across 91 Yahoo folders; download in progress
- Second full fetch completed 2026-03-24: 3,922 total emails (897 from Sent, 35 Refere, 16 Refere OK, 16 Weekly reports, 4 Inbox added)

### ✅ Phase 2 — Intelligence (COMPLETE)
- `src/llm/`: abstract `LLMProvider` base class + Claude, Groq, OpenAI, Ollama implementations
- `src/llm/router.py`: `get_provider(task, override)` — reads `config.yaml` task_providers, caches instances
- `src/analysis/runner.py`: run lifecycle (create/finish), batch helpers, result storage, JSON parsing
- `src/analysis/classifier.py`: topic classification in batches (Groq default), stores to `email_topics`
- `src/analysis/tone.py`: tone/aggression/manipulation/legal-posturing analysis in batches
- `src/analysis/timeline.py`: per-email timeline event extraction, stores to `timeline_events`
- `src/analysis/prompts/`: 4 French-legal prompt templates (classify, tone, timeline, contradictions)
- New CLI commands: `analyze classify/tone/timeline/all/results/stats`
- Cost strategy: Groq (free) for classify+tone+timeline; Claude for contradictions+manipulation
- **Groq rate limiter** in `src/llm/groq_provider.py`: rolling 60-second token bucket + `Retry-After`-aware 429 handling (see Critical Design Constraints below)

### ✅ Phase 2b — Excel Round-Trip Pipeline (COMPLETE)
- `src/analysis/excel_export.py`: exports unanalyzed emails to XLSX for manual LLM processing (ChatGPT, Claude.ai)
  - Blue columns = input (read-only); yellow columns = output (LLM fills these in)
  - Instructions sheet + `_meta` sheet (analysis_type, export_date, email_count) for import validation
  - Emails over 32,767 chars (Excel cell limit) automatically excluded — they remain for Groq (128k context)
  - `--offset` parameter enables paginated batch exports across the unanalyzed pool
  - Sort order: `ORDER BY e.date ASC` (consistent across all export types)
  - `--type` accepts: classify | tone | timeline | manipulation | contradictions
  - `--topic` (contradictions only): filter by topic name
  - `--date-from` / `--date-to` (contradictions only): date range filter for splitting large topics
- `src/analysis/excel_import.py`: imports LLM-filled XLSX back into DB
  - Creates a new `analysis_run` tagged with `provider_name` + `model_id` for full traceability
  - Parses comma-separated topics/confidence for classify; float scores for tone
  - Skips blank rows gracefully for classify/tone (~2% too short/ambiguous — means "undecided")
  - **Manipulation blank rows stored as total_score=0.0** (blank = "reviewed, none detected" — NOT skipped)
  - Idempotent for classify (removes prior `email_topics` from same run before reinserting)
  - `--type` accepts: classify | tone | timeline | manipulation | contradictions
- New CLI commands: `analyze export`, `analyze import-results`, `analyze mark-uncovered`
- New dependency: `openpyxl`
- Primary use case: ChatGPT Plus (gpt-5.4-thinking, 196k context) for free-tier cost avoidance
- Optimal batch size: ~230 emails per batch (fits comfortably in ChatGPT context with instructions)

#### Manipulation export/import format
- Output columns: `total_score` (0.0–1.0), `dominant_pattern`, `detected_patterns` (e.g. "gaslighting:0.8, projection:0.5"), `notes`
- 10 patterns: gaslighting, emotional_weaponization, financial_coercion, legal_threats, children_instrumentalization, guilt_tripping, projection, false_victimhood, moving_goalposts, silent_treatment_threat
- Blank `total_score` → stored as `{"patterns": [], "total_score": 0.0, "dominant_pattern": null, ...}` (NOT skipped)

#### Contradictions export/import format
- Uses TWO sheets (different from all other types):
  - "Emails" sheet: read-only summaries (email_id, date, direction, contact, subject, summary, topics) — uses classified summaries NOT delta_text — more token-efficient
  - "Contradictions" output sheet: LLM fills (email_id_a, email_id_b, scope, topic, severity, explanation)
- Export by topic + date range to keep batches manageable (large topics like "enfants" need 5 splits)
- 17 standard batch files: topics enfants (5 splits — enfants_1/2/2b/3/4), finances (2), ecole (2), logement/vacances/sante/procedure/education/activites/divorce/famille (1 each)
- `enfants_2b` (296 emails, 2018-09-20→2019-12-31) was discovered as a gap and created 2026-03-24

#### mark-uncovered command
- `python cli.py analyze mark-uncovered` — tags remaining unclassified emails as "trop_court" or "non_classifiable"
- Creates both topics if they don't exist; creates a run with provider="manual", model="rule-based"
- These count toward classification coverage % but are excluded from topic distribution charts in the web dashboard

### Current Analysis Coverage (as of 2026-03-27)
- Total emails: 3,922 (3,791 personal + 131 legal corpus)
- Classification: 3,922/3,922 (100%) ✅ COMPLETE
- Tone analysis: 3,922/3,922 (100%) ✅ COMPLETE
- Manipulation: 3,922/3,922 (100%) ✅ COMPLETE — runs #62–78 + all 17 batches via ChatGPT gpt-5.4-thinking
- Timeline extraction: 3,922/3,922 (100%) ✅ COMPLETE — 915 events found — 21 runs total (runs #4, #14, #109, #112, #113, #118–#133)
- Contradictions: 45 pairs total across 9 topics ✅ COMPLETE — (enfants 7, vacances 12, éducation 10, procédure 4, santé 5, logement 2, école 2, finances 1, (none) 2)
  - All 17 batch files imported (including finances_1 + finances_2 — run#114 + run#115/117)
- Procedures: 0 — tables created, awaiting LLM extraction from lawyer emails

### 🔲 Phase 6 — Lawyer Correspondence Module (IN PROGRESS — branch: `feature/lawyer-corpus`)

**Goal**: Extend the system to manage emails with lawyers (2-3 per party, 2014-present) for procedure tracking, document management, cost analysis, and cross-corpus timeline correlation.

#### ✅ Phase 6a — Schema + Migration Infrastructure (COMPLETE)
- **Migration system**: `schema_version` table + `_MIGRATIONS` list in `database.py` — lightweight, idempotent
- **`corpus` column** on `emails`: `'personal'` (default) or `'legal'` — 131 lawyer emails auto-reclassified
- **`attachments` table extended**: 6 new columns (`mime_section`, `imap_uid`, `folder`, `downloaded`, `download_path`, `category`) for on-demand IMAP download
- **`court_events` dropped** (was empty), replaced by `procedures` + `procedure_events` + `lawyer_invoices`
- **New dataclasses**: `Procedure`, `ProcedureEvent`, `LawyerInvoice` in `models.py`
- **Config**: `attachment_download_dir()`, `lawyer_contacts()` helpers; new roles `my_lawyer`, `her_lawyer`, `opposing_counsel`
- DB backup: `data/emails.db.backup-pre-6a`

#### 🔲 Phase 6b — Fetch Pipeline Extension
- Corpus-aware `store_email()` in threader.py
- Attachment metadata-only mode for legal corpus (no BLOB download)
- `fetch_mime_part()` in imap_client.py for on-demand part download
- `--corpus` option + `fetch lawyers` convenience command

#### 🔲 Phase 6g — Corpus Filter + Sidebar Restructure (moved early — highest risk)
- Centralized `corpus_clause()` helper for ~35-40 query updates
- Sidebar: Legal > Case Analysis (Contradictions, Manipulation) + Legal > Legal Strategy (Procedures, Documents, Legal Costs)
- Corpus tabs (Personal | Legal | All) on email browser
- `get_corpus()` dependency in deps.py

#### 🔲 Phase 6g.1 — Email Management (Delete + Reclassify)
- Review ~220 third-party emails (schools, housing, family)
- Delete irrelevant, reclassify between personal/legal
- Bulk actions (select + delete/reclassify)

#### 🔲 Phase 6c — Attachment UI + On-Demand Download
- Attachment list in email detail (replaces 📎-only indicator)
- Serve from BLOB (personal) or filesystem (legal)
- On-demand IMAP FETCH for un-downloaded legal attachments

#### 🔲 Phase 6d — Document Classification
- Manual + auto-suggest (filename regex) for 15 categories
- Categories: invoice, court_filing, conclusion_draft, conclusion_final, judgment, ordonnance, expert_report, convocation, pv_audience, correspondence_adverse, convention, attestation, mise_en_demeure, requete, other

#### 🔲 Phase 6e — Procedures Model
- CRUD for procedures + procedure_events (replaces court_events)
- LLM extraction from lawyer emails
- Web UI: procedure list with events timeline

#### 🔲 Phase 6f — Cost Tracking
- `lawyer_invoices` CRUD + cost dashboard
- Auto-extraction from email body (regex for EUR/TTC/HT)
- Charts: per-lawyer, per-procedure, monthly burn rate

#### 🔲 Phase 6h — Unified Timeline
- Merge both corpora + procedure events + cost events
- Color-coded by source type

#### 🔲 Phase 6i — Judgment PDF Analysis
- PDF text extraction + LLM parsing (parties, judge, ruling, obligations)
- New dependency: `pdfplumber`

### Web Dashboard Bug Fixes (2026-03-25)
- **"View email" modal on timeline**: `hx-on::after-swap` added directly to "View email" link in `partials/timeline_list.html`; `href` changed to `#` to prevent fallback navigation. The global `htmx:afterSwap` handler in `app.js` was not reliably firing when the link resided inside a dynamically-swapped HTMX partial.

### ✅ Phase 3 — Deep Analysis (COMPLETE)
- `src/analysis/contradictions.py`: two-pass contradiction detection (screening summaries → confirming with full delta_text)
- `src/analysis/manipulation.py`: per-email manipulation pattern detection (10 patterns: gaslighting, coercion, projection, etc.)
- `src/analysis/court_correlator.py`: SQL-based court event correlation (±N day window) + optional LLM narrative
- `src/analysis/prompts/manipulation.txt`: French-legal manipulation taxonomy prompt
- `src/analysis/prompts/contradictions_confirm.txt`: Pass 2 confirmation prompt
- `src/analysis/prompts/court_correlation.txt`: narrative synthesis prompt
- `src/analysis/runner.py`: added `get_classification_summaries(run_id=None)` helper
- New CLI commands: `analyze contradictions/contradictions-list/manipulation/court-correlation/correlations-list/deep`
- Default provider: Groq during development (all results tagged with LLM used, deletable, replaceable)
- Contradiction detection requires classification to have run first (uses summaries)

### ✅ Phase 4 — Statistics & Reports (COMPLETE)
- `src/statistics/aggregator.py`: 10 SQL aggregation functions (response times, tone trends, topic evolution, contacts, overview, frequency, merged timeline, contradictions, top aggressive, methodology)
- `src/reports/charts.py`: 5 matplotlib chart generators (frequency, tone trends, topic evolution, tone pie, response time)
- `src/reports/builder.py`: Report dataclasses + 4 builders (timeline, tone, contradictions, full dossier)
- `src/reports/docx_renderer.py`: Word document renderer (python-docx) with styled headings, tables, charts
- `src/reports/pdf_renderer.py`: PDF renderer via weasyprint + Jinja2 (requires `brew install pango`)
- `src/reports/templates/report.html`: Jinja2 HTML template with professional CSS
- Refactored `stats overview` and `stats frequency` to use shared aggregator
- New CLI commands: `stats response-time/tone-trends/topic-evolution/contacts`
- New CLI group: `report timeline/tone/contradictions/full` (--format docx|pdf)
- Dependencies: python-docx, weasyprint, matplotlib, jinja2

### ✅ Phase 5 — Web Dashboard (COMPLETE)
- `src/web/app.py`: FastAPI application factory with static files + router mounting
- `src/web/deps.py`: `get_conn()` (SQLite with `check_same_thread=False`) + `get_perspective()` (cookie-based)
- **Dual-perspective UI**: ⚖️ Legal (navy `#1e3a5f`) / 📖 Book (forest green `#1a3d2e`) — CSS variables on `body.perspective-*`
- **English UI** with French email/analysis content
- **14+ pages**: Dashboard, Emails (two-panel + HTMX detail), Timeline, Analysis (3 HTMX tabs), Contacts, Reports, Settings, Contradictions, Manipulation, Court Events, Narrative Arc, Chapters, Quote Bank, Pivotal Moments
- **Notes CRUD**: perspective-aware notes (Legal/Book tabs) on every email via `POST /notes/` + `DELETE /notes/{id}` with HTMX swap
- **Report generation hub**: Legal (Timeline, Tone, Contradictions, Full Dossier) + Book (Narrative Timeline) with format selector + "Include notes" checkbox
- **Chart endpoints**: 9 `/charts/*` routes streaming matplotlib PNGs via `tempfile` (5 original + 4 manipulation charts)
- **Info-icon tooltips**: global body-level JS tooltip system in `base.html` (escapes `card overflow:hidden`); `.info-icon[data-tip]` badges on every chart across dashboard, manipulation, narrative, and all 3 analysis partials; HTMX-aware (re-attaches after partial swaps)
- **Email browser**: FTS5 search with `<mark>` highlighting, multi-topic filtering (OR/AND), direction/date/bookmark filters, HTMX pagination
- **Analysis topics tab**: shows note that "trop_court" and "non_classifiable" emails are excluded from topic distribution, with live counts per category
- **Book features**: Narrative Arc (emotional intensity chart), Chapters CRUD, Quote Bank, Pivotal Moments
- **7 new DB tables**: `notes`, `chapters`, `chapter_emails`, `quotes`, `pivotal_moments`, `bookmarks`, `generated_reports`
- New CLI command: `python cli.py web [--host] [--port] [--reload]`
- Dependencies: fastapi, uvicorn, python-multipart
- `.claude/launch.json`: dev server config for preview

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

## Web Layer Gotchas

### FastAPI commit-before-redirect race condition
`get_conn()` commits AFTER the HTTP response is sent. Any route returning `RedirectResponse` MUST call `conn.commit()` explicitly before returning — otherwise the browser follows the redirect before the INSERT/UPDATE is persisted.

### FTS5 rejects email addresses
SQLite FTS5 treats `@`, `.`, `+` as syntax tokens. Any search query containing these chars must fall back to `LIKE` on `from_address`/`to_addresses` instead of `emails_fts MATCH`. See `_search_with_filters()` in `src/web/routes/emails.py` for the pattern.

### Silent error swallowing
Several routes use bare `except Exception: return []` (e.g. `_get_chapters()`). This hides schema mismatches entirely. When a page returns empty data unexpectedly, check for swallowed exceptions first.

## Database / Schema Gotchas

### Always verify column names before writing queries
Use `PRAGMA table_info(table)` to confirm actual column names — multiple schema/route mismatches found (chapters used `date_from` but schema has `date_start`; `court_events` was dropped in migration 9 but CLI still referenced it).

### Changing NOT NULL constraints in SQLite
SQLite has no `ALTER COLUMN`. To make a column nullable: CREATE new table, INSERT SELECT, DROP old, RENAME new. See migration 14 (`procedure_id` on `procedure_events`) for the pattern.

### Alias backfill
When adding an alias to a contact (or creating a new contact), always backfill: `UPDATE emails SET contact_id = ? WHERE from_address = ? AND contact_id IS NULL`. Without this, existing emails from that address stay unlinked and don't appear in stats.

### contradictions.topic vs topic_id
The `contradictions` table has BOTH `topic` (TEXT, Excel-import path) and `topic_id` (FK, automated pipeline). Always use `COALESCE(c.topic, t.name)` when querying topic names.
