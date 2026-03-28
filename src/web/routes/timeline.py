"""Timeline route — merged event timeline from email analysis + court events."""
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_corpus, get_perspective
from src.statistics.aggregator import merged_timeline

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


def _get_all_topics(conn: sqlite3.Connection):
    rows = conn.execute("SELECT id, name FROM topics ORDER BY name").fetchall()
    return [dict(r) for r in rows]


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def timeline_page(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    significance: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    topics: Optional[str] = Query(None),
    corpus: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
    corpus_cookie: str = Depends(get_corpus),
):
    # URL param overrides cookie; cookie overrides default
    active_corpus = corpus if corpus is not None else corpus_cookie
    sig_filter = significance if significance and significance != "all" else None
    events = _get_filtered_events(conn, date_from, date_to, sig_filter, source, topics, active_corpus)
    all_topics = _get_all_topics(conn)
    topic_list = [t.strip() for t in topics.split(",")] if topics else []

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "timeline",
        "events": events,
        "all_topics": all_topics,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "significance": significance or "all",
        "source": source or "all",
        "selected_topics": topic_list,
        "total_events": len(events),
        "corpus": active_corpus,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/timeline_list.html", ctx)

    return templates.TemplateResponse("pages/timeline.html", ctx)


@router.get("/events", response_class=HTMLResponse)
async def timeline_events_partial(
    request: Request,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    significance: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    topics: Optional[str] = Query(None),
    corpus: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
    corpus_cookie: str = Depends(get_corpus),
):
    """HTMX partial — filtered event list."""
    active_corpus = corpus if corpus is not None else corpus_cookie
    sig_filter = significance if significance and significance != "all" else None
    events = _get_filtered_events(conn, date_from, date_to, sig_filter, source, topics, active_corpus)
    topic_list = [t.strip() for t in topics.split(",")] if topics else []

    return templates.TemplateResponse("partials/timeline_list.html", {
        "request": request,
        "perspective": perspective,
        "events": events,
        "date_from": date_from or "",
        "date_to": date_to or "",
        "significance": significance or "all",
        "source": source or "all",
        "selected_topics": topic_list,
        "total_events": len(events),
        "corpus": active_corpus,
    })


def _get_filtered_events(conn, date_from, date_to, significance, source, topics, corpus=None):
    """Build filtered merged timeline."""
    events = merged_timeline(
        conn,
        since=date_from or None,
        until=date_to or None,
        significance=significance,
        corpus=corpus,
    )

    # Filter by source
    if source and source != "all":
        events = [e for e in events if e.get("source") == source]

    # Filter by topics (comma-separated topic names).
    # timeline_events imported via Excel have topic_id=NULL, so we resolve
    # the topic via the email's classification in email_topics instead.
    if topics:
        topic_list = [t.strip().lower() for t in topics.split(",") if t.strip()]
        if topic_list:
            placeholders = ",".join("?" * len(topic_list))
            email_ids_for_topics = set(
                r[0] for r in conn.execute(
                    f"""SELECT DISTINCT et.email_id
                          FROM email_topics et
                          JOIN topics t ON t.id = et.topic_id
                         WHERE LOWER(t.name) IN ({placeholders})""",
                    topic_list,
                ).fetchall()
            )
            events = [
                e for e in events
                if e.get("source") == "court"  # court events have no topic, always include
                or e.get("email_id") in email_ids_for_topics
            ]

    return events
