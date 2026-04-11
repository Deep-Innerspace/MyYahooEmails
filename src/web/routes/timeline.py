"""Timeline route — unified event timeline: emails + court proceedings + invoices."""
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_corpus, get_perspective
from src.statistics.aggregator import (
    merged_timeline,
    dossier_timeline,
    court_event_window_aggression,
    all_procedure_event_correlations,
    pre_conclusion_behavior,
)

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

_WINDOW_DAYS = 14  # aggression correlation window


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
    view: Optional[str] = Query("stream"),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
    corpus_cookie: str = Depends(get_corpus),
):
    active_corpus = corpus if corpus is not None else corpus_cookie
    sig_filter = significance if significance and significance != "all" else None
    active_view = view if view in ("stream", "dossier") else "stream"

    if active_view == "dossier":
        procedures = dossier_timeline(conn, since=date_from or None, until=date_to or None)
        ctx = {
            "request": request,
            "perspective": perspective,
            "page": "timeline",
            "procedures": procedures,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "view": active_view,
            "total_events": sum(len(p["events"]) for p in procedures),
        }
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse("partials/timeline_dossier.html", ctx)
        return templates.TemplateResponse("pages/timeline.html", ctx)

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
        "view": active_view,
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
    view: Optional[str] = Query("stream"),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
    corpus_cookie: str = Depends(get_corpus),
):
    """HTMX partial — filtered event list or dossier view."""
    active_corpus = corpus if corpus is not None else corpus_cookie
    active_view = view if view in ("stream", "dossier") else "stream"

    if active_view == "dossier":
        procedures = dossier_timeline(conn, since=date_from or None, until=date_to or None)
        return templates.TemplateResponse("partials/timeline_dossier.html", {
            "request": request,
            "perspective": perspective,
            "procedures": procedures,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "view": active_view,
            "total_events": sum(len(p["events"]) for p in procedures),
        })

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
        "view": active_view,
    })


@router.get("/court-event/{event_date}/correlation", response_class=HTMLResponse)
async def court_event_correlation(
    request: Request,
    event_date: str,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """HTMX partial — aggression correlation panel for a court event date."""
    data = court_event_window_aggression(conn, event_date, _WINDOW_DAYS)
    return templates.TemplateResponse("partials/court_correlation_tooltip.html", {
        "request": request,
        "perspective": perspective,
        "event_date": event_date,
        "window_days": _WINDOW_DAYS,
        **data,
    })


@router.get("/correlations", response_class=HTMLResponse)
async def timeline_correlations(
    request: Request,
    date_from:   Optional[str] = Query(None),
    date_to:     Optional[str] = Query(None),
    window_days: int           = Query(_WINDOW_DAYS),
    event_type:  Optional[str] = Query("conclusions_received"),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Systematic aggression correlation — defaults to adverse conclusions as reference events."""
    window_days = max(1, min(window_days, 90))  # clamp 1–90
    # None sentinel: empty string from form means "all event types"
    etype_filter = event_type if event_type else None

    corr_data = all_procedure_event_correlations(
        conn, window_days=window_days,
        since=date_from or None, until=date_to or None,
        event_type=etype_filter,
    )
    pre_conc = pre_conclusion_behavior(
        conn, window_days=window_days,
        since=date_from or None, until=date_to or None,
    )

    # Build chart URL with date range so it zooms correctly
    chart_params = f"?window_days={window_days}"
    if date_from:
        chart_params += f"&date_from={date_from}"
    if date_to:
        chart_params += f"&date_to={date_to}"

    ctx = {
        "request":        request,
        "perspective":    perspective,
        "page":           "timeline",
        "view":           "correlations",
        "total_events":   corr_data["summary"]["total"],
        "date_from":      date_from or "",
        "date_to":        date_to or "",
        "window_days":    window_days,
        "event_type":     event_type or "",
        "chart_params":   chart_params,
        "corr_data":      corr_data,
        "pre_conclusion": pre_conc,
    }

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse("partials/timeline_correlations.html", ctx)
    return templates.TemplateResponse("pages/timeline.html", ctx)


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
                if e.get("source") in ("court", "invoice")  # non-email events always included
                or e.get("email_id") in email_ids_for_topics
            ]

    return events
