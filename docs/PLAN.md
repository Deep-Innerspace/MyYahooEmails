# MyYahooEmails — Architecture & Implementation Plan

## Context

A 10+ year archive of emails (mostly French, ~5000 unique after dedup) from a Yahoo mailbox related to an international divorce. The goal is to build a local analysis platform AND forward-looking email assistant that:
- Extracts emails via IMAP, filtered by sender/recipient addresses and date ranges
- Deduplicates conversation threads (keeping only unique content per reply)
- Classifies emails by topic (predefined list + AI-discovered categories)
- Analyzes tone, intent, and potential manipulation patterns
- Builds per-topic timelines correlated with external court events (imported from CSV)
- Computes statistics (frequency, response times, trends)
- Supports book writing with facts, human perspective analysis, and evidence traceability
- Provides a web dashboard (phase 2) and exportable reports
- **Future**: Auto-generate context-aware reply drafts for incoming emails from specific contacts (leveraging the full analysis history as context)

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.11+ | Best ecosystem for email/NLP/web |
| Database | SQLite + FTS5 | Zero setup, portable, full-text search built in |
| IMAP | `imapclient` | Clean API, better than stdlib `imaplib` |
| Email parsing | `mail-parser` + stdlib `email` | Robust MIME handling |
| LLM abstraction | Custom provider layer | Swap between Claude/OpenAI/Groq/Ollama |
| Web backend | FastAPI | Async, modern, auto-docs |
| Web frontend | Jinja2 + HTMX + Chart.js | Simple, no JS build step, highly interactive |
| Reports | `python-docx` + `weasyprint` | Word + PDF generation |
| CLI | `click` | Clean CLI with subcommands |
| Config | YAML + env vars | Credentials in `.env`, settings in `config.yaml` |

## Multi-LLM Provider Architecture

```
┌─────────────────────────────────┐
│        LLMRouter                │
│  (selects provider per task)    │
├─────────────────────────────────┤
│  ┌─────────┐ ┌──────┐ ┌──────┐ │
│  │ Claude  │ │OpenAI│ │ Groq │ │
│  └─────────┘ └──────┘ └──────┘ │
│  ┌─────────┐                    │
│  │ Ollama  │  (+ future ones)   │
│  └─────────┘                    │
└─────────────────────────────────┘
```

**Cost strategy:**
- **Dev/testing**: Groq (free tier) or Ollama (local, free)
- **Classification & simple tasks**: Groq or Ollama
- **Deep analysis** (tone, manipulation, contradictions): Claude Sonnet or GPT-4o
- **Critical final pass**: Claude Opus (optional, for highest-stakes emails)
- Config file controls which provider handles which task type

## Data Model (SQLite)

### Core tables
- **emails** — raw + parsed email data (message_id, date, from, to, subject, body_text, body_html, raw_mime, folder, direction, language, delta_text)
- **attachments** — binary attachments linked to emails
- **threads** — reconstructed conversation threads (via Message-ID/References/In-Reply-To)
- **topics** — user-defined topic categories
- **email_topics** — many-to-many with confidence score

### Analysis tables (multi-model, per-sender perspective)
- **contacts** — tracked people (name, email addresses, role: "me", "ex-wife", "lawyer", etc.)
- **analysis_runs** — one row per analysis execution (run_date, analysis_type, provider_name, model_id, prompt_hash, prompt_version label, status)
- **analysis_results** — per-email results linked to a run + sender perspective (run_id FK, email_id FK, sender_contact_id FK, result_json, created_at)
- **contradictions** — pairs of emails with conflicting statements + explanation + run_id (supports intra-sender AND cross-sender contradictions)
- **timeline_events** — extracted events per topic with dates and significance + run_id

This design allows:
- Multiple analyses per email from different models, coexisting in the DB
- Delete a full run or individual results
- Compare model outputs side-by-side for the same email
- Track prompt evolution (prompt_hash + version label)
- Every analysis anchored to sender perspective (her tone vs your tone)

