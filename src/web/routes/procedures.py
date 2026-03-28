"""Procedures CRUD routes — Phase 6e.1."""
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

PROCEDURE_TYPES = [
    "contestation", "premiere_instance", "appel", "refere", "divorce_faute",
    "negociation", "incident", "acquiescement", "plainte", "liquidation",
    "revision_pension", "relocation", "autre",
]

STATUS_OPTIONS = [
    "unknown", "active", "pending", "closed", "won", "lost", "settled", "abandoned",
]

EVENT_TYPES = [
    "assignation", "conclusions_sent", "conclusions_received", "conclusions_adverse",
    "hearing", "judgment", "ordonnance", "convocation", "mediation", "expert_report",
    "settlement_proposal", "filing", "correspondence", "appeal_filed", "notification",
    "other",
]

PRECISION_OPTIONS = ["exact", "approximate", "inferred"]


def _get_lawyer_contacts(conn):
    """Fetch contacts with lawyer roles for dropdowns."""
    rows = conn.execute(
        "SELECT id, name, email, role FROM contacts "
        "WHERE role IN ('my_lawyer', 'her_lawyer', 'opposing_counsel') "
        "ORDER BY role, name"
    ).fetchall()
    return [dict(r) for r in rows]


# ── List all procedures ──────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def procedures_list(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    rows = conn.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM procedure_events pe WHERE pe.procedure_id = p.id) AS event_count,
               ca.name AS party_a_name, cb.name AS party_b_name
        FROM procedures p
        LEFT JOIN contacts ca ON p.party_a_lawyer_id = ca.id
        LEFT JOIN contacts cb ON p.party_b_lawyer_id = cb.id
        ORDER BY
            CASE WHEN p.date_start IS NULL THEN 1 ELSE 0 END,
            p.date_start DESC, p.id DESC
    """).fetchall()
    procedures = [dict(r) for r in rows]

    lawyers = _get_lawyer_contacts(conn)

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "procedures",
        "procedures": procedures,
        "total": len(procedures),
        "procedure_types": PROCEDURE_TYPES,
        "status_options": STATUS_OPTIONS,
        "lawyers": lawyers,
    }
    return templates.TemplateResponse("pages/procedures.html", ctx)


# ── Procedure detail ─────────────────────────────────────────────────────────

@router.get("/{proc_id}", response_class=HTMLResponse)
async def procedure_detail(
    request: Request,
    proc_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    proc = conn.execute("""
        SELECT p.*,
               ca.name AS party_a_name, cb.name AS party_b_name
        FROM procedures p
        LEFT JOIN contacts ca ON p.party_a_lawyer_id = ca.id
        LEFT JOIN contacts cb ON p.party_b_lawyer_id = cb.id
        WHERE p.id = ?
    """, (proc_id,)).fetchone()

    if not proc:
        return HTMLResponse("Procedure not found", status_code=404)

    proc = dict(proc)

    # Fetch events with linked email subject
    event_rows = conn.execute("""
        SELECT pe.*, e.subject AS email_subject
        FROM procedure_events pe
        LEFT JOIN emails e ON pe.source_email_id = e.id
        WHERE pe.procedure_id = ?
        ORDER BY
            CASE WHEN pe.event_date IS NULL THEN 1 ELSE 0 END,
            pe.event_date ASC, pe.id ASC
    """, (proc_id,)).fetchall()
    events = [dict(r) for r in event_rows]

    lawyers = _get_lawyer_contacts(conn)

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "procedures",
        "proc": proc,
        "events": events,
        "lawyers": lawyers,
        "procedure_types": PROCEDURE_TYPES,
        "status_options": STATUS_OPTIONS,
        "event_types": EVENT_TYPES,
        "precision_options": PRECISION_OPTIONS,
    }
    return templates.TemplateResponse("pages/procedure_detail.html", ctx)


# ── Create procedure ─────────────────────────────────────────────────────────

@router.post("", response_class=HTMLResponse)
@router.post("/", response_class=HTMLResponse)
async def create_procedure(
    request: Request,
    name: str = Form(...),
    procedure_type: str = Form("autre"),
    jurisdiction: str = Form(""),
    case_number: str = Form(""),
    status: str = Form("unknown"),
    date_start: str = Form(""),
    date_end: str = Form(""),
    initiated_by: str = Form(""),
    party_a_lawyer_id: Optional[str] = Form(None),
    party_b_lawyer_id: Optional[str] = Form(None),
    description: str = Form(""),
    outcome_summary: str = Form(""),
    notes: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("""
        INSERT INTO procedures
            (name, procedure_type, jurisdiction, case_number, status,
             date_start, date_end, initiated_by,
             party_a_lawyer_id, party_b_lawyer_id,
             description, outcome_summary, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name.strip(),
        procedure_type,
        jurisdiction.strip() or None,
        case_number.strip() or None,
        status,
        date_start or None,
        date_end or None,
        initiated_by.strip() or None,
        int(party_a_lawyer_id) if party_a_lawyer_id else None,
        int(party_b_lawyer_id) if party_b_lawyer_id else None,
        description.strip() or None,
        outcome_summary.strip() or None,
        notes.strip() or None,
    ))
    conn.commit()
    return RedirectResponse("/procedures/", status_code=303)


