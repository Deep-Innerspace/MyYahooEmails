"""Contacts routes — contact list and per-contact detail."""
import sqlite3
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective
from src.statistics.aggregator import contact_summary

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def contacts_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Contact list with summary stats."""
    contacts = contact_summary(conn)

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "contacts",
        "contacts": contacts,
        "total": len(contacts),
    }
    return templates.TemplateResponse("pages/contacts.html", ctx)


@router.get("/{contact_id}", response_class=HTMLResponse)
async def contact_detail(
    request: Request,
    contact_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Contact detail page — shows their emails."""
    contact_row = conn.execute(
        "SELECT id, name, email, aliases, role, notes FROM contacts WHERE id = ?",
        (contact_id,),
    ).fetchone()

    if not contact_row:
        return HTMLResponse("Contact not found", status_code=404)

    contact = dict(contact_row)

    # Get summary stats for this contact
    summaries = contact_summary(conn, contact_email=contact["email"])
    summary = summaries[0] if summaries else {}

    # Get recent emails for this contact (most recent 50)
    emails = conn.execute(
        """SELECT id, date, from_address, from_name, subject, direction, language
           FROM emails WHERE contact_id = ?
           ORDER BY date DESC LIMIT 50""",
        (contact_id,),
    ).fetchall()
    emails = [dict(e) for e in emails]

    # Get topics this contact is involved in
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

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "contacts",
        "contact": contact,
        "summary": summary,
        "emails": emails,
        "topics": topics,
    }
    return templates.TemplateResponse("pages/contact_detail.html", ctx)
