# Session Handoff

> This file is **replaced** each session. It captures the last session's work and the exact resume point.

---

**Last Updated: 2026-04-02**

## What Was Accomplished This Session

### Phase 6f — Invoice Scan Workspace (full redesign + bug fixes)

#### Split-panel triage workspace (`/invoices/scan`)
The invoice scan page was completely redesigned as a persistent two-panel email-client-style workspace so the user can triage all lawyer emails without losing context between emails.

**Architecture:**
- Left panel (280px fixed): compact email list with 5-tab strip (⏳ Pending / 💶 Invoice / 💳 Payment / 🚫 Dismissed / ⊞ All)
- Right panel (flex:1): full email detail with sticky action strip at bottom
- All actions (save invoice / record payment / mark assessed) auto-advance to the next email via HTMX OOB swap
- No page reloads — stays on the same URL throughout

**New routes in `src/web/routes/invoices.py`:**
- `GET  /invoices/scan`         → shell page (renders both panels via `hx-trigger="load"`)
- `GET  /invoices/scan/list`    → list panel partial (tab-filtered, status-flagged)
- `GET  /invoices/scan/detail`  → detail panel partial (email context + action strip)
- `POST /invoices/scan/invoice` → save invoice → returns OOB list + next detail
- `POST /invoices/scan/payment` → record payment confirmation → same
- `POST /invoices/scan/dismiss` → mark assessed → same
- `POST /invoices/scan/undismiss` → undo dismiss → same

**New templates:**
- `src/web/templates/pages/invoice_scan.html` — shell with filter bar + scan_qs helpers
- `src/web/templates/partials/scan_list.html` — compact list with status icons + tab strip
- `src/web/templates/partials/scan_detail.html` — full detail with amount chips + sticky action strip + keyboard shortcuts (1/2/3 = panels, J/→ = next email, F = fetch attachment)
- `src/web/templates/partials/scan_done.html` — empty state for each tab

**New DB tables (migrations 15 + 16):**
- `payment_confirmations` — records payment confirmed emails (amount, payment_type, invoice_id FK)
- `invoice_scan_dismissed` — tracks emails marked as "assessed / no action needed"

**Status icons in list rows:** PDF attachment present, invoice record linked, payment confirmed, dismissed.

**Amount chip detection:** EUR amounts auto-detected from `delta_text`/`body_text` via regex; clicking a chip pre-fills the TTC field and computes HT (÷1.20).

#### Invoice save bug fixed
- `invoice_number.strip() or None` was passing NULL to a NOT NULL column (SQL `DEFAULT` only fires when the column is omitted, not when NULL is explicitly passed)
- Fix: `invoice_number.strip()` and `description.strip()` — empty string satisfies NOT NULL

#### IMAP stale UID fix for `_find_email_imap_location()`
Yahoo invalidates UIDs when emails are moved between folders. Fixed in `src/web/routes/attachments.py`:
- **Pass 1**: search DB-known folders by `HEADER Message-ID` (fast, exact)
- **Pass 2** *(new)*: if Pass 1 fails, search ALL Yahoo IMAP folders via `client.list_folders()` — catches folders created after the initial fetch (e.g. `vclavocat` folder)
- **`_pick_uid_by_subject()`** *(new)*: when SENTON+FROM returns multiple UIDs (two emails from same sender on same day), fetches ENVELOPE for each UID and matches against `subject_normalized` to pick the correct one
- **`[UNAVAILABLE]` in `fetch_mime_part()`**: treated as "not found here" rather than a transient server error — returns `None` immediately to trigger stale-UID recovery, rather than retrying with delays

#### HTMX scan workspace bug fixes (this session)
1. **500 error on emails with attachments**: `scan_detail.html` had `{% from "partials/attachment_item.html" import _ with context %}` — `attachment_item.html` defines no macros, so this Jinja2 import always raised an error. Removed. The attachment rendering is self-contained.
2. **Active row highlight never fired**: JS was querying `input[name="_scan_email_id"]` (old name with underscore). After Pydantic rename to `scan_email_id`, this silently returned nothing and the handler bailed early. Fixed.
3. **Tab switch didn't update detail**: Replaced the old `htmx:afterRequest` handler with a unified `htmx:afterSwap` handler. When `#scan-list` is updated by user interaction (tab click or filter change), it auto-loads the first visible row's detail. OOB swaps from action routes are excluded (they already return the correct next-detail in the main response) by checking `elt.getAttribute('hx-post')?.includes('/invoices/scan/')`.
4. **Filter change showed empty pending tab**: Both `scan_list` and `scan_detail` routes now auto-fallback to `tab=all` when the requested tab (pending) has no matches but other emails exist, so the user always sees something after changing keywords.

---

## Current Database State

| Metric | Value |
|--------|-------|
| Total emails | ~2,743+ legal corpus (vclavocat + Onyx + others) + 3,922 personal |
| Classification | 3,922/3,922 (100%) ✅ |
| Tone analysis | 3,922/3,922 (100%) ✅ |
| Manipulation | 3,922/3,922 (100%) ✅ |
| Timeline events | 915 events (100%) ✅ |
| Contradiction pairs | 45 total across 9 topics ✅ |
| Lawyer invoices | Being entered via new scan workspace |
| Payment confirmations | Being entered via new scan workspace |
| Procedures | 0 (tables created, awaiting Phase 6e) |

---

## Resume Point for Next Session

### Current branch: `feature/corpus-filter-ui`

### State of scan workspace
The split-panel scan workspace is now fully functional:
- List → detail click works (attachment Jinja2 bug fixed)
- Tab switching auto-loads first email's detail
- Filter change auto-loads correct detail
- Invoice / payment / dismiss actions work end-to-end
- Keyboard shortcuts active

### Next tasks (Phase 6 remaining)

**Phase 6e — Procedures CRUD (not started)**
- UI for creating/editing procedures and procedure_events
- Link procedure_events to emails and attachments
- LLM extraction from lawyer emails

**Phase 6h — Unified Timeline (not started)**
- Merge personal + legal corpora + procedure events + cost events
- Color-coded by source type

**Phase 6i — Judgment PDF Analysis (not started)**
- `pdfplumber` extraction + LLM parsing
- New dependency: `pdfplumber`

### Quick Start
```bash
git checkout feature/corpus-filter-ui
.venv/bin/python cli.py web --reload    # http://127.0.0.1:8000
# Navigate to Legal Costs → Scan Emails
```
