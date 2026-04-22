"""Bundle builder — assembles a procedure's tagged evidence into an exportable structure."""
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class BundlePiece:
    email_id: int
    date: str
    subject: str
    direction: str
    from_name: str
    delta_text: str
    rationale: str
    highlights: list = field(default_factory=list)   # [{text, note}]
    topic_names: list = field(default_factory=list)


@dataclass
class Bundle:
    procedure_id: int
    procedure_name: str
    procedure_type: str
    case_number: str
    jurisdiction: str
    description: str
    generated_at: str
    pieces: list = field(default_factory=list)   # list[BundlePiece]


def build_bundle(
    conn: sqlite3.Connection,
    procedure_id: int,
    email_ids: Optional[list] = None,
) -> Bundle:
    """Assemble a Bundle from all evidence_tags rows for a procedure.

    If email_ids is provided, only those emails are included.
    """
    proc = conn.execute(
        """SELECT name, procedure_type, case_number, jurisdiction, description
             FROM procedures WHERE id = ?""",
        (procedure_id,),
    ).fetchone()
    if not proc:
        raise ValueError(f"Procedure {procedure_id} not found")

    query = """
        SELECT et.email_id, et.rationale, et.topic_ids, et.highlights,
               e.date, e.subject, e.from_address, e.direction, e.delta_text,
               c.name AS from_name
          FROM evidence_tags et
          JOIN emails e ON e.id = et.email_id
          LEFT JOIN contacts c ON e.contact_id = c.id
         WHERE et.procedure_id = ?
    """
    params: list = [procedure_id]
    if email_ids:
        ph = ",".join("?" * len(email_ids))
        query += f" AND et.email_id IN ({ph})"
        params.extend(email_ids)
    query += " ORDER BY e.date ASC"

    rows = conn.execute(query, params).fetchall()

    # Resolve topic names in one pass
    all_topic_ids: set = set()
    parsed: list = []
    for r in rows:
        d = dict(r)
        d["_topic_ids"] = json.loads(d.get("topic_ids") or "[]")
        d["_highlights"] = json.loads(d.get("highlights") or "[]")
        all_topic_ids.update(d["_topic_ids"])
        parsed.append(d)

    topic_map: dict = {}
    if all_topic_ids:
        ph = ",".join("?" * len(all_topic_ids))
        for tr in conn.execute(
            f"SELECT id, name FROM topics WHERE id IN ({ph})", list(all_topic_ids)
        ).fetchall():
            topic_map[tr["id"]] = tr["name"]

    pieces = []
    for d in parsed:
        pieces.append(BundlePiece(
            email_id=d["email_id"],
            date=(d["date"] or "")[:10],
            subject=d["subject"] or "(no subject)",
            direction=d["direction"] or "received",
            from_name=d["from_name"] or d["from_address"] or "",
            delta_text=d["delta_text"] or "",
            rationale=d["rationale"] or "",
            highlights=d["_highlights"],
            topic_names=[topic_map.get(tid, str(tid)) for tid in d["_topic_ids"]],
        ))

    return Bundle(
        procedure_id=procedure_id,
        procedure_name=proc["name"],
        procedure_type=proc["procedure_type"],
        case_number=proc["case_number"],
        jurisdiction=proc["jurisdiction"],
        description=proc["description"],
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        pieces=pieces,
    )
