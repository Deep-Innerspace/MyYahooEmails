"""Email browser and detail routes."""
import json
import sqlite3
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel

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


def _get_attachments(conn, email_id: int):
    rows = conn.execute("""
        SELECT id, email_id, filename, content_type, size_bytes,
               mime_section, imap_uid, folder, downloaded, download_path, category,
               CASE WHEN content IS NOT NULL THEN 1 ELSE 0 END AS has_content
        FROM attachments WHERE email_id = ? ORDER BY id
    """, (email_id,)).fetchall()
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
    unlinked: bool = Query(False),          # only emails with no matched contact
    corpus: str = Query("all"),             # 'all', 'personal', 'legal'
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    topic_list = [t.strip() for t in topics.split(",")] if topics else []

    emails, total = _search_with_filters(
        conn, q=q, topics=topic_list, topic_mode=topic_mode,
        direction=direction, contact=contact,
        date_from=date_from, date_to=date_to,
        bookmarked=bookmarked, unlinked=unlinked, page=page, corpus=corpus,
    )

    all_topics = _get_all_topics(conn)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    active_procedures = [dict(r) for r in conn.execute(
        "SELECT id, name FROM procedures ORDER BY date_start DESC, id DESC"
    ).fetchall()]

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
        "unlinked": unlinked,
        "corpus": corpus,
        "all_topics": all_topics,
        "active_procedures": active_procedures,
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
    unlinked: bool = Query(False),
    corpus: str = Query("all"),
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
        bookmarked=bookmarked, unlinked=unlinked, page=page, corpus=corpus,
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
        "unlinked": unlinked,
        "corpus": corpus,
        "all_topics": all_topics,
    })


