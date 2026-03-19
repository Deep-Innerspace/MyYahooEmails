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
<!-- New findings entries go below this line -->
