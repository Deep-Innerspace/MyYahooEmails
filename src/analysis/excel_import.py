"""
Import LLM-filled Excel analysis results back into the database.

Supports results produced by any provider (OpenAI, Claude, Gemini, etc.)
via the ChatGPT or Claude.ai web interface — or the API.

Usage:
    from src.analysis.excel_import import import_results
    stats = import_results(excel_path, "classify", "openai", "gpt-5.4-thinking")
"""
import json
from pathlib import Path
from typing import Optional

try:
    import openpyxl
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False

from src.analysis.runner import (
    create_run,
    finish_run,
    store_result,
    store_topics_for_email,
    store_timeline_events,
)

# ── Provider name normalisation ───────────────────────────────────────────────

_PROVIDER_ALIASES: dict = {
    "chatgpt":   "openai",
    "gpt":       "openai",
    "openai":    "openai",
    "claude":    "claude",
    "anthropic": "claude",
    "gemini":    "google",
    "google":    "google",
    "mistral":   "mistral",
    "llama":     "meta",
    "meta":      "meta",
}

_MODEL_DEFAULTS: dict = {
    "openai":  "gpt-4o",
    "claude":  "claude-opus-4-5",
    "google":  "gemini-1.5-pro",
    "mistral": "mistral-large",
    "meta":    "llama-3.3-70b",
}


def _normalise_provider(provider: str) -> str:
    return _PROVIDER_ALIASES.get(provider.lower(), provider.lower())


def _default_model(provider: str) -> str:
    return _MODEL_DEFAULTS.get(provider, provider)


# ── Main entry point ──────────────────────────────────────────────────────────

def import_results(
    excel_path: Path,
    analysis_type: str,
    provider: str,
    model: Optional[str] = None,
) -> dict:
    """
    Read a filled Excel export file and insert results into the database.

    Creates a new analysis_run tagged with the given provider/model.
    Idempotent: rows with empty output columns are silently skipped.

    Returns a stats dict:
        {run_id, imported, skipped, errors, status}
    """
    if not _HAS_OPENPYXL:
        raise ImportError("openpyxl required: pip install openpyxl")

    provider = _normalise_provider(provider)
    model = model or _default_model(provider)

    wb = openpyxl.load_workbook(str(excel_path), data_only=True)

    if "Emails" not in wb.sheetnames:
        raise ValueError("Workbook has no 'Emails' sheet — was this exported by MyYahooEmails?")

    # Read metadata from _meta sheet if present
    _meta = {}
    if "_meta" in wb.sheetnames:
        ws_meta = wb["_meta"]
        for row in ws_meta.iter_rows(min_row=1, values_only=True):
            if row[0] and row[1]:
                _meta[row[0]] = row[1]

    stored_type = _meta.get("analysis_type", analysis_type)
    if stored_type != analysis_type:
        raise ValueError(
            f"File was exported as '{stored_type}' but you passed --type {analysis_type}. "
            "Re-run with the correct --type."
        )

    ws = wb["Emails"]
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]

    # Create a new run record tagged with this provider / model
    prompt_note = f"excel-import from {excel_path.name}"
    run_id = create_run(
        analysis_type=analysis_type,
        provider_name=provider,
        model_id=model,
        prompt_text=prompt_note,
        prompt_version="v1-excel",
        notes=prompt_note,
    )

    imported = 0
    skipped  = 0
    errors   = []

    # Contradictions uses a completely different sheet/storage path
    if analysis_type == "contradictions":
        return _import_contradictions(wb, excel_path, run_id, provider, model)

    parsers = {
        "classify":     _parse_classify,
        "tone":         _parse_tone,
        "timeline":     _parse_timeline,
        "manipulation": _parse_manipulation,
    }
    parser = parsers.get(analysis_type)
    if parser is None:
        raise ValueError(f"Unsupported analysis_type: {analysis_type}")

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[0]:
            continue

        try:
            email_id = int(row[0])
        except (TypeError, ValueError):
            continue

        try:
            result = parser(row, headers)

            if result is None:
                skipped += 1
                continue

            # Store raw JSON result (same schema as LLM-generated results)
            store_result(run_id, email_id, json.dumps(result))

            # Post-process into typed tables
            if analysis_type == "classify" and result.get("topics"):
                store_topics_for_email(email_id, result["topics"], run_id)

            elif analysis_type == "timeline" and result.get("events"):
                store_timeline_events(run_id, email_id, result["events"])

            imported += 1

        except Exception as exc:
            errors.append(f"email_id={email_id}: {exc}")

    status = "complete" if not errors else "partial"
    finish_run(run_id, status, imported)

    return {
        "run_id":   run_id,
        "imported": imported,
        "skipped":  skipped,
        "errors":   errors,
        "status":   status,
    }


