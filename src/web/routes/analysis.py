"""Analysis routes — tone trends, topic evolution, response times, contradictions, manipulation."""
import json
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective
from src.statistics.aggregator import (
    tone_trends,
    topic_evolution,
    system_topic_counts,
    response_times,
    contradiction_summary,
    top_aggressive_emails,
    contact_summary,
)

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


def _calc_tone_avgs(tone: list) -> dict:
    """Always compute averages for both directions independently."""
    received = [t for t in tone if t["direction"] == "received"]
    sent = [t for t in tone if t["direction"] == "sent"]
    return {
        "avg_aggression_received": round(sum(t["avg_aggression"] for t in received) / len(received), 3) if received else 0,
        "avg_manipulation_received": round(sum(t["avg_manipulation"] for t in received) / len(received), 3) if received else 0,
        "avg_aggression_sent": round(sum(t["avg_aggression"] for t in sent) / len(sent), 3) if sent else 0,
        "avg_manipulation_sent": round(sum(t["avg_manipulation"] for t in sent) / len(sent), 3) if sent else 0,
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def analysis_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Full analysis page — loads with tone tab active."""
    tone = tone_trends(conn, by="quarter", corpus="personal")
    avgs = _calc_tone_avgs(tone)
    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "analysis",
        "active_tab": "tone",
        "tone_data": tone,
        **avgs,
        "tone_by": "quarter",
        "tone_direction": "both",
        "chart_url": "/charts/tone-trends?by=quarter",
    }
    return templates.TemplateResponse("pages/analysis.html", ctx)


@router.get("/tone", response_class=HTMLResponse)
async def analysis_tone_partial(
    request: Request,
    direction: Optional[str] = Query(None),
    by: str = Query("month"),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """HTMX partial — tone trends."""
    dir_filter = direction if direction and direction != "both" else None
    # Always fetch all-direction data so averages are always computed for both sent+received
    all_tone = tone_trends(conn, by=by, direction=None, corpus="personal")
    # Filtered data drives chart only
    tone = tone_trends(conn, by=by, direction=dir_filter, corpus="personal") if dir_filter else all_tone
    avgs = _calc_tone_avgs(all_tone)

    return templates.TemplateResponse("partials/analysis_tone.html", {
        "request": request,
        "perspective": perspective,
        "tone_data": tone,
        "direction": direction or "both",
        "by": by,
        **avgs,
        "chart_url": f"/charts/tone-trends?by={by}" + (f"&direction={dir_filter}" if dir_filter else ""),
    })


@router.get("/topics", response_class=HTMLResponse)
async def analysis_topics_partial(
    request: Request,
    by: str = Query("quarter"),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """HTMX partial — topic evolution."""
    evolution = topic_evolution(conn, by=by, corpus="personal")

    # Aggregate per topic
    topic_totals: dict = {}
    for row in evolution:
        name = row["topic"]
        if name not in topic_totals:
            topic_totals[name] = {"name": name, "total": 0, "top_period": None, "top_count": 0}
        topic_totals[name]["total"] += row["email_count"]
        if row["email_count"] > topic_totals[name]["top_count"]:
            topic_totals[name]["top_count"] = row["email_count"]
            topic_totals[name]["top_period"] = row["period"]

    topic_list = sorted(topic_totals.values(), key=lambda x: x["total"], reverse=True)
    excluded = system_topic_counts(conn, corpus="personal")

    return templates.TemplateResponse("partials/analysis_topics.html", {
        "request": request,
        "perspective": perspective,
        "evolution_data": evolution,
        "topic_list": topic_list,
        "by": by,
        "chart_url": f"/charts/topic-evolution?by={by}",
        "excluded_trop_court": excluded["trop_court"],
        "excluded_non_classifiable": excluded["non_classifiable"],
    })


@router.get("/response-times", response_class=HTMLResponse)
async def analysis_response_times_partial(
    request: Request,
    by: str = Query("quarter"),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """HTMX partial — response times."""
    rt = response_times(conn, by=by, corpus="personal")
    return templates.TemplateResponse("partials/analysis_response_times.html", {
        "request": request,
        "perspective": perspective,
        "rt": rt,
        "by": by,
        "chart_url": f"/charts/response-time?by={by}",
    })


@router.get("/contradictions", response_class=HTMLResponse)
async def contradictions_page(
    request: Request,
    severity: Optional[str] = Query(None),
    scope: Optional[str] = Query(None),
    topic: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Contradiction browser page (legal-focused)."""
    sev_filter   = severity if severity and severity != "all" else None
    scope_filter = scope    if scope    and scope    != "all" else None
    topic_filter = topic    if topic    and topic    != "all" else None
    data = contradiction_summary(conn,
                                 severity=sev_filter,
                                 scope=scope_filter,
                                 topic=topic_filter)

    counts = {
        "total":          data.get("total", 0),
        "filtered_total": data.get("filtered_total", 0),
        **data.get("by_severity", {}),
    }

    ctx = {
        "request":            request,
        "perspective":        perspective,
        "page":               "contradictions",
        "contradiction_items": data.get("items", []),
        "counts":             counts,
        "severity":           severity or "all",
        "scope":              scope    or "all",
        "topic":              topic    or "all",
        "available_topics":   data.get("topics", []),
    }
    return templates.TemplateResponse("pages/contradictions.html", ctx)


@router.get("/manipulation", response_class=HTMLResponse)
async def manipulation_page(
    request: Request,
    min_score: float = Query(0.3),
    direction: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Manipulation patterns page (legal-focused)."""
    wheres = [
        "ru.analysis_type = 'manipulation'",
        "ru.status IN ('complete', 'partial')",
        "e.corpus = 'personal'",   # exclude lawyer emails — professional tone ≠ personal manipulation
    ]
    params: list = []

    if direction and direction != "all":
        wheres.append("e.direction = ?")
        params.append(direction)

    rows = conn.execute(
        f"""SELECT ar.email_id, ar.result_json, e.date, e.subject, e.direction,
                   e.from_address, e.from_name,
                   ru.provider_name, ru.model_id
            FROM analysis_results ar
            JOIN analysis_runs ru ON ru.id = ar.run_id
            JOIN emails e ON e.id = ar.email_id
            WHERE {' AND '.join(wheres)}
            ORDER BY e.date DESC""",
        params,
    ).fetchall()

    manipulation_results = []
    for row in rows:
        try:
            data = json.loads(row["result_json"]) if row["result_json"] else {}
        except (json.JSONDecodeError, TypeError):
            data = {}

        score = float(data.get("total_score", data.get("overall_score", data.get("manipulation_score", 0))) or 0)
        if score >= min_score:
            manipulation_results.append({
                "email_id": row["email_id"],
                "date": str(row["date"])[:10] if row["date"] else "",
                "subject": row["subject"],
                "direction": row["direction"],
                "from_address": row["from_address"],
                "from_name": row["from_name"],
                "score": round(score, 3),
                "patterns": data.get("patterns", []),
                "summary": data.get("summary", ""),
                "model": row["model_id"] or "",
                "provider": row["provider_name"] or "",
                "data": data,
            })

    # Sort by score desc
    manipulation_results.sort(key=lambda x: x["score"], reverse=True)

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "manipulation",
        "results": manipulation_results,
        "min_score": min_score,
        "direction": direction or "all",
        "total": len(manipulation_results),
    }
    return templates.TemplateResponse("pages/manipulation.html", ctx)
