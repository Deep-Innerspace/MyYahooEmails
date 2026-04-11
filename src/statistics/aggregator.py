"""
Pure SQL data aggregation functions for statistics and reports.

Every function takes a sqlite3.Connection as first argument (the caller
holds the get_db() context manager). This avoids opening/closing connections
repeatedly and lets report builders run multiple queries in one transaction.
"""
import json
import sqlite3
from datetime import datetime
from statistics import median
from typing import Any, Dict, List, Optional, Tuple


# ─────────────────────────── HELPERS ─────────────────────────────────────

def _period_expr(by: str) -> str:
    """Return a SQLite expression for period grouping."""
    if by == "year":
        return "strftime('%Y', e.date)"
    elif by == "quarter":
        return ("strftime('%Y', e.date) || '-Q' || "
                "((CAST(strftime('%m', e.date) AS INT) - 1) / 3 + 1)")
    elif by == "week":
        return "strftime('%Y-W%W', e.date)"
    else:  # month (default)
        return "strftime('%Y-%m', e.date)"


def _contact_addresses(conn: sqlite3.Connection, contact_email: str) -> List[str]:
    """Expand a contact email to all known addresses (primary + aliases)."""
    row = conn.execute(
        "SELECT email, aliases FROM contacts WHERE email = ?",
        (contact_email,),
    ).fetchone()
    if not row:
        # Try aliases
        row = conn.execute(
            "SELECT email, aliases FROM contacts WHERE aliases LIKE ?",
            (f"%{contact_email}%",),
        ).fetchone()
    if not row:
        return [contact_email]
    addrs = [row["email"]]
    try:
        addrs.extend(json.loads(row["aliases"]))
    except (json.JSONDecodeError, TypeError):
        pass
    return addrs


def _contact_where(conn: sqlite3.Connection, contact_email: Optional[str],
                   table_alias: str = "e") -> Tuple[str, list]:
    """Build WHERE fragment for contact filtering. Returns (clause, params)."""
    if not contact_email:
        return "", []
    addrs = _contact_addresses(conn, contact_email)
    placeholders = ",".join("?" for _ in addrs)
    clause = f"AND {table_alias}.from_address IN ({placeholders})"
    return clause, list(addrs)


def corpus_clause(corpus: Optional[str], table_alias: str = "e") -> Tuple[str, list]:
    """Build WHERE fragment for corpus filtering. Returns (clause, params).
    corpus='all' or None → no filter. corpus='personal'|'legal' → filter."""
    if not corpus or corpus == "all":
        return "", []
    return f"AND {table_alias}.corpus = ?", [corpus]


# ─────────────────────────── OVERVIEW ────────────────────────────────────

def overview_stats(conn: sqlite3.Connection,
                   corpus: Optional[str] = None) -> Dict[str, Any]:
    """Consolidated overview statistics as a dict."""
    cc, cp = corpus_clause(corpus)
    r = {}
    r["total"] = conn.execute(f"SELECT COUNT(*) FROM emails e WHERE 1=1 {cc}", cp).fetchone()[0]
    r["sent"] = conn.execute(f"SELECT COUNT(*) FROM emails e WHERE direction='sent' {cc}", cp).fetchone()[0]
    r["received"] = conn.execute(f"SELECT COUNT(*) FROM emails e WHERE direction='received' {cc}", cp).fetchone()[0]
    r["threads"] = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    r["french"] = conn.execute(f"SELECT COUNT(*) FROM emails e WHERE language='fr' {cc}", cp).fetchone()[0]
    r["english"] = conn.execute(f"SELECT COUNT(*) FROM emails e WHERE language='en' {cc}", cp).fetchone()[0]
    r["with_attachments"] = conn.execute(f"SELECT COUNT(*) FROM emails e WHERE has_attachments=1 {cc}", cp).fetchone()[0]

    dates = conn.execute(f"SELECT MIN(e.date), MAX(e.date) FROM emails e WHERE 1=1 {cc}", cp).fetchone()
    r["first_date"] = str(dates[0])[:10] if dates[0] else None
    r["last_date"] = str(dates[1])[:10] if dates[1] else None
    r["topics_count"] = conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0]
    r["runs_count"] = conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0]

    # Corpus breakdown (always show both for context)
    r["personal_count"] = conn.execute("SELECT COUNT(*) FROM emails WHERE corpus='personal'").fetchone()[0]
    r["legal_count"] = conn.execute("SELECT COUNT(*) FROM emails WHERE corpus='legal'").fetchone()[0]

    # Phase 2+3 analysis coverage — always scoped to personal corpus
    # (legal emails are professional correspondence; their tone/manipulation analysis
    #  is meaningless for the personal relationship evidence analysis)
    for atype in ("classify", "tone", "timeline", "manipulation"):
        r[f"{atype}_count"] = conn.execute(
            """SELECT COUNT(DISTINCT ar.email_id) FROM analysis_results ar
               JOIN analysis_runs ru ON ru.id=ar.run_id
               JOIN emails e ON e.id=ar.email_id
               WHERE ru.analysis_type=? AND e.corpus='personal'""",
            (atype,),
        ).fetchone()[0]
    r["contradiction_count"] = conn.execute("SELECT COUNT(*) FROM contradictions").fetchone()[0]
    r["procedure_events_count"] = conn.execute("SELECT COUNT(*) FROM procedure_events").fetchone()[0]
    r["timeline_events_count"] = conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]

    # Legal corpus analysis coverage
    r["legal_analysis_count"] = conn.execute(
        """SELECT COUNT(DISTINCT ar.email_id) FROM analysis_results ar
           JOIN analysis_runs ru ON ru.id=ar.run_id
           JOIN emails e ON e.id=ar.email_id
           WHERE ru.analysis_type='legal_analysis' AND e.corpus='legal'""",
    ).fetchone()[0]
    r["procedures_count"] = conn.execute("SELECT COUNT(*) FROM procedures").fetchone()[0]
    r["invoices_count"] = conn.execute("SELECT COUNT(*) FROM lawyer_invoices").fetchone()[0]

    return r


# ─────────────────────────── FREQUENCY ───────────────────────────────────

