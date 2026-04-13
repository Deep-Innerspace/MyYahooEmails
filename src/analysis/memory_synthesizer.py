"""
Memory synthesizer: queries existing analysis results and proposes memory file updates.

Usage:
    python cli.py memories synthesize --topic enfants
    python cli.py memories synthesize --topic vacances --since 2023-01-01
"""
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_SECTIONS = [
    "Quick Context",
    "Current Legal Position",
    "Party A's Established Positions",
    "Party B's Known Positions",
    "Active Open Disputes",
    "Communication Pattern Intelligence",
]


# ── Data gathering ─────────────────────────────────────────────────────────────

def _gather_topic_data(
    conn: sqlite3.Connection,
    topic: str,
    since: Optional[str] = None,
    max_summaries: int = 60,
) -> Dict[str, Any]:
    """Collect all available analysis data for a topic from the DB."""
    date_filter = "AND e.date >= '{}' ".format(since) if since else ""

    # Email summaries (sent + received, most recent first)
    summaries = conn.execute("""
        SELECT e.id, e.date, e.direction, e.subject,
               json_extract(ar.result_json, '$.summary') AS summary,
               json_extract(ar_tone.result_json, '$.aggression_level') AS aggression,
               json_extract(ar_tone.result_json, '$.tone') AS tone_label
        FROM emails e
        JOIN email_topics et ON e.id = et.email_id
        JOIN topics t ON et.topic_id = t.id AND t.name = ?
        JOIN analysis_results ar ON ar.email_id = e.id
        JOIN analysis_runs arun ON ar.run_id = arun.id AND arun.analysis_type = 'classify'
        LEFT JOIN analysis_results ar_tone ON ar_tone.email_id = e.id
        LEFT JOIN analysis_runs arun_t ON ar_tone.run_id = arun_t.id
            AND arun_t.analysis_type = 'tone'
        WHERE e.corpus = 'personal'
          AND json_extract(ar.result_json, '$.summary') IS NOT NULL
          AND json_extract(ar.result_json, '$.summary') != ''
          {}
        ORDER BY ar.run_id DESC, e.date DESC
    """.format(date_filter), (topic,)).fetchall()

    # Deduplicate by email_id (keep first = latest run)
    seen = set()
    unique_summaries = []
    for r in summaries:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique_summaries.append(dict(r))
    unique_summaries = unique_summaries[:max_summaries]

    # Aggression stats
    stats = conn.execute("""
        SELECT e.direction,
               ROUND(AVG(json_extract(ar.result_json, '$.aggression_level')), 2) AS avg_aggr,
               ROUND(MAX(json_extract(ar.result_json, '$.aggression_level')), 2) AS max_aggr,
               COUNT(*) AS cnt
        FROM analysis_results ar
        JOIN analysis_runs arun ON ar.run_id = arun.id AND arun.analysis_type = 'tone'
        JOIN emails e ON ar.email_id = e.id
        JOIN email_topics et ON e.id = et.email_id
        JOIN topics t ON et.topic_id = t.id AND t.name = ?
        WHERE e.corpus = 'personal' {}
        GROUP BY e.direction
    """.format(date_filter), (topic,)).fetchall()

    # Manipulation patterns (received only)
    manip = conn.execute("""
        SELECT json_extract(ar.result_json, '$.dominant_pattern') AS pattern,
               COUNT(*) AS cnt,
               ROUND(AVG(json_extract(ar.result_json, '$.total_score')), 2) AS avg_score
        FROM analysis_results ar
        JOIN analysis_runs arun ON ar.run_id = arun.id AND arun.analysis_type = 'manipulation'
        JOIN emails e ON ar.email_id = e.id AND e.direction = 'received'
        JOIN email_topics et ON e.id = et.email_id
        JOIN topics t ON et.topic_id = t.id AND t.name = ?
        WHERE json_extract(ar.result_json, '$.total_score') > 0.3 {}
        GROUP BY pattern ORDER BY cnt DESC LIMIT 6
    """.format(date_filter), (topic,)).fetchall()

    # Timeline events (high + medium significance)
    events = conn.execute("""
        SELECT DISTINCT te.event_date, te.event_type, te.description,
               e.direction, te.significance
        FROM timeline_events te
        JOIN emails e ON te.email_id = e.id
        JOIN email_topics et ON e.id = et.email_id
        JOIN topics t ON et.topic_id = t.id AND t.name = ?
        WHERE te.significance IN ('high', 'medium')
        ORDER BY te.significance DESC, te.event_date DESC
        LIMIT 20
    """, (topic,)).fetchall()

    # Contradictions
    contras = conn.execute("""
        SELECT c.severity, c.explanation, c.scope,
               ea.date AS date_a, eb.date AS date_b,
               ea.direction AS dir_a, eb.direction AS dir_b
        FROM contradictions c
        JOIN emails ea ON c.email_id_a = ea.id
        JOIN emails eb ON c.email_id_b = eb.id
        WHERE COALESCE(c.topic, (SELECT name FROM topics WHERE id = c.topic_id)) = ?
        ORDER BY CASE c.severity WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END
        LIMIT 10
    """, (topic,)).fetchall()

    # Related procedures
    procedures = conn.execute("""
        SELECT DISTINCT p.id, p.name, p.case_number, p.status,
               p.date_start, p.date_end, p.jurisdiction
        FROM procedures p
        JOIN procedure_events pe ON pe.procedure_id = p.id
        JOIN emails e ON e.procedure_id = p.id
        JOIN email_topics et ON e.id = et.email_id
        JOIN topics t ON et.topic_id = t.id AND t.name = ?
        ORDER BY p.date_start
    """, (topic,)).fetchall()

    return {
        "topic": topic,
        "since": since,
        "summaries": unique_summaries,
        "stats": [dict(r) for r in stats],
        "manipulation": [dict(r) for r in manip],
        "timeline_events": [dict(r) for r in events],
        "contradictions": [dict(r) for r in contras],
        "procedures": [dict(r) for r in procedures],
    }


