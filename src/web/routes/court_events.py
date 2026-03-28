"""Court events route — list of procedure events (legal perspective, Phase 6)."""
import sqlite3
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def court_events_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Procedure events list (replaces court_events after Phase 6a migration)."""
    try:
        rows = conn.execute(
            """SELECT pe.id, pe.event_date, pe.event_type, pe.description, pe.outcome,
                      pe.date_precision, p.name AS procedure_name, p.jurisdiction
               FROM procedure_events pe
               LEFT JOIN procedures p ON p.id = pe.procedure_id
               ORDER BY pe.event_date DESC"""
        ).fetchall()
        events = [dict(r) for r in rows]
    except Exception:
        events = []

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "court",
        "events": events,
        "total": len(events),
    }
    return templates.TemplateResponse("pages/court_events.html", ctx)
