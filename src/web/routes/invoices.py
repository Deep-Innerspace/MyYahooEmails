"""Lawyer invoice CRUD + cost dashboard routes — Phase 6f."""
import json
import re
import sqlite3
from typing import Optional
from urllib.parse import urlencode as _urlencode
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
        invoice_number.strip(),
        description.strip(),
        _float(amount_ht),
        _float(amount_ttc),
        _float(tva_rate) if tva_rate else 0.20,
        status if status in INVOICE_STATUSES else "paid",
        payment_date or None,
        int(email_id) if email_id else None,
    ))
    conn.commit()
    return RedirectResponse("/invoices/", status_code=303)


# ── Scan helpers ──────────────────────────────────────────────────────────────

_VALID_TABS          = {"pending", "invoice", "payment", "dismissed", "all"}
_VALID_PAYMENT_TYPES = ("acompte", "solde_final", "autre")


def _build_lawyer_index(conn) -> dict:
    """Return {email_lower: (contact_id, contact_name)} for all lawyer contacts."""
    rows = conn.execute(
        "SELECT id, name, email, aliases FROM contacts "
        "WHERE role IN ('my_lawyer', 'her_lawyer', 'opposing_counsel')"
    ).fetchall()
    index = {}
    for r in rows:
        index[r["email"].lower()] = (r["id"], r["name"])
        try:
            for alias in json.loads(r["aliases"] or "[]"):
                index[alias.lower()] = (r["id"], r["name"])
        except Exception:
            pass
    return index


def _build_scan_candidates(conn, keywords_str: str, require_amount_bool: bool) -> tuple:
    """Run the full scan query and apply keyword + amount filters.

    Returns (candidates_list, active_keywords_list) ordered by date DESC.
    Candidates carry all status flags so the list and detail can render without
    additional DB queries.
    """
    kw_list = [k.strip() for k in (keywords_str or "").split(",") if k.strip()]
    active_keywords = kw_list or DEFAULT_SCAN_KEYWORDS
    kw_re = _build_kw_regex(active_keywords)
    lawyer_index = _build_lawyer_index(conn)

    rows = conn.execute("""
        SELECT e.id, e.date, e.subject, e.direction,
               e.from_address, e.from_name, e.to_addresses,
               e.delta_text, e.body_text,
               EXISTS(
                   SELECT 1 FROM attachments a
                   WHERE a.email_id = e.id
               ) AS has_attachments,
               EXISTS(
                   SELECT 1 FROM attachments a
                   WHERE a.email_id = e.id AND a.category = 'invoice'
               ) AS has_invoice_attachment,
               EXISTS(
                   SELECT 1 FROM lawyer_invoices li
                   WHERE li.email_id = e.id
               ) AS invoice_linked,
               (SELECT li.id FROM lawyer_invoices li
                WHERE li.email_id = e.id LIMIT 1) AS linked_invoice_id,
               EXISTS(
                   SELECT 1 FROM payment_confirmations pc
                   WHERE pc.email_id = e.id
               ) AS payment_confirmed,
               (SELECT pc.amount FROM payment_confirmations pc
                WHERE pc.email_id = e.id LIMIT 1) AS pay_amount,
               (SELECT pc.payment_type FROM payment_confirmations pc
                WHERE pc.email_id = e.id LIMIT 1) AS pay_type,
               EXISTS(
                   SELECT 1 FROM invoice_scan_dismissed d
                   WHERE d.email_id = e.id
               ) AS dismissed
        FROM emails e
        WHERE e.corpus = 'legal'
        ORDER BY e.date DESC
    """).fetchall()

    candidates = []
    for row in rows:
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

        amounts = []
        for a in raw_amounts[:4]:
            a = re.sub(r'[\s\u00a0]', '', a)
            a = a.replace(',', '.')
            try:
                amounts.append(float(a))
            except ValueError:
                pass

        start   = max(0, m.start() - 60)
        end     = min(len(text), m.start() + 250)
        snippet = "…" + text[start:end].strip() + "…"

        contact_id, contact_name = _resolve_lawyer(dict(row), lawyer_index)

        candidates.append({
            "email_id":               row["id"],
            "date":                   (row["date"] or "")[:10],
            "subject":                row["subject"] or "(no subject)",
            "direction":              row["direction"],
            "contact_name":           contact_name or "—",
            "contact_id":             contact_id,
            "amounts":                amounts,
            "snippet":                snippet,
            "has_attachments":         bool(row["has_attachments"]),
            "has_invoice_attachment": bool(row["has_invoice_attachment"]),
            "invoice_linked":         bool(row["invoice_linked"]),
            "linked_invoice_id":      row["linked_invoice_id"],
            "payment_confirmed":      bool(row["payment_confirmed"]),
            "pay_amount":             row["pay_amount"],
            "pay_type":               row["pay_type"],
            "dismissed":              bool(row["dismissed"]),
        })

    return candidates, active_keywords