### Context tables
- **court_events** — imported from CSV (date, type, description, jurisdiction)
- **external_events** — other key dates (moves, lawyer changes, etc.)

### Deduplication
- **delta_text** field on emails: the "new content only" after stripping quoted replies
- Thread table links replies together; analysis runs on delta_text, not full body
- Duplicate detection via content hashing of delta_text

## Project Structure

```
MyYahooEmails/
├── CLAUDE.md
├── README.md
├── pyproject.toml               # Dependencies, project metadata
├── config.yaml.example          # Template config
├── .env.example                 # Template for API keys
├── .gitignore
│
├── src/
│   ├── __init__.py
│   ├── config.py                # Load YAML config + .env
│   │
│   ├── extraction/              # IMAP fetch + parse
│   │   ├── imap_client.py       # Yahoo IMAP connection, folder listing, download
│   │   ├── parser.py            # MIME → structured data, quote stripping, delta extraction
│   │   └── threader.py          # Thread reconstruction from headers
│   │
│   ├── storage/
│   │   ├── database.py          # SQLite setup, migrations, FTS5 index
│   │   ├── models.py            # Dataclasses for Email, Thread, Analysis, etc.
│   │   └── search.py            # Full-text + filtered search queries
│   │
│   ├── llm/                     # Multi-LLM abstraction
│   │   ├── base.py              # Abstract LLMProvider interface
│   │   ├── router.py            # Task → provider routing logic
│   │   ├── claude_provider.py
│   │   ├── openai_provider.py
│   │   ├── groq_provider.py
│   │   └── ollama_provider.py
│   │
│   ├── analysis/
│   │   ├── classifier.py        # Topic classification
│   │   ├── tone_analyzer.py     # Sentiment, emotion, formality analysis
│   │   ├── timeline_builder.py  # Extract events, build per-topic timelines
│   │   ├── contradiction_finder.py  # Cross-email contradiction detection
│   │   ├── manipulation_analyzer.py # Detect evidence-manufacturing patterns
│   │   ├── prompts/             # Prompt templates (separate from code)
│   │   │   ├── classify.txt
│   │   │   ├── tone.txt
│   │   │   ├── contradiction.txt
│   │   │   └── manipulation.txt
│   │   └── batch_processor.py   # Orchestrates analysis pipeline with progress
│   │
│   ├── statistics/
│   │   ├── frequency.py         # Emails per day/week/month, by direction
│   │   ├── response_time.py     # Average response delays per topic/period
│   │   └── trends.py            # Tone evolution, topic shifts over time
│   │
│   ├── reports/
│   │   ├── docx_report.py       # Per-topic Word reports
│   │   ├── pdf_report.py        # PDF with charts
│   │   └── templates/           # Report templates
│   │
│   └── web/                     # Phase 2: Dashboard
│       ├── app.py               # FastAPI app
│       ├── routes/
│       │   ├── timeline.py
│       │   ├── search.py
│       │   ├── statistics.py
│       │   └── email_detail.py
│       ├── static/              # CSS, JS (Chart.js, HTMX)
│       └── templates/           # Jinja2 HTML templates
│
├── cli.py                       # Main CLI entry point (click)
│
├── data/                        # (gitignored) all local data
│   ├── emails.db
│   └── exports/
│
└── tests/
```

## CLI Interface

