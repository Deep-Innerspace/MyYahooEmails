"""Settings route — analysis runs, coverage stats, system overview."""
import sqlite3
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from fastapi import Form

from src.web.deps import get_conn, get_perspective
from src.statistics.aggregator import overview_stats, analysis_methodology
from src.web.settings_store import get_bool, set_bool

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Settings page — shows analysis runs, coverage stats, system overview."""
    overview = overview_stats(conn)
    runs = _get_all_runs(conn)
    methodology = analysis_methodology(conn)

    # Coverage breakdown — denominator is personal_count because
    # classify/tone/manipulation/timeline counts are now personal-corpus-only.
    # Lawyer emails (legal corpus) are excluded from analysis coverage.
    personal_total = overview.get("personal_count", 1) or 1
    coverage = {
        "classify": {
            "count": overview.get("classify_count", 0),
            "pct": round(overview.get("classify_count", 0) / personal_total * 100, 1),
            "label": "Classification",
        },
        "tone": {
            "count": overview.get("tone_count", 0),
            "pct": round(overview.get("tone_count", 0) / personal_total * 100, 1),
            "label": "Tone Analysis",
        },
        "timeline": {
            "count": overview.get("timeline_count", 0),
            "pct": round(overview.get("timeline_count", 0) / personal_total * 100, 1),
            "label": "Timeline Events",
        },
        "manipulation": {
            "count": overview.get("manipulation_count", 0),
            "pct": round(overview.get("manipulation_count", 0) / personal_total * 100, 1),
            "label": "Manipulation",
        },
    }

    prefs = {
        "auto_sync_on_open": get_bool(conn, "auto_sync_on_open", False),
        "notify_new_emails": get_bool(conn, "notify_new_emails", True),
    }

    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "settings",
        "overview": overview,
        "runs": runs,
        "methodology": methodology,
        "coverage": coverage,
        "prefs": prefs,
    }
    return templates.TemplateResponse("pages/settings.html", ctx)


@router.post("/prefs", response_class=HTMLResponse)
async def save_prefs(
    request: Request,
    auto_sync_on_open: str = Form(""),
    notify_new_emails: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Persist user preference toggles (HTMX form submit)."""
    set_bool(conn, "auto_sync_on_open", auto_sync_on_open == "on")
    set_bool(conn, "notify_new_emails", notify_new_emails == "on")
    conn.commit()
    return HTMLResponse(
        '<span class="pref-saved" role="status">Preferences saved.</span>'
    )


@router.post("/runs/{run_id}/delete", response_class=HTMLResponse)
async def delete_run(
    request: Request,
    run_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Delete an analysis run and all its results (HTMX)."""
    try:
        conn.execute("DELETE FROM analysis_results WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM analysis_runs WHERE id = ?", (run_id,))
        return HTMLResponse(f'<tr id="run-row-{run_id}" style="display:none"></tr>')
    except Exception as e:
        return HTMLResponse(
            f'<tr><td colspan="7" class="text-error">Error deleting run: {e}</td></tr>',
            status_code=500,
        )


def _get_all_runs(conn: sqlite3.Connection):
    """Fetch all analysis runs with email counts."""
    rows = conn.execute(
        """SELECT r.id, r.analysis_type, r.provider_name, r.model_id,
                  r.status, r.run_date, r.prompt_version,
                  COUNT(ar.id) AS result_count
           FROM analysis_runs r
           LEFT JOIN analysis_results ar ON ar.run_id = r.id
           GROUP BY r.id
           ORDER BY r.run_date DESC"""
    ).fetchall()
    return [dict(r) for r in rows]
