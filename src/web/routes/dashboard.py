"""Dashboard route — overview statistics."""
import sqlite3
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective
from src.statistics.aggregator import overview_stats, frequency_data, tone_trends, top_aggressive_emails

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    overview = overview_stats(conn)
    freq = frequency_data(conn, by="month")
    tone = tone_trends(conn, by="month")
    top_aggressive = top_aggressive_emails(conn, limit=5)

    return templates.TemplateResponse("pages/dashboard.html", {
        "request": request,
        "perspective": perspective,
        "page": "dashboard",
        "overview": overview,
        "freq_data": freq,
        "tone_data": tone,
        "top_aggressive": top_aggressive,
    })


@router.post("/set-perspective", response_class=HTMLResponse)
async def set_perspective(
    request: Request,
    response: Response,
    perspective: str = Form(...),
):
    """Set the perspective cookie and redirect back."""
    resp = RedirectResponse(url="/", status_code=303)
    resp.set_cookie("perspective", perspective, max_age=86400 * 30)
    return resp
