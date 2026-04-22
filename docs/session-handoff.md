# Session Handoff

> This file is **replaced** each session. It captures the last session's work and the exact resume point.

---

# Last Session — 2026-04-22c

## What Was Done

### Evidence dismiss persistence (migration 29)

**Problem**: Clicking Dismiss on an AI suggestion card was client-side only (`card.remove()`). Dismissed suggestions reappeared on every reload or re-run of ✦ Suggest.

**Fix — 3 changes**:

| File | Change |
|---|---|
| `src/storage/database.py` | Migration 29: new `evidence_dismissed_suggestions(email_id PK, procedure_id PK, dismissed_at)` table + index on `procedure_id` |
| `src/web/routes/evidence.py` | New `POST /evidence/dismiss/{email_id}/{procedure_id}` route — UPSERT into dismissed table, returns empty `<span id="ev-sug-N">` for outerHTML swap; `suggest_evidence` query gains second `NOT IN` subquery to exclude dismissed emails |
| `src/web/templates/partials/evidence_suggestions.html` | Dismiss button changed from `onclick="card.remove()"` to `hx-post + hx-target + hx-swap="outerHTML"` |

**Key design note**: Dismissing an email does NOT prevent manual tagging via the evidence widget. The `evidence_dismissed_suggestions` table only gates the AI suggester.

## Also confirmed this session
- PDF export works — `pango` is now installed; CLAUDE.md updated to remove `brew install pango` reminder

## DB State
- Migrations applied: **29** (next ID = 30)
- Migration 29 runs automatically on first server start after this commit

## Files Changed
- `src/storage/database.py` — migration 29 added
- `src/web/routes/evidence.py` — dismiss route + updated suggest query
- `src/web/templates/partials/evidence_suggestions.html` — HTMX dismiss button
- `CLAUDE.md` — implementation status updated

## Next Session
- Evidence v3: B2B review loop (gated on B2B launch decision)
- Or: any other feature work — navigation is consistent, evidence pipeline is solid