# ── Update procedure ─────────────────────────────────────────────────────────

@router.post("/{proc_id}/update", response_class=HTMLResponse)
async def update_procedure(
    request: Request,
    proc_id: int,
    name: str = Form(...),
    procedure_type: str = Form("autre"),
    jurisdiction: str = Form(""),
    case_number: str = Form(""),
    status: str = Form("unknown"),
    date_start: str = Form(""),
    date_end: str = Form(""),
    initiated_by: str = Form(""),
    party_a_lawyer_id: Optional[str] = Form(None),
    party_b_lawyer_id: Optional[str] = Form(None),
    description: str = Form(""),
    outcome_summary: str = Form(""),
    notes: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("""
        UPDATE procedures SET
            name = ?, procedure_type = ?, jurisdiction = ?, case_number = ?,
            status = ?, date_start = ?, date_end = ?, initiated_by = ?,
            party_a_lawyer_id = ?, party_b_lawyer_id = ?,
            description = ?, outcome_summary = ?, notes = ?
        WHERE id = ?
    """, (
        name.strip(),
        procedure_type,
        jurisdiction.strip() or None,
        case_number.strip() or None,
        status,
        date_start or None,
        date_end or None,
        initiated_by.strip() or None,
        int(party_a_lawyer_id) if party_a_lawyer_id else None,
        int(party_b_lawyer_id) if party_b_lawyer_id else None,
        description.strip() or None,
        outcome_summary.strip() or None,
        notes.strip() or None,
        proc_id,
    ))
    conn.commit()
    return RedirectResponse(f"/procedures/{proc_id}", status_code=303)


# ── Delete procedure ─────────────────────────────────────────────────────────

@router.post("/{proc_id}/delete", response_class=HTMLResponse)
async def delete_procedure(
    request: Request,
    proc_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    # Cascade: delete events first, then invoices, then procedure
    conn.execute("DELETE FROM procedure_events WHERE procedure_id = ?", (proc_id,))
    conn.execute("DELETE FROM lawyer_invoices WHERE procedure_id = ?", (proc_id,))
    conn.execute("DELETE FROM procedures WHERE id = ?", (proc_id,))
    conn.commit()
    return RedirectResponse("/procedures/", status_code=303)


# ── Add event to procedure ───────────────────────────────────────────────────

@router.post("/{proc_id}/events", response_class=HTMLResponse)
async def add_event(
    request: Request,
    proc_id: int,
    event_date: str = Form(""),
    event_type: str = Form("other"),
    date_precision: str = Form("exact"),
    description: str = Form(""),
    outcome: str = Form(""),
    source_email_id: Optional[str] = Form(None),
    notes: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("""
        INSERT INTO procedure_events
            (procedure_id, event_date, event_type, date_precision,
             description, outcome, source_email_id, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        proc_id,
        event_date or None,
        event_type,
        date_precision,
        description.strip() or None,
        outcome.strip() or None,
        int(source_email_id) if source_email_id else None,
        notes.strip() or None,
    ))
    conn.commit()
    return RedirectResponse(f"/procedures/{proc_id}", status_code=303)


# ── Delete event ─────────────────────────────────────────────────────────────

@router.post("/{proc_id}/events/{event_id}/delete", response_class=HTMLResponse)
async def delete_event(
    request: Request,
    proc_id: int,
    event_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("DELETE FROM procedure_events WHERE id = ? AND procedure_id = ?",
                 (event_id, proc_id))
    conn.commit()
    return RedirectResponse(f"/procedures/{proc_id}", status_code=303)
