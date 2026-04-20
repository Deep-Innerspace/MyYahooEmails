# Evidence workflow — feature spec

Status: **Living spec.** v0 (tagging) shipped 2026-04-19 via migration 26 and
`src/web/routes/evidence.py`. Highlights shipped 2026-04-20 via migration 28.
v1–v3 are proposed, not built.

## Why this document exists

The original user proposal stapled three features together:

(a) Mark emails as proof for a procedure
(b) Auto-share proof with the user's lawyer
(c) Auto-attach a markdown context file with each share

This document argues for splitting them, building (a) and (c) now, and
gating (b) on the B2B launch (where lawyers are actually in the system).

## The split

### (a) Tagging — the feature

Marking an email as a candidate piece for one or more procedures, with a
rationale and optional topic tags. Huge standalone value: it turns
unstructured email into a structured evidence shortlist the user can filter,
export, or bring to a meeting. **This is the feature. Ship it first.**

### (b) Sharing — the B2B hook

Auto-pushing tagged pieces to a lawyer's review queue. Requires lawyers in
the system. Useless in the solo/B2C context — there is no "other side" for
the share to land on. Defer to B2B launch.

### (c) Context bundle — the generator

For a set of tagged emails, assemble a package: the email bodies (optionally
redacted), the per-email rationales, the procedure-level summary, topic
cross-references, and supporting memory excerpts. Build as a pure function
(`build_bundle(email_ids, procedure_id) → Bundle`) so it is reused by:

- v2 personal export (PDF/ZIP) — for B2C users to hand to their own lawyer
- B2B lawyer-review submission — same function, different transport
- Reply review (existing Phase 6 flow) — context packaging already exists
  informally there; consolidate under the bundle generator

## What shipped (v0, 2026-04-19)

- **Migration 26** — `app_settings` + `evidence_tags`
- **Table `evidence_tags`** — forward-compatible schema:
  ```
  id, email_id FK, procedure_id FK, tagged_by DEFAULT 'client',
  tagged_at, status DEFAULT 'candidate',
  rationale, topic_ids (JSON), lawyer_notes,
  piece_number, redaction_zones (JSON),
  UNIQUE(email_id, procedure_id)
  ```
  Only `email_id`, `procedure_id`, `rationale`, `topic_ids`, `tagged_at` are
  surfaced in v0. Other columns are reserved for v1–v3.
- **Routes** — `src/web/routes/evidence.py` with `GET /evidence/widget/{id}`,
  `POST /evidence/tag/{email_id}/{procedure_id}`,
  `POST /evidence/untag/{email_id}/{procedure_id}`
- **UI** — per-email widget on the email detail page (lazy-loaded HTMX);
  evidence star pill (`★ N`) on email rows indicating how many procedures
  this email is tagged against

## What shipped (highlights, 2026-04-20)

- **Migration 28** — `highlights TEXT NOT NULL DEFAULT '[]'` column on `evidence_tags`
- **Routes** — `POST /evidence/highlights/{email_id}/{procedure_id}` (append
  `{text, note}` to highlights JSON); `DELETE /evidence/highlights/{email_id}/{procedure_id}/{index}`
  (remove by array index)
- **`_fetch_procedures_for_email()`** updated to parse highlights JSON for each
  tag into Python list before passing to template
- **Widget** — `evidence_tag_widget.html` updated: `data-tagged` attribute
  (single-quoted, JSON list of `{id, name}` for tagged procedures); per-tagged-procedure
  highlights list (amber left-border cards with text + note + × delete button);
  "No highlights yet" empty hint
- **JS** — `app.js`: mouseup on `#email-body` (when email has tagged procedures)
  → floating ★ Highlight button → `showHighlightPopover()` → procedure selector
  + note textarea → `htmx.ajax('POST', ...)` swaps widget via outerHTML
- **CSS** — `style.css`: `.evidence-highlights`, `.evidence-highlight`,
  `.evidence-highlight__text/note/del`, `.evidence-highlights__empty`,
  `.highlight-save-floating`, `.highlight-popover`, `.highlight-popover__title/excerpt`
- **Design choice**: highlights stored as `[{text, note}]` JSON (text snippet,
  not char offsets) — `delta_text` is immutable post-import so snippet matching
  is stable; snippets are human-readable in DB and portable into the bundle
- **Prerequisite**: email must be tagged to at least one active procedure before
  the ★ Highlight button appears (JS guards on `data-tagged` being non-empty)

## v1 — bulk tagging (next)

- **Emails list** — multi-select checkbox column, sticky action bar at the
  bottom with "Tag as evidence" button
