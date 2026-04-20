"""Evidence tagging — mark emails as candidates for a procedure."""
import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.web.deps import get_conn

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


def _fetch_procedures_for_email(conn, email_id: int):
    """All active procedures + which ones already tag this email."""
    procedures = conn.execute(
        """SELECT id, name, procedure_type, case_number, status
             FROM procedures
            WHERE status IN ('active', 'appealed')
         ORDER BY date_start DESC, id DESC"""
    ).fetchall()
    tagged = conn.execute(
        """SELECT procedure_id, topic_ids, rationale, highlights
             FROM evidence_tags
            WHERE email_id = ?""",
        (email_id,),
    ).fetchall()
    tag_map = {}
    for t in tagged:
        d = dict(t)
        d["highlights"] = json.loads(d.get("highlights") or "[]")
        tag_map[t["procedure_id"]] = d
    return procedures, tag_map


def _fetch_topics(conn):
    return conn.execute(
        "SELECT id, name FROM topics ORDER BY name"
    ).fetchall()


def _render_widget(request: Request, conn, email_id: int) -> HTMLResponse:
    procedures, tag_map = _fetch_procedures_for_email(conn, email_id)
    topics = _fetch_topics(conn)
    return templates.TemplateResponse("partials/evidence_tag_widget.html", {
        "request": request,
        "email_id": email_id,
        "procedures": procedures,
        "tag_map": tag_map,
        "topics": topics,
    })


@router.get("/evidence/widget/{email_id}", response_class=HTMLResponse)
async def evidence_widget(request: Request, email_id: int, conn=Depends(get_conn)):
    return _render_widget(request, conn, email_id)


@router.post("/evidence/tag/{email_id}/{procedure_id}", response_class=HTMLResponse)
async def tag_email(
    request: Request,
    email_id: int,
    procedure_id: int,
    rationale: str = Form(""),
    topic_ids: List[str] = Form(default_factory=list),
    conn=Depends(get_conn),
):
    """Tag or re-tag an email as a candidate for a procedure."""
    ids: list[int] = []
    for raw in topic_ids:
        raw = raw.strip()
        if raw.isdigit():
            ids.append(int(raw))
    topic_ids_json = json.dumps(sorted(set(ids)))

    conn.execute(
        """INSERT INTO evidence_tags(email_id, procedure_id, rationale, topic_ids)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(email_id, procedure_id) DO UPDATE SET
               rationale = excluded.rationale,
               topic_ids = excluded.topic_ids,
               tagged_at = CURRENT_TIMESTAMP""",
        (email_id, procedure_id, rationale.strip(), topic_ids_json),
    )
    return _render_widget(request, conn, email_id)


@router.post("/evidence/untag/{email_id}/{procedure_id}", response_class=HTMLResponse)
async def untag_email(
    request: Request, email_id: int, procedure_id: int, conn=Depends(get_conn)
):
    conn.execute(
        "DELETE FROM evidence_tags WHERE email_id = ? AND procedure_id = ?",
        (email_id, procedure_id),
    )
    return _render_widget(request, conn, email_id)


@router.post("/evidence/highlights/{email_id}/{procedure_id}", response_class=HTMLResponse)
async def add_highlight(
    request: Request,
    email_id: int,
    procedure_id: int,
    text: str = Form(""),
    note: str = Form(""),
    conn=Depends(get_conn),
):
    """Append a highlighted passage to an evidence tag."""
    text = text.strip()
    if not text:
        return _render_widget(request, conn, email_id)
    row = conn.execute(
        "SELECT highlights FROM evidence_tags WHERE email_id = ? AND procedure_id = ?",
        (email_id, procedure_id),
    ).fetchone()
    if not row:
        return _render_widget(request, conn, email_id)
    highlights = json.loads(row["highlights"] or "[]")
    highlights.append({"text": text, "note": note.strip()})
    conn.execute(
        "UPDATE evidence_tags SET highlights = ? WHERE email_id = ? AND procedure_id = ?",
        (json.dumps(highlights), email_id, procedure_id),
    )
    return _render_widget(request, conn, email_id)


@router.delete("/evidence/highlights/{email_id}/{procedure_id}/{index}", response_class=HTMLResponse)
async def remove_highlight(
    request: Request,
    email_id: int,
    procedure_id: int,
    index: int,
    conn=Depends(get_conn),
):
    """Remove a highlight by its position in the array."""
    row = conn.execute(
        "SELECT highlights FROM evidence_tags WHERE email_id = ? AND procedure_id = ?",
        (email_id, procedure_id),
    ).fetchone()
    if not row:
        return _render_widget(request, conn, email_id)
    highlights = json.loads(row["highlights"] or "[]")
    if 0 <= index < len(highlights):
        highlights.pop(index)
    conn.execute(
        "UPDATE evidence_tags SET highlights = ? WHERE email_id = ? AND procedure_id = ?",
        (json.dumps(highlights), email_id, procedure_id),
    )
    return _render_widget(request, conn, email_id)
