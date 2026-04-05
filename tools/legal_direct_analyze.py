"""
Direct LLM analysis for legal corpus emails too large for the Excel round-trip.

Usage:
    .venv/bin/python tools/legal_direct_analyze.py [--provider claude|openai] [--dry-run]

Processes all legal emails not yet covered by a legal_analysis run.
Writes results to procedure_events / timeline_events + analysis_results.
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from src.storage.database import get_db
from src.analysis.runner import create_run, finish_run

# ── Prompt constants ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un analyste juridique expert. Tu analyses des emails entre Gaël MAISON
(architecte, Abu Dhabi) et ses avocats dans le cadre d'un divorce contentieux français (2014–présent).
Gaël est le père de deux enfants (Iannys et Lounys). Son ex-femme est Maud MULLER.
Ses avocats : Valérie Charriot-Lecuyer (2014–2016), puis Hélène Hartwig-Deblauwe / Onyx Avocats
(2017–présent), et François Teytaud pour les appels.

Tu réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans explication."""

PROCEDURES = """PROCÉDURES (utiliser l'ID dans procedure_ref) :
#1 Contestation Paternité (RG 17/10390)
#2 ONC — Ordonnance de Non-Conciliation (RG 15/33553)
#3 Appel ONC (RG 15/13023)
#4 Référé (RG 15/42684)
#5 Divorce pour Faute (RG 15/33553)
#6 Appel Divorce (RG 19/07859)
#7 Négociation Amiable
#8 Incident JME (RG 15/33553)
#9 Incident Appel (RG 17/18289)
#10 Acquiescements (protocole 04/09/2020)
#11 Plainte pour Maltraitance
#12 Liquidation Financière (RG 23/06050)
#13 Révision de Pensions (RG 24/07044)
#14 Révision Pensions Appel
#15 Procédure Lounys Dubai"""

EVENT_TYPES = """event_type — utiliser exactement un de ces termes :
Billing    : invoice_issued | payment_request | payment_confirmed | fee_estimate | expense_note | cost_warning | retainer_requested
Filings    : conclusions_filed | requete_filed | assignation | appeal_filed | document_communicated | constitution_avocat | desistement | signification | consignation | incident_filed
Court      : hearing_scheduled | hearing_occurred | hearing_postponed | hearing_cancelled | judgment_rendered | ordonnance_rendered | arret_rendered | expert_appointed | expert_report_delivered | deadline_set | mise_en_etat
Strategy   : strategy_decision | evidence_discussed | settlement_offer_received | settlement_offer_made | settlement_rejected | adverse_move | judge_observation | case_assessment | client_instruction | lawyer_recommendation
Admin      : meeting_scheduled | meeting_occurred | document_exchange | procuration | change_of_lawyer"""

ANALYSIS_FIELDS = """Champs analysis :
- mood_valence (ENVOYÉS seulement) : neutral | determined | anxious | frustrated | relieved | distressed | angry | hopeful | resigned
- mood_intensity (ENVOYÉS) : 1 (routinier) → 5 (crise/pic émotionnel)
- urgency (ENVOYÉS) : routine | normal | urgent | critical
- key_concern (ENVOYÉS) : en français, préoccupation principale de Gaël (1 phrase)
- trust_in_lawyer (ENVOYÉS) : confident | satisfied | neutral | questioning | dissatisfied
- father_role_stress (ENVOYÉS) : none | mild | significant
- financial_stress (ENVOYÉS) : none | mild | significant
- lawyer_stance (REÇUS seulement) : informative | reassuring | cautious | strategic | urgent | billing | defensive | proactive
- strategy_signal (REÇUS) : en français, direction stratégique signalée par l'avocat (1 phrase)
- action_required (REÇUS) : en français, action demandée à Gaël. null si aucune.
- risk_signal (REÇUS) : none | low | medium | high | critical
- procedure_ref : ID de la procédure la plus pertinente (1–15)
- persons_mentioned : noms des juges, experts, huissiers, etc. mentionnés. null si aucun.
- amounts_mentioned : ex. "3500€ provision, 850€ frais". null si aucun.
- children_mentioned : none | Iannys | Lounys | both"""