def frequency_data(conn: sqlite3.Connection, by: str = "month",
                   contact_email: Optional[str] = None,
                   corpus: Optional[str] = None) -> List[Dict]:
    """Email frequency grouped by time period. Returns list of dicts."""
    period_expr = _period_expr(by)
    contact_clause, contact_params = _contact_where(conn, contact_email)
    cc, cp = corpus_clause(corpus)

    rows = conn.execute(
        f"""SELECT {period_expr} AS period,
                   SUM(CASE WHEN e.direction='sent' THEN 1 ELSE 0 END) AS sent,
                   SUM(CASE WHEN e.direction='received' THEN 1 ELSE 0 END) AS received,
                   COUNT(*) AS total
            FROM emails e
            WHERE 1=1 {contact_clause} {cc}
            GROUP BY period ORDER BY period""",
        contact_params + cp,
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────── RESPONSE TIMES ──────────────────────────────

def response_times(conn: sqlite3.Connection,
                   contact_email: Optional[str] = None,
                   since: Optional[datetime] = None,
                   by: Optional[str] = None,
                   corpus: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute intra-thread response delays between parties.

    Only considers threads where both sent and received emails exist.
    Returns: {your_response: {avg, median, max, count},
              their_response: {avg, median, max, count},
              by_period: [...] if by is set}
    """
    since_clause = "AND e1.date >= ?" if since else ""
    since_params = [since.isoformat()] if since else []
    cc, cp = corpus_clause(corpus, table_alias="e1")

    # Get all cross-direction response pairs
    rows = conn.execute(
        f"""WITH thread_pairs AS (
                SELECT
                    e1.thread_id,
                    e1.date AS sent_at,
                    e1.direction AS dir_from,
                    e2.date AS replied_at,
                    e2.direction AS dir_to,
                    (julianday(e2.date) - julianday(e1.date)) * 24.0 AS hours_delay
                FROM emails e1
                JOIN emails e2 ON e2.thread_id = e1.thread_id
                    AND e2.date = (
                        SELECT MIN(e3.date) FROM emails e3
                        WHERE e3.thread_id = e1.thread_id
                        AND e3.date > e1.date
                    )
                WHERE e1.thread_id IS NOT NULL
                  AND e1.direction != e2.direction
                  AND (julianday(e2.date) - julianday(e1.date)) * 24.0 > 0
                  AND (julianday(e2.date) - julianday(e1.date)) * 24.0 < 8760
                  {since_clause} {cc}
            )
            SELECT dir_from, dir_to, hours_delay
            FROM thread_pairs
            ORDER BY dir_from, hours_delay""",
        since_params + cp,
    ).fetchall()

    # Separate by who responded
    your_delays = []  # You responded to their email (dir_from=received, dir_to=sent)
    their_delays = []  # They responded to your email (dir_from=sent, dir_to=received)

    for r in rows:
        h = r["hours_delay"]
        if r["dir_from"] == "received" and r["dir_to"] == "sent":
            your_delays.append(h)
        elif r["dir_from"] == "sent" and r["dir_to"] == "received":
            their_delays.append(h)

    def _stats(delays: List[float]) -> Dict:
        if not delays:
            return {"avg_hours": 0, "median_hours": 0, "max_hours": 0, "count": 0}
        return {
            "avg_hours": round(sum(delays) / len(delays), 1),
            "median_hours": round(median(delays), 1),
            "max_hours": round(max(delays), 1),
            "count": len(delays),
        }

    result: Dict[str, Any] = {
        "your_response": _stats(your_delays),
        "their_response": _stats(their_delays),
    }

    # Optional period breakdown
    if by:
        period_expr = _period_expr(by).replace("e.date", "e1.date")
        period_rows = conn.execute(
            f"""WITH thread_pairs AS (
                    SELECT
                        e1.thread_id,
                        {period_expr.replace('e.date', 'e1.date')} AS period,
                        e1.direction AS dir_from,
                        e2.direction AS dir_to,
                        (julianday(e2.date) - julianday(e1.date)) * 24.0 AS hours_delay
                    FROM emails e1
                    JOIN emails e2 ON e2.thread_id = e1.thread_id
                        AND e2.date = (
                            SELECT MIN(e3.date) FROM emails e3
                            WHERE e3.thread_id = e1.thread_id
                            AND e3.date > e1.date
                        )
                    WHERE e1.thread_id IS NOT NULL
                      AND e1.direction != e2.direction
                      AND (julianday(e2.date) - julianday(e1.date)) * 24.0 > 0
                      AND (julianday(e2.date) - julianday(e1.date)) * 24.0 < 8760
                      {since_clause} {cc}
                )
                SELECT period, dir_from, dir_to,
                       AVG(hours_delay) AS avg_hours,
                       COUNT(*) AS cnt
                FROM thread_pairs
                GROUP BY period, dir_from, dir_to
                ORDER BY period""",
            since_params + cp,
        ).fetchall()

        # Pivot into {period: {your_avg, their_avg}}
        periods: Dict[str, Dict] = {}
        for r in period_rows:
            p = r["period"]
            if p not in periods:
                periods[p] = {"period": p, "your_avg": 0, "their_avg": 0}
            if r["dir_from"] == "received":
                periods[p]["your_avg"] = round(r["avg_hours"], 1)
            else:
                periods[p]["their_avg"] = round(r["avg_hours"], 1)

        result["by_period"] = list(periods.values())

    return result


# ─────────────────────────── TONE TRENDS ─────────────────────────────────

def tone_trends(conn: sqlite3.Connection, by: str = "month",
                contact_email: Optional[str] = None,
                direction: Optional[str] = None,
                corpus: Optional[str] = None) -> List[Dict]:
    """Aggression/manipulation averages over time, split by direction."""
    period_expr = _period_expr(by)
    contact_clause, contact_params = _contact_where(conn, contact_email)
    dir_clause = "AND e.direction = ?" if direction else ""
    dir_params = [direction] if direction else []
    cc, cp = corpus_clause(corpus)

    rows = conn.execute(
        f"""SELECT {period_expr} AS period,
                   e.direction,
                   AVG(json_extract(ar.result_json, '$.aggression_level')) AS avg_aggression,
                   AVG(json_extract(ar.result_json, '$.manipulation_score')) AS avg_manipulation,
                   COUNT(*) AS email_count
            FROM analysis_results ar
            JOIN analysis_runs r ON r.id = ar.run_id
            JOIN emails e ON e.id = ar.email_id
            WHERE r.analysis_type = 'tone'
              AND r.status IN ('complete', 'partial')
              {contact_clause}
              {dir_clause}
              {cc}
            GROUP BY period, e.direction
            ORDER BY period, e.direction""",
        contact_params + dir_params + cp,
    ).fetchall()
    return [
        {
            "period": r["period"],
            "direction": r["direction"],
            "avg_aggression": round(r["avg_aggression"] or 0, 3),
            "avg_manipulation": round(r["avg_manipulation"] or 0, 3),
            "count": r["email_count"],
        }
        for r in rows
    ]


# ─────────────────────────── TOPIC EVOLUTION ─────────────────────────────

# Topics that are system/admin classifications — excluded from charts & topic tables
SYSTEM_TOPICS = {"trop_court", "non_classifiable"}


def topic_evolution(conn: sqlite3.Connection, by: str = "month",
                    topic_name: Optional[str] = None,
                    corpus: Optional[str] = None) -> List[Dict]:
    """Topic prevalence over time (system topics excluded)."""
    period_expr = _period_expr(by)
    topic_clause = "AND t.name = ?" if topic_name else ""
    topic_params = [topic_name] if topic_name else []
    cc, cp = corpus_clause(corpus)

    rows = conn.execute(
        f"""SELECT {period_expr} AS period,
                   t.name AS topic,
                   COUNT(DISTINCT et.email_id) AS email_count
            FROM email_topics et
            JOIN topics t ON t.id = et.topic_id
            JOIN emails e ON e.id = et.email_id
            WHERE t.name NOT IN ('trop_court', 'non_classifiable') {topic_clause} {cc}
            GROUP BY period, t.name
            ORDER BY period, t.name""",
        topic_params + cp,
    ).fetchall()
    return [dict(r) for r in rows]


def system_topic_counts(conn: sqlite3.Connection,
                        corpus: Optional[str] = None) -> dict:
    """Return counts for trop_court and non_classifiable topics."""
    cc, cp = corpus_clause(corpus)
    rows = conn.execute(
        f"""SELECT t.name, COUNT(DISTINCT et.email_id) AS cnt
           FROM email_topics et
           JOIN topics t ON t.id = et.topic_id
           JOIN emails e ON e.id = et.email_id
           WHERE t.name IN ('trop_court', 'non_classifiable') {cc}
           GROUP BY t.name""",
        cp,
    ).fetchall()
    result = {"trop_court": 0, "non_classifiable": 0}
    for r in rows:
        result[r["name"]] = r["cnt"]
    return result


# ─────────────────────────── CONTACT SUMMARY ─────────────────────────────

def contact_summary(conn: sqlite3.Connection,
                    contact_email: Optional[str] = None,
                    sort_by: str = "count") -> List[Dict]:
    """Per-contact activity summary."""
    where = ""
    params: list = []
    if contact_email:
        where = "WHERE c.email = ? OR c.aliases LIKE ?"
        params = [contact_email, f"%{contact_email}%"]

    sort_col = "total_emails DESC" if sort_by == "count" else "last_email DESC"

    rows = conn.execute(
        f"""SELECT c.id, c.name, c.email, c.aliases, c.role,
                   c.firm_name, c.bar_jurisdiction, c.notes,
                   COUNT(e.id) AS total_emails,
                   SUM(CASE WHEN e.direction='sent' THEN 1 ELSE 0 END) AS sent,
                   SUM(CASE WHEN e.direction='received' THEN 1 ELSE 0 END) AS received,
                   SUM(CASE WHEN e.corpus='personal' THEN 1 ELSE 0 END) AS personal_emails,
                   SUM(CASE WHEN e.corpus='legal' THEN 1 ELSE 0 END) AS legal_emails,
                   MIN(e.date) AS first_email,
                   MAX(e.date) AS last_email
            FROM contacts c
            LEFT JOIN emails e ON e.contact_id = c.id
            {where}
            GROUP BY c.id
            ORDER BY {sort_col}""",
        params,
    ).fetchall()

    results = []
    for r in rows:
        # Top 3 topics for this contact
        top_topics = conn.execute(
            """SELECT t.name, COUNT(*) AS cnt
               FROM email_topics et
               JOIN topics t ON t.id = et.topic_id
               JOIN emails e ON e.id = et.email_id
               WHERE e.contact_id = ?
               GROUP BY t.name ORDER BY cnt DESC LIMIT 3""",
            (r["id"],),
        ).fetchall()

        try:
            aliases = json.loads(r["aliases"]) if r["aliases"] else []
        except (json.JSONDecodeError, TypeError):
            aliases = []

        results.append({
            "id": r["id"],
            "name": r["name"],
            "email": r["email"],
            "aliases": aliases,
            "role": r["role"],
            "firm_name": r["firm_name"] or "",
            "bar_jurisdiction": r["bar_jurisdiction"] or "",
            "notes": r["notes"] or "",
            "total": r["total_emails"] or 0,
            "sent": r["sent"] or 0,
            "received": r["received"] or 0,
            "personal_emails": r["personal_emails"] or 0,
            "legal_emails": r["legal_emails"] or 0,
            "first_email": str(r["first_email"])[:10] if r["first_email"] else None,
            "last_email": str(r["last_email"])[:10] if r["last_email"] else None,
            "top_topics": [t["name"] for t in top_topics],
        })
    return results


def unassigned_senders(conn: sqlite3.Connection, min_count: int = 1) -> List[Dict]:
    """Return from_addresses with email activity but no contact_id, sorted by email count."""
    rows = conn.execute(
        """SELECT from_address,
                  COUNT(*) AS total,
                  SUM(CASE WHEN direction='sent' THEN 1 ELSE 0 END) AS sent,
                  SUM(CASE WHEN direction='received' THEN 1 ELSE 0 END) AS received,
                  MIN(date) AS first_email,
                  MAX(date) AS last_email
           FROM emails
           WHERE contact_id IS NULL
           GROUP BY from_address
           HAVING total >= ?
           ORDER BY total DESC""",
        (min_count,),
    ).fetchall()
    return [
        {
            "from_address": r["from_address"],
            "total": r["total"],
            "sent": r["sent"],
            "received": r["received"],
            "first_email": str(r["first_email"])[:10] if r["first_email"] else None,
            "last_email": str(r["last_email"])[:10] if r["last_email"] else None,
            "domain": r["from_address"].split("@")[-1] if "@" in r["from_address"] else "",
        }
        for r in rows
    ]


# ─────────────────────────── MERGED TIMELINE ─────────────────────────────

def merged_timeline(conn: sqlite3.Connection,
                    since: Optional[str] = None,
                    until: Optional[str] = None,
                    significance: Optional[str] = None,
                    corpus: Optional[str] = None) -> List[Dict]:
    """Merge timeline_events + procedure_events + lawyer_invoices into one
    chronological list.

    Sources:
      'email'   — extracted events from personal email analysis (timeline_events)
      'court'   — procedure events (hearings, judgments, filings)
      'invoice' — lawyer invoice dates with amounts

    *corpus* filters timeline events by the source email's corpus
    ('personal', 'legal', or None/'all' for no filter).
    All court and invoice events are always included regardless of corpus filter.
    """
    sig_clause = ""
    sig_params: list = []
    if significance:
        sig_levels = {"low": 0, "medium": 1, "high": 2}
        min_sig = sig_levels.get(significance, 0)
        sig_clause = "AND te.significance IN ('high'" + (", 'medium'" if min_sig <= 1 else "") + (", 'low'" if min_sig == 0 else "") + ")"

    date_clause_te = ""
    date_clause_ce = ""
    date_clause_inv = ""
    date_params_te: list = []
    date_params_ce: list = []
    date_params_inv: list = []
    if since:
        date_clause_te += " AND te.event_date >= ?"
        date_clause_ce += " AND pe.event_date >= ?"
        date_clause_inv += " AND li.invoice_date >= ?"
        date_params_te.append(since)
        date_params_ce.append(since)
        date_params_inv.append(since)
    if until:
        date_clause_te += " AND te.event_date <= ?"
        date_clause_ce += " AND pe.event_date <= ?"
        date_clause_inv += " AND li.invoice_date <= ?"
        date_params_te.append(until)
        date_params_ce.append(until)
        date_params_inv.append(until)

    cc, cp = corpus_clause(corpus, table_alias="e")

    # Timeline events from email analysis — include avg aggression for context
    te_rows = conn.execute(
        f"""SELECT te.event_date AS date, 'email' AS source,
                   te.event_type AS type, te.description,
                   te.significance, t.name AS topic, te.email_id,
                   NULL AS procedure_id, NULL AS procedure_name,
                   NULL AS amount_ttc, NULL AS aggression
            FROM timeline_events te
            JOIN emails e ON e.id = te.email_id
            LEFT JOIN topics t ON t.id = te.topic_id
            WHERE 1=1 {sig_clause} {date_clause_te} {cc}
            ORDER BY te.event_date""",
        sig_params + date_params_te + cp,
    ).fetchall()

    # Procedure events (hearings, judgments, filings)
    ce_rows = conn.execute(
        f"""SELECT pe.event_date AS date, 'court' AS source,
                   pe.event_type AS type,
                   pe.description AS description,
                   'high' AS significance, NULL AS topic,
                   pe.source_email_id AS email_id,
                   pe.procedure_id, p.name AS procedure_name,
                   NULL AS amount_ttc, NULL AS aggression
            FROM procedure_events pe
            LEFT JOIN procedures p ON p.id = pe.procedure_id
            WHERE 1=1 {date_clause_ce}
            ORDER BY pe.event_date""",
        date_params_ce,
    ).fetchall()

    # Lawyer invoice events
    inv_rows = conn.execute(
        f"""SELECT li.invoice_date AS date, 'invoice' AS source,
                   'invoice' AS type,
                   c.name || ' — ' || COALESCE(li.description, '') || ' (' || COALESCE(p.name, 'no procedure') || ')' AS description,
                   'medium' AS significance, NULL AS topic,
                   li.email_id, li.procedure_id, p.name AS procedure_name,
                   li.amount_ttc, NULL AS aggression
            FROM lawyer_invoices li
            JOIN contacts c ON c.id = li.contact_id
            LEFT JOIN procedures p ON p.id = li.procedure_id
            WHERE 1=1 {date_clause_inv}
            ORDER BY li.invoice_date""",
        date_params_inv,
    ).fetchall()

    # Merge and sort — cast date to str to handle SQLite integer coercion of
    # year-only values like 2015 stored in TIMESTAMP columns
    all_events = [dict(r) for r in te_rows] + [dict(r) for r in ce_rows] + [dict(r) for r in inv_rows]
    for ev in all_events:
        if ev["date"] is not None:
            ev["date"] = str(ev["date"])
    all_events.sort(key=lambda x: x["date"] or "")
    return all_events


def dossier_timeline(conn: sqlite3.Connection,
                     since: Optional[str] = None,
                     until: Optional[str] = None) -> List[Dict]:
    """Return procedures with their nested events for the dossier view.

    Each procedure dict contains:
      - procedure metadata (id, name, type, jurisdiction, case_number, status,
        date_start, date_end, outcome_summary)
      - 'events': list of procedure_events sorted by date
      - 'email_count': personal emails within the procedure date range
      - 'invoice_total': total lawyer costs for this procedure
      - 'aggression_before': avg aggression ±30 days before first event
      - 'aggression_during': avg aggression within procedure date range
    """
    date_clause_p = ""
    date_params_p: list = []
    if since:
        date_clause_p += " AND (p.date_end IS NULL OR p.date_end >= ?)"
        date_params_p.append(since)
    if until:
        date_clause_p += " AND (p.date_start IS NULL OR p.date_start <= ?)"
        date_params_p.append(until)

    procs = conn.execute(
        f"""SELECT p.id, p.name, p.procedure_type, p.jurisdiction, p.case_number,
                   p.status, p.date_start, p.date_end, p.outcome_summary, p.description
              FROM procedures p
             WHERE 1=1 {date_clause_p}
             ORDER BY COALESCE(p.date_start, '9999') ASC""",
        date_params_p,
    ).fetchall()

    result = []
    for proc in procs:
        p = dict(proc)
        pid = p["id"]

        # Procedure events
        events = conn.execute(
            """SELECT pe.id, pe.event_date, pe.event_type, pe.description,
                      pe.outcome, pe.jurisdiction, pe.date_precision,
                      pe.source_email_id, pe.notes
                 FROM procedure_events pe
                WHERE pe.procedure_id = ?
                ORDER BY pe.event_date""",
            (pid,),
        ).fetchall()
        p["events"] = [dict(e) for e in events]

        # Invoice total
        inv = conn.execute(
            "SELECT COALESCE(SUM(amount_ttc), 0) FROM lawyer_invoices WHERE procedure_id = ?",
            (pid,),
        ).fetchone()[0]
        p["invoice_total"] = inv

        # Email count (emails FK-linked to this procedure — legal corpus)
        p["email_count"] = conn.execute(
            "SELECT COUNT(*) FROM emails WHERE procedure_id = ?",
            (pid,),
        ).fetchone()[0]

        # Aggression during procedure (personal emails in date range)
        if p["date_start"]:
            date_end = p["date_end"] or "2099-12-31"
            agg = conn.execute(
                """SELECT AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level') AS REAL))
                     FROM analysis_results ar
                     JOIN analysis_runs ru ON ru.id = ar.run_id
                     JOIN emails e ON e.id = ar.email_id
                    WHERE ru.analysis_type = 'tone'
                      AND e.corpus = 'personal'
                      AND e.date >= ? AND e.date <= ?""",
                (p["date_start"], date_end),
            ).fetchone()[0]
            p["aggression_during"] = round(agg, 2) if agg is not None else None
        else:
            p["aggression_during"] = None

        result.append(p)

    return result


def court_event_window_aggression(conn: sqlite3.Connection,
                                  event_date: str,
                                  window_days: int = 14) -> Dict:
    """Return personal email aggression stats ±window_days around a court event date."""
    agg_before = conn.execute(
        """SELECT AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level') AS REAL)),
                  COUNT(*)
             FROM analysis_results ar
             JOIN analysis_runs ru ON ru.id = ar.run_id
             JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'tone'
              AND e.corpus = 'personal'
              AND e.date >= DATE(?, '-' || ? || ' days')
              AND e.date < ?""",
        (event_date, window_days, event_date),
    ).fetchone()
    agg_after = conn.execute(
        """SELECT AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level') AS REAL)),
                  COUNT(*)
             FROM analysis_results ar
             JOIN analysis_runs ru ON ru.id = ar.run_id
             JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'tone'
              AND e.corpus = 'personal'
              AND e.date > ?
              AND e.date <= DATE(?, '+' || ? || ' days')""",
        (event_date, event_date, window_days),
    ).fetchone()
    agg_base = conn.execute(
        """SELECT AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level') AS REAL))
             FROM analysis_results ar
             JOIN analysis_runs ru ON ru.id = ar.run_id
             JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'tone' AND e.corpus = 'personal'""",
    ).fetchone()[0]

    def _fmt(row):
        avg, cnt = row
        return {"avg": round(avg, 2) if avg is not None else None, "count": cnt or 0}

    return {
        "before": _fmt(agg_before),
        "after": _fmt(agg_after),
        "baseline": round(agg_base, 2) if agg_base is not None else None,
    }


# ──────────────────── SYSTEMATIC PROCEDURE CORRELATIONS ──────────────────


def all_procedure_event_correlations(
    conn: sqlite3.Connection,
    window_days: int = 14,
    since: Optional[str] = None,
    until: Optional[str] = None,
    event_type: Optional[str] = "conclusions_received",
) -> Dict[str, Any]:
    """Batch-compute before/after aggression + manipulation for procedure events.

    event_type: filter to a specific event type (default: 'conclusions_received').
                Pass None to include all event types.
    since/until filter which *procedure events* are analyzed (not the email windows).

    Returns a dict with:
        correlations  — list of per-event rows, sorted by event_date asc
        summary       — aggregate stats (total, spikes, drops, avg_delta)
        baseline_agg / baseline_manip — corpus-wide averages
        window_days / event_type      — params used
    """
    # Corpus-wide baselines
    base = conn.execute(
        """SELECT AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level') AS REAL)),
                  AVG(CAST(JSON_EXTRACT(ar.result_json, '$.manipulation_score') AS REAL))
             FROM analysis_results ar
             JOIN analysis_runs ru ON ru.id = ar.run_id
             JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'tone' AND e.corpus = 'personal'"""
    ).fetchone()
    baseline_agg   = round(base[0], 3) if base[0] is not None else None
    baseline_manip = round(base[1], 3) if base[1] is not None else None

    wheres, params = [], []
    wheres.append("pe.event_date IS NOT NULL AND pe.event_date != ''")
    if event_type:
        wheres.append("pe.event_type = ?")
        params.append(event_type)
    if since:
        wheres.append("pe.event_date >= ?")
        params.append(since)
    if until:
        wheres.append("pe.event_date <= ?")
        params.append(until)
    where_clause = "WHERE " + " AND ".join(wheres)

    events = conn.execute(
        f"""SELECT pe.id, pe.event_date, pe.event_type, pe.description,
                  pe.procedure_id, p.name AS procedure_name
             FROM procedure_events pe
             JOIN procedures p ON p.id = pe.procedure_id
            {where_clause}
            ORDER BY pe.event_date""",
        params,
    ).fetchall()

    correlations = []
    for ev in events:
        ev = dict(ev)
        ed = ev["event_date"][:10]

        b = conn.execute(
            """SELECT COUNT(*),
                      AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level')  AS REAL)),
                      AVG(CAST(JSON_EXTRACT(ar.result_json, '$.manipulation_score') AS REAL))
                 FROM analysis_results ar
                 JOIN analysis_runs ru ON ru.id = ar.run_id
                 JOIN emails e ON e.id = ar.email_id
                WHERE ru.analysis_type = 'tone' AND e.corpus = 'personal'
                  AND e.date >= DATE(?, '-' || ? || ' days') AND e.date < ?""",
            (ed, window_days, ed),
        ).fetchone()

        a = conn.execute(
            """SELECT COUNT(*),
                      AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level')  AS REAL)),
                      AVG(CAST(JSON_EXTRACT(ar.result_json, '$.manipulation_score') AS REAL))
                 FROM analysis_results ar
                 JOIN analysis_runs ru ON ru.id = ar.run_id
                 JOIN emails e ON e.id = ar.email_id
                WHERE ru.analysis_type = 'tone' AND e.corpus = 'personal'
                  AND e.date > ? AND e.date <= DATE(?, '+' || ? || ' days')""",
            (ed, ed, window_days),
        ).fetchone()

        b_cnt, b_agg, b_manip = b
        a_cnt, a_agg, a_manip = a

        if not b_cnt and not a_cnt:
            continue  # no personal emails nearby — skip

        def _r(v):
            return round(v, 3) if v is not None else None

        agg_delta = _r(a_agg - b_agg) if a_agg is not None and b_agg is not None else (
            _r(a_agg - baseline_agg) if a_agg is not None and baseline_agg is not None else None
        )
        manip_delta = _r(a_manip - b_manip) if a_manip is not None and b_manip is not None else None

        correlations.append({
            "event_id":      ev["id"],
            "procedure_id":  ev["procedure_id"],
            "procedure_name": ev["procedure_name"],
            "event_date":    ed,
            "event_type":    ev["event_type"],
            "description":   ev["description"],
            "before_count":  b_cnt or 0,
            "before_agg":    _r(b_agg),
            "before_manip":  _r(b_manip),
            "after_count":   a_cnt or 0,
            "after_agg":     _r(a_agg),
            "after_manip":   _r(a_manip),
            "agg_delta":     agg_delta,
            "manip_delta":   manip_delta,
        })

    deltas = [c["agg_delta"] for c in correlations if c["agg_delta"] is not None]
    # Chronological order — for conclusions this is the natural reading order
    correlations.sort(key=lambda c: c["event_date"])

    return {
        "correlations":    correlations,
        "summary": {
            "total":      len(correlations),
            "with_spike": sum(1 for d in deltas if d > 0.05),
            "with_drop":  sum(1 for d in deltas if d < -0.05),
            "avg_delta":  round(sum(deltas) / len(deltas), 3) if deltas else None,
        },
        "baseline_agg":   baseline_agg,
        "baseline_manip": baseline_manip,
        "window_days":    window_days,
        "event_type":     event_type,
    }


def pre_conclusion_behavior(
    conn: sqlite3.Connection,
    window_days: int = 30,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze personal email behavior in the window before adverse conclusions.

    Targets procedure_events with event_type = 'conclusions_received'.
    since/until filter which conclusion events are included.
    Returns aggression + manipulation + frequency stats per conclusion,
    plus aggregate summary.
    """
    date_wheres, date_params = [], []
    if since:
        date_wheres.append("pe.event_date >= ?")
        date_params.append(since)
    if until:
        date_wheres.append("pe.event_date <= ?")
        date_params.append(until)
    date_clause = ("AND " + " AND ".join(date_wheres)) if date_wheres else ""

    conclusions = conn.execute(
        f"""SELECT pe.id, pe.event_date, pe.description,
                  pe.procedure_id, p.name AS procedure_name
             FROM procedure_events pe
             JOIN procedures p ON p.id = pe.procedure_id
            WHERE pe.event_type = 'conclusions_received'
              AND pe.event_date IS NOT NULL AND pe.event_date != ''
              {date_clause}
            ORDER BY pe.event_date""",
        date_params,
    ).fetchall()

    base = conn.execute(
        """SELECT AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level') AS REAL)),
                  AVG(CAST(JSON_EXTRACT(ar.result_json, '$.manipulation_score') AS REAL))
             FROM analysis_results ar
             JOIN analysis_runs ru ON ru.id = ar.run_id
             JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'tone' AND e.corpus = 'personal'"""
    ).fetchone()
    baseline_agg   = round(base[0], 3) if base[0] is not None else None
    baseline_manip = round(base[1], 3) if base[1] is not None else None

    results = []
    for c in conclusions:
        c = dict(c)
        ed = c["event_date"][:10]

        win = conn.execute(
            """SELECT COUNT(*),
                      AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level')  AS REAL)),
                      AVG(CAST(JSON_EXTRACT(ar.result_json, '$.manipulation_score') AS REAL)),
                      MAX(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level')  AS REAL))
                 FROM analysis_results ar
                 JOIN analysis_runs ru ON ru.id = ar.run_id
                 JOIN emails e ON e.id = ar.email_id
                WHERE ru.analysis_type = 'tone' AND e.corpus = 'personal'
                  AND e.date >= DATE(?, '-' || ? || ' days') AND e.date < ?""",
            (ed, window_days, ed),
        ).fetchone()

        w7 = conn.execute(
            """SELECT COUNT(*),
                      AVG(CAST(JSON_EXTRACT(ar.result_json, '$.aggression_level') AS REAL))
                 FROM analysis_results ar
                 JOIN analysis_runs ru ON ru.id = ar.run_id
                 JOIN emails e ON e.id = ar.email_id
                WHERE ru.analysis_type = 'tone' AND e.corpus = 'personal'
                  AND e.date >= DATE(?, '-7 days') AND e.date < ?""",
            (ed, ed),
        ).fetchone()

        cnt, avg_agg, avg_manip, max_agg = win
        w7_cnt, w7_agg = w7

        def _r(v):
            return round(v, 3) if v is not None else None

        agg_vs_baseline = (
            _r(avg_agg - baseline_agg)
            if avg_agg is not None and baseline_agg is not None
            else None
        )

        results.append({
            "event_id":       c["id"],
            "procedure_id":   c["procedure_id"],
            "procedure_name": c["procedure_name"],
            "event_date":     ed,
            "description":    c["description"],
            "window_count":   cnt or 0,
            "window_agg":     _r(avg_agg),
            "window_manip":   _r(avg_manip),
            "max_agg":        _r(max_agg),
            "week7_count":    w7_cnt or 0,
            "week7_agg":      _r(w7_agg),
            "agg_vs_baseline": agg_vs_baseline,
        })

    vals = [r["window_agg"] for r in results if r["window_agg"] is not None]
    above_baseline = [r for r in results if (r["agg_vs_baseline"] or 0) > 0.02]

    return {
        "conclusions": results,
        "summary": {
            "total":          len(results),
            "with_data":      sum(1 for r in results if r["window_count"] > 0),
            "above_baseline": len(above_baseline),
            "avg_window_agg": round(sum(vals) / len(vals), 3) if vals else None,
        },
        "baseline_agg":   baseline_agg,
        "baseline_manip": baseline_manip,
        "window_days":    window_days,
    }


# ─────────────────────────── CONTRADICTIONS ──────────────────────────────

def contradiction_summary(conn: sqlite3.Connection,
                          severity: Optional[str] = None,
                          scope: Optional[str] = None,
                          topic: Optional[str] = None) -> Dict[str, Any]:
    """Contradiction statistics and items.

    Topic is resolved from COALESCE(c.topic, t.name) to handle both the
    Excel-import path (c.topic TEXT) and the automated pipeline (c.topic_id FK).
    """
    wheres = []
    params: list = []
    if severity:
        wheres.append("c.severity = ?")
        params.append(severity)
    if scope:
        wheres.append("c.scope = ?")
        params.append(scope)
    if topic:
        wheres.append("COALESCE(c.topic, t.name) = ?")
        params.append(topic)
    where = ("WHERE " + " AND ".join(wheres)) if wheres else ""

    # Summary counts (unfiltered — always show totals in the header badges)
    total_all = conn.execute("SELECT COUNT(*) FROM contradictions").fetchone()[0]
    by_severity = {}
    for sev in ("high", "medium", "low"):
        cnt = conn.execute(
            "SELECT COUNT(*) FROM contradictions WHERE severity = ?", (sev,)
        ).fetchone()[0]
        by_severity[sev] = cnt

    by_scope = {}
    for sc in ("intra-sender", "cross-sender"):
        cnt = conn.execute(
            "SELECT COUNT(*) FROM contradictions WHERE scope = ?", (sc,)
        ).fetchone()[0]
        by_scope[sc] = cnt

    # Filtered total (for "N results" label)
    filtered_total = conn.execute(
        f"""SELECT COUNT(*) FROM contradictions c
            LEFT JOIN topics t ON t.id = c.topic_id
            {where}""",
        params,
    ).fetchone()[0]

    # Available topics for filter dropdown (with counts)
    # Exclude system-marker topics (trop_court, non_classifiable) — not real email topics
    topic_rows = conn.execute(
        """SELECT COALESCE(c.topic, t.name) AS topic_name, COUNT(*) AS cnt
           FROM contradictions c
           LEFT JOIN topics t ON t.id = c.topic_id
           WHERE COALESCE(c.topic, t.name) IS NOT NULL
             AND COALESCE(c.topic, t.name) NOT IN ('trop_court', 'non_classifiable')
           GROUP BY topic_name
           ORDER BY cnt DESC, topic_name ASC"""
    ).fetchall()

    # Detailed items — include model info from analysis_runs
    items = conn.execute(
        f"""SELECT c.id, c.email_id_a, c.email_id_b, c.scope, c.severity,
                   c.explanation,
                   COALESCE(c.topic, t.name) AS topic,
                   ar.provider_name, ar.model_id,
                   ea.date AS date_a, ea.subject AS subject_a, ea.direction AS dir_a,
                   eb.date AS date_b, eb.subject AS subject_b, eb.direction AS dir_b
            FROM contradictions c
            LEFT JOIN topics t ON t.id = c.topic_id
            LEFT JOIN analysis_runs ar ON ar.id = c.run_id
            JOIN emails ea ON ea.id = c.email_id_a
            JOIN emails eb ON eb.id = c.email_id_b
            {where}
            ORDER BY CASE c.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                     c.created_at DESC""",
        params,
    ).fetchall()

    return {
        "total": total_all,
        "filtered_total": filtered_total,
        "by_severity": by_severity,
        "by_scope": by_scope,
        "topics": [dict(r) for r in topic_rows],
        "items": [dict(r) for r in items],
    }


# ─────────────────────────── TOP AGGRESSIVE ──────────────────────────────

def top_aggressive_emails(conn: sqlite3.Connection, limit: int = 10,
                          corpus: Optional[str] = None) -> List[Dict]:
    """Most aggressive emails by tone score."""
    cc, cp = corpus_clause(corpus)
    rows = conn.execute(
        f"""SELECT e.id, e.date, e.direction, e.subject, e.from_address,
                  json_extract(ar.result_json, '$.aggression_level') AS aggression,
                  json_extract(ar.result_json, '$.manipulation_score') AS manipulation,
                  json_extract(ar.result_json, '$.tone') AS tone,
                  json_extract(ar.result_json, '$.key_phrases') AS key_phrases
           FROM analysis_results ar
           JOIN analysis_runs r ON r.id = ar.run_id
           JOIN emails e ON e.id = ar.email_id
           WHERE r.analysis_type = 'tone' {cc}
           ORDER BY aggression DESC
           LIMIT ?""",
        cp + [limit],
    ).fetchall()
    results = []
    for r in rows:
        kp = r["key_phrases"]
        try:
            kp = json.loads(kp) if kp else []
        except (json.JSONDecodeError, TypeError):
            kp = []
        results.append({
            "id": r["id"],
            "date": str(r["date"])[:10],
            "direction": r["direction"],
            "subject": r["subject"],
            "from_address": r["from_address"],
            "aggression": round(float(r["aggression"] or 0), 3),
            "manipulation": round(float(r["manipulation"] or 0), 3),
            "tone": r["tone"] or "",
            "key_phrases": kp,
        })
    return results


# ─────────────────────────── METHODOLOGY ─────────────────────────────────

def daily_avg_by_year(conn: sqlite3.Connection,
                      corpus: Optional[str] = None) -> List[Dict]:
    """Average emails per day (sent + received) for each calendar year.

    Returns list of dicts with keys:
        year, sent_count, received_count, days_in_year,
        sent_per_day, received_per_day, ratio (sent/received, None if 0 received)
    """
    cc, cp = corpus_clause(corpus, table_alias="e")
    rows = conn.execute(
        f"""SELECT strftime('%Y', e.date) AS year,
                  SUM(CASE WHEN e.direction='sent'     THEN 1 ELSE 0 END) AS sent_count,
                  SUM(CASE WHEN e.direction='received' THEN 1 ELSE 0 END) AS received_count,
                  COUNT(*) AS total_count,
                  CAST(julianday(strftime('%Y', e.date) || '-12-31')
                       - julianday(strftime('%Y', e.date) || '-01-01') + 1 AS REAL) AS days_in_year
           FROM emails e
           WHERE e.date IS NOT NULL {cc}
           GROUP BY year
           ORDER BY year""",
        cp,
    ).fetchall()
    result = []
    for r in rows:
        sent_pd  = round(r["sent_count"]     / r["days_in_year"], 3)
        recv_pd  = round(r["received_count"] / r["days_in_year"], 3)
        ratio    = round(sent_pd / recv_pd, 2) if recv_pd > 0 else None
        result.append({
            "year":          r["year"],
            "sent_count":    r["sent_count"],
            "received_count":r["received_count"],
            "days_in_year":  int(r["days_in_year"]),
            "sent_per_day":  sent_pd,
            "received_per_day": recv_pd,
            "ratio":         ratio,
        })
    return result


# ─────────────────────────── MANIPULATION CHARTS ─────────────────────────

def manipulation_timeline(conn: sqlite3.Connection, by: str = "quarter",
                          direction: Optional[str] = None,
                          corpus: Optional[str] = None) -> List[Dict]:
    """Avg manipulation score over time, split by direction (>0 scores only)."""
    period_expr = _period_expr(by)
    dir_clause = "AND e.direction = ?" if direction and direction != "all" else ""
    dir_params = [direction] if direction and direction != "all" else []
    cc, cp = corpus_clause(corpus)

    rows = conn.execute(
        f"""SELECT {period_expr} AS period,
                   e.direction,
                   AVG(json_extract(ar.result_json, '$.total_score')) AS avg_score,
                   COUNT(*) AS email_count
            FROM analysis_results ar
            JOIN analysis_runs ru ON ru.id = ar.run_id
            JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'manipulation'
              AND ru.status IN ('complete', 'partial')
              AND CAST(json_extract(ar.result_json, '$.total_score') AS REAL) > 0
              {dir_clause} {cc}
            GROUP BY period, e.direction
            ORDER BY period, e.direction""",
        dir_params + cp,
    ).fetchall()
    return [
        {
            "period": r["period"],
            "direction": r["direction"],
            "avg_score": round(float(r["avg_score"] or 0), 3),
            "count": r["email_count"],
        }
        for r in rows
    ]


def manipulation_pattern_frequency(conn: sqlite3.Connection,
                                   direction: Optional[str] = None,
                                   corpus: Optional[str] = None) -> List[Dict]:
    """Count of each manipulation pattern type across all analysed emails."""
    dir_clause = "AND e.direction = ?" if direction and direction != "all" else ""
    dir_params = [direction] if direction and direction != "all" else []
    cc, cp = corpus_clause(corpus)

    rows = conn.execute(
        f"""SELECT ar.result_json, e.direction
            FROM analysis_results ar
            JOIN analysis_runs ru ON ru.id = ar.run_id
            JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'manipulation'
              AND ru.status IN ('complete', 'partial')
              {dir_clause} {cc}""",
        dir_params + cp,
    ).fetchall()

    totals: dict = {}
    for r in rows:
        try:
            data = json.loads(r["result_json"]) if r["result_json"] else {}
        except (json.JSONDecodeError, TypeError):
            continue
        for pattern in data.get("patterns", []):
            ptype = pattern.get("type") if isinstance(pattern, dict) else str(pattern)
            if not ptype:
                continue
            if ptype not in totals:
                totals[ptype] = {"pattern": ptype, "total": 0, "sent": 0, "received": 0}
            totals[ptype]["total"] += 1
            dir_key = r["direction"] if r["direction"] in ("sent", "received") else "received"
            totals[ptype][dir_key] += 1

    return sorted(totals.values(), key=lambda x: x["total"], reverse=True)


def manipulation_score_distribution(conn: sqlite3.Connection,
                                    direction: Optional[str] = None,
                                    corpus: Optional[str] = None) -> List[Dict]:
    """Score histogram: count of emails per 0.1-wide bucket, by direction."""
    dir_clause = "AND e.direction = ?" if direction and direction != "all" else ""
    dir_params = [direction] if direction and direction != "all" else []
    cc, cp = corpus_clause(corpus)

    rows = conn.execute(
        f"""SELECT json_extract(ar.result_json, '$.total_score') AS score,
                   e.direction
            FROM analysis_results ar
            JOIN analysis_runs ru ON ru.id = ar.run_id
            JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'manipulation'
              AND ru.status IN ('complete', 'partial')
              AND json_extract(ar.result_json, '$.total_score') IS NOT NULL
              {dir_clause} {cc}""",
        dir_params + cp,
    ).fetchall()

    labels = [f"{i/10:.1f}–{(i+1)/10:.1f}" for i in range(10)]
    buckets: dict = {lbl: {"bucket": lbl, "sent": 0, "received": 0, "total": 0}
                     for lbl in labels}
    for r in rows:
        try:
            score = float(r["score"] or 0)
        except (TypeError, ValueError):
            continue
        idx = min(int(score * 10), 9)
        lbl = labels[idx]
        dir_key = r["direction"] if r["direction"] in ("sent", "received") else "received"
        buckets[lbl][dir_key] += 1
        buckets[lbl]["total"] += 1

    return list(buckets.values())


def manipulation_patterns_over_time(conn: sqlite3.Connection, by: str = "quarter",
                                    top_n: int = 5,
                                    direction: str = "",
                                    corpus: Optional[str] = None) -> Dict[str, Any]:
    """Top-N pattern counts grouped by time period (for stacked area chart)."""
    period_expr = _period_expr(by)
    dir_clause  = "AND e.direction = ?" if direction in ("sent", "received") else ""
    dir_params  = [direction] if dir_clause else []
    cc, cp = corpus_clause(corpus)

    rows = conn.execute(
        f"""SELECT {period_expr} AS period, ar.result_json
            FROM analysis_results ar
            JOIN analysis_runs ru ON ru.id = ar.run_id
            JOIN emails e ON e.id = ar.email_id
            WHERE ru.analysis_type = 'manipulation'
              AND ru.status IN ('complete', 'partial')
              AND CAST(json_extract(ar.result_json, '$.total_score') AS REAL) > 0
              {dir_clause} {cc}
            ORDER BY period""",
        dir_params + cp,
    ).fetchall()

    period_patterns: dict = {}
    period_totals:   dict = {}   # total scored emails per period (denominator)
    pattern_totals:  dict = {}
    for r in rows:
        period = r["period"]
        try:
            data = json.loads(r["result_json"]) if r["result_json"] else {}
        except (json.JSONDecodeError, TypeError):
            continue
        if period not in period_patterns:
            period_patterns[period] = {}
        period_totals[period] = period_totals.get(period, 0) + 1
        for pattern in data.get("patterns", []):
            ptype = pattern.get("type") if isinstance(pattern, dict) else str(pattern)
            if not ptype:
                continue
            period_patterns[period][ptype] = period_patterns[period].get(ptype, 0) + 1
            pattern_totals[ptype] = pattern_totals.get(ptype, 0) + 1

    top_patterns = sorted(pattern_totals, key=lambda p: pattern_totals[p], reverse=True)[:top_n]
    periods_sorted = sorted(period_patterns)
    return {
        "periods": periods_sorted,
        "patterns": top_patterns,
        # Values are % of scored emails in that period that contained the pattern
        "data": [
            {
                p: round(
                    period_patterns[period].get(p, 0) / period_totals[period] * 100, 1
                )
                for p in top_patterns
            }
            for period in periods_sorted
        ],
    }


# ─────────────────────────── METHODOLOGY ─────────────────────────────────

def analysis_methodology(conn: sqlite3.Connection) -> List[Dict]:
    """All completed analysis runs with metadata for the report appendix."""
    rows = conn.execute(
        """SELECT id, analysis_type, provider_name, model_id,
                  run_date, prompt_version, status, email_count
           FROM analysis_runs
           WHERE status IN ('complete', 'partial')
           ORDER BY run_date DESC"""
    ).fetchall()
    return [dict(r) for r in rows]
