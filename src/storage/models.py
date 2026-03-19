"""Data classes for all database entities."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Contact:
    id: Optional[int]
    name: str
    email: str            # Primary email address
    aliases: List[str]    # Additional addresses for the same person
    role: str             # 'me', 'ex-wife', 'lawyer', 'other'
    notes: str = ""


@dataclass
class Email:
    id: Optional[int]
    message_id: str       # RFC Message-ID header (unique)
    in_reply_to: str      # In-Reply-To header
    references: str       # References header (space-separated)
    thread_id: Optional[int]
    date: datetime
    from_address: str
    from_name: str
    to_addresses: str     # JSON list
    cc_addresses: str     # JSON list
    subject: str
    subject_normalized: str   # Subject stripped of Re:/TR:/Fwd: prefixes
    body_text: str
    body_html: str
    delta_text: str       # New content only, quotes stripped
    delta_hash: str       # SHA256 of delta_text for dedup
    raw_size_bytes: int
    folder: str           # IMAP folder
    uid: int              # IMAP UID
    direction: str        # 'sent' or 'received'
    language: str         # 'fr', 'en', 'unknown'
    has_attachments: bool
    contact_id: Optional[int]   # FK to contacts (the other party)
    fetched_at: datetime


@dataclass
class Attachment:
    id: Optional[int]
    email_id: int
    filename: str
    content_type: str
    size_bytes: int
    content: Optional[bytes]  # Stored lazily


@dataclass
class Thread:
    id: Optional[int]
    subject_normalized: str
    first_date: datetime
    last_date: datetime
    email_count: int
    contact_id: Optional[int]


@dataclass
class Topic:
    id: Optional[int]
    name: str
    description: str
    color: str = "#6366f1"   # For UI display
    is_user_defined: bool = True


@dataclass
class EmailTopic:
    email_id: int
    topic_id: int
    confidence: float        # 0.0–1.0
    run_id: int


@dataclass
class AnalysisRun:
    id: Optional[int]
    run_date: datetime
    analysis_type: str       # 'classify', 'tone', 'timeline', 'contradictions', 'manipulation'
    provider_name: str       # 'claude', 'openai', 'groq', 'ollama'
    model_id: str            # Exact model string, e.g. 'claude-sonnet-4-6'
    prompt_hash: str         # SHA256 of the prompt template used
    prompt_version: str      # Human label, e.g. 'v1-french-legal'
    status: str              # 'running', 'complete', 'partial', 'failed'
    email_count: int = 0
    notes: str = ""


@dataclass
class AnalysisResult:
    id: Optional[int]
    run_id: int
    email_id: int
    sender_contact_id: Optional[int]   # Who sent this email (perspective for analysis)
    result_json: str                   # Full LLM output as JSON string
    created_at: datetime


@dataclass
class Contradiction:
    id: Optional[int]
    run_id: int
    email_id_a: int
    email_id_b: int
    scope: str               # 'intra-sender' or 'cross-sender'
    topic_id: Optional[int]
    explanation: str
    severity: str            # 'low', 'medium', 'high'
    created_at: datetime


@dataclass
class TimelineEvent:
    id: Optional[int]
    run_id: int
    email_id: int
    topic_id: Optional[int]
    event_date: datetime
    event_type: str          # 'statement', 'commitment', 'accusation', 'demand', etc.
    description: str
    significance: str        # 'low', 'medium', 'high'
    created_at: datetime


@dataclass
class CourtEvent:
    id: Optional[int]
    event_date: datetime
    event_type: str          # 'hearing', 'filing', 'decision', 'appeal', 'other'
    jurisdiction: str        # e.g. 'TGI Paris', 'CAA Lyon'
    description: str
    outcome: str = ""
    notes: str = ""


@dataclass
class ExternalEvent:
    id: Optional[int]
    event_date: datetime
    category: str            # 'move', 'job', 'lawyer_change', 'other'
    description: str
    notes: str = ""
