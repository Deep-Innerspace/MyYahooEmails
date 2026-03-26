"""Notes CRUD API — perspective-aware annotations on any entity."""
import sqlite3
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

LEGAL_CATEGORIES = ["evidence", "lawyer_review", "contradiction_note",
                    "court_relevance", "strategy", "general"]
BOOK_CATEGORIES  = ["narrative_context", "character_insight", "chapter_note",
                    "emotional_significance", "quote_context", "general"]


@router.post("/", response_class=HTMLResponse)
async def create_note(
    request: Request,
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    perspective: str = Form(...),
    category: str = Form(default="general"),
    text: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("""
        INSERT INTO notes (entity_type, entity_id, perspective, category, text)
        VALUES (?, ?, ?, ?, ?)
    """, (entity_type, entity_id, perspective, category, text))

    notes = conn.execute("""
        SELECT id, perspective, category, text, created_at
        FROM notes WHERE entity_type=? AND entity_id=?
        ORDER BY perspective, created_at DESC
    """, (entity_type, entity_id)).fetchall()

    return templates.TemplateResponse("partials/note_list.html", {
        "request": request,
        "notes": [dict(n) for n in notes],
        "entity_type": entity_type,
        "entity_id": entity_id,
        "active_perspective": perspective,
    })


@router.delete("/{note_id}", response_class=HTMLResponse)
async def delete_note(
    request: Request,
    note_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    note = conn.execute(
        "SELECT entity_type, entity_id, perspective FROM notes WHERE id=?", (note_id,)
    ).fetchone()
    if not note:
        return HTMLResponse("")
    entity_type, entity_id, perspective = (
        note["entity_type"], note["entity_id"], note["perspective"]
    )
    conn.execute("DELETE FROM notes WHERE id=?", (note_id,))

    notes = conn.execute("""
        SELECT id, perspective, category, text, created_at
        FROM notes WHERE entity_type=? AND entity_id=?
        ORDER BY perspective, created_at DESC
    """, (entity_type, entity_id)).fetchall()

    return templates.TemplateResponse("partials/note_list.html", {
        "request": request,
        "notes": [dict(n) for n in notes],
        "entity_type": entity_type,
        "entity_id": entity_id,
        "active_perspective": perspective,
    })
