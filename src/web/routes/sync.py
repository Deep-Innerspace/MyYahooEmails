"""Sync routes — IMAP fetch trigger (personal & legal) with HTMX polling."""
import json
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.web.deps import get_conn
from src.web.job_manager import create_job, get_job, update_job

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

_SKIP_FOLDERS = {
    "Trash", "Draft", "Drafts", "Bulk", "Bulk Mail",
    "Spam", "Deleted Messages", "Deleted", "Junk",
}
_DEFAULT_FOLDERS = ["INBOX", "Sent", "Sent Messages"]


# ── Background sync worker ─────────────────────────────────────────────────────

def _sync_worker(job_id: str, corpus: str) -> None:
    """Background thread: IMAP fetch since last sync for the given corpus."""
    update_job(job_id, status="running", started=datetime.now().isoformat())
    try:
        from src.extraction.imap_client import (
            imap_connection, search_uids_by_contact, fetch_raw_emails,
        )
        from src.extraction.parser import parse_raw_email
        from src.extraction.threader import batch_store_emails
        from src.storage.database import get_db, get_last_uid, set_last_uid
        from src.config import yahoo_email

        my_email = yahoo_email()

        with get_db() as conn:
            if corpus == "personal":
                contacts = conn.execute(
                    "SELECT id, name, email, aliases FROM contacts"
                    " WHERE role NOT IN ('my_lawyer','her_lawyer','opposing_counsel','notaire')"
                    "   AND role != 'me'"
                ).fetchall()
            else:
                contacts = conn.execute(
                    "SELECT id, name, email, aliases FROM contacts"
                    " WHERE role IN ('my_lawyer','her_lawyer','opposing_counsel','notaire')"
                ).fetchall()
            all_combos = conn.execute(
                "SELECT DISTINCT folder, contact_email FROM fetch_state"
            ).fetchall()

        # Build addr → set-of-folders lookup from existing fetch state
        combo_map: Dict[str, set] = {}
        for row in all_combos:
            combo_map.setdefault(row["contact_email"], set()).add(row["folder"])

        total_stored = 0
        total_skipped = 0

        update_job(job_id, message="Connecting to Yahoo IMAP…")

        with imap_connection() as client:
            # List all IMAP folders once for existence checks
            try:
                imap_folder_names = {f[2] for f in client.list_folders()}
            except Exception:
                imap_folder_names = set()

            for idx, contact_row in enumerate(contacts, 1):
                contact_email = contact_row["email"]
                aliases: List[str] = json.loads(contact_row["aliases"] or "[]")
                all_addresses = [contact_email] + aliases

                # Folders previously synced for any address of this contact
                folders_for_contact: set = set()
                for addr in all_addresses:
                    folders_for_contact.update(combo_map.get(addr, set()))

                # Always check default folders if they exist on IMAP
                for df in _DEFAULT_FOLDERS:
                    if df in imap_folder_names:
                        folders_for_contact.add(df)

                folders_for_contact -= _SKIP_FOLDERS

                for folder in sorted(folders_for_contact):
                    uid_set: set = set()
                    addr_max_uid: Dict[str, int] = {}

                    for addr in all_addresses:
                        last_uid = get_last_uid(folder, addr)
                        try:
                            uids = search_uids_by_contact(
                                client, folder, addr, min_uid=last_uid
                            )
                        except Exception:
                            continue
                        uid_set.update(uids)
                        if uids:
                            addr_max_uid[addr] = max(uids)

                    if not uid_set:
                        continue

                    download_content = corpus != "legal"
                    all_parsed = []

                    for uid, raw, _ in fetch_raw_emails(client, sorted(uid_set)):
                        parsed = parse_raw_email(
                            uid, raw, folder, my_email,
                            download_content=download_content,
                        )
                        if parsed:
                            all_parsed.append(parsed)

                    if all_parsed:
                        result = batch_store_emails(all_parsed, folder, corpus)
                        total_stored += result.get("stored", 0)
                        total_skipped += result.get("skipped_duplicate", 0)

                    for addr, max_uid in addr_max_uid.items():
                        set_last_uid(folder, max_uid, addr)

                update_job(
                    job_id,
                    message=(
                        f"({idx}/{len(contacts)}) {contact_row['name']} — "
                        f"{total_stored} new so far"
                    ),
                )

        update_job(
            job_id,
            status="done",
            total_stored=total_stored,
            total_skipped=total_skipped,
            finished=datetime.now().isoformat(),
            message=f"Sync complete — {total_stored} new email(s) stored.",
        )

    except Exception as exc:
        update_job(
            job_id,
            status="error",
            error=str(exc),
            detail=traceback.format_exc(),
            finished=datetime.now().isoformat(),
            message=f"Sync failed: {exc}",
        )


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _recent_emails(conn, corpus: str, limit: int = 10):
    return conn.execute(
        """SELECT e.id, e.date, e.from_address, e.subject, e.direction,
                  COALESCE(c.name, e.from_address) AS contact_name
           FROM emails e
           LEFT JOIN contacts c ON e.contact_id = c.id
           WHERE e.corpus = ?
           ORDER BY e.date DESC
           LIMIT ?""",
        (corpus, limit),
    ).fetchall()


