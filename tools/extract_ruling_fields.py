"""
Extract structured ruling fields from existing judgment/ordonnance PDFs.

For each procedure_event of type 'judgment' or 'ordonnance' that has a linked
procedure_document, this script:
  1. Extracts text from the PDF (pdfplumber, first 6 pages)
  2. Sends to Claude with a structured prompt
  3. UPDATEs procedure_events with: judge_name, ruling_for, pension_amount,
     custody_arrangement, obligations (newline-separated)

Usage:
    .venv/bin/python tools/extract_ruling_fields.py [options]

Options:
    --dry-run       Print what would be done, no DB writes
    --force         Re-process events that already have ruling fields set
    --event-id N    Process only this procedure_events.id
    --provider      claude | openai  (default: claude)
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

import pdfplumber

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import src.config  # noqa: F401 — triggers load_dotenv at import time
from src.llm.router import get_provider

# ── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Tu es un expert en droit de la famille français. Tu analyses des
décisions de justice (jugements, ordonnances) dans le cadre d'une procédure de divorce
contentieux. Le père s'appelle Gaël MAISON, son ex-femme Maud MULLER.
Tu réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans explication."""

USER_PROMPT_TEMPLATE = """Voici le texte d'une décision de justice ({event_type}, {event_date}).

Extrais les informations suivantes et retourne un objet JSON avec exactement ces clés :

{{
  "judge_name": "Nom du juge/magistrat présidant (ex: Mme DUPONT). Chaîne vide si non trouvé.",
  "ruling_for": "Qui a gagné : 'party_a' (Gaël MAISON), 'party_b' (Maud MULLER), 'both' (partagé), 'neutral' (procédural/mixte), 'unknown' si pas clair.",
  "pension_amount": montant mensuel de la pension alimentaire en euros (nombre flottant), ou null si non applicable,
  "custody_arrangement": "Arrangement de garde : 'alternée', 'résidence_principale_a' (chez Gaël), 'résidence_principale_b' (chez Maud), 'supervisée', 'other', ou '' si non applicable.",
  "obligations": ["obligation 1", "obligation 2", ...]
}}

Pour 'obligations', liste UNIQUEMENT les obligations concrètes et spécifiques imposées
(paiements, délais, interdictions, remises de documents, etc.). Exclure les généralités procédurales.
Maximum 8 obligations. Liste vide [] si aucune obligation spécifique.

Texte de la décision (premières pages) :

{pdf_text}"""

# ── PDF extraction ─────────────────────────────────────────────────────────────