def _format_data_for_prompt(data: Dict[str, Any]) -> str:
    """Serialize gathered data into a compact, LLM-readable text block."""
    parts = []

    parts.append("=== TOPIC: {} ===".format(data["topic"].upper()))
    if data["since"]:
        parts.append("Période analysée : depuis {}".format(data["since"]))
    parts.append("")

    if data["procedures"]:
        parts.append("PROCÉDURES JUDICIAIRES LIÉES:")
        for p in data["procedures"]:
            end = p["date_end"] or "active"
            parts.append("  #{} {} | {} | {} → {} | {}".format(
                p["id"], p["name"], p.get("case_number") or "RG ?",
                p["date_start"] or "?", end, p["status"]
            ))
        parts.append("")

    if data["stats"]:
        parts.append("STATISTIQUES D'AGRESSIVITÉ:")
        for s in data["stats"]:
            parts.append("  direction={} avg={} max={} ({} emails)".format(
                s["direction"], s["avg_aggr"], s["max_aggr"], s["cnt"]
            ))
        parts.append("")

    if data["manipulation"]:
        parts.append("PATTERNS DE MANIPULATION DÉTECTÉS (emails reçus, score > 0.3):")
        for m in data["manipulation"]:
            parts.append("  {} : {} emails, score moyen {}".format(
                m["pattern"], m["cnt"], m["avg_score"]
            ))
        parts.append("")

    if data["contradictions"]:
        parts.append("PAIRES DE CONTRADICTIONS:")
        for c in data["contradictions"]:
            parts.append("  [{}] {} vs {} : {}".format(
                c["severity"], c["date_a"][:10] if c["date_a"] else "?",
                c["date_b"][:10] if c["date_b"] else "?",
                (c["explanation"] or "")[:200]
            ))
        parts.append("")

    if data["timeline_events"]:
        parts.append("ÉVÉNEMENTS CLÉS (timeline, high/medium significance):")
        for e in data["timeline_events"]:
            parts.append("  [{}|{}|{}] {} : {}".format(
                e["event_date"][:10] if e["event_date"] else "?",
                e["direction"], e["significance"],
                e["event_type"],
                (str(e["description"]) or "")[:150]
            ))
        parts.append("")

    if data["summaries"]:
        parts.append("RÉSUMÉS D'EMAILS (max 60, récents en premier):")
        sent = [s for s in data["summaries"] if s["direction"] == "sent"]
        recv = [s for s in data["summaries"] if s["direction"] == "received"]

        parts.append("  -- Envoyés par le père ({}) --".format(len(sent)))
        for s in sent[:30]:
            aggr = " [aggr:{:.1f}]".format(s["aggression"]) if s.get("aggression") else ""
            parts.append("  [{}]{} {}".format(
                s["date"][:10] if s["date"] else "?", aggr, s["summary"]
            ))

        parts.append("  -- Reçus de la mère ({}) --".format(len(recv)))
        for s in recv[:30]:
            aggr = " [aggr:{:.1f}]".format(s["aggression"]) if s.get("aggression") else ""
            parts.append("  [{}]{} {}".format(
                s["date"][:10] if s["date"] else "?", aggr, s["summary"]
            ))

    return "\n".join(parts)


