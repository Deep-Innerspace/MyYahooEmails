"""Reports routes — report hub, generation, and download."""
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates

from src.web.deps import get_conn, get_perspective
from src.config import report_output_dir

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()


def _get_generated_reports(conn: sqlite3.Connection):
    """Fetch list of previously generated reports from DB."""
    try:
        rows = conn.execute(
            """SELECT id, report_type, format, output_path, generated_at, perspective
               FROM generated_reports
               ORDER BY generated_at DESC LIMIT 50"""
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Reports hub page."""
    generated = _get_generated_reports(conn)
    ctx = {
        "request": request,
        "perspective": perspective,
        "page": "reports",
        "generated_reports": generated,
    }
    return templates.TemplateResponse("pages/reports.html", ctx)


@router.post("/generate", response_class=HTMLResponse)
async def generate_report(
    request: Request,
    report_type: str = Form(...),
    format: str = Form("docx"),
    perspective: str = Form("legal"),
    include_legal_notes: bool = Form(False),
    include_book_notes: bool = Form(False),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Generate a report and return HTMX response with download link."""
    try:
        from src.reports.builder import (
            build_timeline_report,
            build_tone_report,
            build_contradiction_report,
            build_full_report,
        )

        builders = {
            "timeline": build_timeline_report,
            "tone": build_tone_report,
            "contradictions": build_contradiction_report,
            "full": build_full_report,
        }

        if report_type not in builders:
            return HTMLResponse(
                f'<div class="alert alert-error">Unknown report type: {report_type}</div>',
                status_code=400,
            )

        report = builders[report_type](conn)

        output_dir = report_output_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{report_type}_{timestamp}.{format}"
        output_path = output_dir / filename

        if format == "pdf":
            try:
                from src.reports.pdf_renderer import render_pdf
                render_pdf(report, output_path)
            except ImportError:
                return HTMLResponse(
                    '<div class="alert alert-error">PDF generation requires pango. '
                    'Install with: <code>brew install pango</code></div>'
                )
        else:
            from src.reports.docx_renderer import render_docx
            render_docx(report, output_path)

        # Store in generated_reports table
        try:
            conn.execute(
                """INSERT INTO generated_reports
                   (report_type, format, output_path, perspective, generated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))""",
                (report_type, format, str(output_path), perspective),
            )
            report_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        except Exception:
            report_id = None

        download_url = f"/reports/download/{filename}"

        return templates.TemplateResponse("partials/report_generated.html", {
            "request": request,
            "perspective": perspective,
            "report_type": report_type,
            "format": format,
            "filename": filename,
            "download_url": download_url,
            "output_path": str(output_path),
        })

    except Exception as e:
        tb = traceback.format_exc()
        return HTMLResponse(
            f'<div class="alert alert-error">'
            f'<strong>Error generating report:</strong> {str(e)}'
            f'<pre style="font-size:0.75rem;margin-top:8px;white-space:pre-wrap">{tb}</pre>'
            f'</div>'
        )


@router.get("/download/{filename}")
async def download_report(filename: str):
    """Serve a generated report file for download."""
    output_dir = report_output_dir()
    file_path = output_dir / filename

    if not file_path.exists():
        return HTMLResponse("File not found", status_code=404)

    # Validate the file is within the output directory (security)
    try:
        file_path.resolve().relative_to(output_dir.resolve())
    except ValueError:
        return HTMLResponse("Invalid path", status_code=400)

    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if filename.endswith(".docx")
        else "application/pdf"
    )
    return FileResponse(path=str(file_path), filename=filename, media_type=media_type)