# ── Row parsers ───────────────────────────────────────────────────────────────

def _get(row, headers, name):
    """Return the value for a given column name, or None."""
    try:
        idx = headers.index(name)
        val = row[idx] if idx < len(row) else None
        return str(val).strip() if val is not None else None
    except ValueError:
        return None


def _parse_classify(row, headers) -> Optional[dict]:
    topics_raw = _get(row, headers, "topics")
    if not topics_raw:
        return None

    confidence_raw = _get(row, headers, "confidence") or ""
    summary        = _get(row, headers, "summary") or ""

    topic_names = [t.strip() for t in topics_raw.split(",") if t.strip()]
    conf_values = [c.strip() for c in confidence_raw.split(",") if c.strip()]

    topics = []
    for i, name in enumerate(topic_names):
        try:
            conf = float(conf_values[i]) if i < len(conf_values) else 0.8
            conf = max(0.0, min(1.0, conf))
        except (ValueError, IndexError):
            conf = 0.8
        topics.append({"name": name, "confidence": round(conf, 2)})

    return {
        "topics":  topics,
        "summary": summary,
        "source":  "excel-import",
    }


def _parse_tone(row, headers) -> Optional[dict]:
    tone = _get(row, headers, "tone")
    if not tone:
        return None

    def to_float(name):
        val = _get(row, headers, name)
        try:
            return round(max(0.0, min(1.0, float(val))), 2)
        except (TypeError, ValueError):
            return 0.0

    return {
        "tone":               tone,
        "aggression_level":   to_float("aggression_level"),
        "manipulation_score": to_float("manipulation_score"),
        "legal_posturing":    to_float("legal_posturing"),
        "summary":            _get(row, headers, "summary") or "",
        "source":             "excel-import",
    }


def _parse_timeline(row, headers) -> Optional[dict]:
    description = _get(row, headers, "description")

    # Blank = reviewed, no extractable event found — store as empty events list
    if not description:
        return {"events": [], "source": "excel-import"}

    event_date = _get(row, headers, "event_date") or ""
    # Normalise date: keep first 10 chars (YYYY-MM-DD) if present.
    # Pad partial dates so SQLite TIMESTAMP affinity doesn't coerce "2015" → int.
    if event_date and len(event_date) >= 10:
        event_date = event_date[:10]
    elif event_date and len(event_date) == 4 and event_date.isdigit():
        event_date = event_date + "-01"   # "2015" → "2015-01"
    elif event_date and len(event_date) == 7 and event_date[4] == "-":
        pass  # "2015-01" already safe — no coercion possible

    return {
        "events": [{
            "event_date":  event_date,
            "event_type":  _get(row, headers, "event_type") or "statement",
            "significance": _get(row, headers, "significance") or "medium",
            "description":  description,
        }],
        "source": "excel-import",
    }


