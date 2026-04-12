# Decision Log

> Append new entries at the bottom. Format: `## YYYY-MM-DD — Title`

---

## 2026-03-19 — Multi-address contact model

**Decision**: Contacts have a primary email + a JSON `aliases` list. The ex-wife used 4 different addresses over the years.

**Rationale**: A single contact entry with all known addresses ensures that every email from/to that contact is captured regardless of which address was used. The `seed_contacts()` function updates aliases without data loss on re-run.

**Impact**: `search_uids_by_contact()` searches each alias separately; `all_addresses_for_contact()` expands aliases in SQL WHERE clauses; `resolve_contact_id()` checks both primary and aliases on insert.

---

## 2026-03-19 — Delta text & deduplication strategy

**Decision**: Store only the "new" content per reply (`delta_text`) after stripping quoted sections. Use SHA256 hash (`delta_hash`) for duplicate detection.

**Rationale**: Reply chains re-include the entire prior conversation. Storing only the new content per email eliminates redundancy, reduces LLM token costs, and makes analysis cleaner. Duplicate detection via hash catches forwarded emails with identical content.

**Impact**: `strip_quotes()` handles both French and English quote patterns. All LLM analysis runs on `delta_text`. Emails with an existing `delta_hash` are silently skipped.

---

## 2026-03-19 — Groq free tier for all analysis (not just classify/tone)

**Decision**: Use Groq (free tier) for timeline extraction too, despite original plan to use Claude.

**Rationale**: Claude API costs are nonzero and the corpus is large (~1317 emails for timeline). Groq's llama-3.3-70b handles French legal text well enough for initial passes. Claude can be reserved for contradiction detection (cross-email reasoning) where it genuinely outperforms.

**Impact**: `config.yaml` task_providers: `timeline: groq`. Timeline scheduled at 7:07 AM, limit 50/day (~40k tokens/day).

---

## 2026-03-19 — Groq 100k/day rate limit management via scheduled tasks

**Decision**: Spread LLM analysis over multiple days using Claude Code scheduled tasks instead of running all at once.

**Rationale**: Groq free tier has a 100k tokens/day limit. Full corpus analysis (~1317 emails × ~118 tokens = ~155k for classify+tone alone) exceeds the daily limit in one shot.

**Schedule**:
- 6:03 AM: `daily-classify-tone` — classify + tone, 200 emails/day each (~54k tokens total)
- 7:07 AM: `daily-timeline` — timeline, 50 emails/day (~40k tokens)
- Total: ~94k/day, safely under limit

---

## 2026-03-19 — Removed sqlite3 detect_types to fix timestamp parsing

**Decision**: `_connect()` uses plain `sqlite3.connect(str(path))` with NO `detect_types` flag.

**Rationale**: With `detect_types=sqlite3.PARSE_DECLTYPES|PARSE_COLNAMES`, SQLite tried to auto-convert `TIMESTAMP` columns. Some dates stored without a time component (e.g., `"2016-03-15"`) caused `ValueError: not enough values to unpack (expected 2, got 1)`.

**Fix**: Remove `detect_types`; handle date parsing in application code when needed. All `date` values are stored as ISO 8601 strings.

---

## 2026-03-20 — Groq rate limiter: two-layer design with Retry-After

**Decision**: Implement rate limiting inside `GroqProvider.complete()` as two independent layers: a proactive rolling token bucket and a reactive 429 handler that prioritises the `Retry-After` response header.

**Rationale**: Previous implementation had no rate limiting at all. The Groq API hit its token/min ceiling silently, killing analysis runs with no retry. Groq documentation specifies: use `Retry-After` header when available; fall back to custom retry logic otherwise. A proactive bucket prevents most 429s; the reactive layer handles edge cases.

**Design choices**:
- Token bucket is **module-level** (not instance-level) so it persists across multiple `GroqProvider` instances in the same process
- Token estimate uses `len(prompt)//4 + max_tokens//2` — conservative on input, realistic on output (actual output is well below ceiling)
- Limit is **config-driven** (`rate_limit_tokens_per_min`) so it can be tuned without code changes
- Set to 10,000 (not 12,000) to leave a 2,000-token safety margin

**Impact**: `src/llm/groq_provider.py` fully rewritten. `src/config.py` gained `groq_token_rate_limit()`. Both `config.yaml` files updated. Analysis now runs stably at ~20 emails/min (1 batch/min).

---

## 2026-03-20 — GitHub repository created (private)

**Decision**: Push project to `Deep-Innerspace/MyYahooEmails` as a **private** repository on GitHub.

**Rationale**: Project contains sensitive personal/legal data (divorce case emails, contact details). SSH authentication configured via ed25519 key for secure, passwordless git operations.

**Impact**: Remote: `git@github.com:Deep-Innerspace/MyYahooEmails.git`. Initial commit: 42 files, 4,564 lines. `config.yaml`, `.env`, and `data/` remain gitignored.

---

## 2026-03-20 — Groq TPD discovery: rolling 24h window, config-driven threshold

**Decision**: Distinguish TPM (per-minute) vs TPD (per-day) rate limit hits by comparing `Retry-After` against a configurable `daily_limit_threshold_secs` (default: 300 s). On TPD hit, raise `GroqDailyLimitError` immediately instead of retrying.

**Rationale**: Groq's `Retry-After` for a TPM hit is typically 10–60 s; for a TPD hit it's typically 3,000–86,400 s (hours). Retrying in a loop against a TPD hit wastes compute and burns the small remaining TPM quota. The threshold of 300 s cleanly separates the two cases in practice.

**Critical finding**: Groq TPD resets on a **rolling 24-hour window** — NOT at midnight. This means:
- If a run hits TPD at 9 AM, quota won't clear until the same amount consumed 24h earlier drops off the window
- The `x-ratelimit-*` response headers expose TPM and RPD remaining but do NOT expose TPD remaining
- TPD exhaustion is only detectable by a 429 with a long Retry-After

**Reusable pattern for other Groq projects**:
```python
retry_after = exc.response.headers.get("retry-after")
if retry_after and float(retry_after) > DAILY_THRESHOLD:
    raise DailyLimitError(retry_after)   # abort cleanly
elif retry_after:
    time.sleep(float(retry_after))       # TPM hit, short wait
```

**Impact**: `_DAILY_LIMIT_THRESHOLD` in `groq_provider.py` now reads from `config.yaml` via `groq_daily_limit_threshold_secs()`. Four new config keys added. `GroqDailyLimitError` custom exception propagates to CLI for clean user-facing message.

---

## 2026-03-20 — Groq rate-check diagnostic tool

