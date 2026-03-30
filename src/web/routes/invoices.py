"""Lawyer invoice CRUD + cost dashboard routes — Phase 6f."""
import json
import re
import sqlite3
from typing import Optional
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from src.web.deps import get_conn, get_perspective

BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

INVOICE_STATUSES = ["paid", "pending", "disputed"]

# ── Default scan keywords ─────────────────────────────────────────────────────
DEFAULT_SCAN_KEYWORDS = [
    "facture",
    "honoraires",
    "note d'honoraires",
    "relevé",
    "acompte",
    "solde dû",
    "montant TTC",
    "diligences",
]
DEFAULT_SCAN_KEYWORDS_STR = ", ".join(DEFAULT_SCAN_KEYWORDS)

# ── Regex for auto-scan (EUR amounts) ────────────────────────────────────────
# Matches French/standard EUR amounts: 1 234,56 €  /  1234.56 EUR  /  1,234.56 €
_EUR_RE = re.compile(
    r'((?:\d{1,3}(?:[\s\u00a0]\d{3})+|\d+)(?:[,\.]\d{2})?)\s*(?:€|EUR)\b',
    re.IGNORECASE,
)


def _build_kw_regex(keywords: list) -> re.Pattern:
    """Build a case-insensitive OR regex from a list of plain-text keywords."""
    parts = [re.escape(kw.strip()) for kw in keywords if kw.strip()]
    if not parts:
        parts = [re.escape(k) for k in DEFAULT_SCAN_KEYWORDS]
    return re.compile("|".join(parts), re.IGNORECASE)


def _resolve_lawyer(email_row: dict, lawyer_index: dict) -> tuple:
    """Return (contact_id, contact_name) for the lawyer in this email.

    Checks FROM address first (received emails), then TO addresses (sent emails).
    lawyer_index: {email_address_lower: (id, name)}
    """
    # FROM is a lawyer (received email)
    from_addr = (email_row.get("from_address") or "").lower()
    if from_addr in lawyer_index:
        return lawyer_index[from_addr]

    # TO contains a lawyer (sent email)
    try:
        to_addrs = json.loads(email_row.get("to_addresses") or "[]")
    except Exception:
        to_addrs = []
    for addr in to_addrs:
        key = addr.lower()
        if key in lawyer_index:
            return lawyer_index[key]

    return None, None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_lawyers(conn):
    rows = conn.execute(
        "SELECT id, name, role, firm_name FROM contacts "
        "WHERE role IN ('my_lawyer', 'her_lawyer', 'opposing_counsel') "
        "ORDER BY role, name"
    ).fetchall()
    return [dict(r) for r in rows]


