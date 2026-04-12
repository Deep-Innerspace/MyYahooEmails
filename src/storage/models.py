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
    role: str             # 'me', 'ex-wife', 'my_lawyer', 'her_lawyer', 'opposing_counsel', 'family', 'school', 'medical', 'housing', 'other'
    notes: str = ""
    firm_name: str = ""           # Law firm name (for lawyer roles)
    bar_jurisdiction: str = ""    # Bar jurisdiction / city (for lawyer roles)


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
    corpus: str = "personal"    # 'personal' or 'legal'


@dataclass
class Attachment:
    id: Optional[int]
    email_id: int
    filename: str
    content_type: str
    size_bytes: int
    content: Optional[bytes]  # BLOB for personal corpus (legacy)
    mime_section: Optional[str] = None   # IMAP BODY part ID for re-fetch
    imap_uid: Optional[int] = None       # UID on server
    folder: Optional[str] = None         # IMAP folder
    downloaded: bool = True              # True if content available
    download_path: Optional[str] = None  # Filesystem path (on-demand downloads)
    category: Optional[str] = None       # Document classification


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
class Procedure:
    id: Optional[int]
    name: str
    procedure_type: str      # 'divorce', 'custody', 'finances', 'appeal', 'liquidation', 'refere', 'jaf_modification'
    jurisdiction: str        # e.g. 'TGI Paris', 'Cour d''appel Versailles'
    case_number: str = ""
    filing_date: Optional[str] = None
    initiated_by: str = ""   # 'party_a' (Madame) or 'party_b' (Monsieur)
    party_a_lawyer_id: Optional[int] = None
    party_b_lawyer_id: Optional[int] = None
    status: str = "active"   # 'active', 'closed', 'appealed', 'settled'
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    description: str = ""
    outcome_summary: str = ""
    notes: str = ""


@dataclass
class ProcedureEvent:
    id: Optional[int]
    procedure_id: int
    event_date: str
    event_type: str          # 'filing', 'hearing', 'judgment', 'ordonnance', 'signification', 'appeal', 'mediation', 'expertise', 'depot_conclusions', 'conclusions_received'
    date_precision: str = "exact"  # 'exact', 'month', 'approximate'
    description: str = ""
    outcome: str = ""
    source_email_id: Optional[int] = None
    source_attachment_id: Optional[int] = None
    notes: str = ""
    # Structured ruling fields (judgment / ordonnance only)
    judge_name: str = ""
    ruling_for: str = ""          # party_a | party_b | both | neutral | unknown
    pension_amount: Optional[float] = None   # monthly EUR, nullable
    custody_arrangement: str = ""  # alternée | résidence_principale_a | résidence_principale_b | supervisée | other
    obligations: str = ""          # JSON array of specific obligation strings


@dataclass
class LawyerInvoice:
    id: Optional[int]
    procedure_id: Optional[int]
    contact_id: int          # Which lawyer
    email_id: Optional[int]
    attachment_id: Optional[int] = None
    invoice_date: str = ""
    invoice_number: str = ""
    amount_ht: Optional[float] = None
    amount_ttc: Optional[float] = None
    tva_rate: float = 0.20
    description: str = ""
    status: str = "paid"     # 'paid', 'pending', 'disputed'
    payment_date: Optional[str] = None


@dataclass
class ReplyDraft:
    id: Optional[int]
    email_id: int
    version: int = 1
    tone: str = "factual"
    guidelines: str = ""
    memories_used: str = "[]"      # JSON array of memory slugs
    thread_depth: int = 5
    system_prompt: str = ""
    user_prompt: str = ""
    draft_text: str = ""
    edited_text: str = ""
    provider_name: str = ""
    model_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    status: str = "draft"          # 'draft', 'approved', 'sent', 'discarded'
    created_at: Optional[datetime] = None


@dataclass
class PendingAction:
    id: Optional[int]
    email_id: int
    action_type: str = "question"  # 'question', 'request', 'demand', 'deadline', 'proposal'
    text: str = ""
    resolved: bool = False
    resolved_by_draft_id: Optional[int] = None
    extracted_by: str = "manual"   # 'manual' or 'llm'
    created_at: Optional[datetime] = None


@dataclass
class ReplyMemory:
    id: Optional[int]
    slug: str
    display_name: str
    file_path: str
    topic_id: Optional[int] = None
    description: str = ""
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


@dataclass
class ExternalEvent:
    id: Optional[int]
    event_date: datetime
    category: str            # 'move', 'job', 'lawyer_change', 'other'
    description: str
    notes: str = ""
