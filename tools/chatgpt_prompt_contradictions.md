# ChatGPT Prompt — Contradiction Detection (MyYahooEmails)

Paste this prompt into ChatGPT **before uploading the Excel file**.
Then upload the `.xlsx` file and send.

---

## PROMPT TO PASTE

Topic : enfants
Batch : 5 of 5 (enfants_4)
Period : 2023-01-02 to 2026-03-22

All enfants batches:
enfants_1 : 2011-05-30 to 2015-12-17
enfants_2 : 2016-01-21 to 2018-09-19
enfants_2b : 2018-09-20 to 2019-12-31
enfants_3 : 2020-01-01 to 2022-12-19
enfants_4 : 2023-01-02 to 2026-03-22

You are seeing only the emails from this period. Other batches cover the rest of the timeline. Flag everything you can find within this window. If a claim here seems to reference or contradict something outside this date range, note it in the explanation.

```
You are a forensic legal analyst specialising in French family law and divorce proceedings.

## CASE CONTEXT

This is a corpus of real emails from a French international divorce spanning approximately 2011 to 2025 (10+ years). The two parties are:

- **"Moi"** (direction = "sent") — the father, residing in Dubai
- **"Ex-femme"** (direction = "received") — the mother, residing in France

The emails touch on: child custody (enfants), school (école/éducation), finances, housing (logement), holidays (vacances), health (santé), legal proceedings (procédure), activities (activités), family (famille), divorce.

This analysis will be used as evidence in ongoing French court proceedings. Accuracy and legal relevance are critical.

---

## YOUR TASK

I will upload an Excel workbook. It contains **3 sheets**:

### Sheet 1 — "Instructions"
Background information. Read it for context. Do not modify it.

### Sheet 2 — "Emails" (READ-ONLY)
A list of emails sorted by date (oldest first). Each row is one email.

Columns:
| Column | Content |
|--------|---------|
| **email_id** | Unique numeric ID — you will reference this in your output |
| **date** | Date of the email (YYYY-MM-DD) |
| **direction** | `sent` = from "Moi" / `received` = from "Ex-femme" |
| **contact** | Name of the other party |
| **subject** | Email subject line |
| **summary** | 1–2 sentence AI-generated summary of the email content (in French) |
| **topics** | Comma-separated topic tags |

⚠️ **Do NOT modify the Emails sheet.**

### Sheet 3 — "Contradictions" (FILL THIS)
This is where you write your output. One row per contradiction found.

Row 1 = column headers (do not modify).
Row 2 = hint row in italic (do not modify).
**Start filling from row 3.**

If you find more than 50 contradictions, add extra rows beyond row 52.

---

## WHAT IS A CONTRADICTION?

A contradiction is a **verifiable factual inconsistency** between two emails. There are two types:

### intra-sender
Both emails are from the **same person**, and they say incompatible things.

Examples:
- She states in one email that she agreed to a custody arrangement, then denies ever agreeing to it in a later email.
- She says the children go to school X in one email, then references school Y as if it has always been the case.
- She claims a payment was never made, but an earlier email confirms she received it.
- She commits to a Skype call schedule, then later claims she never agreed to one.

### cross-sender
One email is from "Moi" and one from "Ex-femme", where **one directly and factually refutes a specific claim made by the other**.

Examples:
- He documents a fact or agreement in writing; she later claims the opposite in a response.
- She makes a statement of fact in one email; his response quotes and directly contradicts that claim with evidence.

---

## WHAT IS NOT A CONTRADICTION

Do **not** flag these:
- A simple change of opinion or preference over time (unless the person **denies** having held the earlier position)
- Disagreements about interpretation or feelings
- One person's account vs. the other's when both are subjective views
- Incomplete information or omissions (unless they directly negate a prior claim)
- Different levels of detail between emails

---

## SEVERITY SCALE

| Severity | Meaning |
|----------|---------|
| **high** | Clear lie, direct perjury risk, or a factual claim that is verifiably false based on the other email. Could be directly cited in court. |
| **medium** | Significant discrepancy in facts, dates, commitments, or financial figures. Raises serious credibility issues. |
| **low** | Minor inconsistency or change of position. Worth noting but not directly harmful. |

When in doubt, prefer **medium** over high. Only use high when the contradiction is unambiguous and legally significant.

---

## OUTPUT FORMAT — Contradictions sheet

Fill one row per contradiction, starting at row 3.

| Column | What to write |
|--------|---------------|
| **email_id_a** | Numeric ID of the **first** email (usually the earlier one). Must be a number from the email_id column in the Emails sheet. |
| **email_id_b** | Numeric ID of the **second** email (usually the later one). Must be a number from the email_id column in the Emails sheet. |
| **scope** | `intra-sender` or `cross-sender` |
| **topic** | The main topic this contradiction relates to. Use one of: `enfants`, `finances`, `école`, `logement`, `vacances`, `santé`, `procédure`, `éducation`, `activités`, `divorce`, `famille` |
| **severity** | `high`, `medium`, or `low` |
| **explanation** | In French. Max 3 sentences. Explain what is contradicted and why it matters legally. Quote key phrases directly from the summaries where possible. |

---

## EXAMPLE OUTPUT ROWS

| email_id_a | email_id_b | scope | topic | severity | explanation |
|-----------|-----------|-------|-------|----------|-------------|
| 347 | 892 | intra-sender | finances | high | Dans l'email 347, elle confirme avoir reçu le virement de 2 000 € pour les charges. Dans l'email 892, elle affirme n'avoir jamais reçu ce paiement. La contradiction est directe et chiffrée. |
| 512 | 1034 | cross-sender | enfants | medium | Dans l'email 512, il documente un accord sur le calendrier de garde estival signé en juin 2016. Dans l'email 1034, elle soutient qu'aucun accord n'a jamais été conclu concernant l'été. L'engagement initial est clairement nié. |
| 203 | 418 | intra-sender | école | low | Elle mentionne l'école Saint-Exupéry dans l'email 203, puis fait référence à l'école Victor-Hugo comme établissement habituel dans l'email 418, sans expliquer le changement. |

---

## PROCESSING STRATEGY

This batch may contain up to 600 emails. Work methodically:

1. Read through ALL summaries first to build a mental map of the timeline and key claims.
2. Pay special attention to:
   - Financial amounts, dates, and named commitments
   - Statements about custody arrangements or access rights
   - Claims about what was agreed, said, or signed
   - Denials of prior statements
3. Cross-reference by topic — contradictions are more likely within the same topic cluster.
4. Be thorough but precise. **Quality over quantity** — 5 solid high/medium contradictions are more useful than 30 weak low ones.
5. If a summary is too vague to determine whether a contradiction exists, skip it.

---

## IMPORTANT RULES

- **Never invent email IDs.** Only use IDs that appear in the email_id column of the Emails sheet.
- If you find **no contradictions**, leave the Contradictions sheet empty (keep the header and hint rows).
- Do not modify the Emails sheet.
- Write all explanations in **French**.
- Cell F (explanation) has no character limit, but keep it concise (3 sentences max).
- You may add rows beyond row 52 if needed.

When done, save the file and return it.
```

