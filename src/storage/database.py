"""SQLite database setup, migrations, and connection management."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, List, Optional

from src.config import db_path


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Context manager: yields a connection, commits on success, rolls back on error."""
    conn = _connect(db_path())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────── SCHEMA ──────────────────────────────────────

_SCHEMA = """
-- Tracked contacts
CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    aliases     TEXT NOT NULL DEFAULT '[]',   -- JSON list of alternate addresses
    role        TEXT NOT NULL DEFAULT 'other', -- 'me', 'ex-wife', 'lawyer', 'other'
    notes       TEXT NOT NULL DEFAULT ''
);

-- Email messages
CREATE TABLE IF NOT EXISTS emails (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id          TEXT NOT NULL UNIQUE,
    in_reply_to         TEXT NOT NULL DEFAULT '',
    references_header   TEXT NOT NULL DEFAULT '',
    thread_id           INTEGER REFERENCES threads(id),
    date                TIMESTAMP NOT NULL,
    from_address        TEXT NOT NULL,
    from_name           TEXT NOT NULL DEFAULT '',
    to_addresses        TEXT NOT NULL DEFAULT '[]',
    cc_addresses        TEXT NOT NULL DEFAULT '[]',
    subject             TEXT NOT NULL DEFAULT '',
    subject_normalized  TEXT NOT NULL DEFAULT '',
    body_text           TEXT NOT NULL DEFAULT '',
    body_html           TEXT NOT NULL DEFAULT '',
    delta_text          TEXT NOT NULL DEFAULT '',
    delta_hash          TEXT NOT NULL DEFAULT '',
    raw_size_bytes      INTEGER NOT NULL DEFAULT 0,
    folder              TEXT NOT NULL DEFAULT '',
    uid                 INTEGER NOT NULL DEFAULT 0,
    direction           TEXT NOT NULL DEFAULT 'received',
    language            TEXT NOT NULL DEFAULT 'unknown',
    has_attachments     INTEGER NOT NULL DEFAULT 0,
    contact_id          INTEGER REFERENCES contacts(id),
    fetched_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    corpus              TEXT NOT NULL DEFAULT 'personal'  -- 'personal' or 'legal'
);

-- Attachments (metadata always stored; content via BLOB or on-demand IMAP download)
CREATE TABLE IF NOT EXISTS attachments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id      INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL DEFAULT 0,
    content       BLOB,
    mime_section  TEXT,            -- IMAP BODY part ID for on-demand re-fetch
    imap_uid      INTEGER,        -- UID on server for re-fetch
    folder        TEXT,            -- IMAP folder for re-fetch
    downloaded    INTEGER NOT NULL DEFAULT 1,  -- 1 if content available (BLOB or file)
    download_path TEXT,            -- filesystem path (for on-demand downloads)
    category      TEXT             -- document classification (invoice, judgment, etc.)
);

-- Conversation threads
CREATE TABLE IF NOT EXISTS threads (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_normalized  TEXT NOT NULL,
    first_date          TIMESTAMP,
    last_date           TIMESTAMP,
    email_count         INTEGER NOT NULL DEFAULT 0,
    contact_id          INTEGER REFERENCES contacts(id)
);

-- Topics
CREATE TABLE IF NOT EXISTS topics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    color           TEXT NOT NULL DEFAULT '#6366f1',
    is_user_defined INTEGER NOT NULL DEFAULT 1
);

-- Email <-> Topic mapping
CREATE TABLE IF NOT EXISTS email_topics (
    email_id    INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    topic_id    INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    confidence  REAL NOT NULL DEFAULT 1.0,
    run_id      INTEGER NOT NULL REFERENCES analysis_runs(id),
    PRIMARY KEY (email_id, topic_id, run_id)
);

-- Analysis runs (one per provider+type execution)
CREATE TABLE IF NOT EXISTS analysis_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    analysis_type   TEXT NOT NULL,
    provider_name   TEXT NOT NULL,
    model_id        TEXT NOT NULL,
    prompt_hash     TEXT NOT NULL,
    prompt_version  TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'running',
    email_count     INTEGER NOT NULL DEFAULT 0,
    notes           TEXT NOT NULL DEFAULT ''
);

-- Per-email analysis results
CREATE TABLE IF NOT EXISTS analysis_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    email_id            INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    sender_contact_id   INTEGER REFERENCES contacts(id),
    result_json         TEXT NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, email_id)
);

-- Contradiction pairs
CREATE TABLE IF NOT EXISTS contradictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    email_id_a  INTEGER NOT NULL REFERENCES emails(id),
    email_id_b  INTEGER NOT NULL REFERENCES emails(id),
    scope       TEXT NOT NULL DEFAULT 'intra-sender',
    topic_id    INTEGER REFERENCES topics(id),
    explanation TEXT NOT NULL,
    severity    TEXT NOT NULL DEFAULT 'medium',
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Timeline events extracted from emails
CREATE TABLE IF NOT EXISTS timeline_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    email_id    INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    topic_id    INTEGER REFERENCES topics(id),
    event_date  TIMESTAMP NOT NULL,
    event_type  TEXT NOT NULL DEFAULT 'statement',
    description TEXT NOT NULL,
    significance TEXT NOT NULL DEFAULT 'medium',
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Legal procedures (replaces court_events)
CREATE TABLE IF NOT EXISTS procedures (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL DEFAULT '',
    procedure_type   TEXT NOT NULL DEFAULT 'divorce',  -- divorce, custody, finances, appeal, liquidation, refere, jaf_modification
    jurisdiction     TEXT NOT NULL DEFAULT '',          -- e.g. 'TGI Paris', 'Cour d''appel Versailles'
    case_number      TEXT NOT NULL DEFAULT '',
    filing_date      TEXT,
    initiated_by     TEXT NOT NULL DEFAULT '',          -- 'party_a' (Madame) or 'party_b' (Monsieur)
    party_a_lawyer_id INTEGER REFERENCES contacts(id),
    party_b_lawyer_id INTEGER REFERENCES contacts(id),
    status           TEXT NOT NULL DEFAULT 'active',    -- active, closed, appealed, settled
    date_start       TEXT,
    date_end         TEXT,
    description      TEXT NOT NULL DEFAULT '',
    outcome_summary  TEXT NOT NULL DEFAULT '',
    notes            TEXT NOT NULL DEFAULT '',
    created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Events within procedures (hearings, filings, judgments, etc.)
CREATE TABLE IF NOT EXISTS procedure_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure_id    INTEGER NOT NULL REFERENCES procedures(id) ON DELETE CASCADE,
    event_date      TEXT NOT NULL,
    event_type      TEXT NOT NULL DEFAULT 'hearing',  -- filing, hearing, judgment, ordonnance, signification, appeal, mediation, expertise, depot_conclusions
    date_precision  TEXT NOT NULL DEFAULT 'exact',    -- exact, month, approximate
    description     TEXT NOT NULL,
    outcome         TEXT NOT NULL DEFAULT '',
    source_email_id INTEGER REFERENCES emails(id),
    source_attachment_id INTEGER REFERENCES attachments(id),
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Lawyer invoice tracking
CREATE TABLE IF NOT EXISTS lawyer_invoices (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    procedure_id      INTEGER REFERENCES procedures(id),
    contact_id        INTEGER NOT NULL REFERENCES contacts(id),  -- which lawyer
    email_id          INTEGER REFERENCES emails(id),             -- source email mentioning the invoice
    attachment_id     INTEGER REFERENCES attachments(id),        -- the invoice document
    invoice_date      TEXT NOT NULL,
    invoice_number    TEXT NOT NULL DEFAULT '',
    amount_ht         REAL,               -- before tax
    amount_ttc        REAL,               -- total with tax
    tva_rate          REAL DEFAULT 0.20,
    description       TEXT NOT NULL DEFAULT '',
    status            TEXT NOT NULL DEFAULT 'paid',  -- paid, pending, disputed
    payment_date      TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Other external life events
CREATE TABLE IF NOT EXISTS external_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date  TIMESTAMP NOT NULL,
    category    TEXT NOT NULL DEFAULT 'other',
    description TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT ''
);

-- IMAP fetch state (track last synced UID per folder+contact)
CREATE TABLE IF NOT EXISTS fetch_state (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folder      TEXT NOT NULL,
    contact_email TEXT NOT NULL DEFAULT '',
    last_uid    INTEGER NOT NULL DEFAULT 0,
    last_sync   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (folder, contact_email)
);

-- Perspective-aware notes (legal or book) on any entity
CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,      -- 'email', 'contradiction', 'timeline_event',
                                    --  'procedure', 'procedure_event', 'analysis_result', 'chapter'
    entity_id   INTEGER NOT NULL,
    perspective TEXT NOT NULL DEFAULT 'legal',  -- 'legal' or 'book'
    category    TEXT NOT NULL DEFAULT 'general',
    text        TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Book chapters
CREATE TABLE IF NOT EXISTS chapters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    position    INTEGER NOT NULL DEFAULT 0,
    date_start  TEXT,
    date_end    TEXT,
    summary     TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Emails assigned to chapters
CREATE TABLE IF NOT EXISTS chapter_emails (
    chapter_id  INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    email_id    INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL DEFAULT 0,
    is_key_moment INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chapter_id, email_id)
);

-- Quote bank (text selections from email bodies)
CREATE TABLE IF NOT EXISTS quotes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id     INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    text         TEXT NOT NULL,
    context_note TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '[]',  -- JSON array
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Pivotal moments (auto-detected or user-curated)
CREATE TABLE IF NOT EXISTS pivotal_moments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id     INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    moment_type  TEXT NOT NULL DEFAULT 'manual',
    description  TEXT NOT NULL DEFAULT '',
    significance TEXT NOT NULL DEFAULT 'medium',
    auto_detected INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Bookmarks (shared across perspectives)
CREATE TABLE IF NOT EXISTS bookmarks (
    email_id    INTEGER PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Report generation history
CREATE TABLE IF NOT EXISTS generated_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type         TEXT NOT NULL,
    perspective         TEXT NOT NULL DEFAULT 'legal',
    format              TEXT NOT NULL DEFAULT 'docx',
    file_path           TEXT NOT NULL,
    include_legal_notes INTEGER NOT NULL DEFAULT 0,
    include_book_notes  INTEGER NOT NULL DEFAULT 0,
    parameters          TEXT NOT NULL DEFAULT '{}',
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Full-text search index on email content
CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(
    subject,
    body_text,
    delta_text,
    from_address,
    from_name,
    content='emails',
    content_rowid='id'
);

-- Keep FTS in sync
CREATE TRIGGER IF NOT EXISTS emails_fts_insert AFTER INSERT ON emails BEGIN
    INSERT INTO emails_fts(rowid, subject, body_text, delta_text, from_address, from_name)
    VALUES (new.id, new.subject, new.body_text, new.delta_text, new.from_address, new.from_name);
END;

CREATE TRIGGER IF NOT EXISTS emails_fts_update AFTER UPDATE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, body_text, delta_text, from_address, from_name)
    VALUES ('delete', old.id, old.subject, old.body_text, old.delta_text, old.from_address, old.from_name);
    INSERT INTO emails_fts(rowid, subject, body_text, delta_text, from_address, from_name)
    VALUES (new.id, new.subject, new.body_text, new.delta_text, new.from_address, new.from_name);
END;

CREATE TRIGGER IF NOT EXISTS emails_fts_delete AFTER DELETE ON emails BEGIN
    INSERT INTO emails_fts(emails_fts, rowid, subject, body_text, delta_text, from_address, from_name)
    VALUES ('delete', old.id, old.subject, old.body_text, old.delta_text, old.from_address, old.from_name);
END;
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_emails_date        ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_from        ON emails(from_address);
CREATE INDEX IF NOT EXISTS idx_emails_thread      ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_contact     ON emails(contact_id);
CREATE INDEX IF NOT EXISTS idx_emails_delta_hash  ON emails(delta_hash);
CREATE INDEX IF NOT EXISTS idx_emails_corpus      ON emails(corpus);
CREATE INDEX IF NOT EXISTS idx_analysis_results_run  ON analysis_results(run_id);
CREATE INDEX IF NOT EXISTS idx_analysis_results_email ON analysis_results(email_id);
CREATE INDEX IF NOT EXISTS idx_contradictions_run ON contradictions(run_id);
CREATE INDEX IF NOT EXISTS idx_timeline_events_date ON timeline_events(event_date);
CREATE INDEX IF NOT EXISTS idx_procedure_events_date ON procedure_events(event_date);
CREATE INDEX IF NOT EXISTS idx_procedure_events_proc ON procedure_events(procedure_id);
CREATE INDEX IF NOT EXISTS idx_lawyer_invoices_contact ON lawyer_invoices(contact_id);
CREATE INDEX IF NOT EXISTS idx_lawyer_invoices_proc ON lawyer_invoices(procedure_id);
CREATE INDEX IF NOT EXISTS idx_notes_entity      ON notes(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_notes_perspective ON notes(perspective);
CREATE INDEX IF NOT EXISTS idx_quotes_email      ON quotes(email_id);
CREATE INDEX IF NOT EXISTS idx_pivotal_email     ON pivotal_moments(email_id);
CREATE INDEX IF NOT EXISTS idx_chapter_emails    ON chapter_emails(chapter_id);
"""


