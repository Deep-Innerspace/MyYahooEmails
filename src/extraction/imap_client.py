"""
Yahoo IMAP client — strictly READ-ONLY.

Only uses FETCH, SEARCH, SELECT, and LIST commands.
Never calls STORE, EXPUNGE, DELETE, MOVE, or COPY.
"""
import ssl
from contextlib import contextmanager
from datetime import date, datetime
from typing import Dict, Generator, List, Optional, Tuple

import imapclient

from src.config import imap_port, imap_server, imap_ssl, yahoo_email, yahoo_password


@contextmanager
def imap_connection() -> Generator[imapclient.IMAPClient, None, None]:
    """Open an authenticated Yahoo IMAP connection and close it cleanly."""
    ssl_context = ssl.create_default_context()
    client = imapclient.IMAPClient(
        host=imap_server(),
        port=imap_port(),
        ssl=imap_ssl(),
        ssl_context=ssl_context,
    )
    try:
        client.login(yahoo_email(), yahoo_password())
        yield client
    finally:
        try:
            client.logout()
        except Exception:
            pass


def list_folders() -> List[Tuple[bytes, bytes, str]]:
    """Return all folders available in the mailbox."""
    with imap_connection() as client:
        return client.list_folders()


def get_folder_names() -> List[str]:
    """Return just the folder name strings."""
    folders = list_folders()
    return [f[2] for f in folders]


def search_uids_by_contact(
    client: imapclient.IMAPClient,
    folder: str,
    contact_email: str,
    since: Optional[date] = None,
    before: Optional[date] = None,
    min_uid: int = 0,
) -> List[int]:
    """
    Search for UIDs in a folder where the contact appears in FROM, TO, or CC.
    Optionally filtered by date range and resuming from min_uid.
    """
    client.select_folder(folder, readonly=True)  # readonly=True: never modifies mailbox

    # Build IMAP SEARCH criteria
    # We search for emails FROM or TO the contact address
    criteria: List = [
        b"OR",
        [b"FROM", contact_email],
        [b"OR",
         [b"TO", contact_email],
         [b"CC", contact_email]],
    ]

    if since:
        # imapclient expects date as 'DD-Mon-YYYY'
        criteria = [b"SINCE", since] + criteria
    if before:
        criteria = [b"BEFORE", before] + criteria

    uids = client.search(criteria)

    if min_uid > 0:
        uids = [uid for uid in uids if uid > min_uid]

    return sorted(uids)


def search_all_uids(
    client: imapclient.IMAPClient,
    folder: str,
    since: Optional[date] = None,
    before: Optional[date] = None,
    min_uid: int = 0,
) -> List[int]:
    """Search all UIDs in a folder (no contact filter)."""
    client.select_folder(folder, readonly=True)

    criteria: List = [b"ALL"]
    if since:
        criteria = [b"SINCE", since] + criteria[1:]  # replace ALL
        criteria = [b"SINCE", since]
    if before:
        criteria = criteria + [b"BEFORE", before]

    uids = client.search(criteria if criteria != [b"ALL"] else b"ALL")

    if min_uid > 0:
        uids = [uid for uid in uids if uid > min_uid]

    return sorted(uids)


def fetch_raw_emails(
    client: imapclient.IMAPClient,
    uids: List[int],
    batch_size: int = 50,
) -> Generator[Tuple[int, bytes, Dict], None, None]:
    """
    Fetch raw RFC 2822 message bytes for the given UIDs, in batches.

    Yields (uid, raw_bytes, envelope_dict) for each message.
    envelope_dict contains basic metadata from the IMAP ENVELOPE response.
    """
    for i in range(0, len(uids), batch_size):
        batch = uids[i : i + batch_size]
        # Fetch raw message bytes + envelope (metadata without downloading full body)
        response = client.fetch(batch, [b"RFC822", b"ENVELOPE", b"RFC822.SIZE"])
        for uid, data in response.items():
            raw = data.get(b"RFC822", b"")
            envelope = data.get(b"ENVELOPE")
            size = data.get(b"RFC822.SIZE", 0)
            yield uid, raw, {"envelope": envelope, "size": size}


def fetch_envelope_only(
    client: imapclient.IMAPClient,
    uids: List[int],
    batch_size: int = 200,
) -> Generator[Tuple[int, Dict], None, None]:
    """
    Fetch only envelope metadata (no body download) for counting/filtering.
    Much faster than fetching full messages.
    """
    for i in range(0, len(uids), batch_size):
        batch = uids[i : i + batch_size]
        response = client.fetch(batch, [b"ENVELOPE", b"RFC822.SIZE"])
        for uid, data in response.items():
            envelope = data.get(b"ENVELOPE")
            size = data.get(b"RFC822.SIZE", 0)
            yield uid, {"envelope": envelope, "size": size}


def count_messages_in_folder(folder: str) -> int:
    """Return total message count for a folder (fast, no download)."""
    with imap_connection() as client:
        status = client.folder_status(folder, ["MESSAGES"])
        return status.get(b"MESSAGES", 0)


def _is_transient_imap_error(exc: Exception) -> bool:
    """Return True for Yahoo transient server errors that are safe to retry."""
    msg = str(exc).upper()
    return any(token in msg for token in (
        "UNAVAILABLE",
        "SERVER ERROR",
        "TRY AGAIN",
        "INUSE",
        "OVERQUOTA",    # Yahoo occasionally returns this transiently
    ))


def fetch_mime_part(folder: str, uid: int, section: str) -> Optional[bytes]:
    """Fetch a single MIME part from an IMAP message (read-only).

    *section* is the IMAP BODY[] section string, e.g. '2' or '2.1', as stored
    in attachments.mime_section during a metadata-only legal-corpus import.

    Also fetches the part's MIME headers to detect Content-Transfer-Encoding
    and decodes base64 / quoted-printable content automatically so the returned
    bytes are always the raw binary (e.g. a valid PDF, not base64 text).

    Returns the decoded part bytes, or None if the UID was not found in the
    folder (including [UNAVAILABLE] responses, which Yahoo returns when a UID
    no longer exists in a folder after the email was moved elsewhere).

    Non-transient IMAP errors are re-raised immediately.
    """
    import base64
    import quopri
    import email as _email_lib

    with imap_connection() as client:
        client.select_folder(folder, readonly=True)

        body_key = f"BODY.PEEK[{section}]".encode()
        mime_key = f"BODY.PEEK[{section}.MIME]".encode()

        try:
            response = client.fetch([uid], [body_key, mime_key])
        except Exception as exc:
            if _is_transient_imap_error(exc):
                # [UNAVAILABLE] is Yahoo's response for both "server busy" and
                # "UID no longer exists here (email was moved)".  Return None so
                # the caller can trigger stale-UID recovery instead of retrying
                # the wrong folder indefinitely.
                return None
            raise

        if uid not in response:
            return None

        data = response[uid]
        raw  = data.get(f"BODY[{section}]".encode())
        if raw is None:
            return None

        # Detect transfer encoding from the part's MIME headers
        mime_raw = data.get(f"BODY[{section}.MIME]".encode(), b"")
        cte = ""
        if mime_raw:
            part_msg = _email_lib.message_from_bytes(mime_raw)
            cte = part_msg.get("Content-Transfer-Encoding", "").lower().strip()

        if cte == "base64":
            raw = base64.b64decode(raw.replace(b"\r", b"").replace(b"\n", b""))
        elif cte in ("quoted-printable", "qp"):
            raw = quopri.decodestring(raw)
        # '7bit', '8bit', 'binary' — already raw, no decoding needed

        return raw
