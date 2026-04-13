"""
Thread reconstruction and email storage with deduplication.

Priority:
1. References header (most reliable)
2. In-Reply-To header
3. Subject-based grouping (normalized subject)
"""
import json
import logging
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

from src.storage.database import (
    delta_hash_exists,
    email_exists,
    get_db,
)


def find_or_create_thread(
    conn: sqlite3.Connection,
    subject_normalized: str,
    references_header: str,
    in_reply_to: str,
    contact_id: Optional[int],
) -> int:
    """Return an existing thread_id or create a new thread."""

    # Strategy 1: look up thread via referenced message IDs
    if references_header or in_reply_to:
        ref_ids = references_header.split() + ([in_reply_to] if in_reply_to else [])
        ref_ids = [r.strip("<>") for r in ref_ids if r]
        for ref_id in ref_ids:
            row = conn.execute(
                "SELECT thread_id FROM emails WHERE message_id=?", (ref_id,)
            ).fetchone()
            if row and row["thread_id"]:
                return row["thread_id"]

    # Strategy 2: match by normalized subject + contact
    if subject_normalized:
        query = "SELECT id FROM threads WHERE subject_normalized=?"
        params: list = [subject_normalized]
        if contact_id is not None:
            query += " AND (contact_id=? OR contact_id IS NULL)"
            params.append(contact_id)
        row = conn.execute(query, params).fetchone()
        if row:
            return row["id"]

    # Create new thread
    cursor = conn.execute(
        """INSERT INTO threads (subject_normalized, contact_id, email_count)
           VALUES (?, ?, 0)""",
        (subject_normalized, contact_id),
    )
    return cursor.lastrowid


def _update_thread_stats(conn: sqlite3.Connection, thread_id: int) -> None:
    """Refresh thread first_date, last_date, and email_count."""
    conn.execute(
        """UPDATE threads SET
            first_date = (SELECT MIN(date) FROM emails WHERE thread_id=?),
            last_date  = (SELECT MAX(date) FROM emails WHERE thread_id=?),
            email_count = (SELECT COUNT(*) FROM emails WHERE thread_id=?)
           WHERE id=?""",
        (thread_id, thread_id, thread_id, thread_id),
    )


def resolve_contact_id(conn: sqlite3.Connection, email_address: str) -> Optional[int]:
    """Find contact ID for an email address (checking aliases via json_each)."""
    email_lower = email_address.lower()
    row = conn.execute(
        "SELECT id FROM contacts WHERE LOWER(email) = ?", (email_lower,)
    ).fetchone()
    if row:
        return row["id"]
    # Alias search via json_each — avoids full-table scan + Python loop
    row = conn.execute(
        """SELECT c.id FROM contacts c, json_each(c.aliases) je
           WHERE LOWER(je.value) = ?
           LIMIT 1""",
        (email_lower,),
    ).fetchone()
    return row["id"] if row else None


def store_email(
    parsed: Dict,
    conn: sqlite3.Connection,
    corpus: str = "personal",
) -> Optional[int]:
    """
    Insert a parsed email into the database.

    *corpus* is stored on the email row ('personal' or 'legal').
    Legal-corpus attachments are stored as metadata-only (content=NULL,
    downloaded=0) so they can be re-fetched on demand from IMAP.

    Returns the new email ID, or None if skipped (duplicate or already exists).
    """
    message_id = parsed["message_id"]

    # Skip if exact Message-ID already stored
    if email_exists(message_id):
        return None

    # Skip if delta content is identical to an already-stored email
    # (catches forwarded/copy emails with same body)
    delta_hash = parsed["delta_hash"]
    if delta_hash and delta_hash_exists(delta_hash):
        return None

    # Resolve contact
    contact_id = resolve_contact_id(conn, parsed["from_address"])

    # Thread reconstruction
    thread_id = find_or_create_thread(
        conn,
        subject_normalized=parsed["subject_normalized"],
        references_header=parsed["references_header"],
        in_reply_to=parsed["in_reply_to"],
        contact_id=contact_id,
    )

    # Insert email
    cursor = conn.execute(
        """INSERT INTO emails (
            message_id, in_reply_to, references_header, thread_id,
            date, from_address, from_name, to_addresses, cc_addresses,
            subject, subject_normalized, body_text, body_html,
            delta_text, delta_hash, raw_size_bytes,
            folder, uid, direction, language, has_attachments, contact_id,
            corpus
        ) VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?
        )""",
        (
            parsed["message_id"],
            parsed["in_reply_to"],
            parsed["references_header"],
            thread_id,
            parsed["date"].isoformat() if isinstance(parsed["date"], datetime) else parsed["date"],
            parsed["from_address"],
            parsed["from_name"],
            parsed["to_addresses"],
            parsed["cc_addresses"],
            parsed["subject"],
            parsed["subject_normalized"],
            parsed["body_text"],
            parsed["body_html"],
            parsed["delta_text"],
            parsed["delta_hash"],
            parsed["raw_size_bytes"],
            parsed["folder"],
            parsed["uid"],
            parsed["direction"],
            parsed["language"],
            1 if parsed["has_attachments"] else 0,
            contact_id,
            corpus,
        ),
    )
    email_id = cursor.lastrowid

    # Insert attachments
    for att in parsed.get("attachments", []):
        if corpus == "legal":
            # Metadata-only: no BLOB content; mark as not-yet-downloaded so
            # the web UI can trigger on-demand IMAP fetch later.
            conn.execute(
                """INSERT INTO attachments
                   (email_id, filename, content_type, size_bytes, content,
                    mime_section, imap_uid, folder, downloaded)
                   VALUES (?, ?, ?, ?, NULL, ?, ?, ?, 0)""",
                (
                    email_id,
                    att["filename"],
                    att["content_type"],
                    att["size_bytes"],
                    att.get("mime_section"),
                    att.get("imap_uid"),
                    att.get("folder"),
                ),
            )
        else:
            conn.execute(
                """INSERT INTO attachments
                   (email_id, filename, content_type, size_bytes, content,
                    mime_section, imap_uid, folder, downloaded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    email_id,
                    att["filename"],
                    att["content_type"],
                    att["size_bytes"],
                    att["content"],
                    att.get("mime_section"),
                    att.get("imap_uid"),
                    att.get("folder"),
                ),
            )

    _update_thread_stats(conn, thread_id)

    return email_id


def batch_store_emails(
    parsed_emails: List[Dict],
    folder: str,
    corpus: str = "personal",
) -> Dict[str, int]:
    """
    Store a batch of parsed emails, returning stats dict.

    *corpus* is forwarded to every store_email() call so all emails in the
    batch are tagged with the correct corpus ('personal' or 'legal').
    """
    stats = {"stored": 0, "skipped_duplicate": 0, "skipped_error": 0}

    with get_db() as conn:
        for parsed in parsed_emails:
            try:
                result = store_email(parsed, conn, corpus=corpus)
                if result is not None:
                    stats["stored"] += 1
                else:
                    stats["skipped_duplicate"] += 1
            except Exception as e:
                stats["skipped_error"] += 1
                logger.warning(
                    "Failed to store email uid=%s subject=%r: %s",
                    parsed.get("uid"),
                    parsed.get("subject", "")[:60],
                    e,
                    exc_info=True,
                )

    return stats
