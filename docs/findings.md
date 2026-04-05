# Analysis Findings

> Running log of observations from LLM analysis runs, data quality notes, and corpus patterns.
> Append new entries; format: `## YYYY-MM-DD — Topic`

---

## 2026-03-19 — First full analysis run (Phase 2 complete)

### Corpus stats at analysis start
- ~2,676 emails found across 91 Yahoo folders
- ~1,317 emails after deduplication (delta_hash dedup)
- Language: majority French (~99%), some English system emails

### Groq performance on French legal text
- `llama-3.3-70b-versatile` handles French fluently
- Topic classification: confident assignments on clear topics (logement, enfants); lower confidence on ambiguous/mixed emails
- Tone analysis: successfully distinguishes formal legal language from emotionally charged personal messages
- Prompt language: prompts written in French with French legal terminology; model responds correctly

### Rate limit discovery
- Hit Groq 100k/day limit during first full tone analysis run (~660/1317 emails processed before cutoff)
- Switched to 200 emails/day per task type; daily timeline capped at 50/day

### Timeline extraction quality
- Per-email processing (not batched) gives better precision for date/event extraction
- Groq extracts events reliably when emails mention explicit dates and legal proceedings
- Less reliable for implicit timeline references ("suite à notre conversation de la semaine dernière")

### Data quality observations
- Some emails have empty `delta_text` (short acknowledgments, "OK", "Reçu")
- A few emails have encoding issues in `from_name` (garbled characters) — Yahoo IMAP artifact
- Thread reconstruction: subject-based fallback works well; References header missing on ~15% of emails (older Yahoo Mail behavior)

---

## 2026-03-20 — Groq token rate limit investigation (per-minute ceiling)

### Observation from Groq API dashboard
- Dashboard showed token spikes reaching ~16K tokens/min, exceeding the ~12K/min ceiling
- Request rate was well below the 30 req/min limit (peaked at ~10-12 req/min)
- **Conclusion**: the binding constraint is tokens/min, not requests/min

### Root cause of prior run failures
- `GroqProvider.complete()` had no rate limiting and no 429 retry
- When token ceiling was hit, `RateLimitError` propagated uncaught, killing the entire run
- Runs died at batch boundaries with no resumption — `analysis_runs` table left in `running` state

### Rate limiter behaviour observed
- With `rate_limit_tokens_per_min: 10000` and batches of 20 emails × ~2000 chars delta_text each:
  - Estimated tokens per batch: ~10,500 input + ~500 output = ~11,000 total
  - After first batch: token bucket triggers sleep of ~55s before next batch
  - Effective throughput: ~20 emails/min (1 batch/min)
  - Full corpus classify (1,317 emails): ~66 batches → ~66 minutes

### Token estimation accuracy
- `len(prompt) // 4` over-estimates input slightly for French text (French words are longer than English → fewer tokens per char), which is intentional (safe side)
- `max_tokens // 2` for output estimate is realistic: classifier actual output is typically 300–600 tokens for a 20-email batch, well below the 5,024 ceiling

### Retry-After header
- Groq includes `Retry-After` in 429 responses but does not specify a fixed reset interval
- The header value observed in practice: typically 10–60 seconds depending on how far over the limit the call was

## 2026-03-20 — Groq TPD (tokens/day) behaviour — critical for large corpus projects

### Discovery: TPD is a rolling 24h window
Confirmed empirically: the Groq daily token limit (100,000 tokens/day free tier) resets on a **rolling 24-hour window**, not at midnight. Practical consequence:
- A run that starts at 9 AM and hits TPD will get a `Retry-After` of several thousand seconds
- The quota trickles back as the 24h-ago usage drops off the window — NOT in one reset event
- Planning daily budgets must account for this: schedule runs far enough apart to let the window clear

### TPD is invisible in response headers
The `x-ratelimit-*` headers returned on every successful response expose:
- ✅ `x-ratelimit-remaining-tokens` — TPM (per minute) remaining
- ✅ `x-ratelimit-remaining-requests` — RPD (requests/day) remaining
- ❌ TPD (tokens/day) remaining — **not exposed** — only detectable via 429

