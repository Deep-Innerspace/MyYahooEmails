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


_SKIP_FOLDER_TOKENS = frozenset(["trash", "spam", "bulk", "draft", "deleted messages"])


def _find_email_imap_location(
    conn: sqlite3.Connection, email_id: int, known_folder: str
) -> tuple:
    """Search Yahoo IMAP for an email when the stored folder/UID is stale.

    Called when the stored (folder, uid) no longer yields content — typically
    because the user moved the email to a different Yahoo folder after the
    initial fetch, which invalidates the UID and assigns a new one.

    Search order (single IMAP connection to avoid repeated auth overhead):
      Pass 1 — DB-known folders (folders already seen in the legal corpus).
      Pass 2 — ALL remaining IMAP folders the server advertises, excluding
               system folders (Trash, Spam, Bulk, Draft, Deleted Messages).
               This handles folders created AFTER the initial fetch, such as
               a user-organised "vclavocat" folder.

    Within each folder two methods are tried:
      a) Message-ID header search (fast, exact match).
      b) SENTON date + FROM address (Yahoo strips Message-ID on move).

    Returns (folder, uid) of the first match, or (None, None).
    Updates attachments + emails tables with the corrected location on success
    so subsequent fetches are immediate.
    """
    from datetime import datetime
    from src.extraction.imap_client import imap_connection

    row = conn.execute(
        "SELECT message_id, date, from_address, subject_normalized FROM emails WHERE id = ?",
        (email_id,)
    ).fetchone()
    if not row:
        return None, None

    message_id  = (row["message_id"] or "").strip()
    from_addr   = (row["from_address"] or "").strip()
    email_date  = row["date"] or ""
    db_subject  = (row["subject_normalized"] or "").lower().strip()

    sent_on = None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            sent_on = datetime.strptime(email_date[:19], fmt).date()
            break
        except ValueError:
            continue

    # Build initial search order: stored folder first, then DB-known legal folders
    db_folders = [
        r[0] for r in conn.execute(
            "SELECT DISTINCT folder FROM emails WHERE corpus='legal' AND folder IS NOT NULL"
        ).fetchall()
    ]
    priority_folders = [known_folder] + [f for f in db_folders if f != known_folder]
    searched = set()

    def _pick_uid_by_subject(client, uids: list):
        """When SENTON+FROM returns multiple UIDs (same sender, same day), pick
        the one whose ENVELOPE subject matches the stored subject_normalized.
        Falls back to uids[0] if ENVELOPE fetch fails or nothing matches."""
        if len(uids) == 1:
            return uids[0]
        if not db_subject:
            return uids[0]
        try:
            resp = client.fetch(uids, [b"ENVELOPE"])
            for uid in uids:
                if uid not in resp:
                    continue
                env = resp[uid].get(b"ENVELOPE")
                if not env or not env.subject:
                    continue
                subj = env.subject
                if isinstance(subj, bytes):
                    import email.header as _hdr
                    subj = "".join(
                        part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
                        for part, enc in _hdr.decode_header(subj.decode("utf-8", errors="replace"))
                    )
                if db_subject in subj.lower():
                    return uid
        except Exception:
            pass
        return uids[0]   # couldn't disambiguate — best guess

    def _search_folder(client, folder: str):
        """Try Message-ID then SENTON+FROM in one folder. Returns uid or None."""
        if message_id:
            uids = client.search([b"HEADER", b"Message-ID", message_id.encode()])
            if uids:
                return uids[0]  # Message-ID is unique — no disambiguation needed
        if sent_on and from_addr:
            uids = client.search([b"SENTON", sent_on, b"FROM", from_addr.encode()])
            if uids:
                return _pick_uid_by_subject(client, uids)
        return None

    try:
        with imap_connection() as client:

            # ── Pass 1: DB-known folders ──────────────────────────────────────
            for folder in priority_folders:
                if folder in searched:
                    continue
                searched.add(folder)
                try:
                    client.select_folder(folder, readonly=True)
                    uid = _search_folder(client, folder)
                    if uid:
                        return folder, uid
                except Exception:
                    continue

            # ── Pass 2: all IMAP folders not yet searched ─────────────────────
            # Handles user-created folders that didn't exist at initial fetch time
            # (e.g. "vclavocat" folder created after emails were already imported).
            try:
                imap_folders = []
                for _flags, _delim, name in client.list_folders():
                    if isinstance(name, bytes):
                        name = name.decode("utf-8", errors="replace")
                    # Skip system / junk folders — unlikely to contain legal mail
                    if not any(t in name.lower() for t in _SKIP_FOLDER_TOKENS):
                        imap_folders.append(name)
            except Exception:
                imap_folders = []

            for folder in imap_folders:
                if folder in searched:
                    continue
                searched.add(folder)
                try:
                    client.select_folder(folder, readonly=True)
                    uid = _search_folder(client, folder)
                    if uid:
                        return folder, uid
                except Exception:
                    continue

    except Exception:
        pass

    return None, None


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
    raw_name = att["filename"] or "attachment"
    # Strip CR/LF and other control characters — an embedded CRLF would split the
    # HTTP header and produce a completely malformed response (header injection).
    import re as _re
    filename = _re.sub(r"[\x00-\x1f\x7f]", " ", raw_name).strip() or "attachment"
    # Escape any remaining double-quotes inside the filename value
    filename_safe = filename.replace('"', '\\"')

    return Response(
        content=content,
        media_type=ct,
        headers={"Content-Disposition": f'inline; filename="{filename_safe}"'},
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
        from src.extraction.imap_client import fetch_mime_part, imap_connection
        from src.config import attachment_download_dir

        raw = fetch_mime_part(att["folder"], att["imap_uid"], att["mime_section"])

        # UID may be stale if the email was moved to a different Yahoo folder.
        # Re-locate by Message-ID and retry once.
        if not raw:
            new_folder, new_uid = _find_email_imap_location(
                conn, att["email_id"], att["folder"]
            )
            if new_folder and new_uid:
                raw = fetch_mime_part(new_folder, new_uid, att["mime_section"])
                if raw:
                    # Persist corrected location so future fetches don't need to search
                    conn.execute(
                        "UPDATE attachments SET folder=?, imap_uid=? WHERE email_id=?",
                        (new_folder, new_uid, att["email_id"]),
                    )
                    conn.execute(
                        "UPDATE emails SET folder=?, uid=? WHERE id=?",
                        (new_folder, new_uid, att["email_id"]),
                    )
                    conn.commit()

        if not raw:
            return HTMLResponse(
                '<span class="att-error">'
                'Email not found in any Yahoo folder. '
                'It may have been moved to a folder that hasn\'t been fetched yet — '
                'run <code>python cli.py fetch emails --folder &lt;folder&gt; --corpus legal</code> '
                'to import it, then retry.'
                '</span>'
            )

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
        from src.extraction.imap_client import _is_transient_imap_error
        if _is_transient_imap_error(exc):
            # Yahoo's backend was busy even after retries — offer a manual retry button
            return HTMLResponse(
                f'<span class="att-error" style="display:flex;align-items:center;gap:8px">'
                f'⚠️ Yahoo server busy — please try again in a moment.'
                f'<button class="btn btn-secondary" style="font-size:11px;padding:2px 8px"'
                f' hx-post="/attachments/{attachment_id}/fetch"'
                f' hx-target="#att-{attachment_id}"'
                f' hx-swap="outerHTML">'
                f'↺ Retry</button>'
                f'</span>'
            )
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