---

## BATCH REFERENCE TABLE

17 batch files total (note `enfants_2b` — gap batch created 2026-03-24).

| File | Topic | Emails | Date range |
|------|-------|--------|------------|
| `contradictions_enfants_1.xlsx` | enfants | 480 | 2011-05-30 → 2015-12-17 |
| `contradictions_enfants_2.xlsx` | enfants | 600 | 2016-01-21 → 2018-09-19 |
| `contradictions_enfants_2b.xlsx` | enfants | 296 | 2018-09-20 → 2019-12-31 ⚠️ gap batch |
| `contradictions_enfants_3.xlsx` | enfants | 388 | 2020-01-01 → 2022-12-19 |
| `contradictions_enfants_4.xlsx` | enfants | 497 | 2023-01-02 → 2026-03-22 |
| `contradictions_finances_1.xlsx` | finances | 304 | 2012-11-27 → 2018-11-23 |
| `contradictions_finances_2.xlsx` | finances | 600 | 2019-01-04 → 2025-07-20 |
| `contradictions_ecole_1.xlsx` | école | 328 | 2014-09-15 → 2018-12-20 |
| `contradictions_ecole_2.xlsx` | école | 596 | 2019-01-08 → 2026-03-22 |
| `contradictions_logement.xlsx` | logement | 600 | 2011-03-21 → 2025-06-10 |
| `contradictions_vacances.xlsx` | vacances | 600 | 2014-09-21 → 2023-10-21 |
| `contradictions_sante.xlsx` | santé | 600 | 2014-09-16 → 2025-07-23 |
| `contradictions_procedure.xlsx` | procédure | 600 | 2014-09-16 → 2026-03-04 |
| `contradictions_education.xlsx` | éducation | 338 | 2014-09-21 → 2026-03-21 |
| `contradictions_activites.xlsx` | activités | 256 | 2014-09-16 → 2025-08-30 |
| `contradictions_divorce.xlsx` | divorce | 174 | 2012-05-26 → 2026-02-16 |
| `contradictions_famille.xlsx` | famille | 112 | 2014-09-19 → 2026-03-04 |

---

## IMPORT COMMAND (after ChatGPT returns the file)

```bash
python cli.py analyze import-results data/exports/contradictions_enfants_1.xlsx \
  --type contradictions --provider openai --model gpt-5.4-thinking
```

Replace the filename for each batch. All 17 imports use the same flags.

---

## NOTES

- The "Emails" sheet contains **summaries only** (not full email text) — this is intentional for token efficiency. The full delta_text is stored in the DB and used for confirmation in Phase 3b.
- Batches within the same topic (e.g. `enfants_1` through `enfants_4`, `enfants_2b`) cover **non-overlapping date ranges** — ChatGPT will not see the same email twice within one batch, but a contradiction may span two batches (e.g. email A is in `enfants_2` and email B is in `enfants_3`). These cross-batch contradictions will be caught in the confirmation pass later.
- The `contradictions` table uses `INSERT OR IGNORE` — re-importing the same file is safe (duplicate pairs are silently skipped).