**Decision**: Add `tools/groq_rate_check.py` as a standalone runnable script (not a CLI command) that probes the Groq API with a minimal call and reports live quota status.

**Rationale**: Before launching or resuming a long analysis run, it's valuable to know whether Groq has available quota without burning a real batch. The `x-ratelimit-*` headers are returned on every successful response and contain precise TPM/RPD remaining values. Using `client.with_raw_response` in the Groq Python SDK gives direct access to the underlying httpx response headers.

**Key implementation detail**: A tiny probe prompt (`"Reply with the single word: OK"` with `max_tokens=5`) costs ~44 tokens — negligible against any limit. The `with_raw_response` context reads headers before parsing the response body.

**Reusable pattern for other Groq projects**:
```python
from groq import Groq
client = Groq(api_key=...)
raw = client.with_raw_response.chat.completions.create(...)
remaining_tokens = raw.headers.get("x-ratelimit-remaining-tokens")
remaining_requests = raw.headers.get("x-ratelimit-remaining-requests")
parsed = raw.parse()  # get the actual response content
```

**Impact**: New file `tools/groq_rate_check.py`. Exit code 0 = OK, 1 = rate limited (scriptable in CI or scheduled tasks). `--verbose` flag prints all raw rate-limit headers.

---

## 2026-03-19 — All folders fetch (`--all-folders` flag)

**Decision**: Added `--all-folders` flag that fetches every Yahoo folder except system ones (Trash, Draft, Bulk, Spam, Deleted Messages).

**Rationale**: User's emails span 91+ Yahoo folders (many created via search rules). It's impossible to know in advance which folders contain relevant emails. Skipping system folders avoids deleted/draft content while capturing everything else.

**Implementation**: `_SKIP_FOLDERS` set in `cli.py`; `get_folder_names()` returns all folders; CLI loops through each, fetching UIDs per alias and deduplicating before download.

---

## 2026-03-21 — Phase 3: Groq as default provider for all analysis during development

**Decision**: Use Groq (free tier) as the default provider for ALL analysis types during development — including contradictions, manipulation, and court correlation (originally planned for Claude).

**Rationale**: User explicitly required cost minimization during development. All analysis results are tagged with the LLM used (`provider_name`, `model_id` in `analysis_runs`), can be deleted via `runs delete`, and re-run with a different provider using `--provider claude`. This allows cheap Groq runs for testing, then re-running with Claude for production quality.

**Impact**: `config.yaml.example` sets `contradictions: groq`, `manipulation: groq`, `court_correlation: groq`. Users switch to Claude by changing config or using `--provider claude` flag.

---

## 2026-03-21 — Two-pass contradiction detection design

**Decision**: Implement contradiction detection as a two-pass pipeline: Pass 1 screens classification summaries grouped by topic (cheap), Pass 2 confirms flagged pairs using full delta_text (expensive, higher accuracy).

**Rationale**: With 1,326 emails, comparing all pairs is O(n²) ≈ 879k pairs — impossible in a single LLM call. Grouping by topic reduces the search space drastically (contradictions are most likely within the same topic). Pass 1 uses short summaries (~100 tokens each) in batches; Pass 2 only confirms the flagged subset with full text. `--skip-confirmation` flag allows Pass 1-only mode for faster iteration.

**Dependencies**: Requires a prior classify run (uses topic assignments to group). Defaults to most recent completed classify run; `--run-id` flag overrides.

---

## 2026-03-21 — Shared aggregator pattern for Phase 4

**Decision**: Create a single `src/statistics/aggregator.py` module with 10 SQL aggregation functions that are shared between CLI stats commands and report builders.

**Rationale**: Without this, the same SQL queries would be duplicated in cli.py (for terminal display) and in builder.py (for report generation). The aggregator returns Python dicts/lists; display formatting is the caller's responsibility. This also makes it easy to add new consumers (e.g., Phase 5 web dashboard).

**Impact**: Refactored existing `stats overview` and `stats frequency` CLI commands to call `aggregator.overview_stats()` and `aggregator.frequency_data()`. Four new stats commands and four report builders all use the same aggregator functions.

---

## 2026-03-21 — Renderer-agnostic report dataclasses

**Decision**: Report data is structured as `Report` and `ReportSection` dataclasses (in `builder.py`) that are renderer-agnostic. Separate renderers (`docx_renderer.py`, `pdf_renderer.py`) consume these structures.

**Rationale**: Decouples content from presentation. Adding a new format (e.g., HTML for web dashboard) only requires a new renderer, not changes to the builders. Each `ReportSection` has: title, level (1-3), paragraphs, optional table dict, optional chart PNG path, and nested subsections.

**Impact**: `render_docx()` and `render_pdf()` both accept the same `Report` object. PDF requires system deps (`brew install pango`); DOCX works out of the box.

---

## 2026-03-21 — WeasyPrint lazy import for graceful degradation

**Decision**: Import `weasyprint.HTML` inside `render_pdf()` (lazy) rather than at module level, with a helpful error message if system dependencies are missing.

**Rationale**: WeasyPrint requires Pango, Cairo, and GObject system libraries (`brew install pango` on macOS). If imported at module level, even DOCX generation would fail when these are absent. Lazy import means the PDF renderer only fails when actually called, and DOCX works regardless.

**Impact**: `src/reports/pdf_renderer.py` wraps the import in try/except OSError, re-raising with installation instructions.

---

## 2026-03-22 — Dual-perspective web dashboard (single app, cookie-based)

**Decision**: Implement Legal and Book perspectives as a single FastAPI application with a cookie-based perspective switcher, not two separate apps or URL-prefix-separated sections.

**Rationale**: Both perspectives share the same database, same emails, same analysis. Only the UI emphasis, sidebar navigation, dashboard sections, and available features differ. A cookie (`perspective=legal|book`) drives CSS class on `<body>` (navy vs green theming), Jinja2 `{% if perspective == 'legal' %}` conditionals for navigation, and perspective-aware notes.

**Impact**: `get_perspective()` reads cookie (default: legal). `POST /set-perspective` sets 30-day cookie + redirect. CSS variables change sidebar color, accent. Template conditionals show/hide Legal Analysis / Book Writing nav sections.

---

## 2026-03-22 — HTMX for interactivity (no JS framework)

**Decision**: Use HTMX for all interactive behavior — tab switching, email detail panel loading, filter updates, notes CRUD, pagination — with zero JavaScript framework.

