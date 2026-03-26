"""
Export emails to Excel for manual LLM analysis (ChatGPT / Claude web interface).

Usage:
    from src.analysis.excel_export import export_for_analysis
    path, count = export_for_analysis(conn, "classify", Path("exports/batch.xlsx"), limit=10)
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False

# ── Analysis type definitions ─────────────────────────────────────────────────

ANALYSIS_TYPES = {
    "classify": {
        "title": "Topic Classification",
        "task": (
            "Classify each French email by topic. "
            "Fill the YELLOW columns for every row. "
            "Use only topics from the 'Available Topics' list below. "
            "Multiple topics allowed per email, comma-separated. "
            "Do not modify any blue (input) columns."
        ),
        "output_columns": [
            ("topics",     "Comma-separated topic names from the allowed list  e.g.  enfants, finances"),
            ("confidence", "Comma-separated confidence scores 0.0–1.0 matching topics order  e.g.  0.9, 0.75"),
            ("summary",    "1–2 sentence summary of the email content in French"),
        ],
    },
    "tone": {
        "title": "Tone Analysis",
        "task": (
            "Analyse the tone, aggression, and manipulation level of each French email. "
            "Fill the YELLOW columns for every row. "
            "Scores are 0.0 (none) to 1.0 (extreme). "
            "Do not modify any blue (input) columns."
        ),
        "output_columns": [
            ("tone",              "Overall tone label: neutre, cordial, agressif, manipulateur, victimisant, menaçant"),
            ("aggression_level",  "Aggression score 0.0–1.0"),
            ("manipulation_score","Manipulation score 0.0–1.0"),
            ("legal_posturing",   "Legal posturing score 0.0–1.0  (threats, formal citations, pressure tactics)"),
            ("summary",           "1–2 sentence analysis note in French"),
        ],
    },
    "timeline": {
        "title": "Timeline Event Extraction",
        "task": (
            "Extract the key dated event from each French email (one event maximum per row). "
            "Leave all output columns blank if the email contains no extractable event. "
            "Do not modify any blue (input) columns."
        ),
        "output_columns": [
            ("event_date",  "Date of the event mentioned: YYYY-MM-DD format, or leave blank"),
            ("event_type",  "Type: statement | demand | agreement | threat | legal | financial | personal"),
            ("significance","Significance: high | medium | low"),
            ("description", "Event description in French (1 sentence)"),
        ],
    },
    "manipulation": {
        "title": "Manipulation Pattern Detection",
        "task": (
            "Detect manipulation tactics in each French email (divorce legal context). "
            "Fill the YELLOW columns for every row. Score 0.0=absent to 1.0=extreme. "
            "Leave all 4 columns blank if no manipulation is detected (total_score=0). "
            "Do not modify any blue (input) columns."
        ),
        "output_columns": [
            ("total_score",       "Overall manipulation score 0.0–1.0  (0.0 if none detected)"),
            ("dominant_pattern",  "Main pattern detected — one of: gaslighting | emotional_weaponization | "
                                  "financial_coercion | legal_threats | children_instrumentalization | "
                                  "guilt_tripping | projection | false_victimhood | moving_goalposts | "
                                  "silent_treatment_threat — or leave blank"),
            ("detected_patterns", "Comma-separated list of detected patterns with scores: "
                                  "e.g.  gaslighting:0.8, projection:0.5  — leave blank if none"),
            ("notes",             "1–2 sentence evaluation in French (or leave blank)"),
        ],
    },
}

# ── Colour palette ────────────────────────────────────────────────────────────

_NAVY      = "1E3A5F"
_ORANGE    = "C0600A"
_YELLOW_BG = "FFF9C4"
_BLUE_HDR  = "2C5282"
_WHITE     = "FFFFFF"
_GRAY      = "888888"


_EXCEL_CELL_LIMIT = 32767


def export_for_analysis(
    conn: sqlite3.Connection,
    analysis_type: str,
    output_path: Path,
    limit: Optional[int] = None,
    offset: int = 0,
    unanalyzed_only: bool = True,
    exclude_large: bool = True,
) -> tuple:
    """
    Export emails to an Excel workbook for manual LLM analysis.

    Returns:
        (output_path, email_count)
    """
    if not _HAS_OPENPYXL:
        raise ImportError("openpyxl required: pip install openpyxl")

    if analysis_type not in ANALYSIS_TYPES:
        raise ValueError(
            f"Unknown analysis type '{analysis_type}'. "
            f"Choose from: {', '.join(ANALYSIS_TYPES)}"
        )

    cfg = ANALYSIS_TYPES[analysis_type]
    output_cols = cfg["output_columns"]

    # ── Fetch emails ──────────────────────────────────────────────────────────
    wheres = [
        "e.delta_text IS NOT NULL",
        "LENGTH(TRIM(e.delta_text)) > 10",
    ]

    if exclude_large:
        wheres.append(f"LENGTH(e.delta_text) <= {_EXCEL_CELL_LIMIT}")

    if unanalyzed_only:
        if analysis_type == "classify":
            wheres.append(
                "e.id NOT IN (SELECT DISTINCT email_id FROM email_topics)"
            )
        else:
            wheres.append(f"""e.id NOT IN (
                SELECT DISTINCT ar.email_id
                FROM analysis_results ar
                JOIN analysis_runs ru ON ru.id = ar.run_id
                WHERE ru.analysis_type = '{analysis_type}'
                  AND ru.status IN ('complete', 'partial')
            )""")

    if limit:
        limit_sql = f"LIMIT {limit} OFFSET {offset}"
    elif offset:
        limit_sql = f"LIMIT -1 OFFSET {offset}"
    else:
        limit_sql = ""

    rows = conn.execute(f"""
        SELECT e.id, e.date, e.direction, e.subject, e.delta_text,
               c.name AS contact_name
        FROM emails e
        LEFT JOIN contacts c ON c.id = e.contact_id
        WHERE {' AND '.join(wheres)}
        ORDER BY e.date ASC
        {limit_sql}
    """).fetchall()

    if not rows:
        raise ValueError(
            "No emails to export — all are already analyzed, "
            "or no delta_text available."
        )

    # ── Available topics (classify only) ─────────────────────────────────────
    topics_list = []
    if analysis_type == "classify":
        topics_list = [
            r["name"]
            for r in conn.execute("SELECT name FROM topics ORDER BY name").fetchall()
        ]

    # ── Build workbook ────────────────────────────────────────────────────────
    wb = openpyxl.Workbook()

    _build_instructions_sheet(wb, cfg, output_cols, topics_list, len(rows), analysis_type)
    truncated_count = _build_emails_sheet(wb, rows, output_cols)
    _build_meta_sheet(wb, analysis_type, len(rows), output_cols)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    return output_path, len(rows), truncated_count


# ── Sheet builders ────────────────────────────────────────────────────────────

def _build_instructions_sheet(wb, cfg, output_cols, topics_list, email_count, analysis_type):
    ws = wb.active
    ws.title = "Instructions"

    def h(row, col, value, bold=False, size=11, color="000000", bg=None, wrap=False):
        cell = ws.cell(row=row, column=col, value=value)
        cell.font = Font(bold=bold, size=size, color=color)
        if bg:
            cell.fill = PatternFill("solid", fgColor=bg)
        if wrap:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        return cell

    # Title
    h(1, 1, f"MyYahooEmails — {cfg['title']} Batch",
      bold=True, size=15, color=_NAVY)
    h(2, 1,
      f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}   |   "
      f"{email_count} emails   |   "
      f"Import: python cli.py analyze import-results <file.xlsx> --type {analysis_type}",
      color=_GRAY)

    # Task
    h(4, 1, "TASK", bold=True, color=_NAVY)
    cell = ws.cell(row=4, column=2, value=cfg["task"])
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    cell.font = Font(size=11)
    ws.row_dimensions[4].height = 55

    # Output columns
    h(6, 1, "COLUMNS TO FILL (yellow)", bold=True, color=_ORANGE)
    for i, (col_name, description) in enumerate(output_cols, start=7):
        h(i, 1, col_name, bold=True)
        h(i, 2, description, wrap=True)
        ws.row_dimensions[i].height = 20

    # Available topics
    next_row = 7 + len(output_cols) + 1
    if topics_list:
        h(next_row, 1, "AVAILABLE TOPICS", bold=True, color=_NAVY)
        h(next_row, 2, ", ".join(topics_list), bold=True)
        h(next_row + 1, 2,
          "Use ONLY topics from this list. "
          "New topics will be auto-created on import if not found.")
        next_row += 3

    # Provider note
    h(next_row, 1, "PROVIDER / MODEL", bold=True, color=_NAVY)
    h(next_row, 2,
      "When importing, specify --provider and --model. "
      "Examples:  --provider openai --model gpt-5.4-thinking   "
      "or  --provider claude --model claude-opus-4-5")

    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 90


def _build_emails_sheet(wb, rows, output_cols):
    ws = wb.create_sheet("Emails")

    input_cols = ["email_id", "date", "direction", "contact", "subject", "delta_text"]
    out_col_names = [c[0] for c in output_cols]
    all_cols = input_cols + out_col_names

    # Header row
    for col_idx, col_name in enumerate(all_cols, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        is_output = col_name in out_col_names
        cell.fill = PatternFill("solid", fgColor=_ORANGE if is_output else _BLUE_HDR)
        cell.font = Font(color=_WHITE, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    # Data rows
    yellow = PatternFill("solid", fgColor=_YELLOW_BG)
    _TRUNCATION_MARKER = "\n\n[... TRUNCATED — email exceeds Excel 32,767 char limit. Full text available in DB.]"
    truncated_count = 0

    for row_idx, row in enumerate(rows, start=2):
        ws.cell(row=row_idx, column=1, value=row["id"])
        ws.cell(row=row_idx, column=2, value=str(row["date"])[:10] if row["date"] else "")
        ws.cell(row=row_idx, column=3, value=row["direction"] or "")
        ws.cell(row=row_idx, column=4, value=row["contact_name"] or "")
        ws.cell(row=row_idx, column=5, value=row["subject"] or "(no subject)")

        delta = row["delta_text"] or ""
        if len(delta) > _EXCEL_CELL_LIMIT:
            keep = _EXCEL_CELL_LIMIT - len(_TRUNCATION_MARKER)
            delta = delta[:keep] + _TRUNCATION_MARKER
            truncated_count += 1


        delta_cell = ws.cell(row=row_idx, column=6, value=delta)
        delta_cell.alignment = Alignment(wrap_text=False, vertical="top")

        for out_idx in range(len(out_col_names)):
            cell = ws.cell(row=row_idx, column=7 + out_idx, value="")
            cell.fill = yellow

    # Column widths
    widths = {"A": 9, "B": 12, "C": 11, "D": 16, "E": 38, "F": 65}
    for col_letter, width in widths.items():
        ws.column_dimensions[col_letter].width = width
    for i in range(len(out_col_names)):
        ws.column_dimensions[get_column_letter(7 + i)].width = 28

    ws.freeze_panes = "G2"
    return truncated_count


def _build_meta_sheet(wb, analysis_type, email_count, output_cols):
    ws = wb.create_sheet("_meta")
    ws["A1"], ws["B1"] = "analysis_type", analysis_type
    ws["A2"], ws["B2"] = "export_date", datetime.now().isoformat()
    ws["A3"], ws["B3"] = "email_count", email_count
    ws["A4"], ws["B4"] = "schema_version", "1"
    ws["A5"], ws["B5"] = "output_columns", ",".join(c[0] for c in output_cols)


# ── Contradictions export (topic-based, special format) ───────────────────────

_CONTRADICTION_PATTERNS = [
    "gaslighting", "emotional_weaponization", "financial_coercion", "legal_threats",
    "children_instrumentalization", "guilt_tripping", "projection", "false_victimhood",
    "moving_goalposts", "silent_treatment_threat",
]

_VALID_TOPICS = [
    "enfants", "finances", "école", "logement", "vacances", "santé",
    "procédure", "éducation", "activités", "divorce", "contradictions", "famille",
]


def export_contradictions_batch(
    conn: sqlite3.Connection,
    output_path: Path,
    topic: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 600,
) -> tuple:
    """
    Export email summaries grouped by topic for contradiction detection.

    Uses classification summaries (not full delta_text) — much more token-efficient.
    Output sheet has pre-populated headers for ChatGPT to fill contradiction pairs.

    Returns (output_path, email_count).
    """
    if not _HAS_OPENPYXL:
        raise ImportError("openpyxl required: pip install openpyxl")

    # Build filter
    wheres = [
        "ar.result_json IS NOT NULL",
        "ru.analysis_type = 'classify'",
        "ru.status IN ('complete', 'partial')",
        "t.name NOT IN ('trop_court', 'non_classifiable')",
    ]
    params: list = []

    if topic:
        wheres.append("t.name = ?")
        params.append(topic)
    if date_from:
        wheres.append("e.date >= ?")
        params.append(date_from)
    if date_to:
        wheres.append("e.date <= ?")
        params.append(date_to)

    rows = conn.execute(f"""
        SELECT DISTINCT e.id, e.date, e.direction, e.subject,
               JSON_EXTRACT(ar.result_json, '$.summary') AS summary,
               c.name AS contact_name,
               GROUP_CONCAT(DISTINCT t.name) AS topics
        FROM emails e
        JOIN email_topics et ON et.email_id = e.id
        JOIN topics t ON t.id = et.topic_id
        JOIN analysis_results ar ON ar.email_id = e.id
        JOIN analysis_runs ru ON ru.id = ar.run_id
        LEFT JOIN contacts c ON c.id = e.contact_id
        WHERE {' AND '.join(wheres)}
        GROUP BY e.id
        ORDER BY e.date ASC
        LIMIT {limit}
    """, params).fetchall()

    if not rows:
        raise ValueError("No classified emails found for the given filters.")

    wb = openpyxl.Workbook()

    # ── Instructions sheet ────────────────────────────────────────────────────
    ws_inst = wb.active
    ws_inst.title = "Instructions"

    ws_inst["A1"] = "MyYahooEmails — Contradiction Detection Batch"
    ws_inst["A1"].font = Font(bold=True, size=15, color=_NAVY)
    ws_inst["A2"] = (
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}   |   "
        f"{len(rows)} emails   |   topic: {topic or 'all'}   |   "
        f"period: {date_from or 'start'} → {date_to or 'end'}"
    )
    ws_inst["A2"].font = Font(size=11, color=_GRAY)

    ws_inst["A4"] = "TASK"
    ws_inst["A4"].font = Font(bold=True, color=_NAVY)
    ws_inst["B4"] = (
        "You are a forensic legal analyst reviewing French divorce emails. "
        "Read ALL email summaries in the 'Emails' sheet (sorted by date). "
        "Identify pairs of emails where the content directly contradicts each other — "
        "same person making incompatible claims, broken commitments, conflicting facts or dates. "
        "Fill the 'Contradictions' output sheet: one row per contradiction found. "
        "Do NOT modify the Emails sheet."
    )
    ws_inst["B4"].alignment = Alignment(wrap_text=True, vertical="top")
    ws_inst["B4"].font = Font(size=11)
    ws_inst.row_dimensions[4].height = 60

    ws_inst["A6"] = "CONTRADICTION TYPES"
    ws_inst["A6"].font = Font(bold=True, color=_NAVY)
    ws_inst["B6"] = (
        "intra-sender: both emails from the same person, contradicting themselves\n"
        "cross-sender: one email per party, one directly refutes the other's claim"
    )
    ws_inst["B6"].alignment = Alignment(wrap_text=True)
    ws_inst.row_dimensions[6].height = 35

    ws_inst["A8"] = "SEVERITY"
    ws_inst["A8"].font = Font(bold=True, color=_NAVY)
    ws_inst["B8"] = (
        "high: clear lie, perjury risk, or directly falsifiable factual claim\n"
        "medium: significant discrepancy in facts, dates, or commitments\n"
        "low: minor inconsistency or change of position over time"
    )
    ws_inst["B8"].alignment = Alignment(wrap_text=True)
    ws_inst.row_dimensions[8].height = 50

    ws_inst["A10"] = "IMPORT COMMAND"
    ws_inst["A10"].font = Font(bold=True, color=_NAVY)
    ws_inst["B10"] = (
        "python cli.py analyze import-results <file.xlsx> --type contradictions "
        "--provider openai --model gpt-5.4-thinking"
    )

    ws_inst.column_dimensions["A"].width = 22
    ws_inst.column_dimensions["B"].width = 90

    # ── Emails sheet (read-only summaries) ────────────────────────────────────
    ws_emails = wb.create_sheet("Emails")
    email_headers = ["email_id", "date", "direction", "contact", "subject", "summary", "topics"]
    for col_idx, h in enumerate(email_headers, start=1):
        cell = ws_emails.cell(row=1, column=col_idx, value=h)
        cell.fill = PatternFill("solid", fgColor=_BLUE_HDR)
        cell.font = Font(color=_WHITE, bold=True)
        cell.alignment = Alignment(horizontal="center")
    ws_emails.row_dimensions[1].height = 22

    for row_idx, row in enumerate(rows, start=2):
        ws_emails.cell(row=row_idx, column=1, value=row["id"])
        ws_emails.cell(row=row_idx, column=2, value=str(row["date"])[:10] if row["date"] else "")
        ws_emails.cell(row=row_idx, column=3, value=row["direction"] or "")
        ws_emails.cell(row=row_idx, column=4, value=row["contact_name"] or "")
        ws_emails.cell(row=row_idx, column=5, value=row["subject"] or "")
        ws_emails.cell(row=row_idx, column=6, value=row["summary"] or "")
        ws_emails.cell(row=row_idx, column=7, value=row["topics"] or "")

    ws_emails.column_dimensions["A"].width = 10
    ws_emails.column_dimensions["B"].width = 12
    ws_emails.column_dimensions["C"].width = 11
    ws_emails.column_dimensions["D"].width = 16
    ws_emails.column_dimensions["E"].width = 38
    ws_emails.column_dimensions["F"].width = 65
    ws_emails.column_dimensions["G"].width = 30
    ws_emails.freeze_panes = "A2"

    # ── Contradictions output sheet ───────────────────────────────────────────
    ws_contra = wb.create_sheet("Contradictions")
    contra_headers = ["email_id_a", "email_id_b", "scope", "topic", "severity", "explanation"]
    header_notes = [
        "ID of first email",
        "ID of second email",
        "intra-sender OR cross-sender",
        "Main topic (e.g. enfants, finances)",
        "high | medium | low",
        "Explanation in French (max 3 sentences, quote key phrases)",
    ]
    for col_idx, (h, note) in enumerate(zip(contra_headers, header_notes), start=1):
        cell = ws_contra.cell(row=1, column=col_idx, value=h)
        cell.fill = PatternFill("solid", fgColor=_ORANGE)
        cell.font = Font(color=_WHITE, bold=True)
        cell.alignment = Alignment(horizontal="center")
        cell.comment = None  # openpyxl doesn't support comments easily, use row 2 for hints
    ws_contra.row_dimensions[1].height = 22

    # Row 2: hint row
    yellow = PatternFill("solid", fgColor=_YELLOW_BG)
    for col_idx, note in enumerate(header_notes, start=1):
        cell = ws_contra.cell(row=2, column=col_idx, value=f"← {note}")
        cell.fill = yellow
        cell.font = Font(italic=True, color=_GRAY, size=9)

    # Pre-fill 50 empty yellow rows
    for row_idx in range(3, 53):
        for col_idx in range(1, 7):
            ws_contra.cell(row=row_idx, column=col_idx, value="").fill = yellow

    ws_contra.column_dimensions["A"].width = 12
    ws_contra.column_dimensions["B"].width = 12
    ws_contra.column_dimensions["C"].width = 16
    ws_contra.column_dimensions["D"].width = 18
    ws_contra.column_dimensions["E"].width = 10
    ws_contra.column_dimensions["F"].width = 80
    ws_contra.freeze_panes = "A3"

    # ── Meta sheet ────────────────────────────────────────────────────────────
    ws_meta = wb.create_sheet("_meta")
    ws_meta["A1"], ws_meta["B1"] = "analysis_type", "contradictions"
    ws_meta["A2"], ws_meta["B2"] = "export_date", datetime.now().isoformat()
    ws_meta["A3"], ws_meta["B3"] = "email_count", len(rows)
    ws_meta["A4"], ws_meta["B4"] = "topic", topic or "all"
    ws_meta["A5"], ws_meta["B5"] = "date_from", date_from or ""
    ws_meta["A6"], ws_meta["B6"] = "date_to", date_to or ""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(output_path))
    return output_path, len(rows)
