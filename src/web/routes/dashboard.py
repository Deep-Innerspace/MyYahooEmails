"""Dashboard route — overview statistics."""
import sqlite3
from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective
from src.statistics.aggregator import overview_stats, top_aggressive_emails

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
    # Top aggressive + inline tone data are always personal-corpus-only:
    # lawyer emails are professional correspondence and their tone scores
    # are not meaningful for the personal relationship evidence analysis.
    top_aggressive = top_aggressive_emails(conn, limit=5, corpus="personal")

    return templates.TemplateResponse("pages/dashboard.html", {
        "request": request,
        "perspective": perspective,
        "page": "dashboard",
        "overview": overview,
        "top_aggressive": top_aggressive,
    })


@router.post("/set-workspace", response_class=HTMLResponse)
async def set_workspace(
    request: Request,
    workspace: str = Form(...),
):
    """Set workspace + derived perspective/corpus cookies, redirect to workspace default."""
    ws_config = {
        "correspondence":  ("legal", "all",      "/emails/"),
        "case-analysis":   ("legal", "personal", "/"),
        "legal-strategy":  ("legal", "legal",    "/procedures/"),
        "book":            ("book",  "personal", "/narrative"),
    }
    perspective, corpus, default_url = ws_config.get(workspace, ("legal", "personal", "/"))
    resp = RedirectResponse(url=default_url, status_code=303)
    resp.set_cookie("workspace", workspace, max_age=86400 * 30)
    resp.set_cookie("perspective", perspective, max_age=86400 * 30)
    resp.set_cookie("corpus", corpus, max_age=86400 * 30)
    return resp


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


@router.post("/set-corpus", response_class=HTMLResponse)
async def set_corpus(
    request: Request,
    corpus: str = Form(...),
    redirect_to: str = Form(default="/emails/"),
):
    """Set the corpus cookie and redirect to the calling page with ?corpus= in the URL.

    Injecting the corpus value into the URL ensures that routes which rely on
    the Query param (emails, timeline) pick it up immediately on the redirect,
    without needing a second page load to read the cookie.
    """
    from urllib.parse import urlencode, parse_qsl, urlparse, urlunparse
    valid = corpus if corpus in ("personal", "legal", "all") else "personal"

    # Re-build the redirect URL, setting/replacing the corpus query param
    parsed = urlparse(redirect_to)
    params = dict(parse_qsl(parsed.query))
    params["corpus"] = valid
    new_url = urlunparse(parsed._replace(query=urlencode(params)))

    resp = RedirectResponse(url=new_url, status_code=303)
    resp.set_cookie("corpus", valid, max_age=86400 * 30)
    return resp