This means `tools/groq_rate_check.py` returning OK does not guarantee a full production batch will succeed. It only confirms TPM and RPD are clear. A batch calling with 5,000+ tokens may still hit TPD.

### Token budget for this corpus (1,326 emails)
| Task | Tokens/email (est.) | Total tokens | Days at 100k/day |
|------|---------------------|-------------|-----------------|
| classify (20-email batches) | ~750 | ~994,500 | ~10 |
| tone (20-email batches) | ~900 | ~1,193,400 | ~12 |
| timeline (per-email) | ~500 | ~663,000 | ~7 |
| **All three tasks** | — | **~2.8M** | **~28** |

At 8 AM daily runs with full 100k/day budget: approximately 28 days to complete the full corpus across all three analysis types.

### Retry-After distinguishes TPM vs TPD
Observed values:
- **TPM hit**: `Retry-After` typically 10–120 seconds (window resets quickly)
- **TPD hit**: `Retry-After` typically 3,000–86,400 seconds (several hours to 24h)
- Threshold of 300 seconds (5 min) reliably separates the two cases in practice

### Groq diagnostic tool: `tools/groq_rate_check.py`
- Probe cost: ~44 tokens per call (minimal footprint)
- `with_raw_response` pattern in Groq Python SDK gives direct httpx header access
- Reusable in any Python project using the Groq SDK (see decision-log.md for pattern)

## 2026-03-21 — Phase 3+4 implementation notes

### Contradiction detection design considerations
- Two-pass approach is essential for a 1,326-email corpus: comparing all pairs would be O(n²) ≈ 879k comparisons
- Grouping by topic in Pass 1 dramatically reduces the search space — contradictions almost always occur within the same topic
- `--skip-confirmation` flag useful during development to quickly iterate on Pass 1 quality before investing tokens on Pass 2
- Classification summaries must exist before contradictions can be detected — dependency is enforced at CLI level

### Manipulation pattern taxonomy
- 10 patterns chosen based on French family law context (gaslighting, coercion, projection, etc.)
- Each pattern scored 0.0–1.0 independently — a single email can exhibit multiple patterns simultaneously
- Requiring verbatim evidence quotes in the prompt output prevents hallucinated findings
- `min_score` threshold (default 0.0) allows filtering low-confidence detections

### Court correlation approach
- SQL-first design: most useful metrics (email volume, avg aggression, topic shifts) are computable without LLM
- Optional `--narrative` flag adds LLM synthesis only when needed — saves tokens during exploration
- Window size (±14 days by default) is configurable — may need tuning based on how far in advance email tone shifts before court events

### Report generation observations
- DOCX works out of the box on all platforms; PDF requires system dependencies (Pango/Cairo/GObject)
- Lazy weasyprint import was critical — without it, even `report timeline --format docx` would fail on systems without Pango
- matplotlib Agg backend is essential for headless environments (no display server)
- Chart images embedded via file:// paths in PDF; python-docx uses `add_picture()` with absolute paths

<!-- New findings entries go below this line -->

## 2026-03-23 — Classification quality observations (ChatGPT gpt-5.4-thinking, 1,300 emails)

