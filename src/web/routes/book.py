"""Book-writing routes — narrative arc, chapters, quotes, pivotal moments."""
import json
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective
from src.statistics.aggregator import tone_trends, overview_stats

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


# ─────────────────────────── NARRATIVE ARC ───────────────────────────────

@router.get("/narrative", response_class=HTMLResponse)
async def narrative_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    overview = overview_stats(conn)
    tone = tone_trends(conn, by="month")

    # Simple story stats
    first = overview.get("first_date", "")
    last = overview.get("last_date", "")
    years = 0
    if first and last:
        try:
            from datetime import datetime
            d1 = datetime.strptime(first[:10], "%Y-%m-%d")
            d2 = datetime.strptime(last[:10], "%Y-%m-%d")
            years = round((d2 - d1).days / 365.25, 1)
        except Exception:
            pass

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "narrative",
        "overview": overview,
        "tone_data": tone,
        "years": years,
    }
    return templates.TemplateResponse("pages/narrative.html", ctx)


# ─────────────────────────── CHAPTERS ────────────────────────────────────

def _get_chapters(conn: sqlite3.Connection):
    try:
        rows = conn.execute(
            """SELECT id, title, position, date_from, date_to, summary, notes
               FROM chapters ORDER BY position ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


@router.get("/chapters", response_class=HTMLResponse)
async def chapters_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    chapters = _get_chapters(conn)
    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "chapters",
        "chapters": chapters,
    }
    return templates.TemplateResponse("pages/chapters.html", ctx)


@router.get("/chapters/{chapter_id}", response_class=HTMLResponse)
async def chapter_detail(
    request: Request,
    chapter_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Chapter detail (HTMX partial)."""
    try:
        row = conn.execute(
            "SELECT id, title, position, date_from, date_to, summary, notes FROM chapters WHERE id = ?",
            (chapter_id,),
        ).fetchone()
    except Exception:
        row = None

    if not row:
        return HTMLResponse('<div class="empty-state">Chapter not found.</div>', status_code=404)

    chapter = dict(row)

    # Emails in this date range
    emails = []
    if chapter.get("date_from") or chapter.get("date_to"):
        wheres = []
        params = []
        if chapter.get("date_from"):
            wheres.append("date >= ?")
            params.append(chapter["date_from"])
        if chapter.get("date_to"):
            wheres.append("date <= ?")
            params.append(chapter["date_to"] + " 23:59:59")
        where_clause = "WHERE " + " AND ".join(wheres) if wheres else ""
        rows = conn.execute(
            f"SELECT id, date, subject, direction FROM emails {where_clause} ORDER BY date LIMIT 50",
            params,
        ).fetchall()
        emails = [dict(r) for r in rows]

    ctx = {
        "request": request,
        "perspective": perspective,
        "chapter": chapter,
        "emails": emails,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/chapter_detail.html", ctx)
    return templates.TemplateResponse("pages/chapters.html", {
        **ctx,
        "chapters": _get_chapters(conn),
        "page": "chapters",
    })


@router.post("/chapters", response_class=HTMLResponse)
async def create_chapter(
    request: Request,
    title: str = Form(...),
    date_from: Optional[str] = Form(None),
    date_to: Optional[str] = Form(None),
    summary: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    try:
        # Get max position
        max_pos = conn.execute("SELECT COALESCE(MAX(position), 0) FROM chapters").fetchone()[0]
        conn.execute(
            """INSERT INTO chapters (title, position, date_from, date_to, summary, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, max_pos + 1, date_from or None, date_to or None, summary or None, notes or None),
        )
        chapters = _get_chapters(conn)
        return templates.TemplateResponse("partials/chapter_list.html", {
            "request": request,
            "perspective": perspective,
            "chapters": chapters,
        })
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">Error: {e}</div>', status_code=500)


@router.put("/chapters/{chapter_id}", response_class=HTMLResponse)
async def update_chapter(
    request: Request,
    chapter_id: int,
    title: Optional[str] = Form(None),
    date_from: Optional[str] = Form(None),
    date_to: Optional[str] = Form(None),
    summary: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    try:
        conn.execute(
            """UPDATE chapters SET title=?, date_from=?, date_to=?, summary=?, notes=?
               WHERE id=?""",
            (title, date_from or None, date_to or None, summary or None, notes or None, chapter_id),
        )
        row = conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
        chapter = dict(row) if row else {}
        return templates.TemplateResponse("partials/chapter_detail.html", {
            "request": request,
            "perspective": perspective,
            "chapter": chapter,
            "emails": [],
            "saved": True,
        })
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">Error: {e}</div>', status_code=500)


# ─────────────────────────── QUOTES ──────────────────────────────────────

def _get_quotes(conn: sqlite3.Connection):
    try:
        rows = conn.execute(
            """SELECT q.id, q.text, q.tags, q.email_id, q.created_at,
                      e.date AS email_date, e.subject AS email_subject
               FROM quotes q
               LEFT JOIN emails e ON e.id = q.email_id
               ORDER BY q.created_at DESC"""
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            try:
                item["tags"] = json.loads(item["tags"]) if item["tags"] else []
            except (json.JSONDecodeError, TypeError):
                item["tags"] = []
            result.append(item)
        return result
    except Exception:
        return []


@router.get("/quotes", response_class=HTMLResponse)
async def quotes_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    quotes = _get_quotes(conn)
    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "quotes",
        "quotes": quotes,
        "total": len(quotes),
    }
    return templates.TemplateResponse("pages/quotes.html", ctx)


@router.post("/quotes", response_class=HTMLResponse)
async def add_quote(
    request: Request,
    text: str = Form(...),
    email_id: Optional[int] = Form(None),
    tags: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    try:
        tags_json = json.dumps([t.strip() for t in tags.split(",") if t.strip()]) if tags else "[]"
        conn.execute(
            "INSERT INTO quotes (text, email_id, tags) VALUES (?, ?, ?)",
            (text, email_id or None, tags_json),
        )
        quotes = _get_quotes(conn)
        return templates.TemplateResponse("partials/quote_list.html", {
            "request": request,
            "perspective": perspective,
            "quotes": quotes,
        })
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">Error: {e}</div>', status_code=500)


@router.delete("/quotes/{quote_id}", response_class=HTMLResponse)
async def delete_quote(
    request: Request,
    quote_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        conn.execute("DELETE FROM quotes WHERE id = ?", (quote_id,))
        return HTMLResponse("")
    except Exception as e:
        return HTMLResponse(f'<span class="text-error">Error: {e}</span>', status_code=500)


# ─────────────────────────── PIVOTAL MOMENTS ─────────────────────────────

def _get_pivotal_moments(conn: sqlite3.Connection):
    try:
        rows = conn.execute(
            """SELECT pm.id, pm.email_id, pm.description, pm.significance,
                      pm.created_at, e.date AS email_date, e.subject AS email_subject,
                      e.direction
               FROM pivotal_moments pm
               LEFT JOIN emails e ON e.id = pm.email_id
               ORDER BY e.date ASC"""
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


@router.get("/pivotal-moments", response_class=HTMLResponse)
async def pivotal_moments_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    moments = _get_pivotal_moments(conn)
    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "pivotal",
        "moments": moments,
        "total": len(moments),
    }
    return templates.TemplateResponse("pages/pivotal_moments.html", ctx)


@router.post("/pivotal-moments", response_class=HTMLResponse)
async def add_pivotal_moment(
    request: Request,
    email_id: int = Form(...),
    description: Optional[str] = Form(None),
    significance: str = Form("medium"),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    try:
        conn.execute(
            "INSERT OR IGNORE INTO pivotal_moments (email_id, description, significance) VALUES (?, ?, ?)",
            (email_id, description or None, significance),
        )
        moments = _get_pivotal_moments(conn)
        return templates.TemplateResponse("partials/pivotal_moment_list.html", {
            "request": request,
            "perspective": perspective,
            "moments": moments,
        })
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">Error: {e}</div>', status_code=500)


@router.delete("/pivotal-moments/{moment_id}", response_class=HTMLResponse)
async def delete_pivotal_moment(
    request: Request,
    moment_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    try:
        conn.execute("DELETE FROM pivotal_moments WHERE id = ?", (moment_id,))
        return HTMLResponse("")
    except Exception as e:
        return HTMLResponse(f'<span class="text-error">Error: {e}</span>', status_code=500)