```bash
# Extraction — filter by contact and/or date range
python cli.py fetch --list-folders                        # List IMAP folders
python cli.py fetch --contact "ex@email.com"              # Fetch all from/to this address
python cli.py fetch --contact "ex@email.com" --since 2014-01-01 --until 2020-12-31
python cli.py fetch --contact "lawyer@firm.com"           # Can add multiple contacts
python cli.py fetch --status                              # Show download progress

# Analysis — each run is tagged with model and stored independently
python cli.py analyze classify --provider groq            # Topic classification
python cli.py analyze tone --provider claude              # Tone analysis (per sender)
python cli.py analyze contradictions --provider claude    # Intra & cross-sender
python cli.py analyze manipulation --provider claude      # Manipulation detection
python cli.py analyze all --provider groq                 # Run full pipeline

# Analysis run management
python cli.py runs list                                   # Show all analysis runs
python cli.py runs compare 12 15 --email-id 42           # Compare 2 runs for an email
python cli.py runs delete 12                              # Delete a full run
python cli.py runs delete 12 --email-id 42               # Delete single result

# Search & explore
python cli.py search "garde des enfants"                  # Full-text search
python cli.py search --topic children --from 2016 --to 2018

# Statistics
python cli.py stats overview                              # Global stats
python cli.py stats frequency --by month                  # Frequency chart
python cli.py stats response-times                        # Response time analysis

# Timeline
python cli.py timeline --topic flat                       # Show flat-related timeline
python cli.py timeline --all                              # All topics merged

# Court events
python cli.py events import court_dates.csv               # Bulk import from CSV/XLSX
python cli.py events add --date 2016-03-15 --type hearing --description "Custody hearing"
python cli.py events list                                 # Show all external events

# Reports
python cli.py report --topic children --format docx       # Word report
python cli.py report --all --format pdf                   # Full PDF report

# Web dashboard
python cli.py serve                                       # Start local web UI
```

## Implementation Phases

### Phase 1: Foundation (Email Extraction + Storage)
1. Project scaffolding (pyproject.toml, config, .gitignore)
2. SQLite database schema + migrations
3. IMAP client: connect to Yahoo, list folders, search by sender/recipient + date range
4. Email parser: MIME parsing, metadata extraction, French quote stripping, delta extraction
5. Thread reconstruction (References -> In-Reply-To -> Subject normalization)
6. Deduplication logic (content hash of delta_text)
7. Contact management (define watched addresses for targeted fetch)
8. Basic CLI: `fetch`, `search`, `stats overview`, `topics`

### Phase 2: Intelligence (AI Analysis)
1. LLM provider abstraction layer (base + all 4 providers)
2. LLM router (task -> provider mapping from config)
3. Prompt engineering for each analysis type (in French context)
4. Topic classifier
5. Tone/sentiment analyzer
6. Timeline event extractor
7. Batch processor with progress tracking, retry, and caching
8. CLI: `analyze` commands

### Phase 3: Deep Analysis
1. Contradiction detector (cross-email comparison)
2. Manipulation pattern analyzer
3. Court event correlation engine
4. External events overlay
5. CLI: `timeline`, `events` commands

### Phase 4: Statistics & Reports
1. Frequency statistics engine
2. Response time analysis
3. Trend analysis (tone evolution, topic shifts)
4. Word/PDF report generation with embedded charts
5. CLI: `stats`, `report` commands

### Phase 5: Web Dashboard
1. FastAPI app with Jinja2 templates
2. Interactive timeline view (per topic, with links to original emails)
3. Search interface with filters
4. Statistics charts (Chart.js)
5. Email detail view with analysis overlay
6. Court events overlay on timeline
7. CLI: `serve` command

### Phase 6 (Future): Email Reply Assistant
1. IMAP IDLE / periodic poll for new emails from watched contacts
2. Auto-classify incoming emails and pull relevant history
3. Generate context-aware reply drafts
4. Draft review and edit before sending
5. All drafts stored locally

## Topic Discovery Strategy

1. **Predefined topics**: User provides initial list (flat, accounting, children, divorce, contradictions, etc.)
2. **AI discovery pass**: After initial classification, the AI scans unclassified or low-confidence emails and proposes new topic clusters
3. **User refinement**: CLI command to review proposed topics, merge, rename, or discard
4. **Iterative**: Re-run classification after adding new topics

```bash
python cli.py topics list                                 # Show defined topics
python cli.py topics add "school" --description "..."     # Add custom topic
python cli.py topics discover --provider groq             # AI proposes new topics
python cli.py topics review                               # Interactive review of AI suggestions
```

## Key Design Decisions

