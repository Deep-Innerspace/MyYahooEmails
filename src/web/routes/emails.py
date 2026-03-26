"""Email browser and detail routes."""
import json
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

PAGE_SIZE = 50


def _get_email_topics(conn, email_id: int):
    rows = conn.execute("""
        SELECT t.name, t.color, et.confidence
        FROM email_topics et JOIN topics t ON et.topic_id = t.id
        WHERE et.email_id = ?
        ORDER BY et.confidence DESC
    """, (email_id,)).fetchall()
    return [dict(r) for r in rows]


def _get_email_analysis(conn, email_id: int):
    rows = conn.execute("""
        SELECT ar.analysis_type, ar.provider_name, ar.model_id,
               ares.result_json, ares.created_at
        FROM analysis_results ares
        JOIN analysis_runs ar ON ares.run_id = ar.id
        WHERE ares.email_id = ?
        ORDER BY ar.analysis_type, ares.created_at DESC
    """, (email_id,)).fetchall()
    results = {}
    for row in rows:
        atype = row["analysis_type"]
        if atype not in results:
            try:
                parsed = json.loads(row["result_json"])
            except Exception:
                parsed = {}
            results[atype] = {
                "provider": row["provider_name"],
                "model": row["model_id"],
                "data": parsed,
                "created_at": row["created_at"],
            }
    return results


def _get_email_notes(conn, email_id: int):
    rows = conn.execute("""
        SELECT id, perspective, category, text, created_at
        FROM notes WHERE entity_type='email' AND entity_id=?
        ORDER BY perspective, created_at DESC
    """, (email_id,)).fetchall()
    return [dict(r) for r in rows]


def _get_thread_emails(conn, thread_id: int, current_email_id: int):
    if not thread_id:
        return []
    rows = conn.execute("""
        SELECT id, date, from_address, from_name, subject, direction, delta_text
        FROM emails WHERE thread_id=? ORDER BY date ASC
    """, (thread_id,)).fetchall()
    return [dict(r) for r in rows if r["id"] != current_email_id]


def _get_all_topics(conn):
    rows = conn.execute("SELECT id, name, color FROM topics ORDER BY name").fetchall()
    return [dict(r) for r in rows]


@router.get("/", response_class=HTMLResponse)
async def email_list(
    request: Request,
    q: Optional[str] = Query(None),
    topics: Optional[str] = Query(None),   # comma-separated topic names
    topic_mode: str = Query("or"),          # 'or' or 'and'
    direction: Optional[str] = Query(None),
    contact: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    bookmarked: bool = Query(False),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    topic_list = [t.strip() for t in topics.split(",")] if topics else []

    emails, total = _search_with_filters(
        conn, q=q, topics=topic_list, topic_mode=topic_mode,
        direction=direction, contact=contact,
        date_from=date_from, date_to=date_to,
        bookmarked=bookmarked, page=page,
    )

    all_topics = _get_all_topics(conn)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "emails",
        "emails": emails,
        "total": total,
        "total_pages": total_pages,
        "current_page": page,
        "query": q or "",
        "selected_topics": topic_list,
        "topic_mode": topic_mode,
        "direction": direction or "",
        "contact": contact or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
        "bookmarked": bookmarked,
        "all_topics": all_topics,
    }

    # HTMX partial request → return only the list partial
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/email_list.html", ctx)

    return templates.TemplateResponse("pages/emails.html", ctx)