def build_prompt(email: dict) -> str:
    direction_note = (
        "Email ENVOYÉ par Gaël → remplir mood_valence, mood_intensity, urgency, key_concern, "
        "trust_in_lawyer, father_role_stress, financial_stress. Laisser lawyer_stance/strategy_signal/"
        "action_required/risk_signal à null."
        if email["direction"] == "sent"
        else
        "Email REÇU (de l'avocat) → remplir lawyer_stance, strategy_signal, action_required, risk_signal. "
        "Laisser mood_valence/mood_intensity/urgency/key_concern/trust_in_lawyer/"
        "father_role_stress/financial_stress à null."
    )

    return f"""{PROCEDURES}

{EVENT_TYPES}

{ANALYSIS_FIELDS}

---
EMAIL À ANALYSER :
email_id  : {email['id']}
date      : {email['date']}
direction : {email['direction']}  ({direction_note})
sujet     : {email['subject']}

CONTENU :
{email['content']}

---
Réponds avec un JSON EXACTEMENT dans ce format (sans markdown) :
{{
  "events": [
    {{
      "event_date": "YYYY-MM-DD ou YYYY-MM ou YYYY ou null",
      "event_type": "<type exact>",
      "procedure_ref": <id entier ou null>,
      "description": "<en français, 1-2 phrases>",
      "amount_eur": <nombre ou null>,
      "significance": "high|medium|low"
    }}
  ],
  "analysis": {{
    "mood_valence": "<valeur ou null>",
    "mood_intensity": <1-5 ou null>,
    "urgency": "<valeur ou null>",
    "key_concern": "<en français ou null>",
    "trust_in_lawyer": "<valeur ou null>",
    "father_role_stress": "<valeur ou null>",
    "financial_stress": "<valeur ou null>",
    "lawyer_stance": "<valeur ou null>",
    "strategy_signal": "<en français ou null>",
    "action_required": "<en français ou null>",
    "risk_signal": "<valeur ou null>",
    "procedure_ref": <id entier ou null>,
    "persons_mentioned": "<noms ou null>",
    "amounts_mentioned": "<montants ou null>",
    "children_mentioned": "<valeur ou null>"
  }}
}}
Si aucun événement détecté, retourner "events": []."""


def parse_response(text: str) -> dict:
    """Extract JSON from LLM response, stripping any markdown fences."""
    text = text.strip()
    # Strip markdown fences
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text, flags=re.MULTILINE)
    # Find first { ... } block
    start = text.find('{')
    end   = text.rfind('}')
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {text[:200]}")
    return json.loads(text[start:end + 1])


def norm_date(raw):
    if not raw or str(raw).strip().lower() in ('null', 'none', ''):
        return None
    raw = str(raw).strip()
    if len(raw) >= 10:
        return raw[:10]
    if len(raw) == 7 and raw[4] == '-':
        return raw + '-01'
    if len(raw) == 4 and raw.isdigit():
        return raw + '-01-01'
    return raw or None