# ─────────────────────────── MIGRATIONS ──────────────────────────────────────

# Each migration is (id, description, sql).  Applied once; tracked in schema_version.
_MIGRATIONS = [
    (1, "Add corpus column to emails", """
        ALTER TABLE emails ADD COLUMN corpus TEXT NOT NULL DEFAULT 'personal';
    """),
    (2, "Add mime_section to attachments", """
        ALTER TABLE attachments ADD COLUMN mime_section TEXT;
    """),
    (3, "Add imap_uid to attachments", """
        ALTER TABLE attachments ADD COLUMN imap_uid INTEGER;
    """),
    (4, "Add folder to attachments", """
        ALTER TABLE attachments ADD COLUMN folder TEXT;
    """),
    (5, "Add downloaded flag to attachments", """
        ALTER TABLE attachments ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 1;
    """),
    (6, "Add download_path to attachments", """
        ALTER TABLE attachments ADD COLUMN download_path TEXT;
    """),
    (7, "Add category to attachments", """
        ALTER TABLE attachments ADD COLUMN category TEXT;
    """),
    (8, "Add corpus index on emails", """
        CREATE INDEX IF NOT EXISTS idx_emails_corpus ON emails(corpus);
    """),
    (9, "Drop empty court_events table", """
        DROP TABLE IF EXISTS court_events;
    """),
    (10, "Reclassify lawyer emails to legal corpus", """
        UPDATE emails SET corpus = 'legal'
        WHERE from_address IN ('vclavocat@gmail.com', 'h.deblauwe@onyx-avocats.com', 'jtd@jtd-avocats.com')
           OR to_addresses LIKE '%vclavocat@gmail.com%'
           OR to_addresses LIKE '%h.deblauwe@onyx-avocats.com%'
           OR to_addresses LIKE '%jtd@jtd-avocats.com%';
    """),
    (11, "Add firm_name to contacts", """
        ALTER TABLE contacts ADD COLUMN firm_name TEXT NOT NULL DEFAULT '';
    """),
    (12, "Add bar_jurisdiction to contacts", """
        ALTER TABLE contacts ADD COLUMN bar_jurisdiction TEXT NOT NULL DEFAULT '';
    """),
    (13, "Add notes column to chapters", """
        ALTER TABLE chapters ADD COLUMN notes TEXT NOT NULL DEFAULT '';
    """),
    (14, "Make procedure_id nullable and add jurisdiction to procedure_events", """
        CREATE TABLE procedure_events_new (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            procedure_id         INTEGER REFERENCES procedures(id) ON DELETE CASCADE,
            event_date           TEXT NOT NULL,
            event_type           TEXT NOT NULL DEFAULT 'hearing',
            date_precision       TEXT NOT NULL DEFAULT 'exact',
            description          TEXT NOT NULL DEFAULT '',
            outcome              TEXT NOT NULL DEFAULT '',
            jurisdiction         TEXT NOT NULL DEFAULT '',
            source_email_id      INTEGER REFERENCES emails(id),
            source_attachment_id INTEGER REFERENCES attachments(id),
            notes                TEXT NOT NULL DEFAULT '',
            created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO procedure_events_new
            SELECT id, procedure_id, event_date, event_type, date_precision,
                   description, outcome, '', source_email_id, source_attachment_id,
                   notes, created_at
            FROM procedure_events;
        DROP TABLE procedure_events;
        ALTER TABLE procedure_events_new RENAME TO procedure_events;
    """),
    (15, "Add payment_confirmations table for invoice scan workflow", """
        CREATE TABLE IF NOT EXISTS payment_confirmations (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id      INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
            amount        REAL,
            payment_type  TEXT NOT NULL DEFAULT 'autre',
            invoice_id    INTEGER REFERENCES lawyer_invoices(id) ON DELETE SET NULL,
            notes         TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_payment_confirmations_email
            ON payment_confirmations(email_id);
    """),
    (16, "Add invoice_scan_dismissed table for assessed emails", """
        CREATE TABLE IF NOT EXISTS invoice_scan_dismissed (
            email_id     INTEGER PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
            reason       TEXT NOT NULL DEFAULT '',
            dismissed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    """),
    (18, "Add procedure_id FK to emails for legal corpus procedure linkage", """
        ALTER TABLE emails ADD COLUMN procedure_id INTEGER REFERENCES procedures(id);
        CREATE INDEX IF NOT EXISTS idx_emails_procedure ON emails(procedure_id);
    """),
    (19, "Add structured ruling fields to procedure_events (judge, ruling_for, pension, custody, obligations)", """
        ALTER TABLE procedure_events ADD COLUMN judge_name           TEXT NOT NULL DEFAULT '';
        ALTER TABLE procedure_events ADD COLUMN ruling_for           TEXT NOT NULL DEFAULT '';
        ALTER TABLE procedure_events ADD COLUMN pension_amount       REAL;
        ALTER TABLE procedure_events ADD COLUMN custody_arrangement  TEXT NOT NULL DEFAULT '';
        ALTER TABLE procedure_events ADD COLUMN obligations          TEXT NOT NULL DEFAULT '';
    """),
    (17, "Add procedure_documents table for per-procedure file uploads", """
        CREATE TABLE IF NOT EXISTS procedure_documents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            procedure_id  INTEGER NOT NULL REFERENCES procedures(id) ON DELETE CASCADE,
            doc_type      TEXT NOT NULL DEFAULT 'other',
            filename      TEXT NOT NULL,
            original_name TEXT NOT NULL DEFAULT '',
            file_path     TEXT NOT NULL,
            content_type  TEXT NOT NULL DEFAULT 'application/octet-stream',
            size_bytes    INTEGER NOT NULL DEFAULT 0,
            doc_date      TEXT,
            notes         TEXT NOT NULL DEFAULT '',
            uploaded_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_proc_docs_procedure
            ON procedure_documents(procedure_id);
    """),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending migrations. Safe to call repeatedly."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            migration_id  INTEGER PRIMARY KEY,
            description   TEXT NOT NULL,
            applied_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    applied = {r[0] for r in conn.execute("SELECT migration_id FROM schema_version").fetchall()}
    for mid, desc, sql in _MIGRATIONS:
        if mid in applied:
            continue
        try:
            conn.executescript(sql)
        except sqlite3.OperationalError as e:
            # Skip "duplicate column" errors for idempotency
            if "duplicate column" in str(e).lower():
                pass
            else:
                raise
        conn.execute(
            "INSERT INTO schema_version (migration_id, description) VALUES (?, ?)",
            (mid, desc),
        )
    conn.commit()


def init_db() -> None:
    """Create all tables and indexes if they don't exist, then run pending migrations."""
    with get_db() as conn:
        conn.executescript(_SCHEMA)
        _run_migrations(conn)
        conn.executescript(_INDEXES)


def seed_topics(topics_config: List[dict]) -> None:
    """Insert topics from config if they don't already exist."""
    with get_db() as conn:
        for t in topics_config:
            conn.execute(
                "INSERT OR IGNORE INTO topics (name, description) VALUES (?, ?)",
                (t["name"], t.get("description", "")),
            )


def seed_contacts(contacts_config: List[dict]) -> None:
    """Insert contacts from config. Updates aliases if the contact already exists."""
    with get_db() as conn:
        for c in contacts_config:
            aliases = json.dumps(c.get("aliases", []))
            existing = conn.execute(
                "SELECT id FROM contacts WHERE email=?", (c["email"],)
            ).fetchone()
            if existing:
                # Update aliases and role in case config was enriched
                conn.execute(
                    "UPDATE contacts SET aliases=?, role=? WHERE email=?",
                    (aliases, c.get("role", "other"), c["email"]),
                )
            else:
                conn.execute(
                    """INSERT INTO contacts (name, email, role, aliases)
                       VALUES (?, ?, ?, ?)""",
                    (c["name"], c["email"], c.get("role", "other"), aliases),
                )


def get_last_uid(folder: str, contact_email: str = "") -> int:
    """Return the last synced IMAP UID for a folder/contact combo."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT last_uid FROM fetch_state WHERE folder=? AND contact_email=?",
            (folder, contact_email),
        ).fetchone()
        return row["last_uid"] if row else 0


def set_last_uid(folder: str, uid: int, contact_email: str = "") -> None:
    """Update the last synced UID for resumable fetching."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO fetch_state (folder, contact_email, last_uid, last_sync)
               VALUES (?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(folder, contact_email) DO UPDATE SET
                 last_uid=excluded.last_uid, last_sync=excluded.last_sync""",
            (folder, contact_email, uid),
        )


def email_exists(message_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM emails WHERE message_id=?", (message_id,)
        ).fetchone()
        return row is not None


def delta_hash_exists(delta_hash: str) -> bool:
    """True if an email with this content hash already exists (duplicate detection)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM emails WHERE delta_hash=?", (delta_hash,)
        ).fetchone()
        return row is not None


def delete_email(email_id: int) -> bool:
    """Delete an email and all cascaded data. Returns True if found."""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM emails WHERE id=?", (email_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM emails WHERE id=?", (email_id,))
        return True


def update_email_corpus(email_id: int, corpus: str) -> bool:
    """Change the corpus of an email ('personal' or 'legal'). Returns True if found."""
    if corpus not in ("personal", "legal"):
        raise ValueError(f"Invalid corpus: {corpus!r}")
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE emails SET corpus=? WHERE id=?", (corpus, email_id)
        )
        return cur.rowcount > 0


def update_attachment_downloaded(attachment_id: int, download_path: str) -> None:
    """Mark an attachment as downloaded and record its filesystem path."""
    with get_db() as conn:
        conn.execute(
            "UPDATE attachments SET downloaded=1, download_path=? WHERE id=?",
            (download_path, attachment_id),
        )
