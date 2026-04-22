# Session Handoff — 2026-04-22b

## What Was Done

### Comprehensive navigation overhaul — 11 files

A full audit of all navigation patterns across the web dashboard was performed, identifying three root causes behind every "can't get back" problem:

1. `hx-get` with no `hx-push-url` — URL never updates when loading detail inline
2. `window.location='/emails/N'` with no `?back=` — back button returns to wrong page
3. `<a href="/emails/N">` with no `?back=` — same problem for static links

All 23 identified issues were fixed across 11 template files:

| File | Fix |
|---|---|
| `partials/email_row.html` | Added `hx-push-url="/emails/{{ e.id }}"` on the row — clicking any email now updates the URL |
| `partials/email_list.html` | Added `hx-push-url` matching `href` on prev/page/next pagination links |
| `pages/dashboard.html` | `window.location='/emails/N'` → appends `?back=`+current pathname |
| `pages/contact_detail.html` | Same window.location fix |
| `partials/sync_recent.html` | Same window.location fix |
| `pages/contradictions.html` | `<a href="/emails/N">` → `?back=/analysis/contradictions` on both email_id_a and email_id_b links |
| `pages/manipulation.html` | `<a href="/emails/N">` → `?back=/analysis/manipulation` |
| `pages/procedure_detail.html` | Events tab email links → `?back=/procedures/{{ proc.id }}` (both subject and "linked email #N" variants) |
| `partials/quote_list.html` | Quote source links → `?back=/quotes` |
| `partials/timeline_list.html` | `href="#"` on "View email" → real URL `?back=/timeline/` (onclick modal still fires; href is now a JS-disabled fallback) |
| `pages/analysis.html` | Contradictions/Manipulation `window.location` buttons → `<a href>` links; Tone/Topics/Response tab buttons get `hx-push-url="/analysis/?tab=X"` |

### Timeline modal — no change needed
The `email_detail.html` partial already had "Open full page" with dynamic `?back=` via `onclick="this.href='/emails/N?back='+encodeURIComponent(window.location.href)"`. This already works correctly inside the timeline modal — clicking it navigates to the full email page with `/timeline/` as the back URL.

## Key Pattern for Future Routes
Any new "view email" link must include `?back={{ current_page_url }}`. For templates where the parent URL is known statically (procedures, contradictions, manipulation), hardcode it. For dynamic contexts (dashboard rows, contact rows), use `encodeURIComponent(window.location.pathname)`.

## Verified
All four key pages (/, /emails/, /timeline/, /analysis/) return 200 after the changes.

## Files Changed
11 template files — no Python routes changed, no migrations needed.

## Next Session
- `brew install pango` to enable PDF evidence export
- Navigation is now consistent across all pages — resume from any feature work
- Next evidence feature candidates: redaction overlay (v2), dismissed-suggestion persistence