def _filter_by_tab(candidates: list, tab: str) -> list:
    if tab == "pending":
        return [c for c in candidates
                if not c["dismissed"] and not c["invoice_linked"]
                and not c["payment_confirmed"]]
    if tab == "invoice":
        return [c for c in candidates if c["invoice_linked"]]
    if tab == "payment":
        return [c for c in candidates if c["payment_confirmed"]]
    if tab == "dismissed":
        return [c for c in candidates if c["dismissed"]]
    return candidates  # "all"


def _tab_counts(candidates: list) -> dict:
    return {
        "pending":   sum(1 for c in candidates
                         if not c["dismissed"] and not c["invoice_linked"]
                         and not c["payment_confirmed"]),
        "invoice":   sum(1 for c in candidates if c["invoice_linked"]),
        "payment":   sum(1 for c in candidates if c["payment_confirmed"]),
        "dismissed": sum(1 for c in candidates if c["dismissed"]),
        "all":       len(candidates),
    }


def _next_candidate_id(tab_filtered: list, current_id: int):
    """Return the email_id that follows current_id in the tab-filtered list.

    If current_id was just removed from the tab (e.g. pending → invoice), it
    won't appear in tab_filtered; return the first remaining candidate instead.
    Returns None when the list is empty (all done).
    """
    if not tab_filtered:
        return None
    ids = [c["email_id"] for c in tab_filtered]
    try:
        idx = ids.index(current_id)
        return ids[idx + 1] if idx + 1 < len(ids) else None
    except ValueError:
        return ids[0]


def _scan_qs(keywords_str: str, require_amount_bool: bool, tab: str) -> str:
    """Build a URL-encoded query string for scan list/detail endpoints."""
    return _urlencode({
        "keywords":       keywords_str,
        "require_amount": "true" if require_amount_bool else "false",
        "tab":            tab,
    })


def _render_partial(tmpl, name: str, ctx: dict) -> str:
    """Render a Jinja2 template to a plain string (for OOB HTMX responses)."""
    return tmpl.env.get_template(name).render(ctx)


def _fetch_email_detail(conn, email_id: int) -> tuple:
    """Return (email_dict, attachments_list) for the detail panel."""
    email_row = conn.execute(
        "SELECT id, date, subject, from_address, from_name, "
        "       to_addresses, direction, delta_text, body_text "
        "FROM emails WHERE id = ?",
        (email_id,)
    ).fetchone()
    atts = conn.execute(
        "SELECT id, filename, content_type, size_bytes, mime_section, "
        "       imap_uid, folder, downloaded, download_path, category, "
        "       CASE WHEN content IS NOT NULL THEN 1 ELSE 0 END AS has_content "
        "FROM attachments WHERE email_id = ?",
        (email_id,)
    ).fetchall()
    return (
        dict(email_row) if email_row else {},
        [dict(a) for a in atts],
    )


