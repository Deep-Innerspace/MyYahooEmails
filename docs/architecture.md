# MyYahooEmails — Architecture Reference

> Last updated: 2026-03-19

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
   analysis/              ← Phase 2: LLM analysis pipeline
   classifier.py          ← Topic classification (email_topics table)
   tone.py                ← Tone/aggression/manipulation analysis
   timeline.py            ← Event extraction (timeline_events table)
        │
        ▼
    search.py             ← FTS5 + metadata filtered queries
        │
        ▼
     cli.py               ← Click CLI (all user-facing commands)
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
| `src/analysis/runner.py` | Run lifecycle, batch orchestration, result storage |
| `src/analysis/classifier.py` | Topic classification → `email_topics` |
| `src/analysis/tone.py` | Tone/aggression/manipulation → `analysis_results` |
| `src/analysis/timeline.py` | Event extraction → `timeline_events` |
| `src/analysis/prompts/` | French-legal prompt templates |
| `cli.py` | All CLI commands (click groups) |

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
- `contradictions` → Claude (complex reasoning)
- `manipulation` → Claude

**Token budget** (Groq free tier: 100k/day):
- classify+tone: ~118 tokens/email × 200/day ≈ 23.6k tokens per task
- timeline: ~800 tokens/email × 50/day = 40k tokens
- Total per day: ~87k (safely under 100k)

## Key Design Constraints

1. **IMAP is READ-ONLY** — only FETCH and SEARCH; never STORE/EXPUNGE/DELETE
2. **Multi-address contacts** — primary email + aliases JSON; all expanded in search
3. **Delta text** — all LLM analysis on `delta_text` (quote-stripped), not full body
4. **Bilingual** — French bodies + English Yahoo headers; both handled throughout
5. **Resumable fetch** — `fetch_state` tracks last UID per (folder, contact_email)
6. **Multi-run coexistence** — multiple model runs per email; compare/delete independently

## Scheduled Tasks

| Task | Schedule | Command |
|------|----------|---------|
| `daily-classify-tone` | 6:03 AM daily | `analyze classify --provider groq --limit 200` then `analyze tone --provider groq --limit 200` |
| `daily-timeline` | 7:07 AM daily | `analyze timeline --provider groq --limit 50` |
