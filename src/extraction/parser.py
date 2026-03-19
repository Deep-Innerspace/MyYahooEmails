"""
Email MIME parser with bilingual (EN/FR) quote stripping and delta extraction.

The 'delta_text' of an email is the new content only — quoted replies are removed.
This is the core deduplication mechanism and what gets sent to LLMs for analysis.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.header import decode_header as _decode_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

# ──────────────────────────── QUOTE PATTERNS ────────────────────────────────

# Each pattern matches the START of a quoted block.
# Everything from the match to end-of-text is considered a quoted reply.
# Order matters: more specific patterns first.

_QUOTE_PATTERNS = [
    # French: "Le DD/MM/YYYY à HH:MM, Prénom Nom <email> a écrit :"
    re.compile(
        r"Le\s+\d{1,2}[./]\d{1,2}[./]\d{2,4}[\s,àa]+\d{1,2}:\d{2}"
        r"(?:\s*\([A-Z]+\))?[\s,]+.+?\s+a\s+écrit\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # English: "On Mon, Jan 1, 2024 at 12:00 PM, Name <email> wrote:"
    re.compile(
        r"On\s+\w+[\s,]+\w+\s+\d{1,2}[\s,]+\d{4}[\s,]+at\s+\d{1,2}:\d{2}"
        r"(?:\s*[AP]M)?[\s,]+.+wrote\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # English short: "On 01/01/2024 12:00, Name wrote:"
    re.compile(
        r"On\s+\d{1,2}[./]\d{1,2}[./]\d{2,4}[,\s]+\d{1,2}:\d{2}.*wrote\s*:?\s*$",
        re.MULTILINE | re.IGNORECASE,
    ),
    # French separator line
    re.compile(r"^-{4,}\s*Message\s+d.origine\s*-{4,}", re.MULTILINE | re.IGNORECASE),
    # English separator line
    re.compile(r"^-{4,}\s*Original\s+Message\s*-{4,}", re.MULTILINE | re.IGNORECASE),
    # Gmail/generic forwarded message separator
    re.compile(r"^-{8,}\s*(?:Forwarded|Transferred)\s+[Mm]essage\s*-{8,}", re.MULTILINE),
    re.compile(r"^-{8,}\s*[Mm]essage\s+transf.r.\s*-{8,}", re.MULTILINE),
    # French header block (De:/Envoyé:/À:/Objet:)
    re.compile(r"^De\s*:\s*.+\nEnvoy", re.MULTILINE),
    # English header block (From:/Sent:/To:/Subject:)
    re.compile(r"^From\s*:\s*.+\nSent\s*:", re.MULTILINE),
    # Lines starting with > (standard quoting)
    re.compile(r"^\s*>+\s*", re.MULTILINE),
]

# Subject prefixes to strip for normalization
_SUBJECT_PREFIXES = re.compile(
    r"^(?:(?:re|ref|tr|fwd?|réf|transf)\s*:\s*)+",
    re.IGNORECASE,
)


# ─────────────────────────── HEADER DECODING ────────────────────────────────

def _decode_str(value: Optional[str]) -> str:
    """Decode an RFC 2047 encoded email header value to plain text."""
    if not value:
        return ""
    parts = []
    for raw, charset in _decode_header(value):
        if isinstance(raw, bytes):
            try:
                parts.append(raw.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                parts.append(raw.decode("utf-8", errors="replace"))
        else:
            parts.append(raw)
    return "".join(parts).strip()


def _parse_address(header: Optional[str]) -> Tuple[str, str]:
    """Return (name, email) from an address header."""
    if not header:
        return "", ""
    name, addr = parseaddr(_decode_str(header))
    return name.strip(), addr.strip().lower()


def _parse_address_list(header: Optional[str]) -> List[str]:
    """Return list of email addresses from a To/CC header."""
    if not header:
        return []
    decoded = _decode_str(header)
    parts = re.split(r",\s*", decoded)
    result = []
    for p in parts:
        _, addr = parseaddr(p)
        if addr:
            result.append(addr.strip().lower())
    return result


def _parse_date(msg: Message) -> datetime:
    """Parse the Date header; fall back to epoch on failure."""
    date_str = msg.get("Date", "")
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return datetime(1970, 1, 1)


# ─────────────────────────── BODY EXTRACTION ────────────────────────────────

def _get_body(msg: Message) -> Tuple[str, str]:
    """Extract (text_body, html_body) from a MIME message."""
    text_parts: List[str] = []
    html_parts: List[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if ctype == "text/plain":
                text_parts.append(text)
            elif ctype == "text/html":
                html_parts.append(text)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(text)
            else:
                text_parts.append(text)

    return "\n\n".join(text_parts).strip(), "\n\n".join(html_parts).strip()


def _get_attachments(msg: Message) -> List[Dict[str, Any]]:
    """Return list of attachment metadata (without content)."""
    result = []
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" not in disp:
                continue
            filename = _decode_str(part.get_filename() or "")
            ctype = part.get_content_type()
            payload = part.get_payload(decode=True) or b""
            result.append({
                "filename": filename,
                "content_type": ctype,
                "size_bytes": len(payload),
                "content": payload,
            })
    return result


# ─────────────────────────── QUOTE STRIPPING ────────────────────────────────

def strip_quotes(text: str) -> str:
    """
    Remove quoted reply sections from an email body.
    Returns only the new content written by the sender.
    """
    if not text:
        return ""

    # Find the earliest match position among all patterns
    earliest_pos = len(text)
    for pattern in _QUOTE_PATTERNS:
        # For line-based patterns, find the match in the full text
        for match in pattern.finditer(text):
            if match.start() < earliest_pos:
                earliest_pos = match.start()
                break  # First match of this pattern is enough

    # Handle > quoted lines: remove any line starting with >
    # (these can be interspersed, not just at the end)
    if earliest_pos == len(text):
        # No separator found — remove > lines inline
        lines = text.split("\n")
        new_lines = [l for l in lines if not re.match(r"^\s*>", l)]
        text = "\n".join(new_lines)
    else:
        text = text[:earliest_pos]

    # Clean up trailing whitespace and excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_subject(subject: str) -> str:
    """Strip Re:/TR:/Fwd: prefixes for thread grouping."""
    s = _SUBJECT_PREFIXES.sub("", subject.strip())
    return s.strip()


def detect_language(text: str) -> str:
    """Simple heuristic language detection (fr/en/unknown)."""
    if not text:
        return "unknown"
    # Count French-specific words
    fr_words = len(re.findall(
        r"\b(le|la|les|de|du|des|un|une|et|en|à|est|je|tu|il|elle|nous|vous|ils|elles|que|qui|dans|pour|avec|sur|par|pas|plus|vous|mais|ou|donc|or|ni|car)\b",
        text[:500], re.IGNORECASE
    ))
    en_words = len(re.findall(
        r"\b(the|a|an|of|and|in|to|for|is|it|you|he|she|we|they|this|that|at|by|with|from|but|or|not|are|was|be|have|has|had|do|does|did|will|would|could|should|may|might)\b",
        text[:500], re.IGNORECASE
    ))
    if fr_words == 0 and en_words == 0:
        return "unknown"
    if fr_words > en_words * 1.5:
        return "fr"
    if en_words > fr_words * 1.5:
        return "en"
    return "fr"  # Default to French for this project


def compute_delta_hash(delta_text: str) -> str:
    """SHA256 hash of normalized delta text for duplicate detection."""
    normalized = re.sub(r"\s+", " ", delta_text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ─────────────────────────── MAIN PARSER ────────────────────────────────────

def parse_raw_email(
    uid: int,
    raw_bytes: bytes,
    folder: str,
    my_email: str,
) -> Optional[Dict[str, Any]]:
    """
    Parse a raw RFC 2822 email into a structured dict ready for DB insertion.

    Returns None if the message cannot be parsed.
    """
    if not raw_bytes:
        return None

    try:
        msg = message_from_bytes(raw_bytes, policy=policy.compat32)
    except Exception:
        return None

    # Headers
    message_id = _decode_str(msg.get("Message-ID", "")).strip("<>")
    if not message_id:
        return None  # Skip messages without a Message-ID

    in_reply_to = _decode_str(msg.get("In-Reply-To", "")).strip("<>")
    references = _decode_str(msg.get("References", ""))

    from_name, from_address = _parse_address(msg.get("From", ""))
    to_addresses = _parse_address_list(msg.get("To", ""))
    cc_addresses = _parse_address_list(msg.get("Cc", ""))
    subject = _decode_str(msg.get("Subject", ""))
    subject_normalized = normalize_subject(subject)

    date = _parse_date(msg)
    direction = "sent" if from_address.lower() == my_email.lower() else "received"

    # Body
    body_text, body_html = _get_body(msg)

    # Delta extraction (new content only)
    delta_text = strip_quotes(body_text)
    language = detect_language(delta_text or body_text)
    delta_hash = compute_delta_hash(delta_text)

    # Attachments
    attachments = _get_attachments(msg)

    return {
        "message_id": message_id,
        "in_reply_to": in_reply_to,
        "references_header": references,
        "date": date,
        "from_address": from_address,
        "from_name": from_name,
        "to_addresses": json.dumps(to_addresses),
        "cc_addresses": json.dumps(cc_addresses),
        "subject": subject,
        "subject_normalized": subject_normalized,
        "body_text": body_text,
        "body_html": body_html,
        "delta_text": delta_text,
        "delta_hash": delta_hash,
        "raw_size_bytes": len(raw_bytes),
        "folder": folder,
        "uid": uid,
        "direction": direction,
        "language": language,
        "has_attachments": len(attachments) > 0,
        "attachments": attachments,
    }
