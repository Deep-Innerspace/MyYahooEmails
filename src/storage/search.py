"""Full-text and filtered search over the email database."""
import json
from datetime import datetime
from typing import List, Optional

from src.storage.database import get_db


def all_addresses_for_contact(contact_email: str) -> List[str]:
    """Return the primary address + all aliases for a contact (for multi-address search)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT email, aliases FROM contacts WHERE email=?", (contact_email.lower(),)
        ).fetchone()
        if row:
            aliases = json.loads(row["aliases"] or "[]")
            return [row["email"]] + aliases
        # Also check if it's an alias of another contact
        all_contacts = conn.execute("SELECT email, aliases FROM contacts").fetchall()
        for c in all_contacts:
            aliases = json.loads(c["aliases"] or "[]")
            if contact_email.lower() in [a.lower() for a in aliases]:
                return [c["email"]] + aliases
    return [contact_email.lower()]


def search_emails(
    query: Optional[str] = None,
    topic: Optional[str] = None,
    contact_email: Optional[str] = None,
    direction: Optional[str] = None,  # 'sent' | 'received'
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[dict]:
    """Search emails with optional FTS query and metadata filters."""
    with get_db() as conn:
        params = []
        joins = []
        wheres = []

        if query:
            joins.append("JOIN emails_fts fts ON fts.rowid = e.id")
            wheres.append("fts MATCH ?")
            params.append(query)

        if topic:
            joins.append("""
                JOIN email_topics et ON et.email_id = e.id
                JOIN topics t ON t.id = et.topic_id AND t.name = ?
            """)
            params.append(topic)

        if contact_email:
            # Expand to all known addresses (primary + aliases) for this contact
            addrs = all_addresses_for_contact(contact_email)
            addr_clauses = []
            for addr in addrs:
                addr_clauses.append("(e.from_address = ? OR e.to_addresses LIKE ? OR e.cc_addresses LIKE ?)")
                params += [addr, f"%{addr}%", f"%{addr}%"]
            wheres.append("(" + " OR ".join(addr_clauses) + ")")

        if direction:
            wheres.append("e.direction = ?")
            params.append(direction)

        if date_from:
            wheres.append("e.date >= ?")
            params.append(date_from.isoformat())

        if date_to:
            wheres.append("e.date <= ?")
            params.append(date_to.isoformat())

        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        join_clause = " ".join(joins)

        sql = f"""
            SELECT e.id, e.message_id, e.date, e.from_address, e.from_name,
                   e.subject, e.direction, e.language, e.delta_text,
                   e.has_attachments, e.contact_id
            FROM emails e
            {join_clause}
            {where_clause}
            ORDER BY e.date DESC
            LIMIT ? OFFSET ?
        """
        params += [limit, offset]
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def get_email_by_id(email_id: int) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emails WHERE id=?", (email_id,)
        ).fetchone()
        return dict(row) if row else None


def get_thread_emails(thread_id: int) -> List[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM emails WHERE thread_id=? ORDER BY date ASC",
            (thread_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_emails(
    contact_email: Optional[str] = None,
    direction: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
) -> int:
    with get_db() as conn:
        params = []
        wheres = []
        if contact_email:
            addrs = all_addresses_for_contact(contact_email)
            addr_clauses = []
            for addr in addrs:
                addr_clauses.append("(from_address = ? OR to_addresses LIKE ? OR cc_addresses LIKE ?)")
                params += [addr, f"%{addr}%", f"%{addr}%"]
            wheres.append("(" + " OR ".join(addr_clauses) + ")")
        if direction:
            wheres.append("direction=?")
            params.append(direction)
        if date_from:
            wheres.append("date >= ?")
            params.append(date_from.isoformat())
        if date_to:
            wheres.append("date <= ?")
            params.append(date_to.isoformat())
        where = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        row = conn.execute(f"SELECT COUNT(*) FROM emails {where}", params).fetchone()
        return row[0] if row else 0
