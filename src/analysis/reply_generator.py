"""LLM-powered reply draft generation for the Reply Command Center."""
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config import memories_dir
from src.llm.base import LLMResponse
from src.llm.router import get_provider

_PROMPTS_DIR = Path(__file__).parent / "prompts"

# ── Tone configurations ────────────────────────────────────────────────────────

TONE_CONFIGS = {
    "factual": {
        "label": "Factuel",
        "instruction": (
            "Réponse strictement factuelle. Chaque affirmation est sourcée ou datée. "
            "Pas de formules de politesse superflues. Ton neutre et précis."
        ),
    },
    "firm": {
        "label": "Ferme",
        "instruction": (
            "Ton ferme et assertif. Rappelle les obligations légales et les accords existants. "
            "Ne cède pas de terrain sans contrepartie explicite. Chaque point est abordé sans ambiguïté."
        ),
    },
    "conciliatory": {
        "label": "Conciliant",
        "instruction": (
            "Ton ouvert au dialogue. Propose des compromis raisonnables. Maintiens la fermeté "
            "sur les points essentiels mais montre de la bonne volonté et de l'ouverture."
        ),
    },
    "neutral": {
        "label": "Neutre",
        "instruction": (
            "Ton neutre et professionnel. Ni chaleureux ni hostile. "
            "Échange d'informations pur, sans prise de position émotionnelle."
        ),
    },
    "defensive": {
        "label": "Défensif",
        "instruction": (
            "Réfute point par point les accusations ou affirmations inexactes. "
            "Cite les preuves contraires. Protège ta position sans attaquer."
        ),
    },
    "jaf_producible": {
        "label": "Productible JAF",
        "instruction": (
            "Rédigé comme si le Juge aux Affaires Familiales lisait cette réponse demain. "
            "Formulations juridiques précises. Références aux ordonnances et accords existants. "
            "Créer un écrit de qualité probatoire qui démontre la bonne foi et la coopération."
        ),
    },
}


# ── Prompt builders ─────────────────────────────────────────────────────────────

def build_system_prompt(
    tone: str,
    memories_content: str,
    analysis_context: str,
    user_guidelines: str,
) -> str:
    """Assemble the full system prompt for reply generation."""
    base = (_PROMPTS_DIR / "reply_draft.txt").read_text(encoding="utf-8")

    tone_cfg = TONE_CONFIGS.get(tone, TONE_CONFIGS["factual"])
    tone_section = "TONALITÉ DEMANDÉE: {}\n{}".format(
        tone_cfg["label"], tone_cfg["instruction"]
    )

    parts = [base, "", tone_section]

    if memories_content.strip():
        parts.append("")
        parts.append("MÉMOIRES CONTEXTUELLES (faits et positions à connaître):")
        parts.append(memories_content)

    if analysis_context.strip():
        parts.append("")
        parts.append("ANALYSES EXISTANTES DE CET EMAIL:")
        parts.append(analysis_context)

    if user_guidelines.strip():
        parts.append("")
        parts.append("CONSIGNES SPÉCIFIQUES DE L'UTILISATEUR:")
        parts.append(user_guidelines)

    return "\n".join(parts)


def build_user_prompt(
    email_row: Dict[str, Any],
    thread_emails: List[Dict[str, Any]],
    pending_actions: List[Dict[str, Any]],
) -> str:
    """Assemble the user prompt with the email and context."""
    parts = ["Voici l'email auquel tu dois répondre:", ""]
    parts.append("DATE: {}".format(email_row.get("date", "?")))
    parts.append("DE: {}".format(email_row.get("from_address", "?")))
    parts.append("OBJET: {}".format(email_row.get("subject", "(sans objet)")))
    parts.append("CONTENU:")
    parts.append(email_row.get("delta_text", "") or email_row.get("body_text", ""))

    if thread_emails:
        parts.append("")
        parts.append("CONTEXTE DU FIL (emails précédents, du plus ancien au plus récent):")
        for i, te in enumerate(thread_emails, 1):
            parts.append("")
            parts.append("--- Email {} ---".format(i))
            parts.append("Date: {} | De: {} | Direction: {}".format(
                te.get("date", "?"), te.get("from_address", "?"), te.get("direction", "?")
            ))
            parts.append("Objet: {}".format(te.get("subject", "")))
            delta = te.get("delta_text", "") or te.get("body_text", "")
            # Truncate long thread emails to avoid blowing up context
            if len(delta) > 2000:
                delta = delta[:2000] + "\n[... tronqué ...]"
            parts.append(delta)

    if pending_actions:
        parts.append("")
        parts.append("QUESTIONS / DEMANDES IDENTIFIÉES DANS CET EMAIL:")
        for pa in pending_actions:
            parts.append("- [{}] {}".format(pa.get("action_type", "?"), pa.get("text", "")))

    parts.append("")
    parts.append("Rédige une réponse complète couvrant tous les points.")

    return "\n".join(parts)


