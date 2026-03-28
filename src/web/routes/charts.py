"""
Dynamic chart PNG endpoints — serve matplotlib charts as image responses.

Note: src/reports/charts.py functions save to disk and return a Path.
This module calls those functions via a temporary directory and streams
the resulting PNG, closing the figure to free memory.
"""
import io
import sqlite3
import tempfile
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.web.deps import get_conn
from src.statistics.aggregator import (
    frequency_data,
    tone_trends,
    topic_evolution,
    response_times,
    top_aggressive_emails,
    daily_avg_by_year,
    manipulation_timeline,
    manipulation_pattern_frequency,
    manipulation_score_distribution,
    manipulation_patterns_over_time,
)
from src.reports.charts import (
    frequency_chart,
    tone_trend_chart,
    topic_evolution_chart,
    tone_distribution_pie,
    response_time_chart,
    daily_avg_chart,
    manipulation_timeline_chart,
    manipulation_pattern_freq_chart,
    manipulation_score_dist_chart,
    manipulation_patterns_time_chart,
)

router = APIRouter()


def _png_response(chart_path: Path) -> StreamingResponse:
    """Read a chart PNG from disk into memory and stream it."""
    data = chart_path.read_bytes()
    return StreamingResponse(io.BytesIO(data), media_type="image/png")


@router.get("/frequency")
async def chart_frequency(
    by: str = Query("quarter"),
    contact: Optional[str] = Query(None),
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = frequency_data(conn, by=by, contact_email=contact, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = frequency_chart(data, Path(tmp), title="Email Volume by Quarter")
        return _png_response(path)


@router.get("/daily-avg")
async def chart_daily_avg(
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Avg emails per day by year — grouped bars (sent/received) + ratio line."""
    data = daily_avg_by_year(conn, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = daily_avg_chart(data, Path(tmp))
        return _png_response(path)


@router.get("/tone-trends")
async def chart_tone_trends(
    by: str = Query("month"),
    direction: Optional[str] = Query(None),
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = tone_trends(conn, by=by, direction=direction, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = tone_trend_chart(data, Path(tmp))
        return _png_response(path)


@router.get("/topic-evolution")
async def chart_topic_evolution(
    by: str = Query("quarter"),
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = topic_evolution(conn, by=by, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = topic_evolution_chart(data, Path(tmp))
        return _png_response(path)


@router.get("/tone-pie")
async def chart_tone_pie(
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Tone distribution pie chart from top 200 aggressive emails."""
    emails = top_aggressive_emails(conn, limit=200, corpus=corpus)
    # Build tone_counts dict from result data
    tone_counts: dict = {}
    for e in emails:
        tone = e.get("tone") or "neutral"
        tone_counts[tone] = tone_counts.get(tone, 0) + 1
    if not tone_counts:
        tone_counts = {"neutral": 1}
    with tempfile.TemporaryDirectory() as tmp:
        path = tone_distribution_pie(tone_counts, Path(tmp))
        return _png_response(path)


@router.get("/response-time")
async def chart_response_time(
    by: str = Query("quarter"),
    contact: Optional[str] = Query(None),
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = response_times(conn, contact_email=contact, by=by, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = response_time_chart(data, Path(tmp))
        return _png_response(path)


@router.get("/manipulation-timeline")
async def chart_manipulation_timeline(
    by: str = Query("quarter"),
    direction: Optional[str] = Query(None),
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = manipulation_timeline(conn, by=by, direction=direction, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = manipulation_timeline_chart(data, Path(tmp))
        return _png_response(path)


@router.get("/manipulation-pattern-freq")
async def chart_manipulation_pattern_freq(
    direction: Optional[str] = Query(None),
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = manipulation_pattern_frequency(conn, direction=direction, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = manipulation_pattern_freq_chart(data, Path(tmp))
        return _png_response(path)


@router.get("/manipulation-score-dist")
async def chart_manipulation_score_dist(
    direction: Optional[str] = Query(None),
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = manipulation_score_distribution(conn, direction=direction, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = manipulation_score_dist_chart(data, Path(tmp))
        return _png_response(path)


@router.get("/manipulation-patterns-time")
async def chart_manipulation_patterns_time(
    by: str = Query("quarter"),
    direction: str = Query(""),
    corpus: str = Query("personal"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    data = manipulation_patterns_over_time(conn, by=by, direction=direction, corpus=corpus)
    with tempfile.TemporaryDirectory() as tmp:
        path = manipulation_patterns_time_chart(data, Path(tmp), direction=direction)
        return _png_response(path)
