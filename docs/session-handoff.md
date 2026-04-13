# Session Handoff

> This file is **replaced** each session. It captures the last session's work and the exact resume point.

---

**Last Updated: 2026-04-13**

## What Was Accomplished This Session

### 1. SaaS productization architecture

Designed full multi-tenant architecture for extending Northline to hundreds of paying users:
- PostgreSQL schema-per-tenant, FastAPI-Users auth, Celery + Redis job queue
- Encrypted IMAP credentials, Stripe billing, 3-tier pricing (Free / Pro €19 / Premium €39)
- Hetzner deployment plan (VPS + managed DB + Redis)
- Stored in `productization.md` (root of project, gitignored)

### 2. Knowledge base memory enhancement (BM25 retrieval)

Rewrote `src/analysis/reply_generator.py` to use BM25 chunked retrieval based on Karpathy's markdown-as-knowledge-base principle:

- **`_parse_sections()`**: splits memory files at `## ` boundaries into chunks with `{header, body, is_quick_context, source_name}`
- **`load_memories_content()`**: Quick Context sections always injected; remaining sections BM25-ranked against incoming email text; `top_k=8` best sections selected
- **`party_b_profile` always-inject**: prepended to every prompt regardless of user selection
- **Strategic intent field**: new `intent` input in the reply composer — injected as "OBJECTIF STRATÉGIQUE DE CETTE RÉPONSE (contrainte absolue)" before tone
- **Migration 24**: `ALTER TABLE reply_drafts ADD COLUMN intent TEXT NOT NULL DEFAULT ''`

### 3. Memory files — real data rewrite