- **Bulk-tag modal** — choose one procedure + optional shared rationale +
  optional topic tags; server loops over selection and UPSERTs into
  `evidence_tags`
- **Procedure page** — new "Evidence" tab listing all tagged emails for that
  procedure, ordered by date, with rationale inline and a quick-filter by
  topic; supports drag-to-reorder for `piece_number` assignment (future v2)
- **Backend** — add `POST /evidence/batch-tag` and `GET /procedures/{id}/evidence`
- **Status semantics** — keep all rows at `'candidate'` for v1; lifecycle
  states come later

## v2 — bundle export (personal/B2C)

- **Bundle builder** (`src/web/bundle.py` — new) — pure function:
  ```python
  def build_bundle(conn, procedure_id, email_ids=None) -> Bundle:
      # Returns structured dataclass: procedure_summary, pieces[], memories[]
  ```
  Each piece: full email (with delta_text), rationale, linked topics,
  redaction zones applied (if any).
- **Redaction overlay** — per-email character ranges stored in
  `evidence_tags.redaction_zones` (JSON list of `[start, end]` pairs over
  `body_text`); UI is a drag-highlight on the email view that calls
  `POST /evidence/{email_id}/{procedure_id}/redact`
- **Export formats** — PDF (weasyprint, reuses Phase 4 templates) and ZIP
  (raw emails + a `README.md` index). Entry point on the procedure Evidence
  tab: "Download bundle (PDF)" / "Download bundle (ZIP)"
- **Piece numbering** — assign `piece_number` on export ("Pièce 1, Pièce 2…")
  matching French legal convention

## v3 — B2B review loop (gated on B2B launch)

Only meaningful once lawyers have accounts in the system. See
`docs/B2B.md` → Evidence workflow section for the product-shape details.
Reuses the bundle builder from v2; adds:

- `evidence_tags.status` lifecycle: `candidate → submitted → under_review
  → approved | flagged | rejected`
- Lawyer dashboard queue (`/firm/review`) — filters by client, procedure, status
- `lawyer_notes` populated during review
- Version pinning: a `submitted_bundle_id` FK on each tag snapshot so the
  client can't edit an email mid-review without creating a new submission

## AI suggester — separate track

Independent of the tagging UI. Cron or user-triggered "find candidate
evidence" pass that:

- Reuses `src/analysis/manipulation.py` + `src/analysis/contradictions.py`
  outputs already in the DB
- For each procedure, ranks unta​gged emails by relevance score (combination
  of manipulation score, contradiction involvement, topic match on
  procedure description)
- Writes suggestions as `evidence_tags` rows with `tagged_by='ai_suggested'`
  and `status='candidate'` — same table, same UI, surfaced with a distinct
  visual treatment
- User can confirm (flip `tagged_by` to `'client'`) or dismiss (DELETE)

**Non-goal**: do not re-run LLM passes for suggestion. Read existing
analysis results. This keeps the suggester free and fast.

## Build order

1. ✅ v0 — tagging + per-email widget
2. ✅ highlights — per-email text annotation (stored in `evidence_tags.highlights`)
3. v1 — bulk tag + procedure Evidence tab
4. v2 — bundle builder + PDF export + redaction
5. AI suggester (parallelizable with v2)
6. v3 — B2B review loop (only when first B2B customer signs)

## Non-obvious design choices

- **No separate `evidence_topics` junction**. Topics on a tag are stored as
  JSON array `topic_ids` on `evidence_tags`. Rationale: a user-curated topic
  list per tag is not queried often; JSON avoids a third table and the
  awkward `run_id` FK that `email_topics` imposes for machine-generated
  topics.
- **UNIQUE(email_id, procedure_id)**. An email is a candidate for a
  procedure at most once. Multi-procedure requires multiple rows — this is
  the right shape for "same email proves different things in different
  procedures," which happens constantly in real cases.
- **Forward-compatible columns**. Shipping v0 with v2/v3 columns empty
  avoids a schema migration every time the feature grows. The cost is a few
  unused fields on each row — cheap.
- **Bundle as pure function, not endpoint**. Export, share, and review-loop
  submit all call the same builder. This prevents the B2B submission flow
  from drifting away from the B2C export format.

## Cross-references

- `docs/B2B.md` → Evidence workflow section (B2B-specific review loop)
- Migration 26 in `src/storage/database.py` (`evidence_tags` initial schema)
- Migration 28 in `src/storage/database.py` (`highlights` column on `evidence_tags`)
- `src/web/routes/evidence.py` (v0 + highlights backend)
- `src/web/templates/partials/evidence_tag_widget.html` (v0 + highlights UI)