def store_results(conn: sqlite3.Connection, run_id: int, email: dict,
                  parsed: dict, valid_proc_ids: set, errors: list) -> tuple:
    """Write events + analysis to DB. Returns (events_stored, analysis_stored)."""
    email_id   = email['id']
    email_date = str(email['date'])[:10]
    ev_count   = 0
    an_count   = 0

    # ── Events ────────────────────────────────────────────────────────────────
    for ev in parsed.get('events', []):
        try:
            desc = str(ev.get('description') or '').strip()
            if not desc:
                continue
            event_type = str(ev.get('event_type') or 'legal').strip()
            event_date = norm_date(ev.get('event_date'))
            date_precision = 'exact' if event_date and len(event_date) == 10 else 'approximate'
            if not event_date:
                event_date     = email_date
                date_precision = 'approximate'

            raw_proc    = ev.get('procedure_ref')
            proc_id     = int(raw_proc) if raw_proc and str(raw_proc).strip().isdigit() else None
            if proc_id and proc_id not in valid_proc_ids:
                proc_id = None

            significance = str(ev.get('significance') or 'medium').strip()
            amount_raw   = ev.get('amount_eur')
            amount_note  = f" amount={amount_raw}EUR" if amount_raw else ""

            if proc_id:
                conn.execute(
                    """INSERT INTO procedure_events
                       (procedure_id, event_date, event_type, date_precision,
                        description, outcome, jurisdiction, source_email_id, notes)
                       VALUES (?, ?, ?, ?, ?, '', '', ?, ?)""",
                    (proc_id, event_date, event_type, date_precision,
                     desc, email_id,
                     f"direct-llm run_id={run_id} significance={significance}{amount_note}"),
                )
            else:
                conn.execute(
                    """INSERT INTO timeline_events
                       (run_id, email_id, event_date, event_type, description, significance)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (run_id, email_id, event_date, event_type, desc, significance),
                )
            ev_count += 1
        except Exception as exc:
            errors.append(f"email_id={email_id} event error: {exc}")

    # ── Analysis ──────────────────────────────────────────────────────────────
    try:
        an = parsed.get('analysis', {}) or {}

        def _v(key):
            val = an.get(key)
            if val is None or str(val).strip().lower() in ('null', 'none', ''):
                return None
            return str(val).strip()

        def _i(key):
            val = an.get(key)
            if val is None or str(val).strip().lower() in ('null', 'none', ''):
                return None
            try:
                return int(float(str(val)))
            except (ValueError, TypeError):
                return None

        result = {
            'mood_valence':       _v('mood_valence'),
            'mood_intensity':     _i('mood_intensity'),
            'urgency':            _v('urgency'),
            'key_concern':        _v('key_concern'),
            'trust_in_lawyer':    _v('trust_in_lawyer'),
            'father_role_stress': _v('father_role_stress'),
            'financial_stress':   _v('financial_stress'),
            'lawyer_stance':      _v('lawyer_stance'),
            'strategy_signal':    _v('strategy_signal'),
            'action_required':    _v('action_required'),
            'risk_signal':        _v('risk_signal'),
            'procedure_ref':      _v('procedure_ref'),
            'persons_mentioned':  _v('persons_mentioned'),
            'amounts_mentioned':  _v('amounts_mentioned'),
            'children_mentioned': _v('children_mentioned'),
            'source':             'direct-llm',
        }
        result = {k: v for k, v in result.items() if v is not None}

        conn.execute(
            """INSERT OR REPLACE INTO analysis_results
               (run_id, email_id, sender_contact_id, result_json)
               VALUES (?, ?, NULL, ?)""",
            (run_id, email_id, json.dumps(result)),
        )
        an_count = 1
    except Exception as exc:
        errors.append(f"email_id={email_id} analysis error: {exc}")

    return ev_count, an_count


def main():
    parser = argparse.ArgumentParser(description="Direct LLM analysis for oversized legal emails")
    parser.add_argument('--provider', default='openai', choices=['claude', 'openai'],
                        help='LLM provider (default: claude)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print prompt for first email, do not call API or write DB')
    parser.add_argument('--limit', type=int, default=None,
                        help='Max emails to process (default: all)')
    args = parser.parse_args()

    # ── Load provider ─────────────────────────────────────────────────────────
    from src.llm.router import get_provider
    provider = get_provider('contradictions', override=args.provider)
    print(f"Provider : {provider.name} / {getattr(provider, '_model', '?')}")

    # ── Load unanalyzed emails ────────────────────────────────────────────────
    conn = sqlite3.connect(str(ROOT / 'data' / 'emails.db'))
    conn.row_factory = sqlite3.Row

    emails = conn.execute("""
        SELECT e.id, e.date, e.direction, e.subject,
               e.delta_text, e.body_text
        FROM emails e
        WHERE e.corpus = 'legal'
          AND e.id NOT IN (
              SELECT DISTINCT ar.email_id FROM analysis_results ar
              JOIN analysis_runs ru ON ru.id = ar.run_id
              WHERE ru.analysis_type = 'legal_analysis'
          )
        ORDER BY e.date ASC
    """).fetchall()

    if args.limit:
        emails = emails[:args.limit]

    print(f"Emails to analyse: {len(emails)}")

    if not emails:
        print("Nothing to do.")
        conn.close()
        return

    valid_proc_ids = {r[0] for r in conn.execute("SELECT id FROM procedures")}

    # ── Dry run ───────────────────────────────────────────────────────────────
    if args.dry_run:
        e = emails[0]
        delta = (e['delta_text'] or '').strip()
        body  = (e['body_text']  or '').strip()
        content = delta if len(delta) >= 150 else (body or delta)
        email_dict = {
            'id': e['id'], 'date': str(e['date'])[:10],
            'direction': e['direction'], 'subject': e['subject'] or '',
            'content': content[:2000] + '...[truncated for dry-run]',
        }
        print("\n=== PROMPT (truncated) ===")
        print(build_prompt(email_dict)[:3000])
        conn.close()
        return

    # ── Create run ────────────────────────────────────────────────────────────
    model_id = getattr(provider, '_model', args.provider)
    run_id   = create_run('legal_analysis', args.provider, model_id)
    print(f"Run ID   : #{run_id}")
    print()

    total_events   = 0
    total_analysis = 0
    errors         = []
    commit_every   = 10

    try:
        from tqdm import tqdm
        iterator = tqdm(emails, desc="Analysing", unit="email")
    except ImportError:
        iterator = emails

    for i, row in enumerate(iterator):
        delta   = (row['delta_text'] or '').strip()
        body    = (row['body_text']  or '').strip()
        content = delta if len(delta) >= 150 else (body or delta)

        email_dict = {
            'id':        row['id'],
            'date':      str(row['date'])[:10],
            'direction': row['direction'] or 'sent',
            'subject':   row['subject'] or '(no subject)',
            'content':   content,
        }

        prompt = build_prompt(email_dict)

        try:
            resp   = provider.complete_with_retry(
                prompt=prompt,
                system=SYSTEM_PROMPT,
                max_tokens=2048,
                temperature=0.1,
            )
            parsed = parse_response(resp.content)
            ev, an = store_results(conn, run_id, email_dict, parsed, valid_proc_ids, errors)
            total_events   += ev
            total_analysis += an
        except Exception as exc:
            errors.append(f"email_id={row['id']}: {exc}")
            continue

        # Commit periodically
        if (i + 1) % commit_every == 0:
            conn.commit()

    conn.commit()
    conn.close()

    status = 'complete' if not errors else 'partial'
    finish_run(run_id, status, total_analysis)

    print(f"\n{'=' * 50}")
    print(f"Run #{run_id} — {status.upper()}")
    print(f"Events imported   : {total_events}")
    print(f"Analysis imported : {total_analysis}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == '__main__':
    main()
