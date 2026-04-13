"""Reply Command Center — triage, draft generation, action tracking."""
import json
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.web.deps import get_conn
from src.web.job_manager import create_job, get_job, update_job
from src.config import memories_dir

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

_VALID_TABS = ("pending", "drafted", "answered", "na", "all")

REPLY_STATUSES = {
    "unset":          "Unset",
    "pending":        "Pending",
    "drafted":        "Drafted",
    "answered":       "Answered",
    "not_applicable": "N/A",
}


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _reply_candidates(conn: sqlite3.Connection, corpus: str = "personal"):
    """Get all received emails with their reply status and action counts."""
    return conn.execute(
        """SELECT e.id, e.date, e.subject, e.from_address, e.direction,
                  e.reply_status, e.thread_id,
                  COALESCE(c.name, e.from_address) AS contact_name,
                  (SELECT COUNT(*) FROM pending_actions pa
                   WHERE pa.email_id = e.id AND pa.resolved = 0) AS action_count,
                  (SELECT COUNT(*) FROM reply_drafts rd
                   WHERE rd.email_id = e.id AND rd.status = 'draft') AS draft_count
           FROM emails e
           LEFT JOIN contacts c ON e.contact_id = c.id
           WHERE e.direction = 'received'
             AND e.corpus = ?
           ORDER BY e.date DESC""",
        (corpus,),
    ).fetchall()


def _filter_by_tab(candidates, tab):
    """Filter candidates list by tab name."""
    if tab == "all":
        return candidates
    status_map = {
        "pending": ("pending", "unset"),
        "drafted": ("drafted",),
        "answered": ("answered",),
        "na": ("not_applicable",),
    }
    allowed = status_map.get(tab, ("pending", "unset"))
    return [c for c in candidates if c["reply_status"] in allowed]


def _tab_counts(candidates):
    """Count candidates per tab."""
    counts = {"pending": 0, "drafted": 0, "answered": 0, "na": 0, "all": len(candidates)}
    for c in candidates:
        s = c["reply_status"]
        if s in ("pending", "unset"):
            counts["pending"] += 1
        elif s == "drafted":
            counts["drafted"] += 1
        elif s == "answered":
            counts["answered"] += 1
        elif s == "not_applicable":
            counts["na"] += 1
    return counts


def _get_email_detail(conn: sqlite3.Connection, email_id: int):
    """Full email row for the detail panel."""
    return conn.execute(
        """SELECT e.*, COALESCE(c.name, e.from_address) AS contact_name
           FROM emails e
           LEFT JOIN contacts c ON e.contact_id = c.id
           WHERE e.id = ?""",
        (email_id,),
    ).fetchone()


def _get_drafts(conn: sqlite3.Connection, email_id: int):
    """All drafts for an email, newest first."""
    return conn.execute(
        "SELECT * FROM reply_drafts WHERE email_id = ? ORDER BY version DESC",
        (email_id,),
    ).fetchall()


def _get_actions(conn: sqlite3.Connection, email_id: int):
    """Pending actions for an email."""
    return conn.execute(
        "SELECT * FROM pending_actions WHERE email_id = ? ORDER BY resolved ASC, created_at ASC",
        (email_id,),
    ).fetchall()


def _get_memories(conn: sqlite3.Connection, email_id: Optional[int] = None):
    """All memory files with auto-select based on email topics."""
    memories = conn.execute(
        "SELECT rm.*, t.name AS topic_name "
        "FROM reply_memories rm "
        "LEFT JOIN topics t ON rm.topic_id = t.id "
        "ORDER BY rm.display_name"
    ).fetchall()

    result = []
    auto_selected = set()

    # Auto-select based on email topics
    if email_id:
        email_topics = conn.execute(
            "SELECT DISTINCT t.id FROM email_topics et "
            "JOIN topics t ON et.topic_id = t.id "
            "WHERE et.email_id = ?",
            (email_id,),
        ).fetchall()
        auto_topic_ids = {r["id"] for r in email_topics}

        for m in memories:
            if m["topic_id"] and m["topic_id"] in auto_topic_ids:
                auto_selected.add(m["slug"])
            if m["slug"] == "general":
                auto_selected.add(m["slug"])

    for m in memories:
        d = dict(m)
        d["selected"] = m["slug"] in auto_selected
        # Check file exists and get size — single stat() call
        fpath = Path(m["file_path"])
        if not fpath.is_absolute():
            fpath = memories_dir() / fpath.name
        try:
            st = fpath.stat()
            d["file_exists"] = True
            d["file_size"] = st.st_size
        except OSError:
            d["file_exists"] = False
            d["file_size"] = 0
        result.append(d)

    return result


