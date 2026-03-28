"""Attachment serving and on-demand IMAP download (Phase 6c)."""
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from src.web.deps import get_conn

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

# Document category choices (used by Phase 6d classify endpoint too)
CATEGORIES = [
    ("invoice",                "🧾 Invoice"),
    ("court_filing",           "🏛️ Court Filing"),
    ("conclusion_draft",       "📝 Conclusions (draft)"),
    ("conclusion_final",       "📄 Conclusions (final)"),
    ("judgment",               "⚖️ Judgment"),
    ("ordonnance",             "📋 Ordonnance"),
    ("expert_report",          "🔬 Expert Report"),
    ("convocation",            "📬 Convocation"),
    ("pv_audience",            "🎙️ PV Audience"),
    ("official_email",         "📧 Official Email"),
    ("proof",                  "📸 Proof"),
    ("proof_adverse",          "🔍 Adversary Proof"),
    ("correspondence_adverse", "✉️ Adverse Party"),
    ("convention",             "🤝 Convention"),
    ("attestation",            "📜 Attestation"),
    ("mise_en_demeure",        "⚠️ Mise en Demeure"),
    ("requete",                "📑 Requête"),
    ("other",                  "📁 Other"),
]


def _get_attachment(conn: sqlite3.Connection, attachment_id: int):
    """Fetch attachment metadata + content BLOB for serving.

    The returned dict includes a synthetic `has_content` flag (1/0) so the
    attachment_item.html template can decide whether to show Download or Fetch
    without needing to inspect the raw BLOB bytes.
    """
    row = conn.execute("""
        SELECT a.id, a.email_id, a.filename, a.content_type, a.size_bytes,
               a.content, a.mime_section, a.imap_uid, a.folder,
               a.downloaded, a.download_path, a.category,
               e.corpus,
               CASE WHEN a.content IS NOT NULL THEN 1 ELSE 0 END AS has_content
        FROM attachments a
        JOIN emails e ON e.id = a.email_id
        WHERE a.id = ?
    """, (attachment_id,)).fetchone()
    return dict(row) if row else None


def _is_available(att: dict) -> bool:
    """Return True if attachment bytes are locally available."""
    if att.get("has_content") or att.get("content"):
        return True
    if att.get("download_path") and Path(att["download_path"]).exists():
        return True
    return False


@router.get("/{attachment_id}")
async def serve_attachment(
    attachment_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Serve attachment bytes — BLOB (personal) or filesystem (legal downloaded)."""
    att = _get_attachment(conn, attachment_id)
    if not att:
        return Response("Attachment not found", status_code=404)

    content: bytes | None = None

    if att["content"]:
        # Personal corpus: BLOB stored in DB
        raw = att["content"]
        content = bytes(raw) if isinstance(raw, memoryview) else raw
    elif att["download_path"] and Path(att["download_path"]).exists():
        # Legal corpus: previously fetched to filesystem
        content = Path(att["download_path"]).read_bytes()
    else:
        return Response(
            "Attachment not yet downloaded. Use the Fetch button to retrieve it.",
            status_code=404,
        )

    ct = att["content_type"] or "application/octet-stream"
    filename = att["filename"] or "attachment"

    return Response(
        content=content,
        media_type=ct,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/{attachment_id}/fetch", response_class=HTMLResponse)
async def fetch_attachment(
    request: Request,
    attachment_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """On-demand IMAP fetch for legal corpus attachments not yet downloaded.

    Returns an updated attachment_item.html partial for HTMX swap.
    """
    att = _get_attachment(conn, attachment_id)
    if not att:
        return HTMLResponse('<span class="att-error">Attachment not found</span>')

    # Already available — just re-render
    if _is_available(att):
        return templates.TemplateResponse("partials/attachment_item.html", {
            "request": request, "att": att, "categories": CATEGORIES,
        })

    # Need IMAP metadata to fetch
    if not att["imap_uid"] or not att["folder"] or not att["mime_section"]:
        return HTMLResponse(
            '<span class="att-error">Missing IMAP metadata — cannot fetch this attachment</span>'
        )

    try:
        from src.extraction.imap_client import fetch_mime_part
        from src.config import attachment_download_dir

        raw = fetch_mime_part(att["folder"], att["imap_uid"], att["mime_section"])
        if not raw:
            return HTMLResponse('<span class="att-error">IMAP returned empty content</span>')

        # Sanitize filename for filesystem
        safe_name = "".join(
            c for c in (att["filename"] or f"attachment_{attachment_id}")
            if c.isalnum() or c in "._- ()"
        ).strip() or f"attachment_{attachment_id}"

        dl_dir = Path(attachment_download_dir()) / str(att["email_id"])
        dl_dir.mkdir(parents=True, exist_ok=True)
        dl_path = dl_dir / safe_name
        dl_path.write_bytes(raw)

        conn.execute(
            "UPDATE attachments SET downloaded=1, download_path=? WHERE id=?",
            (str(dl_path), attachment_id),
        )
        conn.commit()

        att["downloaded"] = 1
        att["download_path"] = str(dl_path)
        att["has_content"] = 1   # now available for download

    except Exception as exc:
        return HTMLResponse(f'<span class="att-error">Fetch failed: {exc}</span>')

    return templates.TemplateResponse("partials/attachment_item.html", {
        "request": request, "att": att, "categories": CATEGORIES,
    })


@router.post("/{attachment_id}/classify", response_class=HTMLResponse)
async def classify_attachment(
    request: Request,
    attachment_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Set / update the document category for an attachment (Phase 6d)."""
    body = await request.form()
    category = body.get("category", "").strip() or None

    valid_keys = {k for k, _ in CATEGORIES}
    if category and category not in valid_keys:
        category = None

    conn.execute("UPDATE attachments SET category=? WHERE id=?", (category, attachment_id))
    conn.commit()

    att = _get_attachment(conn, attachment_id)
    if not att:
        return HTMLResponse("")

    return templates.TemplateResponse("partials/attachment_item.html", {
        "request": request, "att": att, "categories": CATEGORIES,
    })