def _get_procedures(conn):
    rows = conn.execute(
        "SELECT id, name, procedure_type FROM procedures "
        "ORDER BY CASE WHEN date_start IS NULL THEN 1 ELSE 0 END, date_start DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def _get_summaries(conn):
    """Aggregate totals for summary cards, per-lawyer, and per-procedure tables."""
    total_row = conn.execute("""
        SELECT COUNT(*)                          AS count,
               COALESCE(SUM(amount_ttc), 0)     AS total_ttc,
               COALESCE(SUM(amount_ht), 0)      AS total_ht
        FROM lawyer_invoices
    """).fetchone()

    status_rows = conn.execute("""
        SELECT status,
               COUNT(*)                          AS count,
               COALESCE(SUM(amount_ttc), 0)      AS total_ttc
        FROM lawyer_invoices GROUP BY status
    """).fetchall()
    status_totals = {r["status"]: r["total_ttc"] for r in status_rows}

    by_lawyer = conn.execute("""
        SELECT c.id, c.name, c.role, c.firm_name,
               COUNT(*)                          AS count,
               COALESCE(SUM(li.amount_ht), 0)   AS total_ht,
               COALESCE(SUM(li.amount_ttc), 0)  AS total_ttc
        FROM lawyer_invoices li
        JOIN contacts c ON li.contact_id = c.id
        GROUP BY li.contact_id
        ORDER BY total_ttc DESC
    """).fetchall()
    by_lawyer = [dict(r) for r in by_lawyer]

    by_procedure = conn.execute("""
        SELECT COALESCE(p.name, '— unlinked —')  AS proc_name,
               p.procedure_type,
               COUNT(*)                           AS count,
               COALESCE(SUM(li.amount_ttc), 0)   AS total_ttc
        FROM lawyer_invoices li
        LEFT JOIN procedures p ON li.procedure_id = p.id
        GROUP BY li.procedure_id
        ORDER BY total_ttc DESC
    """).fetchall()
    by_procedure = [dict(r) for r in by_procedure]

    # Add percentage bars (relative to max lawyer)
    max_ttc = max((r["total_ttc"] for r in by_lawyer), default=1) or 1
    for r in by_lawyer:
        r["pct"] = int(r["total_ttc"] / max_ttc * 100)

    return {
        "count":         total_row["count"],
        "total_ttc":     total_row["total_ttc"],
        "total_ht":      total_row["total_ht"],
        "paid_ttc":      status_totals.get("paid",     0),
        "pending_ttc":   status_totals.get("pending",  0),
        "disputed_ttc":  status_totals.get("disputed", 0),
        "by_lawyer":     by_lawyer,
        "by_procedure":  by_procedure,
    }


def _fmt_eur(value) -> str:
    """Format a float as a readable EUR string."""
    if value is None:
        return "—"
    return f"{value:,.2f} €".replace(",", "\u202f")  # narrow no-break space


# ── List + dashboard ──────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def invoices_list(
    request: Request,
    lawyer_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    conditions, params = [], []
    if lawyer_id:
        conditions.append("li.contact_id = ?")
        params.append(lawyer_id)
    if status and status in INVOICE_STATUSES:
        conditions.append("li.status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(f"""
        SELECT li.*,
               c.name  AS lawyer_name,  c.role AS lawyer_role,
               p.name  AS procedure_name
        FROM lawyer_invoices li
        JOIN contacts c ON li.contact_id = c.id
        LEFT JOIN procedures p ON li.procedure_id = p.id
        {where}
        ORDER BY li.invoice_date DESC, li.id DESC
    """, params).fetchall()
    invoices = [dict(r) for r in rows]

    return templates.TemplateResponse("pages/invoices.html", {
        "request":        request,
        "perspective":    perspective,
        "page":           "invoices",
        "invoices":       invoices,
        "summaries":      _get_summaries(conn),
        "lawyers":        _get_lawyers(conn),
        "procedures":     _get_procedures(conn),
        "statuses":       INVOICE_STATUSES,
        "filter_lawyer":  lawyer_id,
        "filter_status":  status or "",
        "fmt_eur":        _fmt_eur,
    })


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", response_class=HTMLResponse)
@router.post("/", response_class=HTMLResponse)
async def create_invoice(
    request: Request,
    contact_id: int = Form(...),
    invoice_date: str = Form(...),
    procedure_id: Optional[str] = Form(None),
    invoice_number: str = Form(""),
    description: str = Form(""),
    amount_ht: Optional[str] = Form(None),
    amount_ttc: Optional[str] = Form(None),
    tva_rate: Optional[str] = Form(None),
    status: str = Form("paid"),
    payment_date: Optional[str] = Form(None),
    email_id: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    def _float(v):
        if not v or str(v).strip() == "":
            return None
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            return None

    conn.execute("""
        INSERT INTO lawyer_invoices
            (contact_id, invoice_date, procedure_id, invoice_number, description,
             amount_ht, amount_ttc, tva_rate, status, payment_date, email_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        contact_id,
        invoice_date,
        int(procedure_id) if procedure_id else None,
        invoice_number.strip() or None,
        description.strip() or None,
        _float(amount_ht),
        _float(amount_ttc),
        _float(tva_rate) if tva_rate else 0.20,
        status if status in INVOICE_STATUSES else "paid",
        payment_date or None,
        int(email_id) if email_id else None,
    ))
    conn.commit()
    return RedirectResponse("/invoices/", status_code=303)


# ── Detail / edit ─────────────────────────────────────────────────────────────

@router.get("/scan", response_class=HTMLResponse)
async def scan_emails(
    request: Request,
    keywords: Optional[str] = Query(None),       # comma-separated; None → defaults
    # 's' sentinel: present whenever the form is submitted (even with all checkboxes off).
    # Without it, absent checkbox = unchecked is indistinguishable from first load.
    s: Optional[str] = Query(None),
    require_amount: Optional[str] = Query(None), # "true" when checked, absent when not
    show_linked: Optional[str] = Query(None),    # "true" when checked, absent when not
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    """Scan legal corpus lawyer emails for invoice-like patterns."""
    # On first load (s absent) apply safe defaults; after form submit
    # respect what the browser sent — absent checkbox means unchecked (False)
    first_load          = s is None
    require_amount_bool = (require_amount == "true") if not first_load else True
    show_linked_bool    = (show_linked    == "true") if not first_load else False

    # Parse keyword list — fall back to defaults if empty/missing
    kw_list = [k.strip() for k in keywords.split(",")] if keywords else []
    kw_list = [k for k in kw_list if k]
    active_keywords = kw_list or DEFAULT_SCAN_KEYWORDS
    kw_re = _build_kw_regex(active_keywords)

    already_linked = {
        r[0] for r in conn.execute(
            "SELECT email_id FROM lawyer_invoices WHERE email_id IS NOT NULL"
        ).fetchall()
    }

    # Build address → (id, name) index for all lawyer contacts + their aliases
    lawyer_rows = conn.execute(
        "SELECT id, name, email, aliases FROM contacts "
        "WHERE role IN ('my_lawyer', 'her_lawyer', 'opposing_counsel')"
    ).fetchall()
    lawyer_index = {}
    for lr in lawyer_rows:
        lawyer_index[lr["email"].lower()] = (lr["id"], lr["name"])
        try:
            for alias in json.loads(lr["aliases"] or "[]"):
                lawyer_index[alias.lower()] = (lr["id"], lr["name"])
        except Exception:
            pass

    # Fetch ALL legal corpus emails — includes both received (from lawyer) and
    # sent (to lawyer) so direction='sent' emails are no longer excluded
    rows = conn.execute("""
        SELECT e.id, e.date, e.subject, e.direction,
               e.from_address, e.from_name, e.to_addresses,
               e.delta_text, e.body_text
        FROM emails e
        WHERE e.corpus = 'legal'
        ORDER BY e.date DESC
    """).fetchall()

    candidates = []
    for row in rows:
        if not show_linked_bool and row["id"] in already_linked:
            continue
        # Prefer delta_text (quotes stripped); fall back to body_text so emails
        # where the invoice content was stripped as a quote are still found
        text = row["delta_text"] or ""
        m = kw_re.search(text)
        if not m:
            text = row["body_text"] or ""
            m = kw_re.search(text)
        if not m:
            continue

        raw_amounts = _EUR_RE.findall(text)
        if require_amount_bool and not raw_amounts:
            continue

        # Normalise amounts (strip spaces, replace comma decimal sep with .)
        amounts = []
        for a in raw_amounts[:4]:
            a = re.sub(r'[\s\u00a0]', '', a)
            a = a.replace(',', '.')
            try:
                amounts.append(float(a))
            except ValueError:
                pass

        # Snippet anchored on the first keyword match
        start = max(0, m.start() - 60)
        end   = min(len(text), m.start() + 250)
        snippet = "…" + text[start:end].strip() + "…"

        contact_id, contact_name = _resolve_lawyer(dict(row), lawyer_index)

        candidates.append({
            "email_id":       row["id"],
            "date":           (row["date"] or "")[:10],
            "subject":        row["subject"] or "(no subject)",
            "direction":      row["direction"],
            "contact_name":   contact_name or "—",
            "contact_id":     contact_id,
            "amounts":        amounts,
            "snippet":        snippet,
            "already_linked": row["id"] in already_linked,
        })

    # Keyword string to echo back into the form
    keywords_display = ", ".join(active_keywords)

    return templates.TemplateResponse("pages/invoice_scan.html", {
        "request":          request,
        "perspective":      perspective,
        "page":             "invoices",
        "candidates":       candidates,
        "lawyers":          _get_lawyers(conn),
        "procedures":       _get_procedures(conn),
        "statuses":         INVOICE_STATUSES,
        # Filter state (echoed back to form)
        "keywords_str":     keywords_display,
        "require_amount":   require_amount_bool,
        "show_linked":      show_linked_bool,
        "default_keywords": DEFAULT_SCAN_KEYWORDS_STR,
    })


@router.get("/{invoice_id}", response_class=HTMLResponse)
async def invoice_detail(
    request: Request,
    invoice_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    row = conn.execute("""
        SELECT li.*,
               c.name AS lawyer_name,
               p.name AS procedure_name
        FROM lawyer_invoices li
        JOIN contacts c ON li.contact_id = c.id
        LEFT JOIN procedures p ON li.procedure_id = p.id
        WHERE li.id = ?
    """, (invoice_id,)).fetchone()

    if not row:
        return HTMLResponse("Invoice not found", status_code=404)

    invoice = dict(row)

    # Linked email (if any)
    linked_email = None
    if invoice.get("email_id"):
        e = conn.execute(
            "SELECT id, date, subject, from_name, from_address FROM emails WHERE id = ?",
            (invoice["email_id"],)
        ).fetchone()
        if e:
            linked_email = dict(e)

    return templates.TemplateResponse("pages/invoice_detail.html", {
        "request":      request,
        "perspective":  perspective,
        "page":         "invoices",
        "invoice":      invoice,
        "linked_email": linked_email,
        "lawyers":      _get_lawyers(conn),
        "procedures":   _get_procedures(conn),
        "statuses":     INVOICE_STATUSES,
        "fmt_eur":      _fmt_eur,
    })


# ── Update ────────────────────────────────────────────────────────────────────

@router.post("/{invoice_id}/update", response_class=HTMLResponse)
async def update_invoice(
    request: Request,
    invoice_id: int,
    contact_id: int = Form(...),
    invoice_date: str = Form(...),
    procedure_id: Optional[str] = Form(None),
    invoice_number: str = Form(""),
    description: str = Form(""),
    amount_ht: Optional[str] = Form(None),
    amount_ttc: Optional[str] = Form(None),
    tva_rate: Optional[str] = Form(None),
    status: str = Form("paid"),
    payment_date: Optional[str] = Form(None),
    email_id: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    def _float(v):
        if not v or str(v).strip() == "":
            return None
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            return None

    conn.execute("""
        UPDATE lawyer_invoices SET
            contact_id = ?, invoice_date = ?, procedure_id = ?,
            invoice_number = ?, description = ?,
            amount_ht = ?, amount_ttc = ?, tva_rate = ?,
            status = ?, payment_date = ?, email_id = ?
        WHERE id = ?
    """, (
        contact_id,
        invoice_date,
        int(procedure_id) if procedure_id else None,
        invoice_number.strip() or None,
        description.strip() or None,
        _float(amount_ht),
        _float(amount_ttc),
        _float(tva_rate) if tva_rate else 0.20,
        status if status in INVOICE_STATUSES else "paid",
        payment_date or None,
        int(email_id) if email_id else None,
        invoice_id,
    ))
    conn.commit()
    return RedirectResponse("/invoices/", status_code=303)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.post("/{invoice_id}/delete", response_class=HTMLResponse)
async def delete_invoice(
    request: Request,
    invoice_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute("DELETE FROM lawyer_invoices WHERE id = ?", (invoice_id,))
    conn.commit()
    return RedirectResponse("/invoices/", status_code=303)
