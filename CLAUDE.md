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

### Current Analysis Coverage (as of 2026-04-06)
- Personal emails: 3,791 (authoritative live count — 131 emails reclassified to legal corpus)
- Legal emails: 2,743
- Classification: 3,791/3,791 (100%) ✅ COMPLETE — personal corpus only
- Tone analysis: 3,791/3,791 (100%) ✅ COMPLETE — personal corpus only
- Manipulation: 3,791/3,791 (100%) ✅ COMPLETE — personal corpus only
- Timeline extraction: 902 events from personal corpus ✅ COMPLETE
- Contradictions: 45 pairs total across 9 topics ✅ COMPLETE — (enfants 7, vacances 12, éducation 10, procédure 4, santé 5, logement 2, école 2, finances 1, (none) 2)
  - All 17 batch files imported (including finances_1 + finances_2 — run#114 + run#115/117)
- Legal corpus: 2,743 emails total
  - legal_analysis (run #156): 2,743/2,743 (100%) ✅ COMPLETE — only analysis type applicable to legal corpus
  - classify/tone/manipulation: NOT run on legal corpus (wrong paradigm — see design constraint below)
  - timeline_events: NOT kept for legal corpus — procedure_events is the authoritative event source
  - 2,114 procedure_events stored; 15 procedures tracked; 37 lawyer invoices
  - 2,892 legal emails have procedure_id FK (migration #18) — 1 unlinked
- Procedures: 15 total — all with date ranges set; 13 with uploaded documents
  - 33 MULLER adverse conclusions downloaded + linked as `procedure_events` (type=conclusions_received) across 11 procedures

### ✅ Phase 6 — Lawyer Correspondence Module (COMPLETE — merged to `main` 2026-04-11)

**Goal**: Extend the system to manage emails with lawyers (2-3 per party, 2014-present) for procedure tracking, document management, cost analysis, and cross-corpus timeline correlation.

#### ✅ Phase 6a — Schema + Migration Infrastructure (COMPLETE)
- **Migration system**: `schema_version` table + `_MIGRATIONS` list in `database.py` — lightweight, idempotent
- **`corpus` column** on `emails`: `'personal'` (default) or `'legal'` — 131 lawyer emails auto-reclassified
- **`attachments` table extended**: 6 new columns (`mime_section`, `imap_uid`, `folder`, `downloaded`, `download_path`, `category`) for on-demand IMAP download
- **`court_events` dropped** (was empty), replaced by `procedures` + `procedure_events` + `lawyer_invoices`
- **New dataclasses**: `Procedure`, `ProcedureEvent`, `LawyerInvoice` in `models.py`
- **Config**: `attachment_download_dir()`, `lawyer_contacts()` helpers; new roles `my_lawyer`, `her_lawyer`, `opposing_counsel`, `notaire`
- DB backup: `data/emails.db.backup-pre-6a`

#### ✅ Phase 6b — Fetch Pipeline Extension (COMPLETE)
- Corpus-aware `store_email()` in threader.py
- Attachment metadata-only mode for legal corpus (no BLOB download)
- `fetch_mime_part()` in imap_client.py for on-demand part download
- `--corpus` option + `fetch lawyers` convenience command

#### ✅ Phase 6g — Corpus Filter + Sidebar Restructure (COMPLETE)
- Centralized `corpus_clause()` helper for ~35-40 query updates
- Sidebar: Legal > Case Analysis (Contradictions, Manipulation) + Legal > Legal Strategy (Procedures, Documents, Legal Costs)
- Corpus tabs (Personal | Legal | All) on email browser
- `get_corpus()` dependency in deps.py

#### ✅ Phase 6g.1 — Email Management (COMPLETE)
- Bulk checkbox selection + toolbar (delete / reclassify personal↔legal)
- "No contact" filter to surface unlinked emails
- JS event delegation for HTMX-aware checkbox state
- `POST /emails/bulk-delete` and `POST /emails/bulk-reclassify` endpoints (Pydantic JSON body)

#### ✅ Phase 6c — Attachment UI + On-Demand Download (COMPLETE)
- Attachment list in email detail with filename, size, category badge
- Serve from BLOB (personal) or filesystem (legal) via `GET /attachments/{id}`
- On-demand IMAP FETCH via `POST /attachments/{id}/fetch`
- Stale-UID recovery: `_find_email_imap_location()` searches by Message-ID then SENTON+FROM when stored folder/UID is outdated (e.g. email moved between Yahoo folders)

#### ✅ Phase 6d — Document Classification (COMPLETE)
- Manual category assignment via `POST /attachments/{id}/classify`
- 18 categories: invoice, court_filing, conclusion_draft, conclusion_final, judgment, ordonnance, expert_report, convocation, pv_audience, official_email, proof, proof_adverse, correspondence_adverse, convention, attestation, mise_en_demeure, requete, other

#### ✅ Phase 6f — Cost Tracking (COMPLETE)
- `lawyer_invoices` full CRUD: list, create, edit, delete at `/invoices/`
- **Invoice scan workspace** (split-panel triage, `/invoices/scan`):
  - Left panel: compact email list with 5-tab strip (⏳ Pending / 💶 Invoice / 💳 Payment / 🚫 Dismissed / ⊞ All) and status icons (PDF attachment, invoice record, payment confirmed)
  - Right panel: email detail with snippet, attachments, EUR amount chips, sticky action strip (Invoice / Payment / Assessed)
  - POST actions (save invoice, record payment, dismiss) auto-advance to next email via HTMX OOB swap
  - Keyboard shortcuts: 1/2/3 = action tabs, J/→ = next email, F = fetch attachment
  - Auto-fallback: if filtered keywords match no pending emails, shows "All" tab immediately
  - Default keywords: facture, honoraires, note d'honoraires, relevé, acompte, solde dû, montant TTC, diligences
  - Falls back from `delta_text` to `body_text` for emails where invoice content was stripped as quoted reply
- **New DB tables** (migrations 15 + 16):
  - `payment_confirmations` — amount, payment_type (acompte/solde_final/autre), invoice_id FK
  - `invoice_scan_dismissed` — emails assessed as having no invoice/payment to record
- Per-lawyer and per-procedure cost summaries on dashboard

#### ✅ Phase 6e — Procedure Document Upload + PDF Analysis (data entry complete)
- 11 court PDFs uploaded via web UI and analysed ad-hoc with pdfplumber
- 41 procedure_events created with dates, types, descriptions, and source_attachment_id links
- **Document-first strategy**: upload PDF → Claude extracts text → auto-fills metadata + events in one transaction
- Procedures fully populated: #1 Contestation Paternité (RG 17/10390), #2 ONC (RG 15/33553), #3 Appel ONC (RG 15/13023), #4 Référé (RG 15/42684), #5 Divorce pour Faute (RG 15/33553), #6 Appel Divorce (RG 19/07859), #8 Incident JME (RG 15/33553), #9 Incident Appel (RG 17/18289), #10 Acquiescements (protocole 04/09/2020), #12 Liquidation Financière (RG 23/06050, open), #13 Révision de Pensions (RG 24/07044)
- Procedures awaiting documents: #11 Plainte pour Maltraitance, #14 Révision Pensions Appel, #15 Procédure Lounys Dubai
- #7 Négociation Amiable: no formal court document (informal negotiation); dates set from attachment evidence
- Key bug: commit each SQL unit separately — a mid-script NOT NULL error rolls back the entire uncommitted transaction including prior UPDATEs
- Web UI for procedure list/detail: already built at `/procedures/` (was marked as needed but is complete)

#### ✅ Phase 6e.1 — Procedure Date Ranges + Analysis Corpus Constraints (COMPLETE 2026-04-06)
- All 15 procedures now have date ranges set (or NULL with documented reason for #11 #14 #15 ongoing)
- **Procedure dates resolved**:
  - #2 Première Instance: `2015-02-05 → 2017-07-21` closed (shares judgment date with #5)
  - #7 Négociation Amiable: `2015-08-10 → 2016-02-22` abandoned (derived from convention de divorce attachment trail)
  - #11 Plainte Maltraitance: `2023-04-07 → NULL` closed (children's procedure, father not direct party; exact end unknown)
  - #14 Révision Pensions Appel: `2025-07-03 → NULL` active
  - #15 Procédure Lounys Dubai: `2026-01-28 → NULL` active (formal requête filed at Nanterre)
- **Analysis corpus constraint enforced**: classify/tone/manipulation restricted to `corpus='personal'` only
  - `src/analysis/runner.py` `get_emails_for_analysis()`: hardcoded `e.corpus = 'personal'` filter
  - `src/analysis/excel_export.py` `export_for_analysis()`: same filter on export
  - `cli.py` `analyze mark-uncovered`: personal corpus only
  - `cli.py` `analyze stats`: now shows personal/legal separately with correct denominators
- **DB cleanup performed**:
  - Deleted 417 `analysis_results` rows (classify/tone/manipulation) for 131 legal corpus emails
  - Deleted 304 `email_topics` rows for legal corpus emails
  - Deleted 22 `timeline_events` rows for legal corpus emails (covered by `procedure_events`)
  - `legal_analysis` (2,893 rows) and `timeline` (131 rows) on legal emails preserved

#### ✅ Phase 6e.2 — Email→Procedure Backfill (COMPLETE 2026-04-06)
- Migration #18: added `procedure_id INTEGER REFERENCES procedures(id)` + index to `emails` table
- Backfill script: mined `procedure_ref` from all `legal_analysis` `result_json` blobs
- Result: 2,892 of 2,743 legal emails linked to their procedure via FK (1 had no procedure_ref)
- Procedure email distribution: #5 Divorce pour Faute 713, #12 Liquidation 355, #1 Contestation 317, #8 Incident 258, #7 Négociation 243…
- Personal corpus `procedure_id` = NULL (correct by design)

#### ✅ Phase 6j — Adverse Conclusions Auto-Download (COMPLETE 2026-04-07)
- `python cli.py fetch conclusions` — detects MULLER adverse conclusion PDFs across all legal-corpus emails
- Detection: `corpus='legal'` + `LOWER(filename) LIKE '%muller%'` + `LIKE '%conclusion%'` or `LIKE '%dire%'`
- Deduplication: same `(filename.lower(), procedure_id)` → keeps earliest email (removes 17 forwarded duplicates)
- Three-tier download strategy:
  1. **Stored IMAP location** (folder + uid from `attachments` table)
  2. **Full stale-UID recovery** (two-pass: Message-ID search across all DB-known folders, then all current IMAP folders using SENTON+FROM date+sender — same logic as `_find_email_imap_location()` in web routes)
  3. **BLOB fallback** (emails reclassified from personal corpus still have content in `attachments.content`)
- On success: saves to `data/attachments/<email_id>/<filename>`, sets `category='conclusion_adverse'`, creates `procedure_events` row of type `conclusions_received` with `source_attachment_id` FK
- Idempotent: checks existing event by `(procedure_id, source_attachment_id, event_type)` before insert
- **Result**: 33/33 MULLER conclusions downloaded and linked across 11 procedures (2015–2026)
- **Options**: `--dry-run`, `--force`, `--limit`

#### ✅ Phase 6k — Procedure Documents Unified View (COMPLETE 2026-04-07)
- Procedure detail page Documents section now shows BOTH sources:
  - `procedure_documents` (manual uploads via web UI) — with delete button
  - `attachments` with `downloaded=1` and `download_path` set, linked via `emails.procedure_id` — with amber "email" badge, no delete button
- Invoices (`category='invoice'`) excluded from document view
- Both sources sorted by date, served via their own URLs (`/procedures/{id}/documents/{doc_id}` vs `/attachments/{doc_id}`)
- Document count header shows "N · M from emails"
- `_source` and `_serve_url` keys added to each document dict for template routing

#### ✅ Phase 6h — Unified Timeline (COMPLETE — partial)
- `src/statistics/aggregator.py`: `merged_timeline()` merges email events + procedure_events + invoice events; `dossier_timeline()` groups by procedure with KPIs; `court_event_window_aggression()` for ±14 day aggression correlation
- `src/web/routes/timeline.py`: stream/dossier views; `GET /timeline/court-event/{date}/correlation` lazy panel
- `src/web/templates/pages/timeline.html`: stream/dossier toggle, source legend
- `src/web/templates/partials/timeline_list.html`, `timeline_dossier.html`, `court_correlation_tooltip.html`
- Remaining: dashboard-level systematic aggression correlation across all procedure events

#### ✅ Procedures Page Enhancements (COMPLETE 2026-04-07)
- **Gantt chart** at `/charts/procedure-gantt`: horizontal bars coloured by initiator, hatched for appeals, faded tail for ongoing; legend at bottom-left
- **Procedure period overlay** on frequency and tone-trend charts: `_add_procedure_bands()` in `charts.py` adds shaded vertical bands
- **Initiator KPI strip** on procedures list: primary cases filed by Party A / Party B / Both / Unknown; appeals attributed to parent case by name matching
- **Procedures list sorted chronologically** (oldest → newest, NULL dates last)
- **`initiated_by` dropdown** in both add and edit forms (party_a / party_b / both / blank=Unknown)
- **Bug fixed**: `NOT NULL constraint failed: procedures.jurisdiction` — `update_procedure` and `create_procedure` now use `field.strip()` not `field.strip() or None` for NOT NULL string columns

#### ✅ Thematic Threads Page (COMPLETE 2026-04-07)
- New page at `GET /themes` (book perspective) — nav link was `href="#"`, now wired to `/href="/themes"`
- Left sidebar: all topics with email count, active topic highlighted
- Stats strip: total/sent/received counts, avg aggression, date range
- Paginated email thread (50 per page, Prev/Next) with full `delta_text` in `white-space:pre-wrap`
- **"Full email ↗" button** on each card: opens right-side slide-in overlay panel (fixed position, 700px wide) via HTMX `hx-get="/emails/{id}"` → `#theme-detail-content`; backdrop click + Escape to close
- Route in `src/web/routes/book.py` `GET /themes`; template `src/web/templates/pages/themes.html`

#### ✅ Phase 6i — Judgment PDF Analysis (COMPLETE)
- PDF text extraction + LLM parsing (parties, judge, ruling, obligations)
- Structured ruling fields on `procedure_events`
- "Rulings at a Glance" summary card on procedure detail page
- Dependency: `pdfplumber`

#### ✅ Phase 6h remainder — Cross-corpus correlation dashboard (COMPLETE)
- Systematic aggression delta across all procedure events
- Pre-conclusion behavior detector: frequency spikes + manipulation scores before `conclusions_received` events

### ✅ Phase 7 — Northline Branding + Reply Command Center (COMPLETE 2026-04-12)

#### ✅ Phase 7a — Northline Branding (COMPLETE 2026-04-12)
- **Brand**: "Northline — Clarity under pressure" — divorce intelligence platform; `docs/branding.md` (791 lines)
- **Navigation redesign**: Workspace-based nav (4 tabs: Correspondence, Case Analysis, Legal Strategy, Book) replaces dual Perspective/Corpus toggles
- **`base.html`**: Complete rewrite — `_ws_map` Jinja2 inference, contextual sidebar per workspace, `body.perspective-*` class preserved for CSS compat
- **`style.css`** (v11): Northline color system — Navy `#1E3557`, Amber `#D6A14B` (sole focal accent), Ivory `#F5F2EA`, Deep Ink for Book (no green); navy topbar, amber active underline
- **`app.js`**: Workspace tab click handler, 3-cookie management (workspace + perspective + corpus), on-load sync
- **Icons**: `favicon.ico`, `apple-touch-icon.png`, `icon-32/64/128.png` in `/static/`; Northline eye-contour logo

#### ✅ Phase 7b — Sync Pages (COMPLETE 2026-04-12)
- `/sync/personal` and `/sync/legal` — IMAP fetch since last sync, background thread, HTMX polling
- `src/web/routes/sync.py`: resumes from `fetch_state` per folder/contact, updates last_uid after each folder
- Templates: `pages/sync.html`, `partials/sync_status.html`, `partials/sync_recent.html`
- Last 10 emails OOB-refreshed on sync complete

#### ✅ Phase 7c — Reply Command Center (COMPLETE 2026-04-12)
**New page**: `/reply/` — split-panel triage workspace for drafting replies

**DB Migrations**:
- Migration 20: `reply_status` column on `emails` (`unset`/`pending`/`drafted`/`answered`/`not_applicable`) + index
- Migration 21: `reply_drafts` table — tone, guidelines, memories_used, full prompts, LLM metadata (provider, model, tokens, latency), status, versioning
- Migration 22: `pending_actions` table — action_type (`question`/`request`/`demand`/`deadline`/`proposal`), text, resolved, extracted_by
- Migration 23: `reply_memories` table — slug, display_name, file_path, topic_id FK, description

**New modules**:
- `src/analysis/reply_generator.py`: `TONE_CONFIGS` (6 tones: factual/firm/conciliatory/neutral/defensive/jaf_producible), `generate_reply_draft()`, `extract_pending_actions()`, `build_system_prompt()`, `build_user_prompt()`, memory loading, analysis context injection
- `src/analysis/prompts/reply_draft.txt`: French legal reply prompt with JAF-producibility rules
- `src/analysis/prompts/extract_actions.txt`: Action extraction prompt
- `src/web/routes/reply.py`: 18 routes — page, list/detail partials, status mgmt, background LLM generation + polling, draft CRUD, action CRUD + LLM extraction, memories CRUD, bulk auto-triage

**Templates** (8 new files): `pages/reply_workspace.html`, `partials/reply_list.html`, `partials/reply_detail.html`, `partials/reply_draft_card.html`, `partials/reply_actions.html`, `partials/reply_generating.html`, `partials/reply_memories.html`, `partials/reply_memory_editor.html`

**Memory files**: `data/memories/` with 6 seeded templates (general, enfants, finances, ecole, logement, vacances); `seed_memories()` in `database.py` called from `init_db()`

**Key features**:
- 5-tab triage strip (Pending/Drafted/Answered/N/A/All) with live counts
- Auto-select topic memories based on email's `email_topics` assignments; General always injected
- Keyboard shortcuts: j/k navigate, a=answered, s=skip, g=generate
- Bulk auto-triage: SQL-based classification of all unset received emails (answered/na/pending)
- Memories slide-out panel with inline markdown editor and file size display
- Full prompt traceability — every draft stores exact system+user prompts sent to LLM

### Web Dashboard Bug Fixes
- **2026-04-12 — `sqlite3.Row` has no `.get()`**: When a route fetches a row with `conn.execute(...).fetchone()`, the result is a `sqlite3.Row` — it supports bracket indexing `row["col"]` but NOT `.get("col")`. Always convert to `dict(row)` before calling `.get()`, or use `row["col"]` directly. Bug surfaced in `reply_detail` route: `email.get("thread_id")` raised `AttributeError`. Fix: `email_dict = dict(email)` then `email_dict.get("thread_id")`.
- **2026-03-25 — "View email" modal on timeline**: `hx-on::after-swap` added directly to "View email" link in `partials/timeline_list.html`; `href` changed to `#` to prevent fallback navigation. The global `htmx:afterSwap` handler in `app.js` was not reliably firing when the link resided inside a dynamically-swapped HTMX partial.
- **2026-04-07 — Procedures NOT NULL bug**: `update_procedure` and `create_procedure` routes used `field.strip() or None` which converts empty strings to NULL, violating NOT NULL DEFAULT '' columns. Fixed by removing `or None` for jurisdiction, description, outcome_summary, notes.
- **2026-04-07 — Emails page row click (FIXED)**: clicking an email row after a search didn't display the detail. Root cause: CSS breakpoint at `max-width: 1200px` collapsed `.emails-layout` to 1-column; with the 240px sidebar, a 1440px laptop content area was right at the threshold, pushing `#detail-panel` below the fold. Fix: (1) raised breakpoint to `1400px` for `emails-layout` + `detail-panel`, splitting them from `dashboard-two-col` (remains at 1200px); (2) added `htmx:afterSwap` auto-scroll in `emails.html` for narrow-screen fallback. CSS version bumped to `?v=8`.

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

### Always verify column names before writing queries
Use `PRAGMA table_info(table)` to confirm actual column names — multiple schema/route mismatches found (chapters used `date_from` but schema has `date_start`; `court_events` was dropped in migration 9 but CLI still referenced it).

### Changing NOT NULL constraints in SQLite
SQLite has no `ALTER COLUMN`. To make a column nullable: CREATE new table, INSERT SELECT, DROP old, RENAME new. See migration 14 (`procedure_id` on `procedure_events`) for the pattern.

### Alias backfill
When adding an alias to a contact (or creating a new contact), always backfill: `UPDATE emails SET contact_id = ? WHERE from_address = ? AND contact_id IS NULL`. Without this, existing emails from that address stay unlinked and don't appear in stats.

### contradictions.topic vs topic_id
The `contradictions` table has BOTH `topic` (TEXT, Excel-import path) and `topic_id` (FK, automated pipeline). Always use `COALESCE(c.topic, t.name)` when querying topic names.