def _build_scan_action_response(request, conn, templates_obj,
                                 saved_id: int, keywords_str: str,
                                 require_amount_bool: bool, tab: str,
                                 next_hint_id) -> HTMLResponse:
    """Build the combined HTMX response after a scan action (save / dismiss).

    Returns an HTMLResponse with:
    - The detail panel for the next pending email (main response)
    - An OOB swap of the list panel (updated icons + new active highlight)
    """
    candidates, _ = _build_scan_candidates(conn, keywords_str, require_amount_bool)
    tab_filtered   = _filter_by_tab(candidates, tab)
    counts         = _tab_counts(candidates)
    qs             = _scan_qs(keywords_str, require_amount_bool, tab)

    # Use pre-computed hint when still valid; otherwise find position after saved
    next_id = None
    if next_hint_id:
        try:
            hint = int(next_hint_id)
            if any(c["email_id"] == hint for c in tab_filtered):
                next_id = hint
        except (ValueError, TypeError):
            pass
    if next_id is None:
        next_id = _next_candidate_id(tab_filtered, saved_id)

    lawyers    = _get_lawyers(conn)
    procedures = _get_procedures(conn)

    if next_id:
        next_c  = next(c for c in candidates if c["email_id"] == next_id)
        email, atts = _fetch_email_detail(conn, next_id)
        upcoming = _next_candidate_id(tab_filtered, next_id)
        detail_html = _render_partial(templates_obj, "partials/scan_detail.html", {
            "request":        request,
            "c":              next_c,
            "email":          email,
            "attachments":    atts,
            "next_id":        upcoming,
            "keywords_str":   keywords_str,
            "require_amount": require_amount_bool,
            "tab":            tab,
            "scan_qs":        qs,
            "lawyers":        lawyers,
            "procedures":     procedures,
            "statuses":       INVOICE_STATUSES,
        })
    else:
        detail_html = _render_partial(templates_obj, "partials/scan_done.html", {
            "request":        request,
            "tab_counts":     counts,
            "active_tab":     tab,
            "keywords_str":   keywords_str,
            "require_amount": require_amount_bool,
            "scan_qs":        qs,
        })

    list_html = _render_partial(templates_obj, "partials/scan_list.html", {
        "request":        request,
        "candidates":     candidates,
        "tab_counts":     counts,
        "active_tab":     tab,
        "active_id":      next_id,
        "keywords_str":   keywords_str,
        "require_amount": require_amount_bool,
        "scan_qs":        qs,
        "oob":            True,
    })

    return HTMLResponse(detail_html + "\n" + list_html)


# ── Scan: shell ────────────────────────────────────────────────────────────────

@router.get("/scan", response_class=HTMLResponse)
async def scan_shell(
    request: Request,
    keywords: Optional[str] = Query(None),
    s: Optional[str] = Query(None),
    require_amount: Optional[str] = Query(None),
    tab: Optional[str] = Query("pending"),
    conn: sqlite3.Connection = Depends(get_conn),
    perspective: str = Depends(get_perspective),
):
    first_load          = s is None
    require_amount_bool = (require_amount == "true") if not first_load else True
    active_tab          = tab if tab in _VALID_TABS else "pending"
    kw_list             = [k.strip() for k in (keywords or "").split(",") if k.strip()]
    keywords_str        = ", ".join(kw_list) if kw_list else DEFAULT_SCAN_KEYWORDS_STR
    qs                  = _scan_qs(keywords_str, require_amount_bool, active_tab)

    return templates.TemplateResponse("pages/invoice_scan.html", {
        "request":          request,
        "perspective":      perspective,
        "page":             "invoices",
        "keywords_str":     keywords_str,
        "require_amount":   require_amount_bool,
        "active_tab":       active_tab,
        "default_keywords": DEFAULT_SCAN_KEYWORDS_STR,
        "scan_qs":          qs,
    })


# ── Scan: list partial ────────────────────────────────────────────────────────