**Rationale**: Server-rendered HTML with HTMX partials is simpler to build and maintain than a React/Vue SPA. The dashboard is a personal tool, not a public product. HTMX's `hx-get`, `hx-post`, `hx-target`, `hx-swap` handle all the needed interactivity. No build step, no node_modules, no API layer to maintain.

**Key pattern**: Routes check `request.headers.get("HX-Request")` to return partial or full-page template. Email browser uses `hx-get="/emails/{id}" hx-target="#detail-panel"` for inline detail loading.

**Impact**: 30+ Jinja2 templates (14 pages + 10+ partials), zero JS framework code, `app.js` is only ~30 lines (perspective switch + quote selection).

---

## 2026-03-22 — Chart endpoints reuse existing matplotlib generators

**Decision**: Web chart endpoints (`/charts/*`) call existing `src/reports/charts.py` functions via `tempfile.TemporaryDirectory()` and stream the resulting PNG as `FileResponse`.

**Rationale**: Zero modification to existing Phase 4 code. The chart functions write PNGs to disk (designed for report embedding). Web routes create a temp dir, call the function, read the file, and stream bytes. If chart functions are ever updated, web gets the changes for free.

**Impact**: 5 chart endpoints added. No code duplication between CLI reports and web charts.

---

## 2026-03-22 — SQLite `check_same_thread=False` for FastAPI

**Decision**: Added `check_same_thread=False` to `sqlite3.connect()` in `database.py`.

**Rationale**: FastAPI runs route handlers in a thread pool. SQLite's default `check_same_thread=True` raises errors when a connection created in one thread is used in another. Since the app is single-user and single-process, thread safety is adequate with `check_same_thread=False`.

**Impact**: `src/storage/database.py` `_connect()` function updated. All existing CLI usage unaffected.

---

## 2026-03-22 — Perspective-aware notes system

**Decision**: Notes have a `perspective` column (legal/book) so the same email can have separate legal annotations and book annotations. Both tabs always visible regardless of current perspective.

**Rationale**: A divorce email might need a legal note ("contradicts testimony on X date") AND a book note ("illustrates emotional escalation pattern — good Chapter 3 material"). Keeping them separate prevents cross-contamination while allowing the user to see both perspectives.

**Impact**: `notes` table with `entity_type + entity_id + perspective + category + content`. `note_list.html` partial shows tabbed Legal/Book view. Add-note form defaults to current perspective.

---

## 2026-03-23 — Excel round-trip as primary analysis path (ChatGPT as provider)

**Decision**: Use an Excel export → ChatGPT Plus → Excel import workflow as the primary analysis path for classify and tone, instead of the Groq scheduled-task approach.

**Rationale**: Groq's free tier imposes a 100k tokens/day rolling limit, requiring ~28 days to complete all three analysis types. ChatGPT Plus (gpt-5.4-thinking) has a 196k token context window and 3,000 messages/week limit — effectively unlimited for this corpus. The Excel round-trip adds manual steps but eliminates the multi-week wait and TPD management overhead. Results are imported back with full traceability (provider_name, model_id tagged on every run).

**Impact**: New files `src/analysis/excel_export.py` and `src/analysis/excel_import.py`. New CLI commands `analyze export` and `analyze import-results`. New dependency: `openpyxl`. Achieved 98% classify + 98% tone coverage in a single session.

---

## 2026-03-23 — ChatGPT gpt-5.4-thinking as primary analysis provider

**Decision**: Use OpenAI ChatGPT Plus with model `gpt-5.4-thinking` (gpt-5.4) for all Excel round-trip analysis.

**Rationale**: Available via ChatGPT Plus subscription at no additional API cost. 196k context window accommodates ~230 emails per batch with instructions comfortably. "thinking" model produces high-quality topic classification and tone analysis on French legal text. Results are tagged in DB as `provider_name=openai, model_id=gpt-5.4-thinking`.

**Impact**: Classification and tone analysis at 98% coverage achieved without any API spend. Multiple batches can be processed in parallel using separate ChatGPT conversations.

---

## 2026-03-23 — 230 emails per batch as optimal ChatGPT batch size

**Decision**: Use batches of ~230 emails as the standard batch size for Excel round-trip exports to ChatGPT.

**Rationale**: At ~230 emails × ~500 chars delta_text average + instruction overhead, batches fit comfortably within ChatGPT's 196k context window while leaving room for the model's output. Smaller batches would require more manual steps; larger batches risk hitting context limits or degrading output quality.

