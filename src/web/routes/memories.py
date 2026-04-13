"""Knowledge Base — memory file management routes."""
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.config import memories_dir
from src.web.deps import get_conn

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

# ── Background synthesis jobs ─────────────────────────────────────────────────
_jobs: Dict[str, dict] = {}
_jobs_lock = threading.Lock()

# ── Section headings preserved in every memory file ──────────────────────────
_CANONICAL_SECTIONS = [
    "Quick Context",
    "Current Legal Position",
    "Party A's Established Positions",
    "Party B's Known Positions",
    "Active Open Disputes",
    "Red Lines — NEVER in Writing",
    "Communication Pattern Intelligence",
    # party_b_profile sections
    "Detected Manipulation Patterns (ranked by frequency)",
    "Rhetorical Fingerprint",
    "Pre-Hearing Behavior (documented)",
    "Known Factual Contradictions (high/medium severity)",
    "What Has Worked",
    "What to Avoid",
    # general sections
    "Communication Rules",
    "Legal Awareness",
    "Tone Calibration by Situation",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_file_path(row: sqlite3.Row) -> Path:
    fpath = Path(row["file_path"])
    if not fpath.is_absolute():
        fpath = memories_dir() / fpath.name
    return fpath


def _parse_sections(content: str) -> list[dict]:
    """Split memory file into sections at ## boundaries."""
    content = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    blocks = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    sections = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        header = lines[0].lstrip("#").strip() if lines[0].startswith("#") else ""
        if not header:
            continue
        body = "\n".join(lines[1:]).strip()
        sections.append({"header": header, "body": body})
    return sections


def _rebuild_file(fpath: Path, sections: list[dict], title: str) -> None:
    """Write sections back to file preserving title and frontmatter."""
    existing = fpath.read_text(encoding="utf-8") if fpath.exists() else ""
    fm_match = re.match(r"(<!--.*?-->\s*\n)", existing, re.DOTALL)
    frontmatter = fm_match.group(1) if fm_match else ""

    parts = [frontmatter.rstrip() + "\n" + title if frontmatter else title]
    for s in sections:
        if s["body"].strip():
            parts.append("\n## {}\n{}".format(s["header"], s["body"]))
    fpath.write_text("\n".join(parts) + "\n", encoding="utf-8")


def _get_title(content: str) -> str:
    m = re.search(r"^# .+", content, re.MULTILINE)
    return m.group(0) if m else "# Memory"


def _memory_meta(row: sqlite3.Row) -> dict:
    d = dict(row)
    fpath = _get_file_path(row)
    d["file_exists"] = fpath.exists()
    d["file_size"] = fpath.stat().st_size if fpath.exists() else 0
    d["file_size_kb"] = round(d["file_size"] / 1024, 1)
    if fpath.exists():
        text = fpath.read_text(encoding="utf-8")
        m = re.search(r"updated=(\S+)", text)
        d["updated"] = m.group(1) if m else "—"
        d["section_count"] = len(_parse_sections(text))
    else:
        d["updated"] = "—"
        d["section_count"] = 0
    return d


# ── List page ─────────────────────────────────────────────────────────────────

@router.get("/memories/", response_class=HTMLResponse)
async def memories_list(
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    rows = conn.execute(
        "SELECT rm.*, t.name AS topic_name "
        "FROM reply_memories rm "
        "LEFT JOIN topics t ON rm.topic_id = t.id "
        "ORDER BY rm.display_name"
    ).fetchall()
    memories = [_memory_meta(r) for r in rows]
    return templates.TemplateResponse("pages/memories.html", {
        "request": request,
        "page": "memories",
        "memories": memories,
    })


# ── Edit page (section-by-section) ───────────────────────────────────────────

@router.get("/memories/{slug}", response_class=HTMLResponse)
async def memory_edit(
    request: Request,
    slug: str,
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = conn.execute(
        "SELECT rm.*, t.name AS topic_name "
        "FROM reply_memories rm "
        "LEFT JOIN topics t ON rm.topic_id = t.id "
        "WHERE rm.slug = ?", (slug,)
    ).fetchone()
    if not row:
        return HTMLResponse("<p>Memory not found.</p>", status_code=404)

    fpath = _get_file_path(row)
    content = fpath.read_text(encoding="utf-8") if fpath.exists() else ""
    sections = _parse_sections(content)
    meta = _memory_meta(row)

    return templates.TemplateResponse("pages/memory_edit.html", {
        "request": request,
        "page": "memories",
        "memory": meta,
        "sections": sections,
        "raw_content": content,
    })


# ── Save single section ───────────────────────────────────────────────────────

@router.post("/memories/{slug}/section", response_class=HTMLResponse)
async def save_section(
    request: Request,
    slug: str,
    header: str = Form(...),
    body: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = conn.execute("SELECT * FROM reply_memories WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return HTMLResponse("<p>Memory not found.</p>", status_code=404)

    fpath = _get_file_path(row)
    content = fpath.read_text(encoding="utf-8") if fpath.exists() else ""
    sections = _parse_sections(content)
    title = _get_title(content)

    # Update or append the section
    updated = False
    for s in sections:
        if s["header"] == header:
            s["body"] = body.strip()
            updated = True
            break
    if not updated:
        sections.append({"header": header, "body": body.strip()})

    fpath.parent.mkdir(parents=True, exist_ok=True)
    _rebuild_file(fpath, sections, title)
    conn.execute(
        "UPDATE reply_memories SET updated_at = CURRENT_TIMESTAMP WHERE slug = ?", (slug,)
    )
    conn.commit()

    return HTMLResponse(
        '<div class="mem-save-feedback mem-save-ok" id="save-feedback-{}">'
        '✓ Saved</div>'.format(header.replace(" ", "-").lower())
    )


# ── Save full raw file ────────────────────────────────────────────────────────

@router.post("/memories/{slug}/raw", response_class=HTMLResponse)
async def save_raw(
    request: Request,
    slug: str,
    content: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = conn.execute("SELECT * FROM reply_memories WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return HTMLResponse("<p>Memory not found.</p>", status_code=404)

    fpath = _get_file_path(row)
    fpath.parent.mkdir(parents=True, exist_ok=True)
    fpath.write_text(content, encoding="utf-8")
    conn.execute(
        "UPDATE reply_memories SET updated_at = CURRENT_TIMESTAMP WHERE slug = ?", (slug,)
    )
    conn.commit()
    return HTMLResponse(
        '<div class="mem-save-feedback mem-save-ok">✓ Raw file saved</div>'
    )


# ── Synthesis: start background job ──────────────────────────────────────────

@router.post("/memories/{slug}/synthesize", response_class=HTMLResponse)
async def synthesize_memory(
    request: Request,
    slug: str,
    since: str = Form(""),
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = conn.execute("SELECT * FROM reply_memories WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return HTMLResponse("<p>Memory not found.</p>", status_code=404)

    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "slug": slug, "result": None, "error": None}

    since_val = since.strip() or None

    def _worker():
        try:
            from src.storage.database import get_db
            from src.analysis.memory_synthesizer import (
                synthesize_topic_memory, diff_sections,
            )
            from pathlib import Path as _Path

            with get_db() as wconn:
                proposed = synthesize_topic_memory(
                    wconn, slug, since=since_val
                )

            fpath = _get_file_path(row)
            diffs = diff_sections(fpath, proposed)
            with _jobs_lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["result"] = {
                    "diffs": [
                        {"header": h, "old": o, "new": n}
                        for h, o, n in diffs
                    ],
                    "slug": slug,
                }
        except Exception as exc:
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
                _jobs[job_id]["error"] = str(exc)

    threading.Thread(target=_worker, daemon=True).start()

    return templates.TemplateResponse("partials/memory_synthesizing.html", {
        "request": request,
        "job_id": job_id,
        "slug": slug,
    })


# ── Synthesis: poll ───────────────────────────────────────────────────────────

@router.get("/memories/{slug}/synthesize/poll/{job_id}", response_class=HTMLResponse)
async def poll_synthesis(
    request: Request,
    slug: str,
    job_id: str,
    conn: sqlite3.Connection = Depends(get_conn),
):
    with _jobs_lock:
        job = _jobs.get(job_id, {})

    if not job or job["status"] == "running":
        return templates.TemplateResponse("partials/memory_synthesizing.html", {
            "request": request,
            "job_id": job_id,
            "slug": slug,
        })

    if job["status"] == "error":
        return HTMLResponse(
            '<div class="mem-save-feedback mem-save-err">'
            '⚠ Synthesis error: {}</div>'.format(job.get("error", "unknown"))
        )

    diffs = job["result"]["diffs"]
    if not diffs:
        return HTMLResponse(
            '<div class="mem-save-feedback mem-save-ok">'
            '✓ Memory is already up to date — no changes proposed.</div>'
        )

    row = conn.execute("SELECT * FROM reply_memories WHERE slug = ?", (slug,)).fetchone()
    memory = _memory_meta(row) if row else {"slug": slug, "display_name": slug}

    return templates.TemplateResponse("partials/memory_diff.html", {
        "request": request,
        "memory": memory,
        "diffs": diffs,
        "slug": slug,
    })


# ── Synthesis: accept a single section diff ───────────────────────────────────

@router.post("/memories/_preview", response_class=HTMLResponse)
async def preview_markdown(content: str = Form(...)):
    """Server-side markdown render — avoids client-side XSS risks."""
    import html as _html

    # Very lightweight subset renderer (no external deps needed)
    lines = content.split("\n")
    out = []
    in_list = False
    in_table = False

    for line in lines:
        # Table rows
        if line.strip().startswith("|"):
            if not in_table:
                out.append("<table>")
                in_table = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue  # separator row
            tag = "th" if not any("<td>" in r for r in out[-3:]) else "td"
            out.append("<tr>" + "".join("<{}>{}</{}>".format(tag, _html.escape(c), tag) for c in cells) + "</tr>")
            continue
        elif in_table:
            out.append("</table>")
            in_table = False

        # Headings
        if line.startswith("### "):
            if in_list: out.append("</ul>"); in_list = False
            out.append("<h4>{}</h4>".format(_html.escape(line[4:])))
        elif line.startswith("## "):
            if in_list: out.append("</ul>"); in_list = False
            out.append("<h3>{}</h3>".format(_html.escape(line[3:])))
        elif line.startswith("# "):
            if in_list: out.append("</ul>"); in_list = False
            out.append("<h2>{}</h2>".format(_html.escape(line[2:])))
        # Bullet
        elif line.startswith("- "):
            if not in_list: out.append("<ul>"); in_list = True
            inner = _html.escape(line[2:])
            # Bold **text**
            inner = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", inner)
            out.append("<li>{}</li>".format(inner))
        # Empty line
        elif line.strip() == "":
            if in_list: out.append("</ul>"); in_list = False
            out.append("<br>")
        # Plain paragraph
        else:
            if in_list: out.append("</ul>"); in_list = False
            inner = _html.escape(line)
            inner = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", inner)
            inner = re.sub(r"`(.+?)`", r"<code>\1</code>", inner)
            out.append("<p>{}</p>".format(inner))

    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")

    return HTMLResponse('<div class="mem-preview">' + "\n".join(out) + "</div>")


@router.post("/memories/{slug}/synthesize/accept", response_class=HTMLResponse)
async def accept_section(
    request: Request,
    slug: str,
    header: str = Form(...),
    body: str = Form(...),
    conn: sqlite3.Connection = Depends(get_conn),
):
    row = conn.execute("SELECT * FROM reply_memories WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return HTMLResponse("<p>Memory not found.</p>", status_code=404)

    fpath = _get_file_path(row)
    content = fpath.read_text(encoding="utf-8") if fpath.exists() else ""
    sections = _parse_sections(content)
    title = _get_title(content)

    updated = False
    for s in sections:
        if s["header"] == header:
            s["body"] = body.strip()
            updated = True
            break
    if not updated:
        sections.append({"header": header, "body": body.strip()})

    _rebuild_file(fpath, sections, title)
    conn.execute(
        "UPDATE reply_memories SET updated_at = CURRENT_TIMESTAMP WHERE slug = ?", (slug,)
    )
    conn.commit()

    return HTMLResponse(
        '<div class="mem-diff-accepted">✓ Section accepted and saved</div>'
    )