def _last_sync(conn) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(last_sync) AS ts FROM fetch_state"
    ).fetchone()
    return row["ts"] if row else None


def _corpus_count(conn, corpus: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM emails WHERE corpus=?", (corpus,)
    ).fetchone()
    return row["n"] if row else 0


# ── Page routes ────────────────────────────────────────────────────────────────

@router.get("/sync/personal", response_class=HTMLResponse)
async def sync_personal_page(request: Request, conn=Depends(get_conn)):
    return templates.TemplateResponse("pages/sync.html", {
        "request": request,
        "page": "sync_personal",
        "corpus": "personal",
        "corpus_label": "Personal",
        "recent_emails": _recent_emails(conn, "personal"),
        "last_sync": _last_sync(conn),
        "total_emails": _corpus_count(conn, "personal"),
    })


@router.get("/sync/legal", response_class=HTMLResponse)
async def sync_legal_page(request: Request, conn=Depends(get_conn)):
    return templates.TemplateResponse("pages/sync.html", {
        "request": request,
        "page": "sync_legal",
        "corpus": "legal",
        "corpus_label": "Legal",
        "recent_emails": _recent_emails(conn, "legal"),
        "last_sync": _last_sync(conn),
        "total_emails": _corpus_count(conn, "legal"),
    })


# ── Trigger route ──────────────────────────────────────────────────────────────

@router.post("/sync/{corpus}/run", response_class=HTMLResponse)
async def run_sync(request: Request, corpus: str):
    if corpus not in ("personal", "legal"):
        return HTMLResponse("<p>Invalid corpus.</p>", status_code=400)

    job_id = create_job(
        status="queued",
        corpus=corpus,
        message="Starting…",
        total_stored=0,
        total_skipped=0,
        error=None,
        started=None,
        finished=None,
    )
    threading.Thread(target=_sync_worker, args=(job_id, corpus), daemon=True).start()

    return templates.TemplateResponse("partials/sync_status.html", {
        "request": request,
        "job_id": job_id,
        "corpus": corpus,
        "job": get_job(job_id),
        "recent_emails": [],
    })


# ── Status poll route ──────────────────────────────────────────────────────────

@router.get("/sync/{corpus}/status/{job_id}", response_class=HTMLResponse)
async def sync_status(
    request: Request, corpus: str, job_id: str, conn=Depends(get_conn)
):
    job = get_job(job_id)
    if not job:
        return HTMLResponse(
            "<div class='sync-result sync-result--error'>"
            "Sync job not found — the server may have restarted. "
            "Please start a new sync."
            "</div>"
        )

    recent_emails = []
    if job.get("status") == "done":
        recent_emails = _recent_emails(conn, corpus, limit=10)

    return templates.TemplateResponse("partials/sync_status.html", {
        "request": request,
        "job_id": job_id,
        "corpus": corpus,
        "job": job,
        "recent_emails": recent_emails,
    })