@router.get("/search", response_class=HTMLResponse)
async def email_search_partial(
    request: Request,
    q: Optional[str] = Query(None),
    topics: Optional[str] = Query(None),
    topic_mode: str = Query("or"),
    direction: Optional[str] = Query(None),
    contact: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    bookmarked: bool = Query(False),
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """HTMX endpoint — returns only the email list partial."""
    topic_list = [t.strip() for t in topics.split(",")] if topics else []
    emails, total = _search_with_filters(
        conn, q=q, topics=topic_list, topic_mode=topic_mode,
        direction=direction, contact=contact,
        date_from=date_from, date_to=date_to,
        bookmarked=bookmarked, page=page,
    )
    all_topics = _get_all_topics(conn)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return templates.TemplateResponse("partials/email_list.html", {
        "request": request,
        "perspective": perspective,
        "emails": emails,
        "total": total,
        "total_pages": total_pages,
        "current_page": page,
        "query": q or "",
        "selected_topics": topic_list,
        "topic_mode": topic_mode,
        "direction": direction or "",
        "contact": contact or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
        "bookmarked": bookmarked,
        "all_topics": all_topics,
    })


@router.get("/{email_id}", response_class=HTMLResponse)
async def email_detail(
    request: Request,
    email_id: int,
    highlight: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    email = conn.execute("""
        SELECT e.*, c.name as contact_name
        FROM emails e LEFT JOIN contacts c ON e.contact_id = c.id
        WHERE e.id = ?
    """, (email_id,)).fetchone()

    if not email:
        return HTMLResponse("Email not found", status_code=404)

    email = dict(email)
    email["topics"] = _get_email_topics(conn, email_id)
    email["analysis"] = _get_email_analysis(conn, email_id)
    email["notes"] = _get_email_notes(conn, email_id)
    email["thread_emails"] = _get_thread_emails(conn, email["thread_id"], email_id)

    # Check bookmark
    bm = conn.execute("SELECT 1 FROM bookmarks WHERE email_id=?", (email_id,)).fetchone()
    email["bookmarked"] = bm is not None

    # Check pivotal moment
    pm = conn.execute("SELECT * FROM pivotal_moments WHERE email_id=?", (email_id,)).fetchone()
    email["pivotal_moment"] = dict(pm) if pm else None

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "emails",
        "email": email,
        "highlight_terms": highlight.split() if highlight else [],
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/email_detail.html", ctx)

    return templates.TemplateResponse("pages/email_detail.html", ctx)


@router.get("/{email_id}/thread", response_class=HTMLResponse)
async def email_thread(
    request: Request,
    email_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """HTMX — load thread context panel."""
    email = conn.execute("SELECT thread_id FROM emails WHERE id=?", (email_id,)).fetchone()
    if not email:
        return HTMLResponse("")
    thread_emails = _get_thread_emails(conn, email["thread_id"], email_id)
    return templates.TemplateResponse("partials/thread_panel.html", {
        "request": request,
        "thread_emails": thread_emails,
        "perspective": perspective,
    })


@router.post("/{email_id}/bookmark", response_class=HTMLResponse)
async def toggle_bookmark(
    request: Request,
    email_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Toggle bookmark state. Returns updated bookmark button."""
    existing = conn.execute("SELECT 1 FROM bookmarks WHERE email_id=?", (email_id,)).fetchone()
    if existing:
        conn.execute("DELETE FROM bookmarks WHERE email_id=?", (email_id,))
        bookmarked = False
    else:
        conn.execute("INSERT OR IGNORE INTO bookmarks (email_id) VALUES (?)", (email_id,))
        bookmarked = True
    return templates.TemplateResponse("partials/bookmark_btn.html", {
        "request": request,
        "email_id": email_id,
        "bookmarked": bookmarked,
    })


def _search_with_filters(conn, q, topics, topic_mode, direction, contact,
                          date_from, date_to, bookmarked, page):
    """Build and execute a filtered email search query."""
    conditions = []
    params = []

    if bookmarked:
        conditions.append("e.id IN (SELECT email_id FROM bookmarks)")

    if direction in ("sent", "received"):
        conditions.append("e.direction = ?")
        params.append(direction)

    if date_from:
        conditions.append("e.date >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("e.date <= ?")
        params.append(date_to + " 23:59:59")

    if contact:
        conditions.append("(e.from_address LIKE ? OR e.to_addresses LIKE ?)")
        params.extend([f"%{contact}%", f"%{contact}%"])

    if topics:
        if topic_mode == "and":
            for topic_name in topics:
                conditions.append("""e.id IN (
                    SELECT et.email_id FROM email_topics et
                    JOIN topics t ON et.topic_id=t.id WHERE t.name=?
                )""")
                params.append(topic_name)
        else:  # OR
            placeholders = ",".join("?" for _ in topics)
            conditions.append(f"""e.id IN (
                SELECT et.email_id FROM email_topics et
                JOIN topics t ON et.topic_id=t.id WHERE t.name IN ({placeholders})
            )""")
            params.extend(topics)

    # FTS search
    if q:
        fts_ids = conn.execute(
            "SELECT rowid FROM emails_fts WHERE emails_fts MATCH ? LIMIT 2000",
            (q,)
        ).fetchall()
        if not fts_ids:
            return [], 0
        id_list = ",".join(str(r[0]) for r in fts_ids)
        conditions.append(f"e.id IN ({id_list})")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count = conn.execute(f"SELECT COUNT(*) FROM emails e {where}", params).fetchone()[0]
    offset = (page - 1) * PAGE_SIZE

    rows = conn.execute(f"""
        SELECT e.id, e.date, e.from_address, e.from_name, e.subject,
               e.direction, e.language, e.has_attachments, e.delta_text,
               c.name as contact_name
        FROM emails e
        LEFT JOIN contacts c ON e.contact_id = c.id
        {where}
        ORDER BY e.date DESC
        LIMIT {PAGE_SIZE} OFFSET {offset}
    """, params).fetchall()

    emails = []
    for row in rows:
        e = dict(row)
        e["topics"] = _get_email_topics(conn, e["id"])
        emails.append(e)

    return emails, count
