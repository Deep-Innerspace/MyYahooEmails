"""
Analysis run orchestrator.

Handles:
- Creating and tracking analysis_run records
- Batching emails for LLM calls
- Storing results with full traceability
- Resuming interrupted runs (skip already-analyzed)

All write helpers accept an optional ``conn`` parameter.  When provided, the
caller is responsible for the transaction (commit/rollback) — no extra
``get_db()`` context is opened, avoiding redundant round-trips during bulk
analysis passes.  When ``conn`` is None, the helper opens its own short-lived
connection (backward-compatible with CLI callers).
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional

from src.storage.database import get_db


# ─────────────────────────── PROMPT LOADING ──────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt template from src/analysis/prompts/<name>.txt"""
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def prompt_hash(prompt_text: str) -> str:
    return hashlib.sha256(prompt_text.encode()).hexdigest()[:16]


# ─────────────────────────── CONNECTION HELPER ───────────────────────────────

@contextmanager
def _conn_or_new(conn: Optional[sqlite3.Connection]):
    """Yield *conn* if provided, otherwise open a fresh get_db() context."""
    if conn is not None:
        yield conn
    else:
        with get_db() as fresh:
            yield fresh


# ─────────────────────────── RUN LIFECYCLE ───────────────────────────────────

def create_run(
    analysis_type: str,
    provider_name: str,
    model_id: str,
    prompt_text: str,
    prompt_version: str = "v1",
    notes: str = "",
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    """Insert a new analysis_run row and return its ID."""
    with _conn_or_new(conn) as c:
        cur = c.execute(
            """INSERT INTO analysis_runs
               (analysis_type, provider_name, model_id, prompt_hash, prompt_version, status, notes)
               VALUES (?, ?, ?, ?, ?, 'running', ?)""",
            (analysis_type, provider_name, model_id,
             prompt_hash(prompt_text), prompt_version, notes),
        )
        return cur.lastrowid


def finish_run(
    run_id: int,
    status: str = "complete",
    email_count: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    with _conn_or_new(conn) as c:
        c.execute(
            "UPDATE analysis_runs SET status=?, email_count=? WHERE id=?",
            (status, email_count, run_id),
        )


def already_analyzed(
    run_id: int,
    email_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """True if this email already has a result for this run."""
    with _conn_or_new(conn) as c:
        row = c.execute(
            "SELECT id FROM analysis_results WHERE run_id=? AND email_id=?",
            (run_id, email_id),
        ).fetchone()
        return row is not None


def store_result(
    run_id: int,
    email_id: int,
    result_json: str,
    sender_contact_id: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    with _conn_or_new(conn) as c:
        c.execute(
            """INSERT OR REPLACE INTO analysis_results
               (run_id, email_id, sender_contact_id, result_json)
               VALUES (?, ?, ?, ?)""",
            (run_id, email_id, sender_contact_id, result_json),
        )


def store_topics_for_email(
    email_id: int,
    topics: List[Dict[str, Any]],
    run_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    """Link email to topics after classification."""
    with _conn_or_new(conn) as c:
        for t in topics:
            topic_name = t.get("name", "")
            confidence = float(t.get("confidence", 1.0))
            row = c.execute(
                "SELECT id FROM topics WHERE name=?", (topic_name,)
            ).fetchone()
            if not row:
                # Auto-create AI-discovered topic
                cur = c.execute(
                    "INSERT OR IGNORE INTO topics (name, description, is_user_defined) VALUES (?,?,0)",
                    (topic_name, ""),
                )
                topic_id = cur.lastrowid or c.execute(
                    "SELECT id FROM topics WHERE name=?", (topic_name,)
                ).fetchone()["id"]
            else:
                topic_id = row["id"]

            c.execute(
                """INSERT OR REPLACE INTO email_topics (email_id, topic_id, confidence, run_id)
                   VALUES (?, ?, ?, ?)""",
                (email_id, topic_id, confidence, run_id),
            )


def store_timeline_events(
    run_id: int,
    email_id: int,
    events: List[Dict[str, Any]],
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    with _conn_or_new(conn) as c:
        for ev in events:
            c.execute(
                """INSERT INTO timeline_events
                   (run_id, email_id, event_date, event_type, description, significance)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    email_id,
                    ev.get("event_date", ""),
                    ev.get("event_type", "statement"),
                    ev.get("description", ""),
                    ev.get("significance", "medium"),
                ),
            )


def store_contradictions(
    run_id: int,
    contradictions: List[Dict[str, Any]],
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    with _conn_or_new(conn) as c:
        for contradiction in contradictions:
            # Resolve topic ID if provided
            topic_id = None
            if contradiction.get("topic"):
                row = c.execute(
                    "SELECT id FROM topics WHERE name=?", (contradiction["topic"],)
                ).fetchone()
                if row:
                    topic_id = row["id"]

            c.execute(
                """INSERT INTO contradictions
                   (run_id, email_id_a, email_id_b, scope, topic_id, explanation, severity)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    contradiction["email_id_a"],
                    contradiction["email_id_b"],
                    contradiction.get("scope", "intra-sender"),
                    topic_id,
                    contradiction.get("explanation", ""),
                    contradiction.get("severity", "medium"),
                ),
            )


# ─────────────────────────── EMAIL FETCHING ──────────────────────────────────

def get_emails_for_analysis(
    skip_if_analyzed: bool = True,
    run_id: Optional[int] = None,
    since: Optional[datetime] = None,
    topic_filter: Optional[str] = None,
    direction: Optional[str] = None,
    limit: Optional[int] = None,
    email_ids: Optional[List[int]] = None,
    skip_classified: bool = False,
) -> List[Dict[str, Any]]:
    """Fetch emails that need analysis, with optional filters.

    email_ids: restrict to this explicit list of IDs (for oversized/targeted runs).
    skip_classified: exclude emails already present in email_topics (for classify reruns).
    """
    with get_db() as conn:
        params = []
        wheres = []

        if email_ids:
            placeholders = ",".join("?" * len(email_ids))
            wheres.append(f"e.id IN ({placeholders})")
            params.extend(email_ids)

        if since:
            wheres.append("e.date >= ?")
            params.append(since.isoformat())

        if direction:
            wheres.append("e.direction = ?")
            params.append(direction)

        if topic_filter:
            wheres.append("""e.id IN (
                SELECT et.email_id FROM email_topics et
                JOIN topics t ON t.id = et.topic_id AND t.name = ?
            )""")
            params.append(topic_filter)

        # Skip emails already classified (across all runs) — for classify command
        if skip_classified:
            wheres.append("NOT EXISTS (SELECT 1 FROM email_topics et WHERE et.email_id = e.id)")

        # Skip emails already analyzed in this run (for mid-run resume)
        if skip_if_analyzed and run_id:
            wheres.append("""e.id NOT IN (
                SELECT email_id FROM analysis_results WHERE run_id = ?
            )""")
            params.append(run_id)

        # Classify / tone / manipulation are personal-corpus only
        wheres.append("e.corpus = 'personal'")

        # Skip emails with no substantive new content
        wheres.append("TRIM(e.delta_text) != ''")
        wheres.append("LENGTH(TRIM(e.delta_text)) > 20")

        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        limit_clause = f"LIMIT {limit}" if limit else ""

        rows = conn.execute(
            f"""SELECT e.id, e.date, e.direction, e.subject,
                       e.delta_text, e.from_address, e.contact_id, e.language
                FROM emails e
                {where_clause}
                ORDER BY e.date ASC
                {limit_clause}""",
            params,
        ).fetchall()

        return [dict(r) for r in rows]


def get_classification_summaries(
    run_id: Optional[int] = None,
    since: Optional[datetime] = None,
    topic_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch email summaries from a classify run.

    If run_id is None, uses the most recent completed/partial classify run.
    Returns: [{id, date, direction, subject, summary, topics}]
    """
    with get_db() as conn:
        # Resolve run_id
        if run_id is None:
            row = conn.execute(
                """SELECT id FROM analysis_runs
                   WHERE analysis_type = 'classify'
                     AND status IN ('complete', 'partial')
                   ORDER BY run_date DESC LIMIT 1"""
            ).fetchone()
            if not row:
                return []
            run_id = row["id"]

        params: list = [run_id]
        wheres = ["r.id = ?"]

        if since:
            wheres.append("e.date >= ?")
            params.append(since.isoformat())

        if topic_filter:
            wheres.append("""e.id IN (
                SELECT et.email_id FROM email_topics et
                JOIN topics t ON t.id = et.topic_id AND t.name = ?
            )""")
            params.append(topic_filter)

        where_clause = "WHERE " + " AND ".join(wheres)

        rows = conn.execute(
            f"""SELECT ar.email_id AS id, ar.result_json,
                       e.date, e.direction, e.subject, e.from_address
                FROM analysis_results ar
                JOIN analysis_runs r ON r.id = ar.run_id
                JOIN emails e ON e.id = ar.email_id
                {where_clause}
                ORDER BY e.date ASC""",
            params,
        ).fetchall()

        results = []
        for r in rows:
            data = json.loads(r["result_json"])
            topic_names = [t.get("name", "") for t in data.get("topics", [])]
            results.append({
                "id": r["id"],
                "date": str(r["date"])[:10],
                "direction": r["direction"],
                "subject": r["subject"],
                "from_address": r["from_address"],
                "summary": data.get("summary", ""),
                "topics": topic_names,
            })
        return results


def batch(items: list, size: int) -> Generator[list, None, None]:
    """Split a list into batches of at most `size` items."""
    for i in range(0, len(items), size):
        yield items[i: i + size]


def parse_json_response(text: str) -> Any:
    """Extract JSON from LLM response, stripping any markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            l for l in lines
            if not l.strip().startswith("```")
        ).strip()
    return json.loads(text)