def _get_thread_emails(conn, thread_id, email_id, limit=5):
    """Get thread context emails."""
    if not thread_id:
        return []
    return conn.execute(
        """SELECT id, date, from_address, from_name, subject,
                  direction, delta_text
           FROM emails
           WHERE thread_id = ? AND id != ?
           ORDER BY date DESC
           LIMIT ?""",
        (thread_id, email_id, limit),
    ).fetchall()


# ── Import tone configs for template ──────────────────────────────────────────
def _tone_options():
    from src.analysis.reply_generator import TONE_CONFIGS
    return [(k, v["label"]) for k, v in TONE_CONFIGS.items()]


# ── Page routes ────────────────────────────────────────────────────────────────

@router.get("/reply/", response_class=HTMLResponse)
async def reply_workspace(
    request: Request,
    tab: Optional[str] = Query("pending"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    candidates = _reply_candidates(conn)
    active_tab = tab if tab in _VALID_TABS else "pending"
    counts = _tab_counts(candidates)

    # Auto-fallback: if pending tab is empty, show all
    if active_tab == "pending" and counts["pending"] == 0 and counts["all"] > 0:
        active_tab = "all"

    return templates.TemplateResponse("pages/reply_workspace.html", {
        "request": request,
        "page": "reply",
        "active_tab": active_tab,
        "tab_counts": counts,
    })


@router.get("/reply/list", response_class=HTMLResponse)
async def reply_list(
    request: Request,
    tab: Optional[str] = Query("pending"),
    active_id: Optional[int] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    candidates = _reply_candidates(conn)
    active_tab = tab if tab in _VALID_TABS else "pending"
    counts = _tab_counts(candidates)
    filtered = _filter_by_tab(candidates, active_tab)

    return templates.TemplateResponse("partials/reply_list.html", {
        "request": request,
        "candidates": filtered,
        "tab_counts": counts,
        "active_tab": active_tab,
        "active_id": active_id,
    })


@router.get("/reply/detail/{email_id}", response_class=HTMLResponse)
async def reply_detail(
    request: Request,
    email_id: int,
    tab: Optional[str] = Query("pending"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    email = _get_email_detail(conn, email_id)
    if not email:
        return HTMLResponse("<p class='text-muted'>Email not found.</p>")

    email_dict = dict(email)
    drafts = _get_drafts(conn, email_id)
    actions = _get_actions(conn, email_id)
    memories = _get_memories(conn, email_id)
    thread = _get_thread_emails(conn, email_dict.get("thread_id"), email_id)

    return templates.TemplateResponse("partials/reply_detail.html", {
        "request": request,
        "email": email_dict,
        "drafts": [dict(d) for d in drafts],
        "actions": [dict(a) for a in actions],
        "memories": memories,
        "thread_emails": [dict(t) for t in thread],
        "tone_options": _tone_options(),
        "active_tab": tab,
    })


# ── Status management ─────────────────────────────────────────────────────────

@router.post("/reply/status/{email_id}", response_class=HTMLResponse)
async def set_reply_status(
    request: Request,
    email_id: int,
    status: str = Form(...),
    tab: Optional[str] = Form("pending"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    if status not in REPLY_STATUSES:
        return HTMLResponse("Invalid status", status_code=400)

    conn.execute(
        "UPDATE emails SET reply_status = ? WHERE id = ?",
        (status, email_id),
    )
    conn.commit()

    # Return updated list + detail via OOB
    candidates = _reply_candidates(conn)
    active_tab = tab if tab in _VALID_TABS else "pending"
    filtered = _filter_by_tab(candidates, active_tab)
    counts = _tab_counts(candidates)

    # Find next email in the filtered list
    next_email = None
    for c in filtered:
        if c["id"] != email_id:
            next_email = c
            break

    list_html = templates.get_template("partials/reply_list.html").render({
        "request": request,
        "candidates": filtered,
        "tab_counts": counts,
        "active_tab": active_tab,
        "active_id": next_email["id"] if next_email else None,
    })

    if next_email:
        email = _get_email_detail(conn, next_email["id"])
        drafts = _get_drafts(conn, next_email["id"])
        actions = _get_actions(conn, next_email["id"])
        mems = _get_memories(conn, next_email["id"])
        thread = _get_thread_emails(conn, email["thread_id"] if email else None, next_email["id"])

        detail_html = templates.get_template("partials/reply_detail.html").render({
            "request": request,
            "email": dict(email) if email else {},
            "drafts": [dict(d) for d in drafts],
            "actions": [dict(a) for a in actions],
            "memories": mems,
            "thread_emails": [dict(t) for t in thread],
            "tone_options": _tone_options(),
            "active_tab": active_tab,
        })
    else:
        detail_html = '<div class="empty-state"><p class="text-muted">All caught up.</p></div>'

    return HTMLResponse(
        detail_html
        + '\n<div id="reply-list" hx-swap-oob="innerHTML">'
        + list_html
        + '</div>'
    )


# ── Draft generation (background) ─────────────────────────────────────────────

@router.post("/reply/generate/{email_id}", response_class=HTMLResponse)
async def generate_draft(
    request: Request,
    email_id: int,
    tone: str = Form("factual"),
    guidelines: str = Form(""),
    intent: str = Form(""),
    memory_slugs: str = Form(""),
    thread_depth: int = Form(5),
    tab: Optional[str] = Form("pending"),
):
    slugs = [s.strip() for s in memory_slugs.split(",") if s.strip()]

    job_id = create_job(
        status="running",
        email_id=email_id,
        result=None,
        error=None,
    )

    def _worker():
        try:
            from src.storage.database import get_db
            with get_db() as conn:
                from src.analysis.reply_generator import generate_reply_draft
                result = generate_reply_draft(
                    conn, email_id,
                    tone=tone,
                    guidelines=guidelines,
                    intent=intent,
                    memory_slugs=slugs,
                    thread_depth=thread_depth,
                )
            update_job(job_id, status="done", result=result)
        except Exception as exc:
            update_job(job_id, status="error", error=str(exc))

    threading.Thread(target=_worker, daemon=True).start()

    return templates.TemplateResponse("partials/reply_generating.html", {
        "request": request,
        "job_id": job_id,
        "email_id": email_id,
        "tab": tab,
    })


@router.get("/reply/generate/{email_id}/poll/{job_id}", response_class=HTMLResponse)
async def poll_generate(
    request: Request,
    email_id: int,
    job_id: str,
    tab: Optional[str] = Query("pending"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    job = get_job(job_id)

    if not job:
        return HTMLResponse(
            '<div class="sync-result sync-result--error" style="margin-bottom:var(--space-4)">'
            '<strong>Generation job not found</strong> — the server may have restarted. '
            'Please try generating again.</div>'
        )

    if job["status"] == "running":
        return templates.TemplateResponse("partials/reply_generating.html", {
            "request": request,
            "job_id": job_id,
            "email_id": email_id,
            "tab": tab,
        })

    if job["status"] == "error":
        return HTMLResponse(
            '<div class="sync-result sync-result--error" style="margin-bottom:var(--space-4)">'
            '<strong>Generation failed:</strong> {}</div>'.format(job.get("error", "Unknown error"))
        )

    # Done — return full detail panel with the new draft
    email = _get_email_detail(conn, email_id)
    drafts = _get_drafts(conn, email_id)
    actions = _get_actions(conn, email_id)
    memories = _get_memories(conn, email_id)
    thread = _get_thread_emails(conn, email["thread_id"] if email else None, email_id)

    return templates.TemplateResponse("partials/reply_detail.html", {
        "request": request,
        "email": dict(email) if email else {},
        "drafts": [dict(d) for d in drafts],
        "actions": [dict(a) for a in actions],
        "memories": memories,
        "thread_emails": [dict(t) for t in thread],
        "tone_options": _tone_options(),
        "active_tab": tab,
        "just_generated": True,
    })


# ── Draft management ──────────────────────────────────────────────────────────

@router.post("/reply/drafts/{draft_id}/edit", response_class=HTMLResponse)
async def edit_draft(
    request: Request,
    draft_id: int,
    edited_text: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        "UPDATE reply_drafts SET edited_text = ? WHERE id = ?",
        (edited_text, draft_id),
    )
    conn.commit()
    draft = conn.execute("SELECT * FROM reply_drafts WHERE id = ?", (draft_id,)).fetchone()
    return templates.TemplateResponse("partials/reply_draft_card.html", {
        "request": request,
        "draft": dict(draft) if draft else {},
    })


@router.post("/reply/drafts/{draft_id}/approve", response_class=HTMLResponse)
async def approve_draft(
    request: Request,
    draft_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("UPDATE reply_drafts SET status = 'approved' WHERE id = ?", (draft_id,))
    draft = conn.execute("SELECT * FROM reply_drafts WHERE id = ?", (draft_id,)).fetchone()
    if draft:
        conn.execute(
            "UPDATE emails SET reply_status = 'answered' WHERE id = ?",
            (draft["email_id"],),
        )
    conn.commit()
    if draft:
        return templates.TemplateResponse("partials/reply_draft_card.html", {
            "request": request,
            "draft": dict(draft),
        })
    return HTMLResponse("")


@router.post("/reply/drafts/{draft_id}/discard", response_class=HTMLResponse)
async def discard_draft(
    request: Request,
    draft_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("UPDATE reply_drafts SET status = 'discarded' WHERE id = ?", (draft_id,))
    conn.commit()
    draft = conn.execute("SELECT * FROM reply_drafts WHERE id = ?", (draft_id,)).fetchone()
    if draft:
        return templates.TemplateResponse("partials/reply_draft_card.html", {
            "request": request,
            "draft": dict(draft),
        })
    return HTMLResponse("")


# ── Pending actions ───────────────────────────────────────────────────────────

@router.get("/reply/actions/{email_id}", response_class=HTMLResponse)
async def list_actions(
    request: Request,
    email_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    actions = _get_actions(conn, email_id)
    return templates.TemplateResponse("partials/reply_actions.html", {
        "request": request,
        "actions": [dict(a) for a in actions],
        "email_id": email_id,
    })


@router.post("/reply/actions/{email_id}", response_class=HTMLResponse)
async def add_action(
    request: Request,
    email_id: int,
    action_type: str = Form("question"),
    text: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        "INSERT INTO pending_actions (email_id, action_type, text, extracted_by) "
        "VALUES (?, ?, ?, 'manual')",
        (email_id, action_type, text.strip()),
    )
    conn.commit()
    actions = _get_actions(conn, email_id)
    return templates.TemplateResponse("partials/reply_actions.html", {
        "request": request,
        "actions": [dict(a) for a in actions],
        "email_id": email_id,
    })


@router.post("/reply/actions/{action_id}/resolve", response_class=HTMLResponse)
async def toggle_resolve(
    request: Request,
    action_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        "UPDATE pending_actions SET resolved = CASE WHEN resolved = 0 THEN 1 ELSE 0 END "
        "WHERE id = ?",
        (action_id,),
    )
    conn.commit()
    row = conn.execute("SELECT email_id FROM pending_actions WHERE id = ?", (action_id,)).fetchone()
    if row:
        actions = _get_actions(conn, row["email_id"])
        return templates.TemplateResponse("partials/reply_actions.html", {
            "request": request,
            "actions": [dict(a) for a in actions],
            "email_id": row["email_id"],
        })
    return HTMLResponse("")


@router.delete("/reply/actions/{action_id}", response_class=HTMLResponse)
async def delete_action(
    request: Request,
    action_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = conn.execute("SELECT email_id FROM pending_actions WHERE id = ?", (action_id,)).fetchone()
    conn.execute("DELETE FROM pending_actions WHERE id = ?", (action_id,))
    conn.commit()
    if row:
        actions = _get_actions(conn, row["email_id"])
        return templates.TemplateResponse("partials/reply_actions.html", {
            "request": request,
            "actions": [dict(a) for a in actions],
            "email_id": row["email_id"],
        })
    return HTMLResponse("")


@router.post("/reply/actions/{email_id}/extract", response_class=HTMLResponse)
async def extract_actions(
    request: Request,
    email_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """LLM-extract pending actions from an email (synchronous — typically fast)."""
    from src.analysis.reply_generator import extract_pending_actions
    extract_pending_actions(conn, email_id)
    actions = _get_actions(conn, email_id)
    return templates.TemplateResponse("partials/reply_actions.html", {
        "request": request,
        "actions": [dict(a) for a in actions],
        "email_id": email_id,
    })


# ── Memories management ───────────────────────────────────────────────────────

@router.get("/reply/memories", response_class=HTMLResponse)
async def list_memories(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    memories = _get_memories(conn)
    return templates.TemplateResponse("partials/reply_memories.html", {
        "request": request,
        "memories": memories,
    })


@router.get("/reply/memories/{slug}", response_class=HTMLResponse)
async def read_memory(request: Request, slug: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = conn.execute("SELECT * FROM reply_memories WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return HTMLResponse("<p>Memory not found.</p>", status_code=404)

    fpath = Path(row["file_path"])
    if not fpath.is_absolute():
        fpath = memories_dir() / fpath.name
    content = fpath.read_text(encoding="utf-8") if fpath.exists() else ""

    return templates.TemplateResponse("partials/reply_memory_editor.html", {
        "request": request,
        "memory": dict(row),
        "content": content,
    })


@router.post("/reply/memories/{slug}", response_class=HTMLResponse)
async def save_memory(
    request: Request,
    slug: str,
    content: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = conn.execute("SELECT * FROM reply_memories WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return HTMLResponse("<p>Memory not found.</p>", status_code=404)

    fpath = Path(row["file_path"])
    if not fpath.is_absolute():
        fpath = memories_dir() / fpath.name
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content, encoding="utf-8")

    conn.execute(
        "UPDATE reply_memories SET updated_at = CURRENT_TIMESTAMP WHERE slug = ?",
        (slug,),
    )
    conn.commit()

    return HTMLResponse(
        '<div class="sync-result sync-result--success" style="padding:var(--space-2) var(--space-4)">'
        '<strong>Saved</strong> — {} updated.</div>'.format(row["display_name"])
    )


@router.post("/reply/memories/create", response_class=HTMLResponse)
async def create_memory(
    request: Request,
    slug: str = Form(...),
    display_name: str = Form(...),
    description: str = Form(""),
    topic_id: Optional[int] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    slug_clean = slug.strip().lower().replace(" ", "_")
    fpath = memories_dir() / "{}.md".format(slug_clean)
    if not fpath.exists():
        fpath.write_text("# {}\n\n".format(display_name.strip()), encoding="utf-8")

    conn.execute(
        "INSERT OR IGNORE INTO reply_memories (slug, display_name, file_path, topic_id, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (slug_clean, display_name.strip(), str(fpath), topic_id, description.strip()),
    )
    conn.commit()

    memories = _get_memories(conn)
    return templates.TemplateResponse("partials/reply_memories.html", {
        "request": request,
        "memories": memories,
    })


# ── Bulk triage ───────────────────────────────────────────────────────────────

@router.post("/reply/bulk-triage", response_class=HTMLResponse)
async def bulk_triage(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Auto-classify received personal emails:
    - Has a sent reply in same thread after this email → answered
    - Older than 30 days with no reply → not_applicable
    - Recent with no reply → pending
    """
    # Mark answered: received emails that have a later sent email in same thread
    conn.execute("""
        UPDATE emails SET reply_status = 'answered'
        WHERE id IN (
            SELECT e.id FROM emails e
            WHERE e.direction = 'received'
              AND e.corpus = 'personal'
              AND e.reply_status = 'unset'
              AND e.thread_id IS NOT NULL
              AND EXISTS (
                SELECT 1 FROM emails e2
                WHERE e2.thread_id = e.thread_id
                  AND e2.direction = 'sent'
                  AND e2.date > e.date
              )
        )
    """)
    answered = conn.execute("SELECT changes()").fetchone()[0]

    # Mark not_applicable: older than 30 days, no reply
    conn.execute("""
        UPDATE emails SET reply_status = 'not_applicable'
        WHERE direction = 'received'
          AND corpus = 'personal'
          AND reply_status = 'unset'
          AND date < datetime('now', '-30 days')
    """)
    na = conn.execute("SELECT changes()").fetchone()[0]

    # Mark pending: remaining unset received emails
    conn.execute("""
        UPDATE emails SET reply_status = 'pending'
        WHERE direction = 'received'
          AND corpus = 'personal'
          AND reply_status = 'unset'
    """)
    pending = conn.execute("SELECT changes()").fetchone()[0]

    conn.commit()

    return HTMLResponse(
        '<div class="sync-result sync-result--success">'
        '<div><strong>Triage complete</strong><br>'
        '{} marked answered · {} marked N/A · {} marked pending</div>'
        '</div>'.format(answered, na, pending)
    )