def _parse_manipulation(row, headers) -> Optional[dict]:
    """Parse a manipulation row: total_score, dominant_pattern, detected_patterns, notes.

    Blank rows are stored as total_score=0.0 (clean — reviewed, no manipulation detected).
    This ensures every processed email is tracked and won't reappear in future exports.
    """
    total_score_raw = _get(row, headers, "total_score")

    # Blank = intentionally left blank by LLM = no manipulation detected = score 0.0
    if not total_score_raw:
        return {
            "patterns":         [],
            "total_score":      0.0,
            "dominant_pattern": None,
            "notes":            "",
            "source":           "excel-import",
        }

    try:
        total_score = round(max(0.0, min(1.0, float(total_score_raw))), 2)
    except (TypeError, ValueError):
        return None

    dominant_pattern = _get(row, headers, "dominant_pattern") or None
    detected_raw     = _get(row, headers, "detected_patterns") or ""
    notes            = _get(row, headers, "notes") or ""

    # Parse "gaslighting:0.8, projection:0.5" → [{type, score}]
    patterns = []
    for item in detected_raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            parts = item.split(":", 1)
            pattern_type = parts[0].strip()
            try:
                score = round(max(0.0, min(1.0, float(parts[1].strip()))), 2)
            except (ValueError, IndexError):
                score = 0.5
        else:
            pattern_type = item
            score = 0.5
        if pattern_type:
            patterns.append({"type": pattern_type, "score": score,
                             "evidence": "", "explanation": ""})

    return {
        "patterns":        patterns,
        "total_score":     total_score,
        "dominant_pattern": dominant_pattern,
        "notes":           notes,
        "source":          "excel-import",
    }


def _import_contradictions(wb, excel_path: Path, run_id: int,
                            provider: str, model: str) -> dict:
    """Import contradiction pairs from the 'Contradictions' output sheet."""
    from src.storage.database import get_db

    if "Contradictions" not in wb.sheetnames:
        raise ValueError(
            "No 'Contradictions' sheet found. "
            "Make sure you filled in the Contradictions output sheet."
        )

    ws = wb["Contradictions"]
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]

    imported = 0
    skipped  = 0
    errors   = []

    with get_db() as conn:
        for row in ws.iter_rows(min_row=3, values_only=True):  # skip header + hint row
            if not row or not row[0]:
                skipped += 1
                continue

            def g(name):
                try:
                    idx = headers.index(name)
                    val = row[idx] if idx < len(row) else None
                    return str(val).strip() if val is not None else None
                except ValueError:
                    return None

            email_id_a  = g("email_id_a")
            email_id_b  = g("email_id_b")
            explanation = g("explanation")

            if not email_id_a or not email_id_b or not explanation:
                skipped += 1
                continue

            # Skip hint row values
            if email_id_a.startswith("←") or not email_id_a.isdigit():
                skipped += 1
                continue

            try:
                conn.execute(
                    """INSERT OR IGNORE INTO contradictions
                       (run_id, email_id_a, email_id_b, scope, topic, severity, explanation)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        int(email_id_a),
                        int(email_id_b),
                        g("scope") or "intra-sender",
                        g("topic") or None,
                        g("severity") or "medium",
                        explanation,
                    ),
                )
                # Also store a result_json for traceability on email_id_a
                result = json.dumps({
                    "email_id_a": int(email_id_a),
                    "email_id_b": int(email_id_b),
                    "scope":      g("scope"),
                    "topic":      g("topic"),
                    "severity":   g("severity"),
                    "explanation": explanation,
                    "source":     "excel-import",
                })
                conn.execute(
                    """INSERT OR REPLACE INTO analysis_results
                       (run_id, email_id, sender_contact_id, result_json)
                       VALUES (?, ?, NULL, ?)""",
                    (run_id, int(email_id_a), result),
                )
                imported += 1
            except Exception as exc:
                errors.append(f"row ({email_id_a},{email_id_b}): {exc}")

        conn.commit()

    status = "complete" if not errors else "partial"
    finish_run(run_id, status, imported)

    return {
        "run_id":   run_id,
        "imported": imported,
        "skipped":  skipped,
        "errors":   errors,
        "status":   status,
    }
