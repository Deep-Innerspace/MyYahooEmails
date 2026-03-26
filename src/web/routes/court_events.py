"""Court events route — list of court events (legal perspective)."""
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
    """Court events list."""
    try:
        rows = conn.execute(
            """SELECT id, event_date, event_type, jurisdiction, description, outcome
               FROM court_events ORDER BY event_date DESC"""
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
