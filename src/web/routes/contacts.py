"""Contacts routes — list, detail, CRUD, alias management, unassigned sender assignment."""
import json
import sqlite3
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from typing import Optional

from src.web.deps import get_conn, get_perspective
from src.statistics.aggregator import contact_summary, unassigned_senders

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

ROLES = [
    ("me", "Me"),
    ("ex-wife", "Ex-wife"),
    ("my_lawyer", "My Lawyer"),
    ("her_lawyer", "Her Lawyer"),
    ("opposing_counsel", "Opposing Counsel"),
    ("notaire", "Notaire"),
    ("my_friend", "My Friend"),
    ("her_friend", "Her Friend"),
    ("family_mediation", "Family Mediation"),
    ("family", "Family"),
    ("school", "School"),
    ("medical", "Medical"),
    ("housing", "Housing"),
    ("other", "Other"),
]

LAWYER_ROLES = {"my_lawyer", "her_lawyer", "opposing_counsel"}


def _backfill_contact(conn: sqlite3.Connection, contact_id: int) -> int:
    """Set contact_id on emails whose from_address matches primary or any alias.
    Returns number of rows updated."""
    row = conn.execute(
        "SELECT email, aliases FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    if not row:
        return 0
    addresses = [row["email"]]
    try:
        addresses.extend(json.loads(row["aliases"]))
    except (json.JSONDecodeError, TypeError):
        pass
    placeholders = ",".join("?" for _ in addresses)
    conn.execute(
        f"UPDATE emails SET contact_id = ? WHERE from_address IN ({placeholders}) AND contact_id IS NULL",
        [contact_id] + addresses,
    )
    return conn.execute("SELECT changes()").fetchone()[0]


def _contact_to_dict(row) -> dict:
    d = dict(row)
    try:
        d["aliases"] = json.loads(d.get("aliases") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["aliases"] = []
    return d


# ─────────────────────────────── LIST ─────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def contacts_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    contacts = contact_summary(conn)
    unassigned = unassigned_senders(conn, min_count=2)

    # Group unassigned by domain for display
    domain_groups: dict = {}
    for s in unassigned:
        domain_groups.setdefault(s["domain"], []).append(s)

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "contacts",
        "contacts": contacts,
        "total": len(contacts),
        "unassigned": unassigned,
        "domain_groups": domain_groups,
        "roles": ROLES,
        "lawyer_roles": LAWYER_ROLES,
    }
    return templates.TemplateResponse("pages/contacts.html", ctx)


# ─────────────────────────────── CREATE ───────────────────────────────────────

@router.post("/", response_class=RedirectResponse)
@router.post("", response_class=RedirectResponse)
async def create_contact(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    role: str = Form(default="other"),
    firm_name: str = Form(default=""),
    bar_jurisdiction: str = Form(default=""),
    notes: str = Form(default=""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    email = email.strip().lower()
    existing = conn.execute(
        "SELECT id FROM contacts WHERE email = ?", (email,)
    ).fetchone()
    if not existing:
        conn.execute(
            """INSERT INTO contacts (name, email, role, firm_name, bar_jurisdiction, notes, aliases)
               VALUES (?, ?, ?, ?, ?, ?, '[]')""",
            (name.strip(), email, role, firm_name.strip(), bar_jurisdiction.strip(), notes.strip()),
        )
        contact_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        _backfill_contact(conn, contact_id)
    conn.commit()
    return RedirectResponse("/contacts/", status_code=303)


# ─────────────────────────────── DETAIL ───────────────────────────────────────

@router.get("/{contact_id}", response_class=HTMLResponse)
async def contact_detail(
    request: Request,
    contact_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    row = conn.execute(
        "SELECT id, name, email, aliases, role, firm_name, bar_jurisdiction, notes FROM contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()
    if not row:
        return HTMLResponse("Contact not found", status_code=404)

    contact = _contact_to_dict(row)

    # Corpus breakdown
    corpus_stats = conn.execute(
        """SELECT corpus, COUNT(*) AS cnt FROM emails WHERE contact_id = ? GROUP BY corpus""",
        (contact_id,),
    ).fetchall()
    corpus_map = {r["corpus"]: r["cnt"] for r in corpus_stats}

    # Summary stats
    summaries = contact_summary(conn, contact_email=contact["email"])
    summary = summaries[0] if summaries else {}

    # Recent emails (most recent 50)
    emails = conn.execute(
        """SELECT id, date, from_address, from_name, subject, direction, language, corpus
           FROM emails WHERE contact_id = ?
           ORDER BY date DESC LIMIT 50""",
        (contact_id,),
    ).fetchall()
    emails = [dict(e) for e in emails]

    # Top topics
    topics = conn.execute(
        """SELECT t.name, COUNT(*) AS cnt
           FROM email_topics et
           JOIN topics t ON et.topic_id = t.id
           JOIN emails e ON et.email_id = e.id
           WHERE e.contact_id = ?
           GROUP BY t.name ORDER BY cnt DESC LIMIT 10""",
        (contact_id,),
    ).fetchall()
    topics = [dict(t) for t in topics]

    # All contacts for "assign alias" dropdown
    all_contacts = conn.execute(
        "SELECT id, name, email FROM contacts ORDER BY name"
    ).fetchall()

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "contacts",
        "contact": contact,
        "summary": summary,
        "corpus_map": corpus_map,
        "emails": emails,
        "topics": topics,
        "roles": ROLES,
        "lawyer_roles": LAWYER_ROLES,
        "all_contacts": [dict(c) for c in all_contacts],
    }
    return templates.TemplateResponse("pages/contact_detail.html", ctx)


# ─────────────────────────────── EDIT ─────────────────────────────────────────

@router.post("/{contact_id}/edit", response_class=RedirectResponse)
async def edit_contact(
    request: Request,
    contact_id: int,
    name: str = Form(...),
    role: str = Form(default="other"),
    firm_name: str = Form(default=""),
    bar_jurisdiction: str = Form(default=""),
    notes: str = Form(default=""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        """UPDATE contacts SET name=?, role=?, firm_name=?, bar_jurisdiction=?, notes=?
           WHERE id=?""",
        (name.strip(), role, firm_name.strip(), bar_jurisdiction.strip(), notes.strip(), contact_id),
    )
    conn.commit()
    return RedirectResponse(f"/contacts/{contact_id}", status_code=303)


# ─────────────────────────────── DELETE ───────────────────────────────────────

@router.post("/{contact_id}/delete", response_class=RedirectResponse)
async def delete_contact(
    request: Request,
    contact_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    # Unlink emails (keep emails, just remove contact association)
    conn.execute("UPDATE emails SET contact_id = NULL WHERE contact_id = ?", (contact_id,))
    conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
    conn.commit()
    return RedirectResponse("/contacts/", status_code=303)


# ─────────────────────────── ALIAS MANAGEMENT ─────────────────────────────────

@router.post("/{contact_id}/aliases/add", response_class=HTMLResponse)
async def add_alias(
    request: Request,
    contact_id: int,
    alias_email: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    alias_email = alias_email.strip().lower()
    row = conn.execute(
        "SELECT aliases FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    if not row:
        return HTMLResponse("Not found", status_code=404)

    try:
        aliases = json.loads(row["aliases"])
    except (json.JSONDecodeError, TypeError):
        aliases = []

    if alias_email and alias_email not in aliases:
        aliases.append(alias_email)
        conn.execute(
            "UPDATE contacts SET aliases = ? WHERE id = ?",
            (json.dumps(aliases), contact_id),
        )
        # Backfill: link existing emails from this alias
        conn.execute(
            "UPDATE emails SET contact_id = ? WHERE from_address = ? AND contact_id IS NULL",
            (contact_id, alias_email),
        )

    updated = conn.execute(
        "SELECT id, name, email, aliases, role, firm_name, bar_jurisdiction, notes FROM contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()
    contact = _contact_to_dict(updated)

    return templates.TemplateResponse("partials/contact_aliases.html", {
        "request": request,
        "contact": contact,
    })


@router.post("/{contact_id}/aliases/remove", response_class=HTMLResponse)
async def remove_alias(
    request: Request,
    contact_id: int,
    alias_email: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    alias_email = alias_email.strip().lower()
    row = conn.execute(
        "SELECT aliases FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    if not row:
        return HTMLResponse("Not found", status_code=404)

    try:
        aliases = json.loads(row["aliases"])
    except (json.JSONDecodeError, TypeError):
        aliases = []

    aliases = [a for a in aliases if a != alias_email]
    conn.execute(
        "UPDATE contacts SET aliases = ? WHERE id = ?",
        (json.dumps(aliases), contact_id),
    )
    # Unlink emails that were linked via this alias (from_address = alias)
    conn.execute(
        "UPDATE emails SET contact_id = NULL WHERE from_address = ? AND contact_id = ?",
        (alias_email, contact_id),
    )

    updated = conn.execute(
        "SELECT id, name, email, aliases, role, firm_name, bar_jurisdiction, notes FROM contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()
    contact = _contact_to_dict(updated)

    return templates.TemplateResponse("partials/contact_aliases.html", {
        "request": request,
        "contact": contact,
    })


# ─────────────────────── ASSIGN UNASSIGNED SENDER ─────────────────────────────

@router.post("/assign-sender", response_class=RedirectResponse)
async def assign_sender(
    request: Request,
    from_address: str = Form(...),
    action: str = Form(...),          # 'new' or 'existing'
    contact_name: str = Form(default=""),
    contact_role: str = Form(default="other"),
    contact_firm: str = Form(default=""),
    existing_contact_id: Optional[int] = Form(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    from_address = from_address.strip().lower()

    if action == "new":
        name = contact_name.strip() or from_address.split("@")[0]
        conn.execute(
            """INSERT INTO contacts (name, email, role, firm_name, aliases)
               VALUES (?, ?, ?, ?, '[]')""",
            (name, from_address, contact_role, contact_firm.strip()),
        )
        contact_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "UPDATE emails SET contact_id = ? WHERE from_address = ? AND contact_id IS NULL",
            (contact_id, from_address),
        )
        conn.commit()
        return RedirectResponse(f"/contacts/{contact_id}", status_code=303)

    elif action == "existing" and existing_contact_id:
        # Add as alias to existing contact
        row = conn.execute(
            "SELECT aliases FROM contacts WHERE id = ?", (existing_contact_id,)
        ).fetchone()
        if row:
            try:
                aliases = json.loads(row["aliases"])
            except (json.JSONDecodeError, TypeError):
                aliases = []
            if from_address not in aliases:
                aliases.append(from_address)
                conn.execute(
                    "UPDATE contacts SET aliases = ? WHERE id = ?",
                    (json.dumps(aliases), existing_contact_id),
                )
            conn.execute(
                "UPDATE emails SET contact_id = ? WHERE from_address = ? AND contact_id IS NULL",
                (existing_contact_id, from_address),
            )
        conn.commit()
        return RedirectResponse(f"/contacts/{existing_contact_id}", status_code=303)

    conn.commit()
    return RedirectResponse("/contacts/", status_code=303)
