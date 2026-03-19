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
- **Web**: FastAPI + Jinja2 + HTMX (Phase 5 — not yet implemented)
- **Reports**: python-docx + weasyprint (Phase 4 — not yet implemented)

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
```

## Project Structure

```
cli.py                        # All CLI commands (click groups: fetch, contacts, topics,
                              #   search, show, stats, events, runs, init)
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
  llm/                        # (Phase 2) Abstract provider layer
  analysis/                   # (Phase 2) Topic classifier, tone, timeline, contradictions
    prompts/                  # Prompt templates (must work with French legal content)
  statistics/                 # (Phase 4) Frequency, response time, trend analysis
  reports/                    # (Phase 4) Word/PDF generation
  web/                        # (Phase 5) FastAPI dashboard
data/                         # Gitignored: emails.db, exports/
tests/
  test_parser.py              # 19 tests for quote stripping, subject normalization, lang detect
```

## Database Schema (Key Tables)

- **contacts** — `id, name, email, aliases (JSON list), role, notes`
- **emails** — `id, message_id (UNIQUE), thread_id, date, from_address, to_addresses (JSON), subject, subject_normalized, body_text, body_html, delta_text, delta_hash, direction, language, has_attachments, contact_id, folder, uid`
- **threads** — grouped by subject_normalized + References chain
- **topics** — predefined + AI-discovered; linked via **email_topics** (email_id, topic_id, confidence, run_id)
- **analysis_runs** — `id, analysis_type, provider_name, model_id, prompt_hash, prompt_version, status`
- **analysis_results** — one row per (run, email); stores full LLM JSON output
- **contradictions** — pairs of conflicting emails with severity + explanation
- **timeline_events** — extracted events with date, type, significance
- **court_events** — manually entered hearings, filings, decisions
- **fetch_state** — `(folder, contact_email)` → `last_uid` for resumable fetching
- **emails_fts** — FTS5 virtual table mirroring subject + body_text + delta_text + addresses

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

### ✅ Phase 2 — Intelligence (COMPLETE)
- `src/llm/`: abstract `LLMProvider` base class + Claude, Groq, OpenAI, Ollama implementations
- `src/llm/router.py`: `get_provider(task, override)` — reads `config.yaml` task_providers, caches instances
- `src/analysis/runner.py`: run lifecycle (create/finish), batch helpers, result storage, JSON parsing
- `src/analysis/classifier.py`: topic classification in batches (Groq default), stores to `email_topics`
- `src/analysis/tone.py`: tone/aggression/manipulation/legal-posturing analysis in batches
- `src/analysis/timeline.py`: per-email timeline event extraction, stores to `timeline_events`
- `src/analysis/prompts/`: 4 French-legal prompt templates (classify, tone, timeline, contradictions)
- New CLI commands: `analyze classify/tone/timeline/all/results/stats`
- Cost strategy: Groq (free) for classify+tone; Claude for timeline+contradictions

### 🔲 Phase 3 — Deep Analysis
- Contradiction detection across the corpus (intra-sender and cross-sender)
- Manipulation pattern detection
- Court event correlation (email tone/content around `court_events` dates)

### 🔲 Phase 4 — Statistics & Reports
- Response time analysis, frequency trends, topic evolution over time
- Word/PDF report generation

### 🔲 Phase 5 — Web Dashboard
- FastAPI + HTMX interactive timeline and search UI

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
    contradictions: claude
    manipulation: claude
  providers:
    claude:
      model: claude-sonnet-4-6
    groq:
      model: llama-3.3-70b-versatile

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
  skip_if_analyzed: true
```
