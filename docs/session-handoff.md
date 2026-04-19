# Session Handoff

> This file is **replaced** each session. It captures the last session's work and the exact resume point.

---

**Last Updated: 2026-04-13**

## What Was Accomplished This Session

### 1. Critical bug fixes (7 issues)

- **Migration atomicity**: `_run_migrations()` now wraps each migration in `SAVEPOINT mig_{id}` + uses `_migration_lock` (threading.Lock) to prevent concurrent startup races. `_split_sql()` helper splits multi-statement SQL for per-statement `execute()`.
- **WAL unbounded growth**: `_connect()` now sets `PRAGMA journal_size_limit=67108864` (64 MB cap) and `PRAGMA wal_autocheckpoint=1000`.
- **LIKE injection fix**: `_escape_like()` added to `search.py`; all LIKE patterns use `ESCAPE '\\'` for `%`, `_`, `\` in email addresses.
- **Silent `seed_memories()` failure**: replaced bare `except Exception: pass` with `warnings.warn()` + `logger.debug`.
- **Silent batch-store errors**: `threader.py` now logs `logger.warning(..., exc_info=True)` per failed email instead of silently incrementing a counter.
- **Stale-poll job store**: All three route modules (`sync.py`, `reply.py`, `memories.py`) now return user-friendly error HTML instead of falling through when a job_id is not found.
- **SQL f-string injection**: `sync.py` replaced `f"SELECT ... WHERE {role_sql}"` with two static hardcoded queries in if/else.

### 2. Dead code removal and optimizations

- **Shared `job_manager.py`**: `src/web/job_manager.py` centralises all background-job state with 30-min TTL cleanup. All three route modules (`sync.py`, `reply.py`, `memories.py`) removed their local `_jobs`/`_jobs_lock`/`_cleanup_jobs()` boilerplate and import from `job_manager`.
- **Alias resolution centralized**: `expand_contact_addresses()` via `json_each()` used everywhere — `threader.py`, `search.py`, `aggregator.py`. No more full-table scan + Python loop.
- **Analysis runner connection sharing**: `runner.py` gained `_conn_or_new()` context manager and optional `conn=` parameter on all write helpers. `classifier.py`, `tone.py`, `timeline.py` now each hold one SQLite connection for the entire analysis run, committing after each batch instead of opening/closing per call.

### 3. CLAUDE.md improvements

- Added `job_manager.py` entry to Project Structure section.
- Updated Multi-Address Contacts constraint to reference `expand_contact_addresses()` with "DO NOT re-implement alias lookup inline" warning.
- Added **Migration authoring** gotcha (SAVEPOINT pattern, `_split_sql()`, ID gap rule, error handling).
- Added **WAL connection settings** gotcha.
- Replaced ~320-line verbose phase history with compact ~50-line "Implementation Status" summary (actionable facts only).

### Commit

```
e681c06 refactor: harden storage, analysis, and web layers
```

---

## Errors Encountered and Resolutions

| Error | Resolution |
|---|---|
| `executescript` auto-commits, defeating SAVEPOINT | Switched to `_split_sql()` + per-statement `conn.execute()` within SAVEPOINT |
| `INSERT OR IGNORE` after rollback on "duplicate column" | Rollback savepoint, then `INSERT OR IGNORE INTO schema_version` to mark applied |
| Agent reported `last_uid` in threader.py as dead code | Confirmed already removed in prior session — Edit tool correctly failed |
| Agent reported `traceback` import in sync.py as dead | `traceback.format_exc()` is live at line 154 — left intact |

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
| DB migrations applied | 24 (next ID = 25) |

---

## Resume Point for Next Session

### First action: run corpus synthesis for each topic

Memory files have been manually populated. The synthesis pipeline can propose further improvements:

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

1. Go to `/reply/` → pick a pending email
2. Fill "Strategic intent" field
3. Generate draft — verify BM25 memory retrieval is working correctly
4. Check that `party_b_profile` content appears in generated prompts

### Third action: productization planning

`productization.md` at project root contains the full SaaS architecture plan. Next step when ready: start a new branch for PostgreSQL migration + auth layer.

### Quick Start

```bash
git log --oneline -5      # verify last commit (e681c06)
.venv/bin/python cli.py web     # http://127.0.0.1:8000
# Navigate to /memories/ to review and synthesize knowledge base
# Navigate to /reply/ to test reply generation
```