**Impact**: 6 classify batches (runs #17–22, #29) + 8 tone batches (runs #23–28, #30–31) covered the full corpus. Standard export command: `analyze export --limit 230 --offset <N*230>`.

---

## 2026-03-23 — ASC date order as standard for all Excel exports

**Decision**: All Excel batch exports use `ORDER BY e.date ASC` (oldest emails first) as the consistent standard.

**Rationale**: Early in the session, batch 01 was exported with DESC order (most recent first). When the export was corrected to ASC, the sort inconsistency combined with missing `--offset` caused tone batch duplication — batches 02–09 all exported the same 230 emails. Establishing ASC as the single standard prevents future inconsistencies and ensures chronological coverage from the start of the corpus.

**Impact**: `excel_export.py` uses `ORDER BY e.date ASC` unconditionally. All future exports are consistent and offset-paginated correctly.

---

## 2026-03-24 — Manipulation blank rows stored as total_score=0.0 (not skipped)

**Decision**: When `_parse_manipulation()` encounters a blank `total_score` row in an imported XLSX, store a zero-score result (`total_score=0.0, patterns=[], dominant_pattern=null`) rather than returning `None` and skipping the row.

**Rationale**: For manipulation analysis, a blank row means "ChatGPT reviewed this email and found no manipulation" — a meaningful, valid result. Skipping it means: (1) it does not count toward coverage %, (2) it reappears in the next export batch wasting ChatGPT quota, (3) there is no record it was ever reviewed. This is different from classify/tone, where blank means "the model was undecided / email too ambiguous" and skipping is correct behaviour.

**Rule**: For analysis types where the absence of a finding is itself a result (manipulation, and likely timeline), blank rows must be stored as zero/empty results. For classify/tone, blank means "not processed" and should be skipped.

**Impact**: `src/analysis/excel_import.py` `_parse_manipulation()` updated. All 230 rows per batch are now stored (both manipulative and clean emails).

---

## 2026-03-24 — Contradictions export uses classified summaries, not delta_text

**Decision**: The contradictions XLSX export uses two sheets: an "Emails" sheet with classified summaries (email_id, date, direction, subject, summary, topics) and a "Contradictions" output sheet for ChatGPT to fill. The Emails sheet uses stored classification summaries, NOT delta_text.

**Rationale**: Full delta_text for 200+ emails would often exceed ChatGPT's context window, and is unnecessary for contradiction detection — what matters is what each email was *about*, not its verbatim content. Classification summaries (~50–100 tokens each vs. 300–1,000+ for delta_text) make batches 3–5x more token-efficient and allow grouping more emails per context window. The trade-off is that the LLM cannot quote exact phrases, but contradiction detection at the summary level is sufficient for the first pass; Pass 2 confirmation (if run) uses full text.

**Impact**: `src/analysis/excel_export.py` contradictions export path selects from `analysis_results` (classify summaries) rather than the `emails` table's `delta_text`. `--topic` and `--date-from`/`--date-to` flags added to support splitting large topics across multiple batches.

---

## 2026-03-24 — mark-uncovered command for residual unclassified emails

**Decision**: Add `python cli.py analyze mark-uncovered` to tag remaining unclassified emails as either "trop_court" (too short, no meaningful content after delta stripping) or "non_classifiable" (ambiguous, multiple topics with no dominant one). Both topics are created on first run if absent.

**Rationale**: After ChatGPT batches achieve ~98–99% coverage, a small tail of emails remains unclassified — typically very short acknowledgments ("OK", "Reçu") or emails where the delta_text is essentially empty. These need to be tracked to reach 100% coverage and prevent them from appearing in future export batches. However, they should be excluded from topic distribution analysis because they are not substantively classifiable. A rule-based "manual" run is the appropriate mechanism.

**Impact**: New CLI command `analyze mark-uncovered`. Creates topics "trop_court" and "non_classifiable" if absent. Creates an `analysis_run` with `provider_name="manual"`, `model_id="rule-based"`. Web dashboard topic analysis tab excludes these two topics from distribution charts and shows a live count of how many emails fall into each.

---

## 2026-03-24 — Groq reserved for oversized emails only; ChatGPT as primary provider

**Decision**: Groq (128k context) is reserved exclusively for emails that exceed the Excel cell limit (32,767 chars) and therefore cannot be exported to ChatGPT batches. For all other emails, ChatGPT Plus (gpt-5.4-thinking, 196k context) via the Excel round-trip pipeline is the primary provider.

**Rationale**: In practice, oversized emails are rare (<1% of the corpus). Groq's 100k tokens/day limit and multi-week processing timeline are unnecessary complications when ChatGPT Plus can handle the entire corpus at no additional cost via the Excel pipeline. Maintaining two active analysis paths adds operational complexity with minimal benefit.

**Impact**: Groq's scheduled tasks (daily-classify-tone, daily-timeline) are no longer needed for the primary analysis workflow. Groq is still configured and available for oversized emails or re-runs on specific emails. Config `task_providers` unchanged — just the operational practice changes.

---

## 2026-03-24 — Body-level tooltip to escape card overflow:hidden

**Problem**: Chart info icons (ⓘ) used CSS `::after` pseudo-elements for tooltips. These were visually clipped by `.card { overflow: hidden }` in `style.css`.

**Decision**: Replaced CSS pseudo-element tooltips with a single JS-driven floating `<div id="info-tooltip">` appended inside `<body>` (in `base.html`). Positioned via `position: fixed` so it is completely outside the card stacking context and never clipped.

**Details**:
- JS in `base.html` attaches `mouseenter`/`mouseleave` to all `.info-icon` elements on page load
- Also attaches on `htmx:afterSwap` events so dynamically-loaded HTMX partials get tooltips automatically
- Arrow caret position recalculated per icon so it always points to the triggering element
- Tooltip flips below icon if not enough space above (viewport-aware)

**Impact**: All pages with charts now have properly visible tooltips. `manipulation.html` local duplicate CSS/JS removed — now inherits from global system.

---

## 2026-03-24 — Groq API usage: manual-only for analysis

**Decision**: All Groq-based analysis tasks (classify, tone, timeline, contradictions, manipulation, court_correlation) are now run **manually only** — no scheduled tasks.

**Rationale**: Groq free-tier TPD (100k tokens/day rolling 24h window) is easily exhausted. Scheduled background runs caused unexpected daily limit hits that blocked manual interactive use. The ChatGPT Excel pipeline (gpt-5.4-thinking) is the primary analysis method; Groq is reserved for oversized emails (>32,767 chars) that cannot be exported to Excel.

**Impact**: All 4 previously-configured cron/scheduled tasks deleted. Groq invoked only via explicit `python cli.py analyze <type>` commands.

---

## 2026-03-24 — contradictions.topic as TEXT column (not FK)

**Decision**: Added `topic TEXT` column to the `contradictions` table alongside the existing `topic_id INTEGER` FK column.

**Rationale**: The Excel importer writes the topic as a free-text string (e.g. "enfants", "ecole") as filled by ChatGPT. Resolving these to `topic_id` FK values at import time would require a lookup that could silently fail for sub-topic names ChatGPT invents (e.g. "education", "procedure" instead of the canonical topic names). Keeping a `topic TEXT` column is more robust for the import path; the automated pipeline continues using `topic_id`.

**Fix applied**: `ALTER TABLE contradictions ADD COLUMN topic TEXT` (live migration, 2026-03-24).

---

## 2026-03-24 — ChatGPT contradiction prompt strategy: topic-specific + batch context

**Decision**: Create per-topic prompt files (`tools/chatgpt_prompt_<topic>.txt`) rather than one generic prompt, with a "BATCH CONTEXT" header the user fills in before each upload.

**Rationale**: For topics split across multiple batches (enfants = 5 batches), ChatGPT needs to know it is seeing a time-slice — not the full history. Without this, it may under-report contradictions because "the context might be elsewhere". The per-topic prompt also includes domain-specific contradiction examples (custody schedules, school enrolments, child support) that improve precision vs. generic examples.

**Impact**: `tools/chatgpt_prompt_contradictions.md` (generic reference + all-batch table), `tools/chatgpt_prompt_enfants.txt` (ready-to-paste, with fill-in batch context block). Future topics should get their own `.txt` file following the same pattern.

---

## 2026-03-24 — Import batches sequentially, never in parallel

**Decision**: Always run `python cli.py analyze import-results` for one file at a time, never in a loop sent to background.

**Rationale**: SQLite WAL mode does not support concurrent writes from multiple processes. Running a `for` loop as a background task while also importing in the foreground caused `database is locked` errors on all rows, leaving runs with `status=partial` and 0 imported rows. Cleanup required: delete duplicate `analysis_runs` rows and the orphaned `contradictions` rows they created.

**Impact**: Import command must always be run sequentially. Never use `run_in_background=true` for import loops.

---

## 2026-03-25 — Timeline extraction strategy: in-session Claude analysis

**Decision**: Perform timeline event extraction in-session (Claude acting as analyst) rather than uploading batches to ChatGPT or running Groq.

**Rationale**: Timeline analysis requires careful forensic reading of each email to extract dated, typed events (legal filings, financial transactions, child facts, accusations, etc.). Claude can do this accurately within the context window. The Excel export/import pipeline is reused — Claude reads the export, fills a RESULTS dict, writes the filled XLSX, then imports it. This avoids ChatGPT upload overhead and Groq rate limits, while keeping full traceability (provider=claude, model=claude-sonnet-4-6).

**Pattern**: Read batch in ~50-email chunks via bash → build RESULTS = {email_id: (date, type, significance, description)} → Python script writes filled XLSX → `python cli.py analyze import-results ... --type timeline --provider claude --model claude-sonnet-4-6`.

**Fill rate**: 14–21% per batch is acceptable — many emails are logistics/forwarding/weekly reports with no extractable temporal fact anchor. Target 20–35%.

---

## 2026-03-25 — HTMX modal: hx-on::after-swap over global htmx:afterSwap handler

**Decision**: Use `hx-on::after-swap` inline attribute on "View email" links instead of relying solely on the global `document.addEventListener('htmx:afterSwap', ...)` handler in `app.js`.

**Rationale**: The global handler with `evt.detail.target.id === 'email-modal'` check was not reliably firing when the triggering link was inside content that had itself been dynamically swapped by HTMX (the `#timeline-list` partial). Using `hx-on::after-swap` on the element itself fires directly when that specific element's swap completes, regardless of nesting.

**Impact**: `href` also changed to `#` to prevent browser navigation if HTMX is ever slow to intercept. The global handler in `app.js` is retained as a fallback.

---

## 2026-03-27 — Corpus column approach for lawyer emails (not separate tables)

**Decision**: Add a `corpus` column (`'personal'` | `'legal'`) to the existing `emails` table rather than creating a separate `lawyer_emails` table.

**Rationale**: The email structure is identical for both corpora — what differs is the analysis on top. A single table enables: full code reuse (fetch, parse, thread, FTS5, search), cross-corpus timeline correlation queries via simple JOINs, and a unified FTS5 index. The cost is adding `WHERE corpus = ?` to ~35-40 queries, managed via a centralized `corpus_clause()` helper.

**Impact**: All existing 3,922 emails default to `corpus='personal'`. 131 emails to/from known lawyer addresses auto-reclassified to `corpus='legal'`. New tables (`procedures`, `procedure_events`, `lawyer_invoices`) reference `emails.id` across both corpora.

---

## 2026-03-27 — Lightweight migration system (schema_version + _MIGRATIONS list)

**Decision**: Introduce a `schema_version` table and `_MIGRATIONS` list of `(id, description, sql)` tuples in `database.py`. `init_db()` runs `_SCHEMA` first (for fresh DBs), then `_run_migrations()` (for existing DBs), then `_INDEXES` (last, so new columns exist).

**Rationale**: The project had no migration framework — only `CREATE TABLE IF NOT EXISTS` which can't add columns to existing tables. SQLite's `ALTER TABLE ADD COLUMN` requires `DEFAULT` values for `NOT NULL` columns. This lightweight approach avoids Alembic overhead while supporting incremental schema evolution. Duplicate column errors are caught and silently skipped for idempotency.

**Impact**: 10 initial migrations applied: corpus column, 6 attachment columns, 3 new tables, court_events drop, lawyer email reclassification. Order: schema → migrations → indexes (critical — indexes on new columns must come after migrations).

---

## 2026-03-27 — Drop court_events, replace with procedures + procedure_events

**Decision**: Drop the `court_events` table entirely (confirmed empty, 0 rows) and replace with a richer two-table model: `procedures` (the legal proceeding) + `procedure_events` (events within a proceeding).

**Rationale**: A flat `court_events` table can't represent the structure of French divorce law: multiple parallel procedures (divorce principal, garde, pension, appel), each with their own jurisdiction, case number, parties' lawyers, and sequence of events. The two-table model allows grouping events by procedure, tracking which lawyer represented which party per procedure, and linking events to source emails and attachments.

**Impact**: `court_events` dropped. `procedures` table: type, jurisdiction, case_number, initiated_by, party_a/b_lawyer_id, status. `procedure_events` table: event_type (filing/hearing/judgment/etc.), date_precision, source_email_id, source_attachment_id. `court_correlator.py` will be refactored in Phase 6e.

---

## 2026-03-27 — Extend attachments table (not replace) for on-demand download

**Decision**: Add 6 columns to the existing `attachments` table rather than creating a new `email_attachments` table. Existing 1,464 BLOB rows get `downloaded=1` automatically via DEFAULT.

**Rationale**: The existing attachments table has 1,464 rows with actual BLOB content — can't simply replace it. Extending it keeps one codebase for attachment handling across both corpora. Personal corpus: content in BLOB column (already downloaded). Legal corpus: `downloaded=0`, `mime_section`+`imap_uid`+`folder` stored for on-demand IMAP re-fetch. Both served through the same web endpoint.

**Impact**: New columns: `mime_section` (IMAP part ID), `imap_uid`, `folder`, `downloaded` (bool), `download_path` (filesystem), `category` (document classification). Existing rows: `downloaded=1`, other new columns NULL.

---

## 2026-04-02 — Invoice scan workspace: split-panel triage design

**Decision**: Redesign the invoice scan page as a persistent two-panel workspace (email-client style) instead of a list-navigate-back-list workflow.

**Rationale**: The original scan page required navigating away from the list for every email, then back, losing scroll position and filter context each time. With 100+ invoice emails to triage, this was too slow. The new design keeps both panels visible simultaneously, auto-advances to the next email after each action, and retains filter state across actions.

**Key design choices**:
- Left panel (280px fixed): compact rows with status icons, 5-tab strip, HTMX row click → detail
- Right panel: full email context + sticky action strip (Invoice / Payment / Assessed tabs)
- Amount detection via EUR regex auto-fills form fields; clicking chips also pre-fills HT via ÷1.20
- All POST actions return combined HTML: main body = next-email detail, OOB = updated list
- `_build_scan_action_response()` central helper handles all 4 action routes identically
- Two new tables: `payment_confirmations` (migration 15) and `invoice_scan_dismissed` (migration 16)

**Impact**: `src/web/routes/invoices.py` +7 scan routes +7 helper functions. Three new template partials (scan_list, scan_detail, scan_done). `invoice_scan.html` full rewrite.

---

## 2026-04-02 — IMAP stale UID: two-pass recovery + subject disambiguation

**Decision**: Extend `_find_email_imap_location()` in `attachments.py` with Pass 2 (all IMAP folders) and `_pick_uid_by_subject()` for disambiguation.

**Rationale**: Yahoo invalidates UIDs when emails are moved between folders. The original Pass 1 only searched folders already in the DB. A folder created by the user after the initial fetch (e.g. `vclavocat`) would never be searched, leaving the attachment permanently unfetchable. Additionally, SENTON+FROM searches can return multiple UIDs when two emails from the same sender arrive on the same day — without disambiguation, the wrong UID would be used.

**Pass 2 implementation**: `client.list_folders()` returns ALL current Yahoo IMAP folders; Skip set: `{"trash", "spam", "bulk", "draft", "deleted messages"}` (case-insensitive). A single IMAP connection is reused across both passes for efficiency.

**Subject disambiguation**: `_pick_uid_by_subject()` fetches `ENVELOPE` for all candidate UIDs, normalizes the subject string, and matches against `subject_normalized` from the emails table. Falls back to `uids[0]` if envelope fetch fails.

**`[UNAVAILABLE]` as "not found here"**: Yahoo returns `[UNAVAILABLE]` both for transient server errors AND for non-existent UIDs after an email is moved. Retrying with delays (original fix) wasted 21+ seconds and still failed. Correct fix: return `None` immediately on `[UNAVAILABLE]` to trigger stale-UID recovery path without delay.

**Impact**: `src/web/routes/attachments.py` (Pass 2 + disambiguation), `src/extraction/imap_client.py` (`fetch_mime_part` catches `[UNAVAILABLE]`). Any future feature storing `imap_uid + folder` for on-demand fetch must apply the same fallback.

---

## 2026-04-02 — HTMX two-panel sync: unified afterSwap handler + OOB exclusion

**Decision**: Replace the `htmx:afterRequest` filter-form handler with a single `htmx:afterSwap` handler that manages list→detail auto-load and active-row sync, using `hx-post` attribute presence to exclude OOB updates from action routes.

**Rationale**: `htmx:afterRequest` fires before the DOM swap, so querying `.sl-row` returns stale list content. `htmx:afterSwap` fires after — rows are in the DOM and first-row auto-load works reliably. Using `htmx:afterSwap` for both responsibilities (list update → load detail; detail update → sync highlight) avoids double-registration and makes the logic easier to reason about.

**OOB exclusion**: when a POST action route returns `detail_html + list_html (OOB)`, two `htmx:afterSwap` events fire (one per swap). For the list OOB, `evt.detail.elt` is the action form, which has `hx-post="/invoices/scan/…"`. The check `hxPost?.includes('/invoices/scan/')` correctly skips the auto-detail-load for these (the main response already contains the correct next-email detail).

**Auto-fallback in routes**: Both `scan_list` and `scan_detail` routes auto-switch `active_tab` to `"all"` when the requested tab has no matches, so the user always sees content after a filter change rather than an empty-tab + scan_done flash.

**Impact**: `invoice_scan.html` JS section rewritten (~40 lines). `invoices.py` scan_list + scan_detail routes updated with fallback logic.

---

## 2026-04-04 — Document-first strategy for procedure metadata

**Decision**: Populate procedure metadata by uploading court PDFs and having Claude extract+insert all fields via pdfplumber, rather than an Excel round-trip or manual entry.

**Rationale**: LLMs cannot infer RG numbers, jurisdictions, dates, lawyers, or financial outcomes from email context alone — they need the actual documents. The upload infrastructure (procedure_documents table + file storage) was already in place from last session. pdfplumber extracts text reliably from French court PDFs. Claude can then parse all relevant fields and generate SQL in a single step.

**Workflow**: User uploads PDF via web UI → user asks Claude to "analyse the judgment of [procedure name]" → Claude reads via pdfplumber → generates UPDATE + INSERT procedure_events SQL → commits in a single transaction.

**Bug discovered**: When an INSERT fails mid-script before `conn.commit()`, any previously executed UPDATEs in the same transaction are also rolled back. Fix: always commit each logical unit separately, or use explicit `notes=''` (empty string, not `None`) for NOT NULL columns with DEFAULT ''.

**Impact**: Procedures #1, #8, #9, #10, #12, #13 fully populated this session. 41 procedure_events total. pdfplumber now a de-facto dependency (already installed).

---

## 2026-04-04 — Procedure #8 vs #9 disambiguation

**Decision**: The ordonnance du JME du 20/02/2017 (TGI Paris, RG 15/33553) belongs to procedure #8 "Incident", not procedure #9 "Incident — Appel".

**Rationale**: Procedure #9 is the art. 526 CPC radiation incident at the Cour d'Appel (RG 17/18289, 02/10/2018). Procedure #8 is an earlier incident during the first-instance divorce instruction, decided by the JME Sophie LECARME at the TGI Paris. Both share the same underlying RG 15/33553 but are distinct proceedings at different court levels and dates.

**Impact**: `data/documents/procedures/8/9_ordonnance_JME_20022017.pdf` — copied from Downloads and linked to procedure #8.

---

## 2026-04-04 — Acquiescements procedure type = private protocol, not court judgment

**Decision**: Procedure #10 "Acquiescements" is a private settlement protocol (not a court judgment). The document type is `convention`, not `judgment`.

**Rationale**: The "Protocole d'accord" signed 04/09/2020 is a private contract between the parties and their lawyers that formalises acquiescements to two recent judgments and settles the financial accounts between them. It has no RG number from a court. The case_number field was set to "Protocole du 04/09/2020" to distinguish it from court proceedings.

**Impact**: `procedure_documents.doc_type` updated to `'convention'` for doc #11. Highlights that not all procedures in the system map to court cases — some are private agreements.

---

## 2026-04-05 — Direct in-session LLM analysis for oversized legal emails

**Decision**: Analyze the 150 legal corpus emails that exceeded the Excel cell limit (30,000 chars) directly in-session as Claude, reading from DB and writing results back without an external API call.

**Rationale**: These emails (May–July 2015 forwarded evidence chains) were excluded from the Excel export pipeline by `_LEGAL_CELL_LIMIT = 30000`. Options considered:
1. Raise the limit — rejected: Excel crashes on 30k+ cells; ChatGPT context would be overwhelmed by a single email
2. Call Claude API externally — rejected by user: preferred in-session approach for traceability and cost
3. Direct in-session analysis — chosen: read emails from DB in batches of 10–25, analyze as Claude, write JSON results back to `analysis_results` and events to `procedure_events`/`timeline_events`

**Storage pattern**: identical to `_import_legal_analysis()` in `excel_import.py` — ensures consistency with Excel-imported results.

**IDs tracking**: `/tmp/legal_remaining_ids.json` stores `{run_id, ids}` for session-resumable batch processing.

**Impact**: `run_id=156` completed with 150/150 emails, 131 procedure_events. This approach is reusable for any future oversized batch.

---

## 2026-04-05 — Legal corpus KPIs added to dashboard

**Decision**: Add a dedicated "Legal Corpus Analysis" card to the dashboard (legal-only perspective) showing completion percentage, procedures count, procedure events count, and invoice count.

**Rationale**: The legal analysis is now 100% complete. The dashboard previously showed only personal corpus analysis coverage. Legal corpus data (2,743 emails, 15 procedures, 2,114 events) is a significant body of work that deserves visibility in the top-level overview.

**Implementation**: New full-width card in the `legal-only` section, spanning all grid columns. Three new fields added to `overview_stats()`: `legal_analysis_count`, `procedures_count`, `invoices_count`.

**Impact**: `src/statistics/aggregator.py` + `src/web/templates/pages/dashboard.html`.

---

## 2026-04-06 — Classify/Tone/Manipulation restricted to personal corpus only

**Decision**: These three analysis types are permanently restricted to `corpus='personal'` emails. Legal corpus emails will never be classified, tone-analysed, or manipulation-scored.

**Rationale**: The prompts are calibrated for intimate partner conflict dynamics (gaslighting, emotional weaponization, children instrumentalization, aggression scoring). Legal correspondence is formal by construction — the same language that scores "high aggression" in personal emails is standard register in lawyer letters. Running these analyses on legal emails produces noise, not signal. The `legal_analysis` type already captures the relevant legal dimensions (`lawyer_stance`, `risk_signal`, `strategy_signal`, `action_required`).

**Implementation**:
- `src/analysis/runner.py` `get_emails_for_analysis()`: hardcoded `e.corpus = 'personal'`
- `src/analysis/excel_export.py` `export_for_analysis()`: hardcoded `e.corpus = 'personal'`
- `cli.py` `analyze_mark_uncovered`: added `corpus = 'personal'` filter
- `cli.py` `analyze_stats`: refactored to show both corpora separately with correct denominators
- DB cleanup: 417 analysis_results rows + 304 email_topics rows deleted for 131 legal emails that were originally personal

---

## 2026-04-06 — procedure_events is the authoritative event source for legal corpus; timeline_events is personal only

**Decision**: `timeline_events` table contains only personal corpus events. `procedure_events` is the sole event source for the legal corpus.

**Rationale**: Inspection of the 18 legal emails that had both `timeline_events` and `procedure_events` showed pure duplication — same event, different framing — with `procedure_events` being richer (structured `event_type`, `date_precision`, `outcome`). The 2,114 `procedure_events` from `legal_analysis` already cover the legal event space comprehensively. Adding `timeline_events` on top would create maintenance burden with no analytical gain.

**Implementation**: Deleted 22 `timeline_events` rows for legal corpus emails.

**Impact on Phase 6h**: Unified timeline queries `timeline_events` for personal events and `procedure_events` for legal events — two clean, non-overlapping tables.

---

## 2026-04-06 — Email→Procedure FK via migration #18

**Decision**: Add `procedure_id INTEGER REFERENCES procedures(id)` directly to the `emails` table and backfill from `legal_analysis` result_json.

**Rationale**: The `procedure_ref` field was already extracted by the LLM for every legal email and stored in `analysis_results.result_json`. It was trapped inside a JSON blob. Surfacing it as a proper FK enables: procedure-filtered email browsing, email counts per procedure, procedure dossier export, and efficient unified timeline queries without JSON extraction at query time.

**Implementation**: Migration #18 in `database.py`. Backfill script read `procedure_ref` from 2,743 `legal_analysis` results and wrote `procedure_id` to 2,892 `emails` rows (2,743 legal emails; some had multiple analysis results). 1 email had no `procedure_ref` and remains unlinked.

**Impact**: Personal corpus `procedure_id` = NULL by design. Legal corpus `procedure_id` = the procedure they belong to. This is the foundation for Phase 6h procedure dossier view.

---

## 2026-04-06 — Procedure #7 date range derived from attachment trail

**Decision**: Use attachment filenames and email dates to establish the date range for Négociation Amiable (#7), rather than leaving it NULL.

**Rationale**: #7 has no formal court filing — it was an informal exchange of divorce convention drafts between lawyers. The attachment trail is unambiguous: `projet de convention de divorce.doc` first appeared 2015-08-10; the last document (`160205 MULLER Convention de divorce corrigée MM.doc`) was exchanged 2016-02-22, one week before Divorce pour Faute was filed (2016-02-29), confirming negotiation collapsed at that point.

**Result**: `date_start=2015-08-10`, `date_end=2016-02-22`, `status=abandoned`.

---

## 2026-04-07 — MULLER conclusions: three-tier CLI download strategy

**Decision**: `fetch conclusions` CLI command uses a three-tier fallback: stored IMAP location → full stale-UID recovery (two-pass, identical to web route logic) → BLOB content from DB.

**Rationale**: Legal corpus attachments were imported as metadata-only (no BLOB). When Yahoo moves emails between folders, stored UIDs are invalidated. The web route's `_find_email_imap_location()` already handles this. Rather than calling into the web route from CLI, the logic was inlined in CLI as `_locate_email_imap()` (same algorithm: Pass 1 = DB-known folders by Message-ID; Pass 2 = all IMAP folders by SENTON+FROM; subject disambiguation for same-sender same-day collisions). The BLOB fallback is needed for the 5 emails that were originally personal corpus (had `attachments.content` stored) and later reclassified to legal.

**Deduplication key**: `(filename.lower().strip(), procedure_id)` — keeps the earliest email carrying the attachment, discards 17 forwarded copies. This ensures we download the original filing, not a re-sent copy.

**Idempotency**: `procedure_events` insert checks for existing `(procedure_id, source_attachment_id, event_type='conclusions_received')` before inserting. `--force` flag bypasses the `downloaded=1` check to re-download existing files.

**Result**: 33/33 MULLER adverse conclusions downloaded and linked as `procedure_events.conclusions_received` across 11 procedures.

---

## 2026-04-07 — Emails page layout breakpoint raised from 1200px → 1400px

**Decision**: The CSS breakpoint that collapses `.emails-layout` from two-column to one-column was raised from `max-width: 1200px` to `max-width: 1400px`.

**Rationale**: The sidebar is 240px fixed. A 1440px laptop display (common MacBook resolution) leaves ~1200px for the main content area — exactly at the old breakpoint, causing the layout to collapse unpredictably. The two-column grid needs `1fr + 500px` = at least 600 + 24 + 500 = 1124px of content space, so 1400px total (with sidebar) is the correct minimum. The `dashboard-two-col` breakpoint was kept at 1200px (it's a simpler 1fr/1fr grid) by splitting it into its own media query block.

**Belt-and-suspenders**: An `htmx:afterSwap` listener in `emails.html` auto-scrolls to `#detail-panel` when a detail is loaded and the panel is outside the viewport — covers any edge case where the layout still collapses (e.g. window resize after load).

**Impact**: `src/web/static/css/style.css` (version bumped to `?v=8`), `src/web/templates/pages/emails.html`, `src/web/templates/base.html`.

---

## 2026-04-07 — Procedure documents unified view: merge two sources in route

**Decision**: The procedure detail page Documents section merges `procedure_documents` (manual uploads) and `attachments` (downloaded email attachments) in the route layer, not the template.

**Rationale**: Both sources have different PKs, URLs, and metadata shapes. Merging in the route normalises them to a common dict shape with `_source` and `_serve_url` keys, keeping template logic simple (one loop, two conditionals: badge + delete button). Invoices are excluded (`category != 'invoice'`) to keep the Documents section focused on court filings and evidence. Sort is by `doc_date` after merge so the combined list is chronological.

**Impact**: `src/web/routes/procedures.py` `procedure_detail()`, `src/web/templates/pages/procedure_detail.html`.

---

## 2026-04-07 — Thematic Threads: separate stats query from paginated content query

**Decision**: For the `/themes` route, run two separate SQL queries: one lightweight stats query (no body text, all emails for the topic) and one paginated content query (with `delta_text`, `LIMIT PAGE_SIZE OFFSET`).

**Rationale**: Topics like `enfants` have 2,225 emails. Fetching all `delta_text` for the stats strip would be unnecessarily heavy and risk a timeout or memory spike. The stats query only selects `direction`, `aggression`, `date` — three small columns — and runs on the full topic without pagination. The content query fetches `delta_text` for 50 emails at a time. This pattern supports both accurate stats (total, avg aggression, date range) and fast page loads.

**Bug avoided**: `analysis_results` has no `analysis_type` column — it's on `analysis_runs`. The JOIN must be `LEFT JOIN analysis_runs run ON run.id = ar.run_id AND run.analysis_type = 'tone'` (not `WHERE ar.analysis_type = 'tone'`).

**Impact**: `src/web/routes/book.py` `GET /themes`, `src/web/templates/pages/themes.html` (new file).

---

## 2026-04-11 — Email delete must clear non-cascade FK references explicitly

**Decision**: Before `DELETE FROM emails WHERE id = ?`, explicitly clear all non-cascade FK references in both single-delete and bulk-delete routes.

**Rationale**: `PRAGMA foreign_keys=ON` is set on every connection. Five references to `emails(id)` have no `ON DELETE CASCADE`:
- `contradictions.email_id_a` / `email_id_b` (NOT NULL) — delete the whole contradiction pair
- `procedure_events.source_email_id` (nullable) — NULL out (event remains meaningful without the source email)
- `lawyer_invoices.email_id` (nullable) — NULL out
- `procedure_documents.source_email_id` (nullable) — NULL out

**Rule**: Any new table with a non-cascade FK to `emails` must be handled in both `delete_email()` and `bulk_delete_emails()` in `src/web/routes/emails.py`.

**Impact**: `src/web/routes/emails.py` — 4 statements added to each of the two delete flows. Commit `d70626e` on `main`.

---

## 2026-04-12 — Northline branding: workspace-based navigation replaces Perspective/Corpus toggles

**Decision**: Replaced the dual Perspective toggle (Legal/Book) + Corpus toggle (Personal/Legal/All) with 4 unified workspace tabs: Correspondence, Case Analysis, Legal Strategy, Book. Each workspace implies its corpus and perspective automatically.

**Rationale**: The dual-toggle system was confusing — two separate "Legal" toggles meaning entirely different things, and the corpus concept was invisible to new users. Workspaces are semantically clear and map naturally to how the user actually works.

**Impact**: `_ws_map` Jinja2 dict in `base.html` infers workspace from the `page` variable. `body.perspective-*` class and data attributes remain for backward CSS compatibility. Cookie management in `app.js` sets all 3 cookies (workspace, perspective, corpus) on tab click.

---

## 2026-04-12 — File-based memories for reply context (not DB BLOBs)

**Decision**: Topic memory files for the Reply Command Center are stored as markdown files in `data/memories/` on disk. The `reply_memories` DB table holds only metadata (slug, display_name, file_path, topic_id).

**Rationale**: Markdown files can be edited with any external text editor, are readable without the app, can be version-controlled separately, and don't bloat the SQLite DB. The `data/` directory is already gitignored, so sensitive case facts won't leak.

**Impact**: `src/config.py::memories_dir()` returns the canonical path. `seed_memories()` in `database.py` creates DB rows and template markdown files on first `init_db()`. Web routes in `reply.py` read/write files directly from disk.

---

## 2026-04-12 — Reply draft generation uses background threads + HTMX polling

**Decision**: LLM reply generation runs in a daemon thread (same pattern as IMAP sync). The UI submits a POST, gets back a polling partial, and polls every 2 seconds until done.

**Rationale**: Claude calls for reply generation take 5–15 seconds. Synchronous FastAPI would block the request. Background threads are already proven by the sync routes. WebSockets would add complexity with no benefit at single-user scale.

**Impact**: `_jobs` dict in `reply.py` holds in-memory job state. `POST /reply/generate/{email_id}` starts the thread; `GET /reply/generate/{email_id}/poll/{job_id}` returns status. On completion, returns the full refreshed detail panel (not just the draft card).

---

## 2026-04-11 — All feature branches deleted; main is sole branch

**Decision**: After merging Phase 6 (`feature/corpus-filter-ui`) to main, both feature branches (`feature/corpus-filter-ui`, `feature/lawyer-corpus`) were deleted locally and from GitHub.

**Rationale**: Both were fully merged; no unmerged commits remained. Git history preserves all work. Future features will branch from main as needed.

**Impact**: `origin/main` is now the only remote branch. Direct commits to main are acceptable for small fixes.