@router.get("/scan/list", response_class=HTMLResponse)
async def scan_list(
    request: Request,
    keywords: Optional[str] = Query(None),
    require_amount: Optional[str] = Query(None),
    tab: Optional[str] = Query("pending"),
    active_id: Optional[int] = Query(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    require_amount_bool = require_amount == "true"
    active_tab   = tab if tab in _VALID_TABS else "pending"
    keywords_str = keywords or DEFAULT_SCAN_KEYWORDS_STR
    qs           = _scan_qs(keywords_str, require_amount_bool, active_tab)

    candidates, _ = _build_scan_candidates(conn, keywords_str, require_amount_bool)

    # Auto-fallback: if requested tab has no results, fall back to "all" so the
    # user always sees something after changing keywords instead of an empty list.
    if active_tab == "pending" and not _filter_by_tab(candidates, "pending"):
        active_tab = "all"
        qs = _scan_qs(keywords_str, require_amount_bool, active_tab)

    return templates.TemplateResponse("partials/scan_list.html", {
        "request":        request,
        "candidates":     candidates,
        "tab_counts":     _tab_counts(candidates),
        "active_tab":     active_tab,
        "active_id":      active_id,
        "keywords_str":   keywords_str,
        "require_amount": require_amount_bool,
        "scan_qs":        qs,
        "oob":            False,
    })


# ── Scan: detail partial ──────────────────────────────────────────────────────

@router.get("/scan/detail", response_class=HTMLResponse)
async def scan_detail(
    request: Request,
    email_id: Optional[int] = Query(None),
    keywords: Optional[str] = Query(None),
    require_amount: Optional[str] = Query(None),
    tab: Optional[str] = Query("pending"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    require_amount_bool = require_amount == "true"
    active_tab   = tab if tab in _VALID_TABS else "pending"
    keywords_str = keywords or DEFAULT_SCAN_KEYWORDS_STR
    qs           = _scan_qs(keywords_str, require_amount_bool, active_tab)

    candidates, _ = _build_scan_candidates(conn, keywords_str, require_amount_bool)
    tab_filtered   = _filter_by_tab(candidates, active_tab)

    requested_email_id = email_id   # preserve original query param for fallback logic
    current = None
    if email_id:
        current = next((c for c in candidates if c["email_id"] == email_id), None)
    if current is None and tab_filtered:
        current = tab_filtered[0]
        email_id = current["email_id"]

    # Auto-fallback for initial / no-specific-email loads: if the requested tab is
    # empty and no explicit email_id was given, fall back to "all" so the detail
    # always shows something rather than flashing the "all done" empty state.
    if current is None and not requested_email_id and active_tab != "all":
        if candidates:
            active_tab   = "all"
            qs           = _scan_qs(keywords_str, require_amount_bool, active_tab)
            tab_filtered = candidates          # "all" = every candidate
            current      = candidates[0]
            email_id     = current["email_id"]

    if current is None:
        return templates.TemplateResponse("partials/scan_done.html", {
            "request":        request,
            "tab_counts":     _tab_counts(candidates),
            "active_tab":     active_tab,
            "keywords_str":   keywords_str,
            "require_amount": require_amount_bool,
            "scan_qs":        qs,
        })

    email, atts = _fetch_email_detail(conn, email_id)
    next_id     = _next_candidate_id(tab_filtered, email_id)

    return templates.TemplateResponse("partials/scan_detail.html", {
        "request":        request,
        "c":              current,
        "email":          email,
        "attachments":    atts,
        "next_id":        next_id,
        "keywords_str":   keywords_str,
        "require_amount": require_amount_bool,
        "tab":            active_tab,
        "scan_qs":        qs,
        "lawyers":        _get_lawyers(conn),
        "procedures":     _get_procedures(conn),
        "statuses":       INVOICE_STATUSES,
    })


# ── Scan: save invoice ────────────────────────────────────────────────────────

@router.post("/scan/invoice", response_class=HTMLResponse)
async def scan_save_invoice(
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
    scan_email_id: int = Form(...),
    scan_keywords: str = Form(""),
    scan_require_amount: str = Form("false"),
    scan_tab: str = Form("pending"),
    scan_next_id: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    def _f(v):
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
        invoice_number.strip(),
        description.strip(),
        _f(amount_ht),
        _f(amount_ttc),
        _f(tva_rate) if tva_rate else 0.20,
        status if status in INVOICE_STATUSES else "paid",
        payment_date or None,
        scan_email_id,
    ))
    conn.commit()

    return _build_scan_action_response(
        request, conn, templates,
        saved_id=scan_email_id,
        keywords_str=scan_keywords or DEFAULT_SCAN_KEYWORDS_STR,
        require_amount_bool=scan_require_amount == "true",
        tab=scan_tab if scan_tab in _VALID_TABS else "pending",
        next_hint_id=scan_next_id,
    )


# ── Scan: save payment ────────────────────────────────────────────────────────

@router.post("/scan/payment", response_class=HTMLResponse)
async def scan_save_payment(
    request: Request,
    amount: Optional[str] = Form(None),
    payment_type: str = Form("autre"),
    notes: str = Form(""),
    scan_email_id: int = Form(...),
    scan_keywords: str = Form(""),
    scan_require_amount: str = Form("false"),
    scan_tab: str = Form("pending"),
    scan_next_id: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    def _f(v):
        if not v or str(v).strip() == "":
            return None
        try:
            return float(str(v).replace(",", "."))
        except ValueError:
            return None

    conn.execute(
        "INSERT INTO payment_confirmations (email_id, amount, payment_type, notes) "
        "VALUES (?, ?, ?, ?)",
        (
            scan_email_id,
            _f(amount),
            payment_type if payment_type in _VALID_PAYMENT_TYPES else "autre",
            notes.strip(),
        ),
    )
    conn.commit()

    return _build_scan_action_response(
        request, conn, templates,
        saved_id=scan_email_id,
        keywords_str=scan_keywords or DEFAULT_SCAN_KEYWORDS_STR,
        require_amount_bool=scan_require_amount == "true",
        tab=scan_tab if scan_tab in _VALID_TABS else "pending",
        next_hint_id=scan_next_id,
    )


# ── Scan: dismiss / undismiss ─────────────────────────────────────────────────

@router.post("/scan/dismiss", response_class=HTMLResponse)
async def scan_dismiss(
    request: Request,
    scan_email_id: int = Form(...),
    scan_keywords: str = Form(""),
    scan_require_amount: str = Form("false"),
    scan_tab: str = Form("pending"),
    scan_next_id: Optional[str] = Form(None),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        "INSERT OR REPLACE INTO invoice_scan_dismissed (email_id) VALUES (?)",
        (scan_email_id,),
    )
    conn.commit()

    return _build_scan_action_response(
        request, conn, templates,
        saved_id=scan_email_id,
        keywords_str=scan_keywords or DEFAULT_SCAN_KEYWORDS_STR,
        require_amount_bool=scan_require_amount == "true",
        tab=scan_tab if scan_tab in _VALID_TABS else "pending",
        next_hint_id=scan_next_id,
    )


@router.post("/scan/undismiss", response_class=HTMLResponse)
async def scan_undismiss(
    request: Request,
    scan_email_id: int = Form(...),
    scan_keywords: str = Form(""),
    scan_require_amount: str = Form("false"),
    scan_tab: str = Form("pending"),
    conn: sqlite3.Connection = Depends(get_conn),
):
    conn.execute(
        "DELETE FROM invoice_scan_dismissed WHERE email_id = ?",
        (scan_email_id,),
    )
    conn.commit()

    # Refresh the same email's detail (don't advance to next)
    candidates, _ = _build_scan_candidates(
        conn, scan_keywords or DEFAULT_SCAN_KEYWORDS_STR, scan_require_amount == "true"
    )
    active_tab   = scan_tab if scan_tab in _VALID_TABS else "pending"
    tab_filtered = _filter_by_tab(candidates, active_tab)
    counts       = _tab_counts(candidates)
    qs           = _scan_qs(scan_keywords or DEFAULT_SCAN_KEYWORDS_STR,
                            scan_require_amount == "true", active_tab)

    current = next((c for c in candidates if c["email_id"] == scan_email_id), None)
    if current is None and tab_filtered:
        current = tab_filtered[0]
        scan_email_id = current["email_id"]

    if current is None:
        detail_html = _render_partial(templates, "partials/scan_done.html", {
            "request":        request,
            "tab_counts":     counts,
            "active_tab":     active_tab,
            "keywords_str":   scan_keywords,
            "require_amount": scan_require_amount == "true",
            "scan_qs":        qs,
        })
    else:
        email, atts = _fetch_email_detail(conn, scan_email_id)
        next_id = _next_candidate_id(tab_filtered, scan_email_id)
        detail_html = _render_partial(templates, "partials/scan_detail.html", {
            "request":        request,
            "c":              current,
            "email":          email,
            "attachments":    atts,
            "next_id":        next_id,
            "keywords_str":   scan_keywords,
            "require_amount": scan_require_amount == "true",
            "tab":            active_tab,
            "scan_qs":        qs,
            "lawyers":        _get_lawyers(conn),
            "procedures":     _get_procedures(conn),
            "statuses":       INVOICE_STATUSES,
        })

    list_html = _render_partial(templates, "partials/scan_list.html", {
        "request":        request,
        "candidates":     candidates,
        "tab_counts":     counts,
        "active_tab":     active_tab,
        "active_id":      scan_email_id,
        "keywords_str":   scan_keywords,
        "require_amount": scan_require_amount == "true",
        "scan_qs":        qs,
        "oob":            True,
    })
    return HTMLResponse(detail_html + "\n" + list_html)


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
        invoice_number.strip(),
        description.strip(),
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