### Bilingual quote stripping & delta extraction
The most critical preprocessing step. The system is **bilingual by design** (English Yahoo UI + French email content). Must handle both simultaneously:

**English patterns** (Yahoo UI, some clients):
- `>` prefix (standard)
- `On DATE, NAME wrote:` header before quoted block
- `-----Original Message-----` separator
- `From:` / `Sent:` / `To:` / `Subject:` headers in quoted blocks
- `---------- Forwarded message ----------`

**French patterns** (ex-wife's client, other French contacts):
- `Le XX/XX/XXXX a HH:MM, XXX a ecrit :` header
- `-----Message d'origine-----` separator
- `De :` / `Envoye :` / `A :` / `Objet :` headers in quoted blocks
- `---------- Message transfere ----------`

**Subject normalization** (strip all variants):
- English: `Re:`, `RE:`, `Fwd:`, `Fw:`
- French: `Re:`, `RE:`, `TR:` (transfere), `Ref:`

We'll use a pattern registry (list of compiled regexes) so new patterns can be added easily.

### Thread reconstruction priority
1. `References` header (most reliable)
2. `In-Reply-To` header
3. Subject-based grouping (normalized: strip Re:, Fwd:, RE:, TR:, etc.)
4. Content similarity within time windows (fallback)

### Prompt design for French legal context
All analysis prompts will be:
- Written in French (or bilingual with French primary)
- Tuned for divorce/family law context
- Include examples of manipulation patterns common in high-conflict divorces
- Request structured JSON output for machine-readable results

### Caching & incremental processing
- Each analysis result stored in DB with the provider name and prompt hash
- Re-running analysis skips already-processed emails unless `--force` flag
- Allows switching providers mid-project without losing work

## Yahoo IMAP Setup Requirements

The user will need to:
1. Enable IMAP in Yahoo Mail settings
2. Generate an "App Password" (Yahoo requires this with 2FA)
3. IMAP server: `imap.mail.yahoo.com`, port 993, SSL

**Safety guarantee**: The IMAP client is strictly READ-ONLY. It uses only `FETCH` and `SEARCH` commands. No `STORE`, `EXPUNGE`, `DELETE`, `MOVE`, or `COPY` commands are ever issued. Emails on Yahoo are never modified or deleted.

**Contact-based fetching**: The `--contact` flag triggers an IMAP SEARCH across all folders:
`OR (FROM "address") (OR (TO "address") (CC "address"))`
Combined with optional `SINCE`/`BEFORE` date filters. This captures both sides of every conversation with a given person.

## Cost Estimate (Phase 2 analysis)

~5,000 unique emails, average ~500 tokens each:
- **Groq (free tier)**: $0 — good for dev/testing and classification
- **Claude Sonnet** (deep analysis): ~$5-15 for full corpus
- **Ollama** (local): $0 — electricity only

Recommendation: Develop and validate all prompts with Groq/Ollama, then run final quality pass with Claude.

## Important Considerations

### Privacy & Security
- All data stays local (SQLite + filesystem). No cloud storage.
- API calls to Claude/OpenAI/Groq send email content to their servers — user should be aware of each provider's data retention policy.
- Ollama is fully local and private — best for initial development and sensitive content.
- `.env` file with API keys is gitignored. `config.yaml.example` ships without secrets.

### Bilingual by Design (English + French)
- Email bodies mostly in French, but Yahoo UI generates English metadata/headers
- All prompts written to handle both languages (instruct LLM to analyze in whichever language the email is in)
- French legal terminology in prompts (garde, pension alimentaire, JAF, etc.)
- Quote stripping handles both English and French patterns simultaneously
- Date formats: DD/MM/YYYY (European) throughout the UI, but parser also handles US formats in headers
- Language auto-detection per email stored in DB for filtering

### Resilience
- IMAP fetch is resumable (tracks last fetched UID per folder)
- Analysis is idempotent (skip already-processed, re-run with `--force`)
- All LLM calls have retry logic with exponential backoff
- Progress bars on long operations (tqdm)
