# Session Handoff

> This file is **replaced** each session. It captures the last session's work and the exact resume point.

---

**Last Updated: 2026-04-12**

## What Was Accomplished This Session

### 1. Northline branding — full interface adaptation

Replaced all old branding and dual Perspective/Corpus toggles with the Northline brand system:

- **Navigation redesign**: 4 workspace tabs (Correspondence, Case Analysis, Legal Strategy, Book) replace the old Perspective + Corpus toggles. Each workspace implies a corpus and perspective automatically.
- **`src/web/templates/base.html`**: Complete rewrite — Northline brand mark, icon, workspace tabs with SVG icons, contextual sidebar per workspace, Jinja2 `_ws_map` inference, `body.perspective-*` class, settings icon.
- **`src/web/static/css/style.css`** (v11): Full CSS variable replacement — Northline Navy `#1E3557`, Signal Amber `#D6A14B` as sole focal accent, Soft Ivory `#F5F2EA` background, Deep Ink for Book workspace (no more green).
- **`src/web/static/js/app.js`**: Workspace tab click handler, cookie management (workspace + perspective + corpus), on-load sync.
- **`src/web/app.py`**: `FastAPI(title="Northline")`.
- **Icons**: Copied `favicon.ico`, `apple-touch-icon.png`, `icon-32.png`, `icon-64.png`, `icon-128.png` to `/static/`.
- **`docs/branding.md`**: User-written 791-line brand guide.

### 2. Workspace icon size fix

Bumped `.ws-icon` from 15px → 18px to match the `1.15rem` Northline brand name height.

### 3. Sync pages — personal and legal IMAP fetch

New pages at `/sync/personal` and `/sync/legal` (Correspondence sidebar):
- **`src/web/routes/sync.py`**: Background-thread IMAP fetch, per-corpus, resumes from `fetch_state` last_uid. HTMX polling for live progress.
- **`src/web/templates/pages/sync.html`**: Control card with total count + last sync + corpus badge + Sync Now button.
- **`src/web/templates/partials/sync_status.html`**: HTMX polling partial with spinner → success/error banner.
- **`src/web/templates/partials/sync_recent.html`**: Last 10 emails table, OOB-refreshed on sync complete.
- **Bug fixed**: Python 3.9 doesn't support `str | None` union syntax → changed to `Optional[str]`.

### 4. Reply Command Center — full implementation (Phase 7)

New page at `/reply/` (Correspondence sidebar, between All Emails and Sync Personal).

#### Database (4 new migrations)
- **Migration 20**: `reply_status` column on `emails` (`unset`/`pending`/`drafted`/`answered`/`not_applicable`) + index
- **Migration 21**: `reply_drafts` table — full draft storage with tone, guidelines, memories_used, prompts, LLM metadata
- **Migration 22**: `pending_actions` table — extracted questions/requests/demands/deadlines/proposals per email
- **Migration 23**: `reply_memories` table — metadata for topic memory markdown files

#### New Python modules
- **`src/analysis/reply_generator.py`**: `generate_reply_draft()`, `extract_pending_actions()`, `TONE_CONFIGS` (6 tones: factual, firm, conciliatory, neutral, defensive, jaf_producible), dynamic system/user prompt builders, memory file loading, analysis context injection.
- **`src/analysis/prompts/reply_draft.txt`**: French legal reply system prompt with JAF-awareness rules.
- **`src/analysis/prompts/extract_actions.txt`**: LLM prompt to extract pending actions from emails.

#### New web route
- **`src/web/routes/reply.py`**: 18 routes covering: workspace page, list/detail partials, status management, background LLM generation + polling, draft CRUD (edit/approve/discard), pending actions CRUD + LLM extraction, memories list/read/save/create, bulk auto-triage.