### Coverage
- 1,300/1,326 emails classified across 7 batches (runs #17–22, #29)
- Blank rate: ~1.5–3% per batch (5–18 blank rows) — emails that were too short or ambiguous for the model to classify confidently
- The ~26 unclassified emails are very short acknowledgments ("OK", "Reçu", "D'accord") or near-empty delta_text after quote stripping

### Topic distribution (observed across batches)
- Topics with highest frequency: `enfants` (child custody/support), `logement` (housing), `finances` (financial disputes)
- Topics less frequent but clearly present: `procedure` (legal proceedings), `communication` (meta-discussion about the correspondence itself)
- Many emails tagged with 2–3 topics simultaneously (confident multi-label assignments)
- gpt-5.4-thinking handles French legal vocabulary (garde alternée, pension alimentaire, TGI) without errors

### Model quality observations
- Classification is notably confident and specific — more granular than Groq llama-3.3-70b on ambiguous emails
- Does not hallucinate topic names outside the provided list
- Confidence scores tend to cluster high (0.8–0.95) for clear topics; lower (0.5–0.7) for genuinely ambiguous content

---

## 2026-03-23 — Tone analysis observations (ChatGPT gpt-5.4-thinking, 1,299 emails)

### Coverage
- 1,299/1,326 emails tone-analysed across 8 batches (runs #23–28, #30–31)
- Blank rate similar to classify: ~1.5–3% per batch (consistent with classify — same short/ambiguous emails)

### Dominant tone patterns observed
- Received emails (975 total) show higher aggression scores on average than sent emails (351 total) — consistent with the expected pattern
- Legal posturing scores elevated in emails referencing specific articles of French family law or solicitor correspondence
- Manipulation scores: present but not uniformly high — episodic rather than consistent

### Tone field quality
- `aggression_level` (0.0–1.0): well-calibrated — model distinguishes polite formal requests (0.1–0.2) from hostile accusations (0.7–0.9)
- `manipulation_score` (0.0–1.0): captures gaslighting and deflection patterns in French; some false positives on strongly assertive but non-manipulative emails
- `legal_posturing` (0.0–1.0): reliably high on emails that cite legal precedents or threaten legal action; near-zero on casual exchanges

### Blank row interpretation
- ~2% of emails across all analysis types return blank rows from ChatGPT
- These are reliably the shortest emails after delta-text stripping (< 20 words)
- They represent genuine data — "OK", "Reçu", "Merci" — and their absence from analysis results is not a data quality problem

---

## 2026-03-24 — Manipulation detection rate (first 2 batches, 460 emails)

### Detection rate
- Batch 01 (230 emails): 34 manipulative (14.8%)
- Batch 02 (230 emails): 29 manipulative (12.6%)
- **Overall observed rate: ~13–15% of emails contain detectable manipulation patterns**

### Pattern distribution (qualitative, 2 batches)
- Most common patterns: gaslighting, guilt_tripping, false_victimhood
- Less common but high-impact: financial_coercion, legal_threats, children_instrumentalization
- Many manipulative emails combine 2–3 patterns simultaneously (overlapping tactics)

### Score calibration
- ChatGPT gpt-5.4-thinking produces well-calibrated scores — not inflated
- A 13–15% rate is consistent with the expected pattern: most emails are formal/neutral; manipulation is episodic and concentrated in certain periods
- Low total_score (0.0–0.2) correctly assigned to formal administrative emails even when they contain assertive language

---

## 2026-03-24 — 2017–2023 gap confirmed: communication moved to lawyers

### Observation
The tone chart showed almost no received emails from the ex-wife during 2017–2023. Initial hypothesis: missing data or IMAP fetch failure.

### Investigation
- Ran IMAP diagnostic query filtering specifically on FROM: her email addresses across all folders
- Confirmed: she genuinely sent very few direct emails during that period
- The Sent folder (896 emails fetched) contained our outgoing messages throughout, but very few incoming from her
- **Conclusion: communication during 2017–2023 moved almost entirely through lawyers (avocats)**

### Yahoo webmail misleading UI
- Yahoo's "filter by contact" feature in the webmail browser shows all emails in conversation threads that include a contact — including sent messages and multi-party threads — NOT just emails where that contact is the FROM: address
- This caused the initial impression that there were more emails from her in that period than actually existed in the raw data
- For accurate counts: always query the DB directly with `WHERE from_address IN (her known addresses)` or `direction = 'received' AND contact_id = <her_id>`

### Implication for analysis
- The lawyer communication period (2017–2023) will not appear in tone/manipulation charts based on direct emails
- Court event correlation (Phase 3) is more important for this period — it can correlate legal proceedings with the sparse direct emails that do exist
- Any narrative reconstruction of 2017–2023 must rely primarily on court events and the few emails that exist, not the email volume

---

## 2026-03-24 — Corpus size update: 3,922 emails after second full fetch

### New fetch results
- Previous total: 1,326 emails
- Added: 968 new emails (897 Sent, 35 Refere, 16 Refere OK, 16 Weekly reports, 4 Inbox)
- 279 Sent emails detected as duplicates (delta_hash match) and skipped correctly
- **New total: 3,922 emails**

### Impact on analysis coverage
- Classification batches for the new 2,596 emails required additional ChatGPT runs (runs #33, #36, #38–41+)
- Tone analysis now at ~66% — significantly more work needed for the new emails
- Manipulation and contradictions batches were exported against the full 3,922-email corpus

---

## 2026-03-24 — Manipulation analysis complete (3,907 / 3,922 emails)

### Top patterns by direction
| Pattern | Received | Sent |
|---------|----------|------|
| children_instrumentalization | 164 | 103 |
| financial_coercion | 106 | 82 |
| legal_threats | 102 | 98 |
| projection | 54 | 39 |
| gaslighting | 29 | 20 |

### Key observations
- **Same top-5 patterns appear in both directions.** This is expected: children and finances are the dominant dispute topics, so both parties invoked them. Legal threats mirror each other (she threatens → you counter-threaten through lawyers). This is a sign of escalating adversarial framing on both sides.
- **Volume asymmetry is significant.** She sent 164 emails with children_instrumentalization vs 103 from you. Similarly 106 vs 82 for financial_coercion. The ratio ~1.5:1 received:sent is consistent across all patterns.
- **Sent Patterns chart is visibly sparser.** Your manipulation patterns were concentrated in specific periods (spikes), while hers were continuous throughout the correspondence. This may indicate reactive vs systematic behaviour.
- **~77% of all analysed emails had no detected manipulation** (score = 0). Manipulation was not the norm — it concentrated in ~23% of emails with measurable presence.
- **Batch 17 was the smallest** (213 emails, 19 scored). Consistent with ChatGPT being conservative on short or ambiguous emails in the final batch.

---

## 2026-04-05 — Legal corpus analysis complete (2,743 / 2,743)

### Pipeline summary
- Batches 1–14: Excel round-trip via ChatGPT gpt-5.4-thinking (prior sessions)
- Batches 15–19: Excel round-trip via ChatGPT gpt-5.4-thinking (this session)
- 150 oversized emails (>30k chars): direct in-session analysis as Claude (run #156)

### May–July 2015 period — key narrative findings (from 150 oversized emails)

These emails were all forwarded evidence chains — Gaël systematically transmitting the entire correspondence trail to Valérie as legal exhibits. This bulk evidence assembly happened across two periods:

**July 7, 2015 (pieces 1–15)**: First wave — general evidence of family situation (lease, employment history, job searches, Maud's early 2014 emails, visa correspondence, housing search). Pieces numbered sequentially starting from 1.

**July 13, 2015 (pieces 109–131)**: Second wave — specifically targeted at the MAREP/Necker dispute and visa conflict, submitted just 7 days before the Référé hearing (July 20). The high piece numbers (109–131) suggest Gaël had compiled a very large dossier — hundreds of pieces — with the key medical evidence in the 100+ range.

**Central evidence piece**: Dr. Crétolle's June 26 letter (Pièce 112) — the most legally significant document in this batch. Dr. Crétolle explicitly complained that she was receiving contradictory parallel requests from both parents, effectively documenting Maud's unauthorized unilateral actions regarding Lounÿs's medical care.

**Mood pattern**: Gaël's mood across all 108 sent emails was nearly uniform — `determined` or `frustrated`, intensity 3–4, consistently noting `trust_in_lawyer: confident`. This contrasts with the personal corpus where mood fluctuated widely. The legal correspondence shows a man in "execution mode" — methodical, strategic, focused on building the case rather than expressing emotion.

**Valérie's strategy pattern**: Her `lawyer_stance` values were predominantly `strategic` with `proactive` for approvals. She pushed back on communication approach (shorten emails, use confidential not official letters) but broadly endorsed Gaël's evidence-gathering instincts.

### Observations on legal analysis quality vs personal corpus

- Legal analysis (`legal_analysis`) covers different fields from personal analysis (`tone`, `manipulation`): mood_valence, lawyer_stance, strategy_signal, procedure_ref, children_mentioned, amounts_mentioned — these are more factual and less subjective than tone/manipulation scores
- The Excel-imported batches (via ChatGPT) showed ~2–5% blank rows per batch for sent emails, consistent with very short coordination messages ("ok je m'arrangerai", "C'est noté!")
- The 150 oversized emails had zero blank/undecided cases — they all had clear, analyzable content despite being mostly evidence-forwarding emails