def load_memories_content(slugs: List[str], conn: sqlite3.Connection) -> str:
    """Load and concatenate memory file contents for the given slugs."""
    if not slugs:
        return ""

    placeholders = ",".join("?" for _ in slugs)
    rows = conn.execute(
        "SELECT slug, display_name, file_path FROM reply_memories "
        "WHERE slug IN ({})".format(placeholders),
        slugs,
    ).fetchall()

    parts = []
    mem_dir = memories_dir()
    for row in rows:
        fpath = Path(row["file_path"])
        if not fpath.is_absolute():
            fpath = mem_dir / fpath.name
        if fpath.exists():
            content = fpath.read_text(encoding="utf-8").strip()
            if content:
                parts.append("=== {} ===".format(row["display_name"]))
                parts.append(content)
                parts.append("")

    return "\n".join(parts)


def get_analysis_context(conn: sqlite3.Connection, email_id: int) -> str:
    """Fetch existing tone/manipulation analysis for the email."""
    rows = conn.execute(
        """SELECT ar.result_json, arun.analysis_type
           FROM analysis_results ar
           JOIN analysis_runs arun ON ar.run_id = arun.id
           WHERE ar.email_id = ?
           AND arun.analysis_type IN ('tone', 'manipulation')""",
        (email_id,),
    ).fetchall()

    parts = []
    for row in rows:
        try:
            data = json.loads(row["result_json"])
        except (json.JSONDecodeError, TypeError):
            continue

        atype = row["analysis_type"]
        if atype == "tone":
            parts.append("- Tonalité détectée: {}".format(data.get("tone", "?")))
            parts.append("- Niveau d'agressivité: {}".format(data.get("aggression_level", "?")))
            parts.append("- Score de manipulation: {}".format(data.get("manipulation_score", "?")))
            parts.append("- Posture juridique: {}".format(
                "Oui" if data.get("legal_posturing") else "Non"
            ))
        elif atype == "manipulation":
            score = data.get("total_score", 0)
            if score and score > 0:
                dominant = data.get("dominant_pattern", "?")
                parts.append("- Manipulation dominante: {} (score: {:.1f})".format(
                    dominant, score
                ))

    # Contradictions involving this email
    contras = conn.execute(
        """SELECT c.explanation, c.severity,
                  COALESCE(c.topic, t.name) AS topic_name
           FROM contradictions c
           LEFT JOIN topics t ON c.topic_id = t.id
           WHERE c.email_id_a = ? OR c.email_id_b = ?""",
        (email_id, email_id),
    ).fetchall()
    if contras:
        parts.append("")
        parts.append("CONTRADICTIONS DÉTECTÉES impliquant cet email:")
        for c in contras:
            parts.append("- [{}] {}: {}".format(
                c["severity"], c["topic_name"] or "?", c["explanation"]
            ))

    return "\n".join(parts)


def get_thread_context(
    conn: sqlite3.Connection,
    email_id: int,
    thread_id: int,
    depth: int = 5,
) -> List[Dict[str, Any]]:
    """Fetch up to `depth` preceding emails in the thread."""
    rows = conn.execute(
        """SELECT id, date, from_address, from_name, subject,
                  direction, delta_text, body_text
           FROM emails
           WHERE thread_id = ? AND id != ?
           ORDER BY date DESC
           LIMIT ?""",
        (thread_id, email_id, depth),
    ).fetchall()
    # Return in chronological order (oldest first)
    return [dict(r) for r in reversed(rows)]