Rewrote all 6 topic memory files with actual corpus data (not template placeholders):
- `data/memories/general.md` — Quick Context with dense facts, Communication Rules, Legal Awareness, Tone Calibration
- `data/memories/enfants.md` — 2,225 emails, 3 active procedures (#14 #15), passport blockages
- `data/memories/finances.md` — Liquidation #12 active, ESSEC 75% judgment, contradiction documented
- `data/memories/ecole.md` — Jean-Mermoz Dubai blocked without judgment, ESSEC frais
- `data/memories/logement.md` — 11-year contradiction (email 160 vs email 748), mediation with Sanson
- `data/memories/vacances.md` — highest aggression topic (avg 0.31), 12 contradiction pairs, 3 passport refusals

### 4. `party_b_profile.md` adversarial dossier (new file)

Created `data/memories/party_b_profile.md` with:
- 10 manipulation patterns ranked by frequency (children_instrumentalization #1: 142 emails avg 0.53)
- Pre-hearing behavior: aggression spikes documented
- Known contradictions by severity
- Rhetorical fingerprint + what has/hasn't worked
- Always injected into every reply prompt

### 5. Corpus synthesis pipeline

New module `src/analysis/memory_synthesizer.py`:
- `synthesize_topic_memory()` — gathers summaries, aggression stats, manipulation patterns, timeline events, contradictions, procedures from DB; calls LLM to propose updated memory sections
- `diff_sections()` — returns `[(header, old_body, new_body)]` for review
- `apply_section_updates()` — writes approved sections back

New prompt: `src/analysis/prompts/memory_synthesis.txt`

New CLI commands (`python cli.py memories`):
- `memories list` — table with slug, name, file size, updated, description
- `memories synthesize --topic <slug> [--since DATE] [--provider X] [--auto-accept]` — interactive section-by-section review

### 6. Dedicated Knowledge Base web page (`/memories/`)

New web page and routes in `src/web/routes/memories.py` (registered in `__init__.py`):

**List page** (`GET /memories/`):
- Card grid: name, slug badge, file size, section count, last-updated, description
- Edit → and Synthesize buttons per card
- Inline synthesis result panel (HTMX)

**Edit page** (`GET /memories/{slug}`):
- Left: sticky section nav (click to switch active section)
- Right: per-section editor with Edit/Preview tabs
- Preview POSTs to `/memories/_preview` (server-side rendering — no XSS risk)
- Raw file editor at bottom
- Synthesize button with `since` date input

**New routes**:
- `POST /memories/{slug}/section` — save single section
- `POST /memories/{slug}/raw` — save full file
- `POST /memories/{slug}/synthesize` — start background LLM synthesis job
- `GET /memories/{slug}/synthesize/poll/{job_id}` — HTMX polling
- `POST /memories/_preview` — server-side markdown renderer
- `POST /memories/{slug}/synthesize/accept` — accept one diff section

**New templates**:
- `src/web/templates/pages/memories.html`
- `src/web/templates/pages/memory_edit.html`
- `src/web/templates/partials/memory_synthesizing.html`
- `src/web/templates/partials/memory_diff.html`

`base.html` updated: `'memories': 'correspondence'` in `_ws_map`; "Knowledge Base" nav link added to Correspondence sidebar.

### 7. Procedures page bug fixes

- **Obligations in "Rulings at a Glance"**: was rendering `N item(s)` count; fixed to full bullet list by iterating `ev.obligations.split('\n')` and stripping bullet prefixes
- **Procedure ID badge**: `#{{ proc.id }}` now visible in both detail header (navy/white, prominent) and list card (subtle navy, next to status badge)

---

## Errors Encountered and Resolutions

| Error | Resolution |
|---|---|
| `Write` tool "File has not been read yet" for memory files | Used `Bash cat` to read all files first |
| Security hook blocked `innerHTML = marked.parse(body)` (XSS) | Created server-side `/memories/_preview` endpoint with Python HTML escaping |
| `SQLite LEFT() function not found` | SQLite has no `LEFT()` — used Python string slicing `str(r['explanation'])[:120]` |
| `rich.table.Table` reference error in CLI | `Table` was already imported directly — used `Table(...)` not `rich.table.Table(...)` |

---

## Current DB State

| Metric | Value |
|---|---|
| Personal emails | 3,791 |
| Legal emails | 2,743 |
| Personal: classify/tone/manipulation | 100% ✅ |
| Personal: timeline events | 902 events |
| Legal: legal_analysis | 2,743/2,743 (100%) ✅ |
| Procedures | 15 — all with date ranges |
| Procedure events | 2,114 |
| MULLER conclusions downloaded | 33/33 ✅ |
| Lawyer invoices | 37 |
| Contradictions | 45 pairs |
| Reply memories | 7 (6 topic + party_b_profile) |
| DB migrations applied | 24 |

---

## Resume Point for Next Session

### First action: run corpus synthesis for each topic

The memory files have been manually populated with real data. The synthesis pipeline is ready to propose further improvements from the full corpus:

```bash
.venv/bin/python cli.py memories synthesize --topic enfants
.venv/bin/python cli.py memories synthesize --topic vacances
.venv/bin/python cli.py memories synthesize --topic finances
.venv/bin/python cli.py memories synthesize --topic ecole
.venv/bin/python cli.py memories synthesize --topic logement
.venv/bin/python cli.py memories synthesize --topic general
```

Or use the web UI: `/memories/` → Synthesize button per card.

### Second action: test reply draft quality

1. Go to `/reply/` → pick a pending email (after Auto-Triage if not yet run)
2. Fill "Strategic intent" field (e.g. "Document passeport refusal, demand 10-day deadline")
3. Generate draft — verify memory sections are being retrieved correctly
4. Check that `party_b_profile` content appears in generated prompts

### Third action: productization planning

`productization.md` at project root contains the full SaaS architecture plan. Next step when ready: start a new branch for PostgreSQL migration + auth layer.

### Quick Start

```bash
git log --oneline -5      # verify last commit
.venv/bin/python cli.py web     # http://127.0.0.1:8000
# Navigate to /memories/ to review and edit knowledge base
# Navigate to /reply/ to test reply generation
```