def extract_pdf_text(file_path: str, max_pages: int = 6) -> str:
    """Extract text from the first max_pages of a PDF."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")
    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i >= max_pages:
                break
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
    return "\n\n--- PAGE ---\n\n".join(pages)


# ── DB helpers ─────────────────────────────────────────────────────────────────

def get_events(conn: sqlite3.Connection, event_id=None, force=False):
    """Return judgment/ordonnance events with their best linked document path."""
    where = "pe.event_type IN ('judgment', 'ordonnance')"
    params = []
    if event_id:
        where += " AND pe.id = ?"
        params.append(event_id)
    if not force:
        where += " AND (pe.judge_name = '' OR pe.judge_name IS NULL)"

    rows = conn.execute(f"""
        SELECT pe.id, pe.event_date, pe.event_type, pe.procedure_id,
               pe.judge_name, pe.ruling_for, pe.pension_amount,
               pe.custody_arrangement, pe.obligations,
               p.name AS procedure_name,
               -- prefer source_attachment download_path, then best procedure_document
               COALESCE(
                   att.download_path,
                   (SELECT pd.file_path FROM procedure_documents pd
                    WHERE pd.procedure_id = pe.procedure_id
                    ORDER BY pd.uploaded_at ASC LIMIT 1)
               ) AS doc_path
          FROM procedure_events pe
          JOIN procedures p ON p.id = pe.procedure_id
          LEFT JOIN attachments att ON att.id = pe.source_attachment_id
                                   AND att.download_path IS NOT NULL
                                   AND att.download_path != ''
         WHERE {where}
         ORDER BY pe.event_date
    """, params).fetchall()
    return [dict(r) for r in rows]


def best_doc_for_event(conn: sqlite3.Connection, event: dict) -> Optional[str]:
    """Pick the most relevant procedure document for this event.

    Priority:
      1. doc whose filename contains the event_type keyword
      2. doc whose filename contains 'decision', 'jugement', 'ordonnance', 'minute'
      3. first document in the procedure (already set via COALESCE in get_events)
    """
    if event.get("doc_path"):
        return event["doc_path"]

    docs = conn.execute("""
        SELECT file_path FROM procedure_documents
        WHERE procedure_id = ?
        ORDER BY uploaded_at ASC
    """, (event["procedure_id"],)).fetchall()

    if not docs:
        return None

    et = event["event_type"].lower()
    keywords = [et, "decision", "jugement", "ordonnance", "minute", "arret", "arrêt"]
    for row in docs:
        fp = row[0].lower()
        for kw in keywords:
            if kw in fp:
                return row[0]
    return docs[0][0]


def update_event(conn: sqlite3.Connection, event_id: int, fields: dict) -> None:
    conn.execute("""
        UPDATE procedure_events
           SET judge_name          = ?,
               ruling_for          = ?,
               pension_amount      = ?,
               custody_arrangement = ?,
               obligations         = ?
         WHERE id = ?
    """, (
        fields.get("judge_name", ""),
        fields.get("ruling_for", ""),
        fields.get("pension_amount"),         # float or None
        fields.get("custody_arrangement", ""),
        fields.get("obligations", ""),        # newline-joined string
        event_id,
    ))
    conn.commit()


# ── LLM call ──────────────────────────────────────────────────────────────────

def call_llm(provider, event: dict, pdf_text: str) -> dict:
    prompt = USER_PROMPT_TEMPLATE.format(
        event_type=event["event_type"],
        event_date=event["event_date"],
        pdf_text=pdf_text[:12000],   # ~3k tokens input ceiling
    )
    response = provider.complete(
        system=SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=600,
    )
    raw = response.strip()
    # Strip markdown fences if any
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def normalise_fields(data: dict) -> dict:
    """Clean LLM output into DB-safe values."""
    # obligations: list → newline-joined string
    obs = data.get("obligations", [])
    if isinstance(obs, list):
        obs_str = "\n".join(str(o).strip() for o in obs if str(o).strip())
    else:
        obs_str = str(obs).strip()

    pension = data.get("pension_amount")
    if pension is not None:
        try:
            pension = float(pension)
        except (TypeError, ValueError):
            pension = None

    return {
        "judge_name":          (data.get("judge_name") or "").strip(),
        "ruling_for":          (data.get("ruling_for") or "").strip(),
        "pension_amount":      pension,
        "custody_arrangement": (data.get("custody_arrangement") or "").strip(),
        "obligations":         obs_str,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run",   action="store_true")
    ap.add_argument("--force",     action="store_true",
                    help="Re-process events that already have ruling fields")
    ap.add_argument("--event-id",  type=int, default=None)
    ap.add_argument("--provider",  default="claude",
                    choices=["claude", "openai", "groq"])
    args = ap.parse_args()

    conn = sqlite3.connect(str(ROOT / "data" / "emails.db"))
    conn.row_factory = sqlite3.Row

    events = get_events(conn, event_id=args.event_id, force=args.force)
    if not events:
        print("No events to process. Use --force to re-process existing ones.")
        return

    print(f"Processing {len(events)} event(s) with provider={args.provider}\n")

    # Defer provider init so --dry-run works without a live API key
    provider = None
    if not args.dry_run:
        provider = get_provider(task="contradictions", override=args.provider)

    for ev in events:
        doc_path = best_doc_for_event(conn, ev)
        tag = f"[#{ev['id']} {ev['event_type']} {ev['event_date']} — {ev['procedure_name']}]"

        if not doc_path:
            print(f"  {tag}  ⚠️  No document found — skipping")
            continue

        print(f"  {tag}")
        print(f"    PDF: {doc_path}")

        if args.dry_run:
            print("    → dry-run, skipping LLM call\n")
            continue

        try:
            pdf_text = extract_pdf_text(doc_path)
        except FileNotFoundError as e:
            print(f"    ⚠️  {e} — skipping\n")
            continue

        if not pdf_text.strip():
            print("    ⚠️  PDF yielded no text — skipping\n")
            continue

        try:
            raw = call_llm(provider, ev, pdf_text)
        except Exception as e:
            print(f"    ⚠️  LLM error: {e} — skipping\n")
            continue

        fields = normalise_fields(raw)
        print(f"    judge:    {fields['judge_name'] or '—'}")
        print(f"    ruling:   {fields['ruling_for'] or '—'}")
        print(f"    pension:  {fields['pension_amount']} €/mo" if fields['pension_amount'] else "    pension:  —")
        print(f"    custody:  {fields['custody_arrangement'] or '—'}")
        if fields["obligations"]:
            for line in fields["obligations"].split("\n")[:4]:
                print(f"    · {line}")
        print()

        update_event(conn, ev["id"], fields)
        time.sleep(1)   # avoid rate limits

    print("Done.")


if __name__ == "__main__":
    main()
