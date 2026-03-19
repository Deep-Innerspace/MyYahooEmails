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

## 2026-03-19 — All folders fetch (`--all-folders` flag)

**Decision**: Added `--all-folders` flag that fetches every Yahoo folder except system ones (Trash, Draft, Bulk, Spam, Deleted Messages).

**Rationale**: User's emails span 91+ Yahoo folders (many created via search rules). It's impossible to know in advance which folders contain relevant emails. Skipping system folders avoids deleted/draft content while capturing everything else.

**Implementation**: `_SKIP_FOLDERS` set in `cli.py`; `get_folder_names()` returns all folders; CLI loops through each, fetching UIDs per alias and deduplicating before download.