@router.get("/{email_id}", response_class=HTMLResponse)
async def email_detail(
    request: Request,
    email_id: int,
    highlight: Optional[str] = Query(None),
    back: Optional[str] = Query(None),
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
    email["attachments"] = _get_attachments(conn, email_id)

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
        "back_url": back or "/emails/",
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


def _build_fts_prefix_query(q: str) -> str:
    """Convert plain search terms to FTS5 prefix queries.

    Each unquoted word gets a * suffix so 'diligence' matches 'diligences',
    'garde' matches 'gardes', etc.  Quoted phrases and boolean operators
    (AND, OR, NOT) are left untouched.

    Examples:
        'diligence'          → 'diligence*'
        'diligences'         → 'diligences*'   (same results as above)
        'garde enfants'      → 'garde* enfants*'
        '"pension alimentaire"' → '"pension alimentaire"'   (exact phrase)
        'garde AND pension'  → 'garde* AND pension*'
    """
    _BOOL_OPS = {'AND', 'OR', 'NOT'}
    tokens = q.split()
    result = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        # Preserve boolean operators
        if token.upper() in _BOOL_OPS:
            result.append(token.upper())
        # Preserve quoted phrases — accumulate until closing quote
        elif token.startswith('"'):
            phrase = [token]
            while not token.endswith('"') or token == '"':
                i += 1
                if i >= len(tokens):
                    break
                token = tokens[i]
                phrase.append(token)
            result.append(' '.join(phrase))
        else:
            # Plain word — add prefix wildcard (strip any trailing * first)
            result.append(token.rstrip('*') + '*')
        i += 1
    return ' '.join(result)


def _search_with_filters(conn, q, topics, topic_mode, direction, contact,
                          date_from, date_to, bookmarked, page, corpus=None,
                          unlinked=False):
    """Build and execute a filtered email search query."""
    conditions = []
    params = []

    if corpus and corpus != "all":
        conditions.append("e.corpus = ?")
        params.append(corpus)

    if unlinked:
        conditions.append("e.contact_id IS NULL")

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

    # FTS search — fall back to LIKE when query contains FTS5-special chars (e.g. email addresses)
    if q:
        _FTS5_SPECIAL = set('@.+-*/^()[]{}~"')
        use_like = any(c in _FTS5_SPECIAL for c in q)
        if use_like:
            like_q = f"%{q}%"
            conditions.append(
                "(e.from_address LIKE ? OR e.to_addresses LIKE ? OR e.subject LIKE ? OR e.body_text LIKE ?)"
            )
            params.extend([like_q, like_q, like_q, like_q])
        else:
            try:
                # Auto-prefix each word so "diligence" matches "diligences" etc.
                # Quoted phrases (e.g. "exact phrase") are left intact.
                # Boolean operators (AND OR NOT) are preserved.
                fts_q = _build_fts_prefix_query(q)
                fts_ids = conn.execute(
                    "SELECT rowid FROM emails_fts WHERE emails_fts MATCH ? LIMIT 2000",
                    (fts_q,)
                ).fetchall()
                if not fts_ids:
                    return [], 0
                id_list = ",".join(str(r[0]) for r in fts_ids)
                conditions.append(f"e.id IN ({id_list})")
            except Exception:
                # Last-resort fallback if FTS5 still rejects the query
                like_q = f"%{q}%"
                conditions.append(
                    "(e.from_address LIKE ? OR e.to_addresses LIKE ? OR e.subject LIKE ? OR e.body_text LIKE ?)"
                )
                params.extend([like_q, like_q, like_q, like_q])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count = conn.execute(f"SELECT COUNT(*) FROM emails e {where}", params).fetchone()[0]
    offset = (page - 1) * PAGE_SIZE

    rows = conn.execute(f"""
        SELECT e.id, e.date, e.from_address, e.from_name, e.subject,
               e.direction, e.language, e.has_attachments, e.delta_text,
               e.corpus, c.name as contact_name
        FROM emails e
        LEFT JOIN contacts c ON e.contact_id = c.id
        {where}
        ORDER BY e.date DESC
        LIMIT {PAGE_SIZE} OFFSET {offset}
    """, params).fetchall()

    emails = [dict(row) for row in rows]

    # Batch-fetch all topics for the returned page in a single query (avoids N+1).
    if emails:
        email_ids = [e["id"] for e in emails]
        placeholders = ",".join("?" * len(email_ids))
        topic_rows = conn.execute(
            f"""SELECT et.email_id, t.name, t.color, et.confidence
                FROM email_topics et JOIN topics t ON et.topic_id = t.id
                WHERE et.email_id IN ({placeholders})
                ORDER BY et.confidence DESC""",
            email_ids,
        ).fetchall()
        topics_by_id: dict = {}
        for tr in topic_rows:
            topics_by_id.setdefault(tr["email_id"], []).append(
                {"name": tr["name"], "color": tr["color"], "confidence": tr["confidence"]}
            )
        for e in emails:
            e["topics"] = topics_by_id.get(e["id"], [])

        # Batch: how many procedures each email is tagged against
        evidence_rows = conn.execute(
            f"""SELECT email_id, COUNT(*) AS n
                  FROM evidence_tags
                 WHERE email_id IN ({placeholders})
              GROUP BY email_id""",
            email_ids,
        ).fetchall()
        evidence_by_id = {r["email_id"]: r["n"] for r in evidence_rows}
        for e in emails:
            e["evidence_count"] = evidence_by_id.get(e["id"], 0)
    else:
        for e in emails:
            e["topics"] = []
            e["evidence_count"] = 0

    return emails, count


# ── Bulk action models ───────────────────────────────────────────────────────

class BulkIdsRequest(BaseModel):
    ids: List[int]


class BulkReclassifyRequest(BaseModel):
    ids: List[int]
    corpus: str


# ── Bulk endpoints ────────────────────────────────────────────────────────────

@router.post("/bulk-delete", response_class=HTMLResponse)
async def bulk_delete_emails(
    body: BulkIdsRequest,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Delete multiple emails and all their related data from the local DB."""
    for email_id in body.ids:
        conn.execute("DELETE FROM timeline_events WHERE email_id = ?", (email_id,))
        conn.execute("DELETE FROM email_topics WHERE email_id = ?", (email_id,))
        conn.execute("DELETE FROM attachments WHERE email_id = ?", (email_id,))
        conn.execute("DELETE FROM notes WHERE entity_type='email' AND entity_id = ?", (email_id,))
        conn.execute("DELETE FROM bookmarks WHERE email_id = ?", (email_id,))
        conn.execute("DELETE FROM analysis_results WHERE email_id = ?", (email_id,))
        # contradictions: NOT NULL FKs — delete the whole pair
        conn.execute("DELETE FROM contradictions WHERE email_id_a = ? OR email_id_b = ?", (email_id, email_id))
        # nullable FKs — NULL out rather than delete the parent row
        conn.execute("UPDATE procedure_events SET source_email_id = NULL WHERE source_email_id = ?", (email_id,))
        conn.execute("UPDATE lawyer_invoices SET email_id = NULL WHERE email_id = ?", (email_id,))
        conn.execute("UPDATE procedure_documents SET source_email_id = NULL WHERE source_email_id = ?", (email_id,))
        conn.execute("DELETE FROM emails WHERE id = ?", (email_id,))
    conn.commit()
    return HTMLResponse("")


@router.post("/bulk-reclassify", response_class=HTMLResponse)
async def bulk_reclassify_emails(
    body: BulkReclassifyRequest,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Set corpus on multiple emails at once."""
    valid = body.corpus if body.corpus in ("personal", "legal") else "personal"
    for email_id in body.ids:
        conn.execute("UPDATE emails SET corpus = ? WHERE id = ?", (valid, email_id))
    conn.commit()
    return HTMLResponse("")


# ── Per-email management (6g.1) ───────────────────────────────────────────────

@router.post("/{email_id}/reclassify", response_class=HTMLResponse)
async def reclassify_email(
    request: Request,
    email_id: int,
    corpus: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Toggle an email's corpus tag (personal ↔ legal).
    Returns an updated email row partial for HTMX swap.
    """
    valid = corpus if corpus in ("personal", "legal") else "personal"
    conn.execute("UPDATE emails SET corpus = ? WHERE id = ?", (valid, email_id))
    conn.commit()

    row = conn.execute("""
        SELECT e.id, e.date, e.from_address, e.from_name, e.subject,
               e.direction, e.language, e.has_attachments, e.delta_text,
               e.corpus, c.name as contact_name
        FROM emails e LEFT JOIN contacts c ON e.contact_id = c.id
        WHERE e.id = ?
    """, (email_id,)).fetchone()

    if not row:
        return HTMLResponse("")

    e = dict(row)
    e["topics"] = _get_email_topics(conn, email_id)

    return templates.TemplateResponse("partials/email_row.html", {
        "request": request,
        "perspective": perspective,
        "e": e,
        "query": "",
    })


@router.post("/{email_id}/delete", response_class=HTMLResponse)
async def delete_email(
    request: Request,
    email_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Delete an email and all its related data from the local DB.

    This removes data from the local SQLite database only — it never touches
    the original email on Yahoo IMAP (which is always read-only).
    """
    # Cascade: remove analysis results, topics, timeline events, attachments, notes
    conn.execute("DELETE FROM timeline_events WHERE email_id = ?", (email_id,))
    conn.execute("DELETE FROM email_topics WHERE email_id = ?", (email_id,))
    conn.execute("DELETE FROM attachments WHERE email_id = ?", (email_id,))
    conn.execute("DELETE FROM notes WHERE entity_type='email' AND entity_id = ?", (email_id,))
    conn.execute("DELETE FROM bookmarks WHERE email_id = ?", (email_id,))
    conn.execute("DELETE FROM analysis_results WHERE email_id = ?", (email_id,))
    # contradictions: NOT NULL FKs — delete the whole pair
    conn.execute("DELETE FROM contradictions WHERE email_id_a = ? OR email_id_b = ?", (email_id, email_id))
    # nullable FKs — NULL out rather than delete the parent row
    conn.execute("UPDATE procedure_events SET source_email_id = NULL WHERE source_email_id = ?", (email_id,))
    conn.execute("UPDATE lawyer_invoices SET email_id = NULL WHERE email_id = ?", (email_id,))
    conn.execute("UPDATE procedure_documents SET source_email_id = NULL WHERE source_email_id = ?", (email_id,))
    conn.execute("DELETE FROM emails WHERE id = ?", (email_id,))
    conn.commit()

    # Return empty string — HTMX will swap the row out
    return HTMLResponse("")