def generate_reply_draft(
    conn: sqlite3.Connection,
    email_id: int,
    tone: str = "factual",
    guidelines: str = "",
    memory_slugs: Optional[List[str]] = None,
    thread_depth: int = 5,
    provider_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate a reply draft for an email using the configured LLM provider.

    Returns a dict with the draft details (stored in reply_drafts table).
    """
    if memory_slugs is None:
        memory_slugs = []

    # Load email
    email_row = conn.execute(
        "SELECT * FROM emails WHERE id = ?", (email_id,)
    ).fetchone()
    if not email_row:
        raise ValueError("Email {} not found".format(email_id))

    email_dict = dict(email_row)

    # Thread context
    thread_id = email_dict.get("thread_id")
    thread_emails = []
    if thread_id:
        thread_emails = get_thread_context(conn, email_id, thread_id, thread_depth)

    # Pending actions
    actions = conn.execute(
        "SELECT action_type, text FROM pending_actions "
        "WHERE email_id = ? AND resolved = 0",
        (email_id,),
    ).fetchall()
    pending_actions = [dict(a) for a in actions]

    # Build prompts
    memories_content = load_memories_content(memory_slugs, conn)
    analysis_context = get_analysis_context(conn, email_id)

    system_prompt = build_system_prompt(tone, memories_content, analysis_context, guidelines)
    user_prompt = build_user_prompt(email_dict, thread_emails, pending_actions)

    # Call LLM
    provider = get_provider("reply_draft", override=provider_override)
    response = provider.complete_with_retry(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=4096,
        temperature=0.3,
    )

    # Get next version number
    ver_row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM reply_drafts WHERE email_id = ?",
        (email_id,),
    ).fetchone()
    next_version = (ver_row["v"] if ver_row else 0) + 1

    # Store draft
    cursor = conn.execute(
        """INSERT INTO reply_drafts
           (email_id, version, tone, guidelines, memories_used, thread_depth,
            system_prompt, user_prompt, draft_text, provider_name, model_id,
            input_tokens, output_tokens, latency_ms, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')""",
        (
            email_id, next_version, tone, guidelines,
            json.dumps(memory_slugs), thread_depth,
            system_prompt, user_prompt, response.content,
            response.provider_name, response.model_id,
            response.input_tokens, response.output_tokens,
            response.latency_ms,
        ),
    )
    conn.commit()

    draft_id = cursor.lastrowid

    # Update email status to 'drafted' if it was 'pending'
    conn.execute(
        "UPDATE emails SET reply_status = 'drafted' "
        "WHERE id = ? AND reply_status IN ('unset', 'pending')",
        (email_id,),
    )
    conn.commit()

    return {
        "id": draft_id,
        "email_id": email_id,
        "version": next_version,
        "tone": tone,
        "draft_text": response.content,
        "provider_name": response.provider_name,
        "model_id": response.model_id,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
    }


def extract_pending_actions(
    conn: sqlite3.Connection,
    email_id: int,
    provider_override: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Use LLM to extract questions/requests/demands from an email."""
    email_row = conn.execute(
        "SELECT delta_text, body_text, subject FROM emails WHERE id = ?",
        (email_id,),
    ).fetchone()
    if not email_row:
        return []

    content = email_row["delta_text"] or email_row["body_text"] or ""
    if not content.strip():
        return []

    system_prompt = (_PROMPTS_DIR / "extract_actions.txt").read_text(encoding="utf-8")
    user_prompt = "OBJET: {}\n\nCONTENU:\n{}".format(
        email_row["subject"] or "(sans objet)", content
    )

    provider = get_provider("reply_draft", override=provider_override)
    response = provider.complete_with_retry(
        prompt=user_prompt,
        system=system_prompt,
        max_tokens=2048,
        temperature=0.1,
    )

    # Parse JSON response
    text = response.content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]

    try:
        actions = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(actions, list):
        return []

    # Store in DB
    stored = []
    for action in actions:
        atype = action.get("action_type", "question")
        atext = action.get("text", "").strip()
        if not atext:
            continue
        cursor = conn.execute(
            "INSERT INTO pending_actions (email_id, action_type, text, extracted_by) "
            "VALUES (?, ?, ?, 'llm')",
            (email_id, atype, atext),
        )
        stored.append({
            "id": cursor.lastrowid,
            "email_id": email_id,
            "action_type": atype,
            "text": atext,
            "resolved": False,
            "extracted_by": "llm",
        })
    conn.commit()

    return stored