# ── LLM call ───────────────────────────────────────────────────────────────────

def synthesize_topic_memory(
    conn: sqlite3.Connection,
    topic: str,
    since: Optional[str] = None,
    provider_override: Optional[str] = None,
) -> str:
    """
    Query the DB, call the LLM, return the proposed new memory content as a string.
    """
    from src.llm.router import get_provider

    data = _gather_topic_data(conn, topic, since)
    data_text = _format_data_for_prompt(data)

    system_prompt = (_PROMPTS_DIR / "memory_synthesis.txt").read_text(
        encoding="utf-8"
    ).replace("{topic}", topic)

    sections_list = "\n".join("- ## {}".format(s) for s in _SECTIONS)
    user_prompt = (
        "Voici les données d'analyse pour le topic '{}':\n\n{}\n\n"
        "Génère le contenu Markdown pour les sections suivantes "
        "(dans cet ordre exact, sans omettre aucune) :\n{}\n\n"
        "Pour '## Red Lines — NEVER in Writing', écris uniquement : [À COMPLÉTER]\n"
        "Pour '## Quick Context', limite-toi à 150 tokens maximum (faits denses, "
        "bullet points courts)."
    ).format(topic, data_text, sections_list)

    provider = get_provider("memory_synthesis", override=provider_override)
    response = provider.complete_with_retry(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=3000,
        temperature=0.1,
    )

    return response.content.strip()


# ── Section-level diff ─────────────────────────────────────────────────────────

def _parse_sections_from_text(text: str) -> Dict[str, str]:
    """Extract ## section bodies from a markdown string."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    blocks = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    result = {}
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        header = lines[0].lstrip("#").strip()
        body = "\n".join(lines[1:]).strip()
        result[header] = body
    return result


def diff_sections(
    existing_path: Path,
    proposed_text: str,
) -> List[Tuple[str, str, str]]:
    """
    Return list of (section_header, old_body, new_body) for sections that differ.
    Sections absent in existing are treated as empty.
    """
    existing_text = existing_path.read_text(encoding="utf-8") if existing_path.exists() else ""
    existing = _parse_sections_from_text(existing_text)
    proposed = _parse_sections_from_text(proposed_text)

    diffs = []
    for header in _SECTIONS:
        old = existing.get(header, "").strip()
        new = proposed.get(header, "").strip()
        if old != new and new:
            diffs.append((header, old, new))
    return diffs


def apply_section_updates(
    file_path: Path,
    updates: Dict[str, str],
) -> None:
    """
    Write approved section updates back into the memory file.
    Preserves frontmatter comment and file structure.
    """
    existing = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

    # Extract frontmatter comment if present
    frontmatter = ""
    fm_match = re.match(r"(<!--.*?-->\s*\n)", existing, re.DOTALL)
    if fm_match:
        frontmatter = fm_match.group(1)

    # Parse existing sections
    sections = _parse_sections_from_text(existing)

    # Apply updates
    for header, new_body in updates.items():
        sections[header] = new_body

    # Find the H1 title
    title_match = re.search(r"^# .+", existing, re.MULTILINE)
    title = title_match.group(0) if title_match else "# {}".format(file_path.stem.title())

    # Rebuild file preserving section order
    parts = [frontmatter + title]
    for header in _SECTIONS + [h for h in sections if h not in _SECTIONS]:
        body = sections.get(header, "")
        if body:
            parts.append("\n## {}\n{}".format(header, body))

    # Update meta comment date
    new_content = "\n".join(parts)
    new_content = re.sub(
        r"(<!-- meta:.*?updated=)\S+",
        r"\g<1>2026-04-13",
        new_content,
    )

    file_path.write_text(new_content, encoding="utf-8")
