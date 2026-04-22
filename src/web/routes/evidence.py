"""Evidence tagging — mark emails as candidates for a procedure."""
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from src.config import report_output_dir
from src.web.bundle import build_bundle
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
    tagged_by: str = Form("client"),
    conn=Depends(get_conn),
):
    """Tag or re-tag an email as a candidate for a procedure."""
    if tagged_by not in ("client", "ai_suggested"):
        tagged_by = "client"
    ids: list[int] = []
    for raw in topic_ids:
        raw = raw.strip()
        if raw.isdigit():
            ids.append(int(raw))
    topic_ids_json = json.dumps(sorted(set(ids)))

    conn.execute(
        """INSERT INTO evidence_tags(email_id, procedure_id, rationale, topic_ids, tagged_by)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(email_id, procedure_id) DO UPDATE SET
               rationale = excluded.rationale,
               topic_ids = excluded.topic_ids,
               tagged_by = excluded.tagged_by,
               tagged_at = CURRENT_TIMESTAMP""",
        (email_id, procedure_id, rationale.strip(), topic_ids_json, tagged_by),
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


@router.post("/evidence/batch-tag")
async def batch_tag_emails(
    request: Request,
    email_ids: List[int] = Form(default_factory=list),
    procedure_id: int = Form(...),
    rationale: str = Form(""),
    topic_ids: List[str] = Form(default_factory=list),
    conn=Depends(get_conn),
):
    """Tag multiple emails as evidence for a procedure (UPSERT)."""
    ids: list[int] = [int(r) for r in topic_ids if r.strip().isdigit()]
    topic_ids_json = json.dumps(sorted(set(ids)))
    tagged = 0
    for email_id in email_ids:
        conn.execute(
            """INSERT INTO evidence_tags(email_id, procedure_id, rationale, topic_ids)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(email_id, procedure_id) DO UPDATE SET
                   rationale = CASE WHEN excluded.rationale != '' THEN excluded.rationale ELSE rationale END,
                   topic_ids = CASE WHEN excluded.topic_ids != '[]' THEN excluded.topic_ids ELSE topic_ids END,
                   tagged_at = CURRENT_TIMESTAMP""",
            (email_id, procedure_id, rationale.strip(), topic_ids_json),
        )
        tagged += 1
    return JSONResponse({"tagged": tagged, "procedure_id": procedure_id})


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


# ── Bundle export ─────────────────────────────────────────────────────────────

def _safe_filename(text: str, maxlen: int = 40) -> str:
    return re.sub(r"[^\w\-]", "_", text)[:maxlen]


@router.get("/evidence/export/{procedure_id}/pdf")
async def export_bundle_pdf(procedure_id: int, conn=Depends(get_conn)):
    """Generate a PDF dossier of all tagged evidence for a procedure."""
    from src.reports.builder import Report, ReportSection
    from src.reports.pdf_renderer import render_pdf

    bundle = build_bundle(conn, procedure_id)

    proc_slug = _safe_filename(bundle.procedure_name)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    bundles_dir = report_output_dir() / "bundles"
    bundles_dir.mkdir(parents=True, exist_ok=True)
    output_path = bundles_dir / f"evidence_{proc_slug}_{ts}.pdf"

    # Build Report structure
    meta_rows = [
        ["Type", bundle.procedure_type],
        ["Juridiction", bundle.jurisdiction or "—"],
        ["N° de dossier", bundle.case_number or "—"],
        ["Généré le", bundle.generated_at],
        ["Pièces", str(len(bundle.pieces))],
    ]
    if bundle.description:
        meta_rows.append(["Description", bundle.description])

    summary_section = ReportSection(
        title="Procédure",
        level=1,
        table={"headers": ["Champ", "Valeur"], "rows": meta_rows},
    )

    pieces_section = ReportSection(title="Pièces à conviction", level=1)
    for i, piece in enumerate(bundle.pieces, 1):
        direction_label = "Envoyé" if piece.direction == "sent" else "Reçu"
        topics_label = ", ".join(piece.topic_names) if piece.topic_names else "—"
        header = (
            f"Pièce {i} — {piece.date}  |  {direction_label}  |  {piece.from_name}  |  {topics_label}"
        )
        sub = ReportSection(title=header, level=2)
        sub.paragraphs.append(f"Objet : {piece.subject}")
        if piece.rationale:
            sub.paragraphs.append(f"Motif : {piece.rationale}")
        for hl in piece.highlights:
            note_suffix = f"  [{hl['note']}]" if hl.get("note") else ""
            sub.paragraphs.append(f"★ « {hl['text']} »{note_suffix}")
        sub.paragraphs.append(piece.delta_text)
        pieces_section.subsections.append(sub)

    report = Report(
        title=f"{bundle.procedure_name} — Dossier de Preuves",
        subtitle=f"{len(bundle.pieces)} pièce(s) sélectionnée(s)",
        date=bundle.generated_at,
        sections=[summary_section, pieces_section],
    )

    try:
        render_pdf(report, output_path)
    except OSError as e:
        return HTMLResponse(
            f'<p style="color:#dc2626;padding:1rem">PDF export requires WeasyPrint system libraries. '
            f'Install with: <code>brew install pango</code><br><small>{e}</small></p>',
            status_code=503,
        )
    filename = f"evidence_{proc_slug}_{ts}.pdf"
    return FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/evidence/export/{procedure_id}/zip")
async def export_bundle_zip(procedure_id: int, conn=Depends(get_conn)):
    """Generate a ZIP archive of all tagged evidence for a procedure."""
    bundle = build_bundle(conn, procedure_id)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # README index
        lines = [
            f"# {bundle.procedure_name} — Dossier de Preuves",
            f"",
            f"Type : {bundle.procedure_type}",
            f"Juridiction : {bundle.jurisdiction or '—'}",
            f"N° de dossier : {bundle.case_number or '—'}",
            f"Généré le : {bundle.generated_at}",
            f"",
        ]
        if bundle.description:
            lines += [f"Description : {bundle.description}", ""]
        lines.append(f"## Index ({len(bundle.pieces)} pièce(s))")
        lines.append("")
        for i, piece in enumerate(bundle.pieces, 1):
            lines.append(f"{i:02d}. [{piece.date}] {piece.subject} ({piece.from_name})")
        zf.writestr("README.md", "\n".join(lines))

        # One text file per piece
        for i, piece in enumerate(bundle.pieces, 1):
            subject_slug = _safe_filename(piece.subject, 30)
            fname = f"piece_{i:02d}_{piece.date}_{subject_slug}.txt"
            direction_label = "Envoyé" if piece.direction == "sent" else "Reçu"
            content_lines = [
                f"Pièce {i}",
                f"Date    : {piece.date}",
                f"Sens    : {direction_label}",
                f"De/À    : {piece.from_name}",
                f"Objet   : {piece.subject}",
            ]
            if piece.topic_names:
                content_lines.append(f"Thèmes  : {', '.join(piece.topic_names)}")
            if piece.rationale:
                content_lines += ["", f"Motif   : {piece.rationale}"]
            if piece.highlights:
                content_lines.append("")
                for hl in piece.highlights:
                    note_suffix = f"  [{hl['note']}]" if hl.get("note") else ""
                    content_lines.append(f"★ « {hl['text']} »{note_suffix}")
            content_lines += ["", "─" * 60, "", piece.delta_text]
            zf.writestr(fname, "\n".join(content_lines))

    buf.seek(0)
    proc_slug = _safe_filename(bundle.procedure_name)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"evidence_{proc_slug}_{ts}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── AI Suggester ──────────────────────────────────────────────────────────────

@router.post("/evidence/dismiss/{email_id}/{procedure_id}", response_class=HTMLResponse)
async def dismiss_suggestion(email_id: int, procedure_id: int, conn=Depends(get_conn)):
    """Persist a dismissed AI suggestion so it doesn't reappear on reload."""
    conn.execute(
        """INSERT INTO evidence_dismissed_suggestions(email_id, procedure_id)
           VALUES (?, ?)
           ON CONFLICT(email_id, procedure_id) DO NOTHING""",
        (email_id, procedure_id),
    )
    return HTMLResponse(f'<span id="ev-sug-{email_id}"></span>')


@router.post("/evidence/suggest/{procedure_id}", response_class=HTMLResponse)
async def suggest_evidence(request: Request, procedure_id: int, conn=Depends(get_conn)):
    """Score untagged emails against a procedure and return candidate cards."""

    # 1. Manipulation scores from most recent tone run (per email, best run wins)
    manip_rows = conn.execute("""
        SELECT ar.email_id,
               MAX(json_extract(ar.result_json, '$.manipulation_score')) AS manip
          FROM analysis_results ar
          JOIN analysis_runs run ON run.id = ar.run_id
         WHERE run.analysis_type = 'tone'
           AND run.status IN ('complete', 'partial')
           AND ar.email_id NOT IN (
               SELECT email_id FROM evidence_tags WHERE procedure_id = ?
           )
           AND ar.email_id NOT IN (
               SELECT email_id FROM evidence_dismissed_suggestions WHERE procedure_id = ?
           )
         GROUP BY ar.email_id
    """, (procedure_id, procedure_id)).fetchall()

    if not manip_rows:
        return HTMLResponse('<p class="text-muted text-sm" style="padding:var(--space-4)">No tone analysis data found. Run tone analysis first.</p>')

    manip_map = {r["email_id"]: float(r["manip"] or 0) for r in manip_rows}

    # 2. Contradiction counts per email
    contradiction_rows = conn.execute("""
        SELECT email_id, COUNT(*) AS cnt FROM (
            SELECT email_id_a AS email_id FROM contradictions
            UNION ALL
            SELECT email_id_b AS email_id FROM contradictions
        ) GROUP BY email_id
    """).fetchall()
    contradiction_map = {r["email_id"]: r["cnt"] for r in contradiction_rows}

    # 3. Topic IDs used by already-tagged emails in this procedure
    tagged_topic_rows = conn.execute(
        "SELECT topic_ids FROM evidence_tags WHERE procedure_id = ?",
        (procedure_id,),
    ).fetchall()
    proc_topic_ids: set = set()
    for tr in tagged_topic_rows:
        proc_topic_ids.update(json.loads(tr["topic_ids"] or "[]"))

    # Topic matches per email (only if procedure has tagged emails with topics)
    topic_match_map: dict = {}
    if proc_topic_ids:
        ph = ",".join("?" * len(proc_topic_ids))
        topic_rows = conn.execute(
            f"""SELECT et.email_id, COUNT(DISTINCT et.topic_id) AS matched
                  FROM email_topics et
                 WHERE et.topic_id IN ({ph})
                   AND et.email_id IN ({",".join("?" * len(manip_map))})
                 GROUP BY et.email_id""",
            list(proc_topic_ids) + list(manip_map.keys()),
        ).fetchall()
        denom = len(proc_topic_ids)
        for tr in topic_rows:
            topic_match_map[tr["email_id"]] = min(tr["matched"] / denom, 1.0)

    # 4. Score and filter
    candidates = []
    for email_id, manip in manip_map.items():
        contra_raw = min(contradiction_map.get(email_id, 0), 3) / 3.0
        topic_raw = topic_match_map.get(email_id, 0.0)
        if proc_topic_ids:
            score = 0.4 * manip + 0.3 * contra_raw + 0.3 * topic_raw
        else:
            score = 0.6 * manip + 0.4 * contra_raw
        if score < 0.15:
            continue
        reason_flags = []
        if manip >= 0.3:
            reason_flags.append("manipulation")
        if contra_raw > 0:
            reason_flags.append("contradiction")
        if topic_raw > 0:
            reason_flags.append("topic_match")
        candidates.append({
            "email_id": email_id,
            "score": round(score, 3),
            "reason_flags": reason_flags,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    candidates = candidates[:30]

    if not candidates:
        return HTMLResponse('<p class="text-muted text-sm" style="padding:var(--space-4)">No strong candidates found above threshold.</p>')

    # 5. Fetch email metadata for the candidates
    ids = [c["email_id"] for c in candidates]
    ph = ",".join("?" * len(ids))
    email_rows = conn.execute(
        f"""SELECT e.id, e.date, e.subject, e.direction, e.from_address, c.name AS from_name
              FROM emails e
              LEFT JOIN contacts c ON e.contact_id = c.id
             WHERE e.id IN ({ph})""",
        ids,
    ).fetchall()
    email_map = {r["id"]: dict(r) for r in email_rows}

    for c in candidates:
        em = email_map.get(c["email_id"], {})
        c["date"] = (em.get("date") or "")[:10]
        c["subject"] = em.get("subject") or "(no subject)"
        c["from_name"] = em.get("from_name") or em.get("from_address") or ""

    return templates.TemplateResponse("partials/evidence_suggestions.html", {
        "request": request,
        "candidates": candidates,
        "procedure_id": procedure_id,
    })