#### New templates (8 files)
- `pages/reply_workspace.html` — split-panel shell, keyboard shortcuts (j/k navigate, a=answered, s=skip, g=generate)
- `partials/reply_list.html` — left panel with 5-tab strip + status dots + action/draft count badges
- `partials/reply_detail.html` — right panel: email header, status buttons, collapsible thread context, email body, pending actions, reply composer, draft area
- `partials/reply_draft_card.html` — versioned draft card with edit/approve/discard/copy
- `partials/reply_actions.html` — action list with resolve toggle and delete, add form
- `partials/reply_generating.html` — HTMX polling spinner for LLM generation
- `partials/reply_memories.html` — memories panel with create form and editor slot
- `partials/reply_memory_editor.html` — inline markdown editor for a memory file

#### Memory files seeded
- `data/memories/general.md` — always-injected communication rules (auto-selected)
- `data/memories/enfants.md` — children context
- `data/memories/finances.md` — financial obligations
- `data/memories/ecole.md` — school matters
- `data/memories/logement.md` — housing
- `data/memories/vacances.md` — vacation scheduling
- `seed_memories()` function in `database.py`, called from `init_db()`

#### CSS additions
~150 lines added to `style.css`: `.rw-panels`, `.rw-tab*`, `.rw-row*`, `.rw-status-*`, `.rw-draft-*`, `.rw-composer*`, `.rw-memory*`, `.rw-memories-panel` (fixed slide-out), responsive 900px breakpoint.

#### Bug fixed during testing
`sqlite3.Row` doesn't support `.get()` — `email.get("thread_id")` failed in `reply_detail` route. Fixed: `email_dict = dict(email)` then `email_dict.get("thread_id")`.

---

## Current DB State

| Metric | Value |
|---|---|
| Personal emails | 3,791 |
| Legal emails | 2,743 |
| Emails with `reply_status = 'unset'` | 7,301 (all, awaiting first triage) |
| Personal: classify/tone/manipulation | 100% ✅ |
| Personal: timeline events | 902 events |
| Legal: legal_analysis | 2,743/2,743 (100%) ✅ |
| Procedures | 15 — all with date ranges |
| Procedure events | 2,114 |
| MULLER conclusions downloaded | 33/33 ✅ |
| Lawyer invoices | 37 |
| Contradictions | 45 pairs |
| Reply memories | 6 seeded |

---

## Current Git State

- Branch: `main`
- Uncommitted changes: all Phase 7 (Reply Command Center) + branding + sync pages
- Previous latest commit: `2a31b5c` — docs: session handoff 2026-04-11

---

## Resume Point for Next Session

### First action: populate the memory files

The 6 memory files in `data/memories/` are seeded with template headers only. Fill them in with actual case facts before generating reply drafts — the quality of LLM replies depends entirely on the accuracy of these memories.

```
data/memories/general.md       ← already has sensible rules, review/refine
data/memories/enfants.md       ← fill custody arrangement, key dates, legal position
data/memories/finances.md      ← fill pension amounts, court rulings, disputed items
data/memories/ecole.md         ← fill school name, enrollment, transport
data/memories/logement.md      ← fill current housing situation
data/memories/vacances.md      ← fill court-ordered holiday schedule
```

### Second action: run Auto-Triage

On `/reply/`, click **Auto-Triage** to classify the 7,301 unset received emails:
- Has a later sent email in same thread → **answered**
- Older than 30 days, no reply → **not_applicable**
- Recent with no reply → **pending**

### Third action: configure `reply_draft` provider in config.yaml

Ensure `config.yaml` has:
```yaml
llm:
  task_providers:
    reply_draft: claude   # Claude preferred for reply quality
```

### Then: generate first reply drafts

1. Go to Reply Center → pick a pending email
2. Memories auto-selected based on email topics (General always injected)
3. Add specific guidelines in the textarea
4. Click **Generate Draft** → LLM generates in background
5. Edit in the textarea → **Approve** → **Copy** → send manually

### Quick Start
```bash
git status              # verify state
.venv/bin/python cli.py init    # runs seed_memories() if not yet done
.venv/bin/python cli.py web     # http://127.0.0.1:8000
```
