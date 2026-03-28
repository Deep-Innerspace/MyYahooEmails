#!/usr/bin/env python3
"""
MyYahooEmails — Main CLI entry point.

Usage: python cli.py <command> [options]
       mye <command> [options]        (after pip install -e .)
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


@click.group()
def cli():
    """Email analysis platform for Yahoo Mail."""
    pass


# ═══════════════════════════════════════════════════════════════════════════
#  FETCH — Download emails from Yahoo via IMAP
# ═══════════════════════════════════════════════════════════════════════════

@cli.group()
def fetch():
    """Download emails from Yahoo via IMAP."""
    pass


@fetch.command("folders")
def fetch_folders():
    """List all IMAP folders in the mailbox."""
    from src.extraction.imap_client import get_folder_names, count_messages_in_folder
    with console.status("Connecting to Yahoo Mail..."):
        folders = get_folder_names()
    table = Table(title="Yahoo Mail Folders", show_lines=True)
    table.add_column("Folder", style="cyan")
    table.add_column("Messages", justify="right")
    for f in folders:
        try:
            count = count_messages_in_folder(f)
            table.add_row(f, str(count))
        except Exception:
            table.add_row(f, "?")
    console.print(table)


# Folders that are never useful to fetch (system/transient folders)
_SKIP_FOLDERS = {"Trash", "Draft", "Bulk", "Spam", "Deleted Messages"}

@fetch.command("emails")
@click.option("--contact", "-c", multiple=True, help="Fetch emails from/to this address (repeatable).")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None, help="Start date (YYYY-MM-DD).")
@click.option("--until", type=click.DateTime(formats=["%Y-%m-%d"]), default=None, help="End date (YYYY-MM-DD).")
@click.option("--folder", "-f", multiple=True, help="IMAP folder(s) to search. Repeatable.")
@click.option("--all-folders", is_flag=True, help="Search ALL folders (except Trash/Draft/Bulk). Recommended for first full import.")
@click.option("--skip-folder", multiple=True, help="Folder to skip when using --all-folders (repeatable).")
@click.option("--resume/--no-resume", default=True, show_default=True, help="Resume from last fetched UID.")
@click.option("--dry-run", is_flag=True, help="Count matching emails without downloading.")
@click.option("--corpus", default="personal", type=click.Choice(["personal", "legal"]),
              show_default=True, help="Corpus tag for stored emails. Use 'legal' for lawyer emails.")
def fetch_emails(contact, since, until, folder, all_folders, skip_folder, resume, dry_run, corpus):
    """Download emails filtered by contact address and/or date range.

    For a complete first import use --all-folders so nothing is missed.
    The contact filter (From/To/CC) is applied server-side on every folder,
    so only relevant emails are downloaded regardless of folder size.

    Use --corpus legal when fetching lawyer emails; attachments will be stored
    as metadata-only (no BLOB download) and can be fetched on demand later.

    Examples:
      python cli.py fetch emails --all-folders --dry-run
      python cli.py fetch emails --all-folders --since 2014-01-01
      python cli.py fetch emails --folder Divorce --folder Avocat
      python cli.py fetch emails --corpus legal --contact avocat@cabinet.fr
    """
    from src.config import yahoo_email, contacts as cfg_contacts
    from src.extraction.imap_client import (
        imap_connection, search_uids_by_contact, fetch_raw_emails,
        fetch_envelope_only, get_folder_names,
    )
    from src.extraction.parser import parse_raw_email
    from src.extraction.threader import batch_store_emails
    from src.storage.database import init_db, seed_contacts, seed_topics, get_last_uid, set_last_uid
    from src.config import contacts as cfg_contacts_fn, topics as cfg_topics_fn
    from tqdm import tqdm

    # Ensure DB is initialized
    init_db()
    seed_contacts(cfg_contacts_fn())
    seed_topics(cfg_topics_fn())

    my_email = yahoo_email()

    # Determine which folders to search
    skip_set = _SKIP_FOLDERS | set(skip_folder)
    if all_folders:
        all_available = get_folder_names()
        folders_to_search = [f for f in all_available if f not in skip_set]
        console.print(f"[bold]Mode:[/bold] ALL folders ({len(folders_to_search)} folders, skipping: {', '.join(skip_set)})")
    elif folder:
        folders_to_search = list(folder)
    else:
        folders_to_search = ["INBOX", "Sent"]
        console.print(f"[dim]Tip: use --all-folders to search every folder and miss nothing.[/dim]")

    since_date = since.date() if since else None
    until_date = until.date() if until else None

    # Build the full list of addresses to search for (primary + all aliases),
    # grouped by contact so we can display meaningful names.
    # Structure: list of (display_name, [addr1, addr2, ...])
    contact_groups = []

    if contact:
        # Addresses passed explicitly on the CLI: check DB for each one
        from src.storage.database import get_db as _get_db
        with _get_db() as _conn:
            for addr in contact:
                addr_lower = addr.strip().lower()
                row = _conn.execute(
                    "SELECT name, email, aliases FROM contacts WHERE email=?", (addr_lower,)
                ).fetchone()
                if row:
                    aliases = json.loads(row["aliases"] or "[]")
                    contact_groups.append((row["name"], [row["email"]] + aliases))
                else:
                    # Unknown address — search for it as-is, no aliases
                    contact_groups.append((addr_lower, [addr_lower]))
    else:
        # Use all non-me contacts from DB (includes any added via CLI/config)
        from src.storage.database import get_db as _get_db
        with _get_db() as _conn:
            rows = _conn.execute(
                "SELECT name, email, aliases FROM contacts WHERE role != 'me'"
            ).fetchall()
            for row in rows:
                aliases = json.loads(row["aliases"] or "[]")
                contact_groups.append((row["name"], [row["email"]] + aliases))

    if not contact_groups:
        console.print("[yellow]No contacts to fetch. Use --contact or run: python cli.py contacts add[/yellow]")
        return

    # Print summary of who we'll fetch for
    for name, addrs in contact_groups:
        console.print(f"[bold]Contact:[/bold] {name} — {len(addrs)} address(es): {', '.join(addrs)}")
    console.print(f"[bold]Folders:[/bold] {len(folders_to_search)} folder(s) to search")
    if since_date:
        console.print(f"[bold]Since:[/bold] {since_date}")
    if until_date:
        console.print(f"[bold]Until:[/bold] {until_date}")
    console.print(f"[bold]Corpus:[/bold] {corpus}")

    total_stored = total_skipped = total_error = 0

    with imap_connection() as client:
        for folder_name in folders_to_search:
            for contact_name, addr_list in contact_groups:
                # Collect UIDs from ALL addresses of this contact, deduplicated
                all_uids: set = set()
                for contact_addr in addr_list:
                    min_uid = 0
                    if resume:
                        min_uid = get_last_uid(folder_name, contact_addr)
                        if min_uid > 0:
                            console.print(f"  [dim]Resuming {contact_addr} from UID {min_uid}[/dim]")
                    try:
                        uids = search_uids_by_contact(
                            client, folder_name, contact_addr,
                            since=since_date, before=until_date,
                            min_uid=min_uid,
                        )
                        all_uids.update(uids)
                    except Exception as e:
                        console.print(f"[red]Error searching {folder_name} for {contact_addr}: {e}[/red]")

                if not all_uids:
                    console.print(f"  [dim]{folder_name} / {contact_name}: 0 new messages[/dim]")
                    continue

                uid_list = sorted(all_uids)
                console.print(
                    f"\n[cyan]{folder_name}[/cyan] / [bold]{contact_name}[/bold]"
                    f" ({len(addr_list)} addresses): [bold]{len(uid_list)}[/bold] messages to fetch"
                )

                if dry_run:
                    continue

                parsed_batch = []
                with tqdm(total=len(uid_list), desc=f"  Downloading", unit="msg") as pbar:
                    for uid, raw, meta in fetch_raw_emails(client, uid_list):
                        parsed = parse_raw_email(
                            uid, raw, folder_name, my_email,
                            download_content=(corpus != "legal"),
                        )
                        if parsed:
                            parsed_batch.append(parsed)
                        pbar.update(1)

                if parsed_batch:
                    stats = batch_store_emails(parsed_batch, folder_name, corpus=corpus)
                    total_stored += stats["stored"]
                    total_skipped += stats["skipped_duplicate"]
                    total_error += stats["skipped_error"]
                    # Update resume state for each address with the max UID seen
                    max_uid = max(uid_list)
                    for contact_addr in addr_list:
                        set_last_uid(folder_name, max_uid, contact_addr)
                    console.print(
                        f"  [green]✓ {stats['stored']} stored[/green]"
                        f" [dim]{stats['skipped_duplicate']} duplicates skipped"
                        f" {stats['skipped_error']} errors[/dim]"
                    )

    if not dry_run:
        console.print(f"\n[bold green]Done! {total_stored} new emails stored.[/bold green]"
                      f" ({total_skipped} duplicates, {total_error} errors)")


@fetch.command("status")
def fetch_status():
    """Show how many emails are stored and fetch state."""
    from src.storage.database import init_db, get_db
    init_db()
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        sent = conn.execute("SELECT COUNT(*) FROM emails WHERE direction='sent'").fetchone()[0]
        received = conn.execute("SELECT COUNT(*) FROM emails WHERE direction='received'").fetchone()[0]
        threads = conn.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
        contacts_n = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        fetch_states = conn.execute("SELECT * FROM fetch_state ORDER BY last_sync DESC").fetchall()

    table = Table(title="Database Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Total emails", str(total))
    table.add_row("  Sent", str(sent))
    table.add_row("  Received", str(received))
    table.add_row("Threads", str(threads))
    table.add_row("Contacts", str(contacts_n))
    console.print(table)

    if fetch_states:
        table2 = Table(title="Last Fetch State (for resumable fetch)")
        table2.add_column("Folder")
        table2.add_column("Contact")
        table2.add_column("Last UID", justify="right")
        table2.add_column("Last Sync")
        for row in fetch_states:
            table2.add_row(row["folder"], row["contact_email"], str(row["last_uid"]), str(row["last_sync"]))
        console.print(table2)


@fetch.command("lawyers")
@click.option("--folder", "-f", multiple=True, help="Specific IMAP folder(s) to search (default: all non-system).")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None, help="Start date (YYYY-MM-DD).")
@click.option("--resume/--no-resume", default=True, show_default=True, help="Resume from last fetched UID.")
@click.option("--dry-run", is_flag=True, help="Count matching emails without downloading.")
def fetch_lawyers(folder, since, resume, dry_run):
    """Fetch all lawyer emails and store them with corpus='legal'.

    Reads contacts with role my_lawyer or her_lawyer from config.yaml.
    Attachments are stored as metadata-only (no BLOB) and can be downloaded
    on demand from the web UI later.

    Examples:
      python cli.py fetch lawyers --dry-run
      python cli.py fetch lawyers --since 2014-01-01
      python cli.py fetch lawyers --folder Avocat --folder INBOX
    """
    from src.config import lawyer_contacts, yahoo_email
    from src.config import contacts as cfg_contacts_fn, topics as cfg_topics_fn
    from src.extraction.imap_client import (
        imap_connection, search_uids_by_contact, fetch_raw_emails, get_folder_names,
    )
    from src.extraction.parser import parse_raw_email
    from src.extraction.threader import batch_store_emails
    from src.storage.database import init_db, seed_contacts, seed_topics, get_last_uid, set_last_uid
    from tqdm import tqdm

    init_db()
    seed_contacts(cfg_contacts_fn())
    seed_topics(cfg_topics_fn())

    lawyers = lawyer_contacts()
    if not lawyers:
        console.print("[yellow]No lawyer contacts found in config.yaml.[/yellow]")
        console.print("[dim]Add contacts with role: my_lawyer or her_lawyer and re-run.[/dim]")
        return

    my_email = yahoo_email()
    since_date = since.date() if since else None

    console.print(
        f"[bold]Fetching emails for {len(lawyers)} lawyer contact(s)"
        f" — corpus: [green]legal[/green][/bold]"
        f" [dim](attachments: metadata-only)[/dim]"
    )

    total_stored = total_skipped = total_error = 0

    with imap_connection() as client:
        folders_to_search = (
            list(folder) if folder
            else [f for f in get_folder_names() if f not in _SKIP_FOLDERS]
        )

        for lawyer in lawyers:
            name = lawyer.get("name", "Unknown")
            primary = lawyer.get("email", "")
            aliases = lawyer.get("aliases", [])
            all_addrs = [primary] + aliases
            role = lawyer.get("role", "lawyer")

            console.print(f"\n[bold cyan]{name}[/bold cyan] ({role}) — {', '.join(all_addrs)}")

            for folder_name in folders_to_search:
                all_uids: set = set()
                for addr in all_addrs:
                    min_uid = get_last_uid(folder_name, addr) if resume else 0
                    try:
                        uids = search_uids_by_contact(
                            client, folder_name, addr,
                            since=since_date, min_uid=min_uid,
                        )
                        all_uids.update(uids)
                    except Exception as e:
                        err = str(e).lower()
                        # Silently skip folders that don't exist on this mailbox
                        if "doesn't exist" not in err and "no such mailbox" not in err:
                            console.print(f"  [red]Error searching {folder_name}: {e}[/red]")

                if not all_uids:
                    continue

                uid_list = sorted(all_uids)
                console.print(
                    f"  [cyan]{folder_name}[/cyan]: [bold]{len(uid_list)}[/bold] message(s)"
                )

                if dry_run:
                    continue

                parsed_batch = []
                with tqdm(total=len(uid_list), desc="  Downloading", unit="msg") as pbar:
                    for uid, raw, meta in fetch_raw_emails(client, uid_list):
                        parsed = parse_raw_email(
                            uid, raw, folder_name, my_email,
                            download_content=False,  # metadata-only for legal corpus
                        )
                        if parsed:
                            parsed_batch.append(parsed)
                        pbar.update(1)

                if parsed_batch:
                    stats = batch_store_emails(parsed_batch, folder_name, corpus="legal")
                    total_stored += stats["stored"]
                    total_skipped += stats["skipped_duplicate"]
                    total_error += stats["skipped_error"]
                    max_uid = max(uid_list)
                    for addr in all_addrs:
                        set_last_uid(folder_name, max_uid, addr)
                    console.print(
                        f"  [green]✓ {stats['stored']} stored[/green]"
                        f" [dim]{stats['skipped_duplicate']} duplicates"
                        f" {stats['skipped_error']} errors[/dim]"
                    )

    if not dry_run:
        console.print(
            f"\n[bold green]Done! {total_stored} new lawyer emails stored"
            f" (corpus=legal).[/bold green]"
            f" ({total_skipped} duplicates, {total_error} errors)"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  CONTACTS — Manage tracked contacts
# ═══════════════════════════════════════════════════════════════════════════

@cli.group()
def contacts():
    """Manage tracked email contacts."""
    pass


@contacts.command("list")
def contacts_list():
    """List all tracked contacts (including aliases)."""
    from src.storage.database import init_db, get_db
    init_db()
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM contacts ORDER BY role, name").fetchall()

    table = Table(title="Contacts", show_lines=True)
    table.add_column("ID", justify="right")
    table.add_column("Name")
    table.add_column("Primary Email")
    table.add_column("Aliases", style="dim")
    table.add_column("Role")
    table.add_column("Notes")
    for row in rows:
        aliases = json.loads(row["aliases"] or "[]")
        alias_str = "\n".join(aliases) if aliases else ""
        table.add_row(str(row["id"]), row["name"], row["email"], alias_str, row["role"], row["notes"])
    console.print(table)


@contacts.command("add")
@click.option("--name", required=True, help="Contact display name.")
@click.option("--email", required=True, help="Primary email address.")
@click.option("--role", default="other", type=click.Choice(["me", "ex-wife", "lawyer", "other"]))
@click.option("--notes", default="")
def contacts_add(name, email, role, notes):
    """Add a new contact."""
    from src.storage.database import init_db, get_db
    init_db()
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO contacts (name, email, role, notes) VALUES (?,?,?,?)",
            (name, email.lower(), role, notes),
        )
    console.print(f"[green]Contact added: {name} <{email}> ({role})[/green]")


@contacts.command("alias")
@click.option("--contact-id", "-i", type=int, required=True, help="ID of the contact (from contacts list).")
@click.option("--add", "add_addr", default=None, help="Alias email address to add.")
@click.option("--remove", "remove_addr", default=None, help="Alias email address to remove.")
def contacts_alias(contact_id, add_addr, remove_addr):
    """Add or remove an alias email address for a contact.

    Example — add two addresses she used:
      python cli.py contacts alias -i 2 --add ancienne@hotmail.com
      python cli.py contacts alias -i 2 --add pro@entreprise.fr

    Aliases are used automatically during fetch AND when resolving contact
    ownership of stored emails.
    """
    from src.storage.database import init_db, get_db
    init_db()

    if not add_addr and not remove_addr:
        console.print("[yellow]Provide --add <email> or --remove <email>[/yellow]")
        return

    with get_db() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
        if not row:
            console.print(f"[red]Contact #{contact_id} not found.[/red]")
            return

        aliases = json.loads(row["aliases"] or "[]")

        if add_addr:
            addr = add_addr.strip().lower()
            # Prevent adding an address that is already a primary email of another contact
            conflict = conn.execute(
                "SELECT name FROM contacts WHERE email=? AND id!=?", (addr, contact_id)
            ).fetchone()
            if conflict:
                console.print(f"[red]'{addr}' is already the primary address of '{conflict['name']}'.[/red]")
                return
            if addr not in aliases:
                aliases.append(addr)
                conn.execute(
                    "UPDATE contacts SET aliases=? WHERE id=?",
                    (json.dumps(aliases), contact_id),
                )
                console.print(f"[green]Alias added:[/green] {addr} → {row['name']}")
                console.print(f"  {row['name']} now has [bold]{len(aliases)}[/bold] alias(es): {', '.join(aliases)}")
            else:
                console.print(f"[yellow]'{addr}' is already an alias for {row['name']}.[/yellow]")

        if remove_addr:
            addr = remove_addr.strip().lower()
            if addr in aliases:
                aliases.remove(addr)
                conn.execute(
                    "UPDATE contacts SET aliases=? WHERE id=?",
                    (json.dumps(aliases), contact_id),
                )
                console.print(f"[green]Alias removed:[/green] {addr} from {row['name']}")
            else:
                console.print(f"[yellow]'{addr}' is not an alias of {row['name']}.[/yellow]")


@contacts.command("delete")
@click.argument("contact_id", type=int)
@click.confirmation_option(prompt="Delete this contact and unlink all their emails?")
def contacts_delete(contact_id):
    """Delete a contact by ID. Their emails are kept but unlinked (contact_id set to NULL)."""
    from src.storage.database import init_db, get_db
    init_db()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
        if not row:
            console.print(f"[red]Contact #{contact_id} not found.[/red]")
            return
        # Unlink emails rather than delete them
        conn.execute("UPDATE emails SET contact_id=NULL WHERE contact_id=?", (contact_id,))
        conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
        console.print(f"[green]Contact #{contact_id} ({row['name']} <{row['email']}>) deleted.[/green]")
        console.print("  [dim]Their emails are still in the database, just unlinked.[/dim]")


# ═══════════════════════════════════════════════════════════════════════════
#  TOPICS — Manage email topics
# ═══════════════════════════════════════════════════════════════════════════

@cli.group()
def topics():
    """Manage email topic categories."""
    pass


@topics.command("list")
def topics_list():
    """List all topics."""
    from src.storage.database import init_db, get_db
    init_db()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT t.*, COUNT(DISTINCT et.email_id) as email_count
               FROM topics t LEFT JOIN email_topics et ON et.topic_id = t.id
               GROUP BY t.id ORDER BY t.name"""
        ).fetchall()

    table = Table(title="Topics")
    table.add_column("ID", justify="right")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Emails", justify="right")
    table.add_column("User-defined")
    for row in rows:
        table.add_row(
            str(row["id"]), row["name"], row["description"],
            str(row["email_count"]), "✓" if row["is_user_defined"] else "AI"
        )
    console.print(table)


@topics.command("add")
@click.option("--name", required=True)
@click.option("--description", default="")
@click.option("--color", default="#6366f1")
def topics_add(name, description, color):
    """Add a custom topic."""
    from src.storage.database import init_db, get_db
    init_db()
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO topics (name, description, color, is_user_defined) VALUES (?,?,?,1)",
            (name, description, color),
        )
    console.print(f"[green]Topic '{name}' added.[/green]")


# ═══════════════════════════════════════════════════════════════════════════
#  SEARCH — Full-text and filtered search
# ═══════════════════════════════════════════════════════════════════════════

@cli.command("search")
@click.argument("query", required=False)
@click.option("--topic", "-t", default=None)
@click.option("--contact", "-c", default=None)
@click.option("--direction", "-d", type=click.Choice(["sent", "received"]), default=None)
@click.option("--from", "date_from", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--to", "date_to", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--limit", default=20, show_default=True)
def search(query, topic, contact, direction, date_from, date_to, limit):
    """Search emails by content and/or metadata filters."""
    from src.storage.search import search_emails
    results = search_emails(
        query=query,
        topic=topic,
        contact_email=contact,
        direction=direction,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"{len(results)} result(s)", show_lines=True)
    table.add_column("ID", justify="right", style="dim")
    table.add_column("Date", style="cyan")
    table.add_column("Dir", justify="center")
    table.add_column("From")
    table.add_column("Subject")
    table.add_column("Lang", justify="center")

    for row in results:
        direction_icon = "→" if row["direction"] == "sent" else "←"
        date_str = row["date"][:10] if row["date"] else "?"
        table.add_row(
            str(row["id"]),
            date_str,
            direction_icon,
            row["from_name"] or row["from_address"],
            (row["subject"] or "")[:60],
            row["language"],
        )
    console.print(table)


@cli.command("show")
@click.argument("email_id", type=int)
@click.option("--full", is_flag=True, help="Show full body instead of delta text.")
def show(email_id, full):
    """Show a single email by ID."""
    from src.storage.search import get_email_by_id
    row = get_email_by_id(email_id)
    if not row:
        console.print(f"[red]Email #{email_id} not found.[/red]")
        return

    console.print(f"\n[bold]#{row['id']} — {row['subject']}[/bold]")
    console.print(f"[cyan]Date:[/cyan]      {row['date']}")
    console.print(f"[cyan]From:[/cyan]      {row['from_name']} <{row['from_address']}>")
    console.print(f"[cyan]Direction:[/cyan] {row['direction']} | [cyan]Language:[/cyan] {row['language']}")
    console.print(f"[cyan]Thread:[/cyan]    {row['thread_id']}")
    console.print()
    body = row["body_text"] if full else row["delta_text"]
    console.print(body or "[dim](no text content)[/dim]")


# ═══════════════════════════════════════════════════════════════════════════
#  STATS — Email statistics
# ═══════════════════════════════════════════════════════════════════════════

@cli.group()
def stats():
    """Email statistics and analysis."""
    pass


@stats.command("overview")
def stats_overview():
    """Show overall email statistics."""
    from src.storage.database import init_db, get_db
    from src.statistics.aggregator import overview_stats
    init_db()
    with get_db() as conn:
        s = overview_stats(conn)

    table = Table(title="Email Statistics Overview")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right", style="bold")

    table.add_row("Total emails", str(s["total"]))
    table.add_row("  Sent", str(s["sent"]))
    table.add_row("  Received", str(s["received"]))
    table.add_row("Threads", str(s["threads"]))
    table.add_row("With attachments", str(s["with_attachments"]))
    table.add_row("", "")
    table.add_row("Language: French", str(s["french"]))
    table.add_row("Language: English", str(s["english"]))
    table.add_row("", "")
    table.add_row("Date range", f"{s['first_date'] or 'N/A'} → {s['last_date'] or 'N/A'}")
    table.add_row("Topics defined", str(s["topics_count"]))
    table.add_row("Analysis runs", str(s["runs_count"]))

    console.print(table)


@stats.command("frequency")
@click.option("--by", type=click.Choice(["year", "month", "week"]), default="month", show_default=True)
@click.option("--contact", "-c", default=None)
def stats_frequency(by, contact):
    """Show email frequency grouped by time period."""
    from src.storage.database import get_db
    from src.statistics.aggregator import frequency_data
    with get_db() as conn:
        rows = frequency_data(conn, by=by, contact_email=contact)

    table = Table(title=f"Email Frequency (by {by})")
    table.add_column("Period", style="cyan")
    table.add_column("Sent", justify="right")
    table.add_column("Received", justify="right")
    table.add_column("Total", justify="right", style="bold")
    table.add_column("Chart")

    max_total = max((r["total"] for r in rows), default=1)
    for row in rows:
        bar = "█" * int(row["total"] / max_total * 30)
        table.add_row(row["period"], str(row["sent"]), str(row["received"]), str(row["total"]), bar)

    console.print(table)


@stats.command("response-time")
@click.option("--contact", "-c", default=None)
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--by", type=click.Choice(["month", "quarter"]), default=None,
              help="Show breakdown by time period.")
def stats_response_time(contact, since, by):
    """Show intra-thread response times between parties.

    Computes how long each party takes to reply within threads.

    Examples:
      python cli.py stats response-time
      python cli.py stats response-time --by month
    """
    from src.storage.database import get_db
    from src.statistics.aggregator import response_times
    with get_db() as conn:
        data = response_times(conn, contact_email=contact, since=since, by=by)

    def _fmt_hours(h):
        if h == 0:
            return "—"
        if h < 1:
            return f"{h * 60:.0f} min"
        if h < 48:
            return f"{h:.1f} h"
        return f"{h / 24:.1f} j"

    table = Table(title="Temps de réponse (dans les threads)")
    table.add_column("Qui répond", style="cyan")
    table.add_column("Moyenne", justify="right")
    table.add_column("Médiane", justify="right")
    table.add_column("Maximum", justify="right")
    table.add_column("Échanges", justify="right", style="dim")

    yr = data["your_response"]
    tr = data["their_response"]
    table.add_row("Vous", _fmt_hours(yr["avg_hours"]), _fmt_hours(yr["median_hours"]),
                  _fmt_hours(yr["max_hours"]), str(yr["count"]))
    table.add_row("Ex-conjoint(e)", _fmt_hours(tr["avg_hours"]), _fmt_hours(tr["median_hours"]),
                  _fmt_hours(tr["max_hours"]), str(tr["count"]))
    console.print(table)

    if "by_period" in data and data["by_period"]:
        ptable = Table(title="Temps de réponse par période (moyenne en heures)")
        ptable.add_column("Période", style="cyan")
        ptable.add_column("Vous", justify="right")
        ptable.add_column("Ex-conjoint(e)", justify="right")
        for p in data["by_period"]:
            ptable.add_row(p["period"], _fmt_hours(p["your_avg"]), _fmt_hours(p["their_avg"]))
        console.print(ptable)


@stats.command("tone-trends")
@click.option("--by", type=click.Choice(["month", "quarter", "year"]), default="month", show_default=True)
@click.option("--contact", "-c", default=None)
@click.option("--direction", type=click.Choice(["sent", "received"]), default=None)
def stats_tone_trends(by, contact, direction):
    """Show aggression/manipulation trends over time.

    Examples:
      python cli.py stats tone-trends
      python cli.py stats tone-trends --by quarter --direction received
    """
    from src.storage.database import get_db
    from src.statistics.aggregator import tone_trends
    with get_db() as conn:
        rows = tone_trends(conn, by=by, contact_email=contact, direction=direction)

    if not rows:
        console.print("[dim]No tone analysis data available. Run 'analyze tone' first.[/dim]")
        return

    table = Table(title=f"Tendances du ton (par {by})")
    table.add_column("Période", style="cyan")
    table.add_column("Direction")
    table.add_column("Agressivité", justify="right")
    table.add_column("Manipulation", justify="right")
    table.add_column("Emails", justify="right", style="dim")
    table.add_column("Aggr.", min_width=20)

    max_aggr = max((r["avg_aggression"] for r in rows), default=0.01) or 0.01
    for r in rows:
        bar = "█" * int(r["avg_aggression"] / max_aggr * 15)
        dir_label = "↑ envoyé" if r["direction"] == "sent" else "↓ reçu"
        table.add_row(
            r["period"], dir_label,
            f"{r['avg_aggression']:.3f}", f"{r['avg_manipulation']:.3f}",
            str(r["count"]), f"[red]{bar}[/red]",
        )
    console.print(table)


@stats.command("topic-evolution")
@click.option("--by", type=click.Choice(["month", "quarter", "year"]), default="month", show_default=True)
@click.option("--topic", "-t", default=None, help="Filter to a specific topic.")
def stats_topic_evolution(by, topic):
    """Show topic prevalence over time.

    Examples:
      python cli.py stats topic-evolution --by quarter
      python cli.py stats topic-evolution --topic enfants
    """
    from src.storage.database import get_db
    from src.statistics.aggregator import topic_evolution
    with get_db() as conn:
        rows = topic_evolution(conn, by=by, topic_name=topic)

    if not rows:
        console.print("[dim]No topic data available. Run 'analyze classify' first.[/dim]")
        return

    if topic:
        # Simple table for a single topic
        table = Table(title=f"Évolution du sujet « {topic} » (par {by})")
        table.add_column("Période", style="cyan")
        table.add_column("Emails", justify="right")
        table.add_column("Chart")
        max_count = max((r["email_count"] for r in rows), default=1)
        for r in rows:
            bar = "█" * int(r["email_count"] / max_count * 25)
            table.add_row(r["period"], str(r["email_count"]), bar)
        console.print(table)
    else:
        # Pivoted table: periods as rows, topics as columns
        from collections import OrderedDict
        all_topics = sorted(set(r["topic"] for r in rows))
        periods = OrderedDict()
        for r in rows:
            if r["period"] not in periods:
                periods[r["period"]] = {}
            periods[r["period"]][r["topic"]] = r["email_count"]

        table = Table(title=f"Évolution des sujets (par {by})")
        table.add_column("Période", style="cyan")
        for t in all_topics:
            table.add_column(t, justify="right")
        for period, counts in periods.items():
            row_vals = [str(counts.get(t, 0)) for t in all_topics]
            table.add_row(period, *row_vals)
        console.print(table)


@stats.command("contacts")
@click.option("--contact", "-c", default=None, help="Filter to a specific contact email.")
@click.option("--sort", type=click.Choice(["count", "date"]), default="count", show_default=True)
def stats_contacts(contact, sort):
    """Show per-contact activity summary.

    Examples:
      python cli.py stats contacts
      python cli.py stats contacts --sort date
    """
    from src.storage.database import get_db
    from src.statistics.aggregator import contact_summary
    with get_db() as conn:
        rows = contact_summary(conn, contact_email=contact, sort_by=sort)

    if not rows:
        console.print("[dim]No contact data found.[/dim]")
        return

    table = Table(title="Activité par contact")
    table.add_column("Nom", style="cyan")
    table.add_column("Rôle")
    table.add_column("Envoyés", justify="right")
    table.add_column("Reçus", justify="right")
    table.add_column("Total", justify="right", style="bold")
    table.add_column("Période")
    table.add_column("Sujets principaux", max_width=30)

    for r in rows:
        date_range = f"{r['first_email'] or '?'} → {r['last_email'] or '?'}"
        topics_str = ", ".join(r["top_topics"]) if r["top_topics"] else "—"
        table.add_row(
            r["name"], r["role"],
            str(r["sent"]), str(r["received"]), str(r["total"]),
            date_range, topics_str,
        )
    console.print(table)


# ═══════════════════════════════════════════════════════════════════════════
#  EVENTS — Court and external events
# ═══════════════════════════════════════════════════════════════════════════

@cli.group()
def events():
    """Manage court dates and external events."""
    pass


@events.command("add")
@click.option("--date", "event_date", required=True, type=click.DateTime(formats=["%Y-%m-%d"]))
@click.option("--type", "event_type", default="hearing",
              type=click.Choice(["hearing", "filing", "decision", "appeal", "other"]))
@click.option("--description", required=True)
@click.option("--jurisdiction", default="")
@click.option("--outcome", default="")
def events_add(event_date, event_type, description, jurisdiction, outcome):
    """Add a court event."""
    from src.storage.database import init_db, get_db
    init_db()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO procedure_events
               (procedure_id, event_date, event_type, jurisdiction, description, outcome)
               VALUES (NULL, ?, ?, ?, ?, ?)""",
            (event_date.date().isoformat(), event_type, jurisdiction, description, outcome),
        )
    console.print(f"[green]Court event added: {event_date.date()} — {description}[/green]")


@events.command("list")
def events_list():
    """List all court and external events."""
    from src.storage.database import get_db
    with get_db() as conn:
        rows = conn.execute(
            """SELECT pe.id, pe.event_date, pe.event_type, pe.description, pe.outcome,
                      COALESCE(NULLIF(pe.jurisdiction,''), p.jurisdiction, '') AS jurisdiction,
                      p.name AS procedure_name
               FROM procedure_events pe
               LEFT JOIN procedures p ON p.id = pe.procedure_id
               ORDER BY pe.event_date"""
        ).fetchall()

    if not rows:
        console.print("[yellow]No events recorded.[/yellow]")
        return

    table = Table(title="Court Events")
    table.add_column("Date", style="cyan")
    table.add_column("Type")
    table.add_column("Jurisdiction")
    table.add_column("Description")
    table.add_column("Outcome")
    for row in rows:
        table.add_row(str(row["event_date"])[:10], row["event_type"],
                      row["jurisdiction"], row["description"], row["outcome"])
    console.print(table)


@events.command("import")
@click.argument("filepath", type=click.Path(exists=True))
def events_import(filepath):
    """Import court events from a CSV file (columns: date, type, jurisdiction, description, outcome)."""
    import csv
    from src.storage.database import init_db, get_db
    init_db()
    count = 0
    with open(filepath, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        with get_db() as conn:
            for row in reader:
                conn.execute(
                    """INSERT INTO procedure_events
                       (procedure_id, event_date, event_type, jurisdiction, description, outcome)
                       VALUES (NULL, ?, ?, ?, ?, ?)""",
                    (
                        row.get("date", "").strip(),
                        row.get("type", "other").strip(),
                        row.get("jurisdiction", "").strip(),
                        row.get("description", "").strip(),
                        row.get("outcome", "").strip(),
                    ),
                )
                count += 1
    console.print(f"[green]{count} court events imported from {filepath}[/green]")


# ═══════════════════════════════════════════════════════════════════════════
#  RUNS — Analysis run management
# ═══════════════════════════════════════════════════════════════════════════

@cli.group()
def runs():
    """Manage LLM analysis runs."""
    pass


@runs.command("list")
def runs_list():
    """List all analysis runs."""
    from src.storage.database import get_db
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM analysis_runs ORDER BY run_date DESC"
        ).fetchall()

    if not rows:
        console.print("[yellow]No analysis runs yet.[/yellow]")
        return

    table = Table(title="Analysis Runs")
    table.add_column("ID", justify="right")
    table.add_column("Date")
    table.add_column("Type")
    table.add_column("Provider")
    table.add_column("Model")
    table.add_column("Version")
    table.add_column("Emails", justify="right")
    table.add_column("Status")
    for row in rows:
        status_style = "green" if row["status"] == "complete" else "yellow" if row["status"] == "running" else "red"
        table.add_row(
            str(row["id"]),
            str(row["run_date"])[:16],
            row["analysis_type"],
            row["provider_name"],
            row["model_id"],
            row["prompt_version"],
            str(row["email_count"]),
            f"[{status_style}]{row['status']}[/{status_style}]",
        )
    console.print(table)


@runs.command("delete")
@click.argument("run_id", type=int)
@click.option("--email-id", type=int, default=None, help="Delete only this email's result.")
@click.confirmation_option(prompt="Are you sure you want to delete this run?")
def runs_delete(run_id, email_id):
    """Delete an analysis run (or a single result within a run)."""
    from src.storage.database import get_db
    with get_db() as conn:
        if email_id:
            conn.execute(
                "DELETE FROM analysis_results WHERE run_id=? AND email_id=?",
                (run_id, email_id),
            )
            console.print(f"[green]Deleted result for email #{email_id} in run #{run_id}[/green]")
        else:
            conn.execute("DELETE FROM analysis_results WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM email_topics WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM contradictions WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM timeline_events WHERE run_id=?", (run_id,))
            conn.execute("DELETE FROM analysis_runs WHERE id=?", (run_id,))
            console.print(f"[green]Analysis run #{run_id} deleted.[/green]")


# ═══════════════════════════════════════════════════════════════════════════
#  REPORT — Document generation (Phase 4)
# ═══════════════════════════════════════════════════════════════════════════

@cli.group()
def report():
    """Generate analysis reports (Word/PDF)."""
    pass


@report.command("timeline")
@click.option("--format", "fmt", type=click.Choice(["docx", "pdf"]), default="docx", show_default=True)
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path.")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--until", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
def report_timeline(fmt, output, since, until):
    """Generate a timeline report (merged events + court dates).

    Examples:
      python cli.py report timeline
      python cli.py report timeline --format pdf --output dossier_timeline.pdf
    """
    import tempfile
    from datetime import date
    from src.storage.database import init_db, get_db
    from src.reports.builder import build_timeline_report
    init_db()

    chart_dir = Path(tempfile.mkdtemp(prefix="mye_charts_"))
    if not output:
        output = f"data/exports/timeline_{date.today().isoformat()}.{fmt}"
    output_path = Path(output)

    with get_db() as conn:
        rpt = build_timeline_report(
            conn, chart_dir,
            since=since.strftime("%Y-%m-%d") if since else None,
            until=until.strftime("%Y-%m-%d") if until else None,
        )

    if fmt == "docx":
        from src.reports.docx_renderer import render_docx
        render_docx(rpt, output_path)
    else:
        from src.reports.pdf_renderer import render_pdf
        render_pdf(rpt, output_path)

    console.print(f"[bold green]✓ Rapport généré :[/bold green] {output_path}")


@report.command("tone")
@click.option("--format", "fmt", type=click.Choice(["docx", "pdf"]), default="docx", show_default=True)
@click.option("--output", "-o", type=click.Path(), default=None)
def report_tone(fmt, output):
    """Generate a tone analysis report (aggression/manipulation trends).

    Examples:
      python cli.py report tone
      python cli.py report tone --format pdf
    """
    import tempfile
    from datetime import date
    from src.storage.database import init_db, get_db
    from src.reports.builder import build_tone_report
    init_db()

    chart_dir = Path(tempfile.mkdtemp(prefix="mye_charts_"))
    if not output:
        output = f"data/exports/tone_{date.today().isoformat()}.{fmt}"
    output_path = Path(output)

    with get_db() as conn:
        rpt = build_tone_report(conn, chart_dir)

    if fmt == "docx":
        from src.reports.docx_renderer import render_docx
        render_docx(rpt, output_path)
    else:
        from src.reports.pdf_renderer import render_pdf
        render_pdf(rpt, output_path)

    console.print(f"[bold green]✓ Rapport généré :[/bold green] {output_path}")


@report.command("contradictions")
@click.option("--format", "fmt", type=click.Choice(["docx", "pdf"]), default="docx", show_default=True)
@click.option("--output", "-o", type=click.Path(), default=None)
def report_contradictions(fmt, output):
    """Generate a contradiction report (grouped by severity).

    Examples:
      python cli.py report contradictions
      python cli.py report contradictions --format pdf
    """
    import tempfile
    from datetime import date
    from src.storage.database import init_db, get_db
    from src.reports.builder import build_contradiction_report
    init_db()

    chart_dir = Path(tempfile.mkdtemp(prefix="mye_charts_"))
    if not output:
        output = f"data/exports/contradictions_{date.today().isoformat()}.{fmt}"
    output_path = Path(output)

    with get_db() as conn:
        rpt = build_contradiction_report(conn, chart_dir)

    if fmt == "docx":
        from src.reports.docx_renderer import render_docx
        render_docx(rpt, output_path)
    else:
        from src.reports.pdf_renderer import render_pdf
        render_pdf(rpt, output_path)

    console.print(f"[bold green]✓ Rapport généré :[/bold green] {output_path}")


@report.command("full")
@click.option("--format", "fmt", type=click.Choice(["docx", "pdf"]), default="docx", show_default=True)
@click.option("--output", "-o", type=click.Path(), default=None)
def report_full(fmt, output):
    """Generate the full analysis dossier (all sections combined).

    Includes: overview, timeline, tone analysis, contradictions,
    topic evolution, response times, contact activity, methodology.

    Examples:
      python cli.py report full
      python cli.py report full --format pdf --output dossier_complet.pdf
    """
    import tempfile
    from datetime import date
    from src.storage.database import init_db, get_db
    from src.reports.builder import build_full_report
    init_db()

    chart_dir = Path(tempfile.mkdtemp(prefix="mye_charts_"))
    if not output:
        output = f"data/exports/dossier_{date.today().isoformat()}.{fmt}"
    output_path = Path(output)

    with console.status("[bold]Generating full dossier..."):
        with get_db() as conn:
            rpt = build_full_report(conn, chart_dir)

    if fmt == "docx":
        from src.reports.docx_renderer import render_docx
        render_docx(rpt, output_path)
    else:
        from src.reports.pdf_renderer import render_pdf
        render_pdf(rpt, output_path)

    console.print(f"[bold green]✓ Dossier complet généré :[/bold green] {output_path}")


# ═══════════════════════════════════════════════════════════════════════════
#  INIT — First-time setup helper
# ═══════════════════════════════════════════════════════════════════════════

@cli.command("init")
def init_cmd():
    """Initialize the database and seed from config.yaml."""
    from src.storage.database import init_db, seed_contacts, seed_topics
    from src.config import contacts as cfg_contacts, topics as cfg_topics

    with console.status("Initializing database..."):
        init_db()
        seed_contacts(cfg_contacts())
        seed_topics(cfg_topics())

    console.print("[bold green]✓ Database initialized.[/bold green]")
    console.print("  Next step: run [cyan]python cli.py fetch emails --contact <email>[/cyan]")


# ═══════════════════════════════════════════════════════════════════════════
#  ANALYZE — LLM-powered analysis (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════

@cli.group()
def analyze():
    """Run LLM analysis on stored emails (classify, tone, timeline)."""
    pass


@analyze.command("classify")
@click.option("--provider", "-p", default=None, help="Override LLM provider (claude/groq/openai/ollama).")
@click.option("--batch-size", "-b", type=int, default=None, help="Emails per LLM call (default from config).")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None, help="Only emails after this date.")
@click.option("--limit", type=int, default=None, help="Max number of emails to process (for testing).")
@click.option("--force", is_flag=True, help="Re-analyse emails that already have results.")
@click.option("--max-chars", type=int, default=2000, show_default=True,
              help="Max delta_text chars sent per email. Increase for oversized emails (e.g. 100000).")
@click.option("--email-ids", default=None,
              help="Comma-separated email IDs to classify (e.g. 1414,595,1415). Bypasses skip logic.")
def analyze_classify(provider, batch_size, since, limit, force, max_chars, email_ids):
    """Classify emails by topic (logement, enfants, finances, divorce, ...).

    Uses Groq by default (free, fast). Results stored in email_topics table.

    Examples:
      python cli.py analyze classify
      python cli.py analyze classify --provider claude --limit 10
      python cli.py analyze classify --since 2018-01-01
      python cli.py analyze classify --provider groq --batch-size 1 --max-chars 100000 --email-ids 1414,595,1415,1377,1416,2122
    """
    from src.analysis.classifier import run_classification
    ids = [int(i.strip()) for i in email_ids.split(",")] if email_ids else None
    run_classification(
        provider_override=provider,
        batch_size=batch_size,
        since=since,
        force=force,
        limit=limit,
        max_chars=max_chars,
        email_ids=ids,
    )


@analyze.command("tone")
@click.option("--provider", "-p", default=None, help="Override LLM provider.")
@click.option("--batch-size", "-b", type=int, default=None)
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--limit", type=int, default=None)
@click.option("--force", is_flag=True)
def analyze_tone(provider, batch_size, since, limit, force):
    """Analyse tone, aggression level, and legal posturing in each email.

    Results stored in analysis_results (tone run). Includes:
    - Tone category (neutre/agressif/manipulateur/juridique/...)
    - Aggression level (0.0–1.0)
    - Manipulation score (0.0–1.0)
    - Legal posturing flag
    - Key phrases illustrating the tone

    Examples:
      python cli.py analyze tone
      python cli.py analyze tone --provider claude --limit 20
    """
    from src.analysis.tone import run_tone_analysis
    run_tone_analysis(
        provider_override=provider,
        batch_size=batch_size,
        since=since,
        force=force,
        limit=limit,
    )


@analyze.command("timeline")
@click.option("--provider", "-p", default=None, help="Override LLM provider (claude recommended).")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--limit", type=int, default=None)
@click.option("--force", is_flag=True)
@click.option("--min-significance", type=click.Choice(["low", "medium", "high"]), default="low",
              show_default=True, help="Only store events at or above this significance level.")
def analyze_timeline(provider, since, limit, force, min_significance):
    """Extract dated events from each email and build a legal timeline.

    Each email is processed individually for maximum precision.
    Events are stored in timeline_events and can be viewed alongside
    court events with: python cli.py events list

    Examples:
      python cli.py analyze timeline --provider claude
      python cli.py analyze timeline --min-significance medium
    """
    from src.analysis.timeline import run_timeline_extraction
    run_timeline_extraction(
        provider_override=provider,
        since=since,
        force=force,
        limit=limit,
        min_significance=min_significance,
    )


@analyze.command("contradictions")
@click.option("--provider", "-p", default=None, help="Override LLM provider.")
@click.option("--batch-size", "-b", type=int, default=None,
              help="Summaries per LLM call in Pass 1 (default: 50).")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--limit", type=int, default=None, help="Limit number of summaries to process.")
@click.option("--force", is_flag=True)
@click.option("--skip-confirmation", is_flag=True,
              help="Skip Pass 2 confirmation (faster but less precise).")
@click.option("--topic", default=None, help="Only search within this topic.")
@click.option("--min-severity", type=click.Choice(["low", "medium", "high"]),
              default="low", show_default=True)
@click.option("--run-id", "classify_run_id", type=int, default=None,
              help="Use summaries from this classify run (default: most recent).")
def analyze_contradictions(provider, batch_size, since, limit, force,
                           skip_confirmation, topic, min_severity, classify_run_id):
    """Detect contradictions across the email corpus (two-pass).

    Pass 1: Screen classification summaries by topic for candidate contradictions.
    Pass 2: Confirm each candidate using full email text.

    Requires classification to have run first.

    Examples:
      python cli.py analyze contradictions
      python cli.py analyze contradictions --topic enfants --min-severity medium
      python cli.py analyze contradictions --skip-confirmation --limit 500
      python cli.py analyze contradictions --run-id 5   # use specific classify run
    """
    from src.analysis.contradictions import run_contradiction_detection
    run_contradiction_detection(
        provider_override=provider,
        batch_size=batch_size,
        since=since,
        force=force,
        limit=limit,
        skip_confirmation=skip_confirmation,
        topic_filter=topic,
        min_severity=min_severity,
        classify_run_id=classify_run_id,
    )


@analyze.command("contradictions-list")
@click.option("--severity", type=click.Choice(["low", "medium", "high"]), default=None)
@click.option("--scope", type=click.Choice(["intra-sender", "cross-sender"]), default=None)
@click.option("--topic", default=None)
@click.option("--limit", type=int, default=20, show_default=True)
def analyze_contradictions_list(severity, scope, topic, limit):
    """Browse detected contradictions.

    Examples:
      python cli.py analyze contradictions-list
      python cli.py analyze contradictions-list --severity high --scope intra-sender
    """
    from rich.table import Table
    from src.storage.database import get_db

    with get_db() as conn:
        params = []
        wheres = []

        if severity:
            wheres.append("c.severity = ?")
            params.append(severity)
        if scope:
            wheres.append("c.scope = ?")
            params.append(scope)
        if topic:
            wheres.append("t.name = ?")
            params.append(topic)

        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""

        rows = conn.execute(
            f"""SELECT c.id, c.email_id_a, c.email_id_b, c.scope, c.severity,
                       c.explanation, t.name AS topic_name,
                       ea.date AS date_a, ea.subject AS subject_a,
                       eb.date AS date_b, eb.subject AS subject_b,
                       r.provider_name, r.model_id
                FROM contradictions c
                LEFT JOIN topics t ON t.id = c.topic_id
                JOIN emails ea ON ea.id = c.email_id_a
                JOIN emails eb ON eb.id = c.email_id_b
                JOIN analysis_runs r ON r.id = c.run_id
                {where_clause}
                ORDER BY c.severity DESC, c.created_at DESC
                LIMIT ?""",
            params + [limit],
        ).fetchall()

    if not rows:
        console.print("[dim]No contradictions found.[/dim]")
        return

    table = Table(title=f"Contradictions ({len(rows)} shown)")
    table.add_column("#", style="dim")
    table.add_column("Scope", style="cyan")
    table.add_column("Severity")
    table.add_column("Topic")
    table.add_column("Email A")
    table.add_column("Email B")
    table.add_column("Explanation", max_width=50)
    table.add_column("LLM", style="dim")

    sev_colors = {"low": "yellow", "medium": "dark_orange", "high": "red bold"}

    for r in rows:
        sev_style = sev_colors.get(r["severity"], "")
        table.add_row(
            str(r["id"]),
            r["scope"],
            f"[{sev_style}]{r['severity']}[/{sev_style}]",
            r["topic_name"] or "—",
            f"#{r['email_id_a']} ({str(r['date_a'])[:10]})",
            f"#{r['email_id_b']} ({str(r['date_b'])[:10]})",
            r["explanation"][:100] + ("…" if len(r["explanation"]) > 100 else ""),
            f"{r['provider_name']}/{r['model_id'][:15]}",
        )

    console.print(table)


@analyze.command("manipulation")
@click.option("--provider", "-p", default=None, help="Override LLM provider.")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--limit", type=int, default=None)
@click.option("--force", is_flag=True)
@click.option("--direction", type=click.Choice(["sent", "received"]), default=None,
              help="Only analyse emails in this direction.")
@click.option("--min-score", type=float, default=0.0,
              help="Only flag results with total_score >= this threshold.")
def analyze_manipulation(provider, since, limit, force, direction, min_score):
    """Detect manipulation patterns in each email.

    Identifies: gaslighting, emotional weaponization, financial coercion,
    legal threats, children instrumentalization, guilt-tripping, projection,
    false victimhood, moving goalposts, silent treatment threats.

    Processes one email at a time for precision.

    Examples:
      python cli.py analyze manipulation
      python cli.py analyze manipulation --direction received --min-score 0.3
      python cli.py analyze manipulation --provider claude --limit 20
    """
    from src.analysis.manipulation import run_manipulation_detection
    run_manipulation_detection(
        provider_override=provider,
        since=since,
        force=force,
        limit=limit,
        direction=direction,
        min_score=min_score,
    )


@analyze.command("court-correlation")
@click.option("--provider", "-p", default=None, help="Override LLM provider.")
@click.option("--window", type=int, default=14, show_default=True,
              help="Days before/after each court event to examine.")
@click.option("--narrative", is_flag=True,
              help="Generate LLM narrative summary for each correlation.")
@click.option("--limit", type=int, default=None,
              help="Limit number of court events to process.")
def analyze_court_correlation(provider, window, narrative, limit):
    """Correlate email patterns around court event dates.

    For each court event, analyses email volume, tone shifts, and topic
    distribution in a configurable time window. Optionally generates
    an LLM narrative summary with --narrative.

    Requires court events in DB (use 'events add' or 'events import').

    Examples:
      python cli.py analyze court-correlation
      python cli.py analyze court-correlation --window 30 --narrative
    """
    from src.analysis.court_correlator import run_court_correlation
    run_court_correlation(
        provider_override=provider,
        window_days=window,
        include_narrative=narrative,
        limit=limit,
    )


@analyze.command("correlations-list")
@click.option("--limit", type=int, default=None)
def analyze_correlations_list(limit):
    """Browse court event correlations (SQL stats only, no LLM needed).

    Examples:
      python cli.py analyze correlations-list
    """
    from rich.table import Table
    from src.analysis.court_correlator import get_court_event_correlation, _get_court_events

    events = _get_court_events(limit=limit)
    if not events:
        console.print("[dim]No court events found.[/dim]")
        return

    table = Table(title=f"Court Event Correlations ({len(events)} events)")
    table.add_column("Date", style="cyan")
    table.add_column("Type")
    table.add_column("Description", max_width=30)
    table.add_column("Before", justify="right")
    table.add_column("After", justify="right")
    table.add_column("Vol Δ%", justify="right")
    table.add_column("Aggr Δ", justify="right")
    table.add_column("Manip Δ", justify="right")

    for ce in events:
        corr = get_court_event_correlation(ce["id"])
        if not corr:
            continue
        d = corr["delta"]
        vol_pct = f"{d['volume_change_pct']:+.0f}%" if d["volume_change_pct"] is not None else "—"
        aggr_d = f"{d['aggression_change']:+.3f}"
        manip_d = f"{d['manipulation_change']:+.3f}"

        table.add_row(
            str(corr["event"]["date"]),
            corr["event"]["type"],
            corr["event"]["description"][:30],
            str(corr["before"]["count"]),
            str(corr["after"]["count"]),
            vol_pct,
            aggr_d,
            manip_d,
        )

    console.print(table)


@analyze.command("all")
@click.option("--provider", "-p", default=None, help="Override LLM provider for all tasks.")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--limit", type=int, default=None)
@click.option("--force", is_flag=True)
def analyze_all(provider, since, limit, force):
    """Run classify + tone + timeline sequentially.

    Recommended for a full first-pass analysis of the entire corpus.
    Cost tip: set provider=groq in config.yaml for classify/tone, claude for timeline.

    Example:
      python cli.py analyze all
      python cli.py analyze all --limit 50   # test on 50 emails first
    """
    from src.analysis.classifier import run_classification
    from src.analysis.tone import run_tone_analysis
    from src.analysis.timeline import run_timeline_extraction

    console.print("[bold cyan]Step 1/3 — Topic Classification[/bold cyan]")
    run_classification(provider_override=provider, since=since, force=force, limit=limit)

    console.print("\n[bold cyan]Step 2/3 — Tone Analysis[/bold cyan]")
    run_tone_analysis(provider_override=provider, since=since, force=force, limit=limit)

    console.print("\n[bold cyan]Step 3/3 — Timeline Extraction[/bold cyan]")
    run_timeline_extraction(provider_override=provider, since=since, force=force, limit=limit)

    console.print("\n[bold green]✓ Full analysis complete. Run 'python cli.py stats overview' to review.[/bold green]")


@analyze.command("deep")
@click.option("--provider", "-p", default=None, help="Override LLM provider for all Phase 3 tasks.")
@click.option("--since", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--limit", type=int, default=None)
@click.option("--force", is_flag=True)
def analyze_deep(provider, since, limit, force):
    """Run all Phase 3 analyses: contradictions + manipulation + court-correlation.

    Equivalent to running contradictions, manipulation, and court-correlation
    sequentially.

    Examples:
      python cli.py analyze deep
      python cli.py analyze deep --limit 100
      python cli.py analyze deep --provider claude
    """
    from src.analysis.contradictions import run_contradiction_detection
    from src.analysis.manipulation import run_manipulation_detection
    from src.analysis.court_correlator import run_court_correlation

    console.print("[bold cyan]Step 1/3 — Contradiction Detection[/bold cyan]")
    run_contradiction_detection(provider_override=provider, since=since, force=force, limit=limit)

    console.print("\n[bold cyan]Step 2/3 — Manipulation Detection[/bold cyan]")
    run_manipulation_detection(provider_override=provider, since=since, force=force, limit=limit)

    console.print("\n[bold cyan]Step 3/3 — Court Event Correlation[/bold cyan]")
    run_court_correlation(provider_override=provider)

    console.print("\n[bold green]✓ Deep analysis complete. Run 'python cli.py analyze stats' to review.[/bold green]")


@analyze.command("results")
@click.argument("email_id", type=int)
@click.option("--type", "analysis_type", default=None,
              type=click.Choice(["classify", "tone", "timeline", "contradictions", "manipulation", "court_correlation"]),
              help="Filter by analysis type.")
def analyze_results(email_id, analysis_type):
    """Show analysis results for a specific email."""
    from src.storage.database import get_db
    with get_db() as conn:
        query = """
            SELECT ar.run_id, ar2.analysis_type, ar2.provider_name, ar2.model_id,
                   ar2.run_date, ar.result_json
            FROM analysis_results ar
            JOIN analysis_runs ar2 ON ar2.id = ar.run_id
            WHERE ar.email_id = ?
        """
        params = [email_id]
        if analysis_type:
            query += " AND ar2.analysis_type = ?"
            params.append(analysis_type)
        query += " ORDER BY ar2.run_date DESC"
        rows = conn.execute(query, params).fetchall()

    if not rows:
        console.print(f"[yellow]No analysis results for email #{email_id}.[/yellow]")
        return

    for row in rows:
        console.print(f"\n[bold cyan]Run #{row['run_id']} — {row['analysis_type']}[/bold cyan]"
                      f" [{row['provider_name']} / {row['model_id']}] {str(row['run_date'])[:16]}")
        try:
            parsed = json.loads(row["result_json"])
            console.print_json(json.dumps(parsed, ensure_ascii=False, indent=2))
        except Exception:
            console.print(row["result_json"])


@analyze.command("stats")
def analyze_stats():
    """Show analysis coverage statistics."""
    from src.storage.database import get_db
    with get_db() as conn:
        total_emails = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        classified = conn.execute(
            "SELECT COUNT(DISTINCT email_id) FROM analysis_results ar "
            "JOIN analysis_runs r ON r.id=ar.run_id WHERE r.analysis_type='classify'"
        ).fetchone()[0]
        toned = conn.execute(
            "SELECT COUNT(DISTINCT email_id) FROM analysis_results ar "
            "JOIN analysis_runs r ON r.id=ar.run_id WHERE r.analysis_type='tone'"
        ).fetchone()[0]
        timeline_emails = conn.execute(
            "SELECT COUNT(DISTINCT email_id) FROM timeline_events"
        ).fetchone()[0]
        timeline_events = conn.execute("SELECT COUNT(*) FROM timeline_events").fetchone()[0]
        topic_links = conn.execute("SELECT COUNT(DISTINCT email_id) FROM email_topics").fetchone()[0]

        # Phase 3 stats
        manipulation_analyzed = conn.execute(
            "SELECT COUNT(DISTINCT email_id) FROM analysis_results ar "
            "JOIN analysis_runs r ON r.id=ar.run_id WHERE r.analysis_type='manipulation'"
        ).fetchone()[0]
        contradiction_pairs = conn.execute("SELECT COUNT(*) FROM contradictions").fetchone()[0]
        court_events_count = conn.execute("SELECT COUNT(*) FROM procedure_events").fetchone()[0]

        # Top topics (exclude system topics)
        top_topics = conn.execute(
            """SELECT t.name, COUNT(DISTINCT et.email_id) as cnt
               FROM email_topics et JOIN topics t ON t.id=et.topic_id
               WHERE t.name NOT IN ('trop_court', 'non_classifiable')
               GROUP BY t.name ORDER BY cnt DESC LIMIT 10"""
        ).fetchall()

    table = Table(title="Analysis Coverage")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Coverage", justify="right")

    def pct(n):
        return f"{n/total_emails*100:.1f}%" if total_emails else "—"

    table.add_row("Total emails in DB", str(total_emails), "100%")
    table.add_row("Classified (topics)", str(classified), pct(classified))
    table.add_row("Tone analysed", str(toned), pct(toned))
    table.add_row("Timeline processed", str(timeline_emails), pct(timeline_emails))
    table.add_row("Timeline events found", str(timeline_events), "—")
    table.add_row("Emails with topic link", str(topic_links), pct(topic_links))
    table.add_row("", "", "")
    table.add_row("[bold]Phase 3 — Deep Analysis[/bold]", "", "")
    table.add_row("Manipulation analysed", str(manipulation_analyzed), pct(manipulation_analyzed))
    table.add_row("Contradiction pairs", str(contradiction_pairs), "—")
    table.add_row("Procedure events in DB", str(court_events_count), "—")
    console.print(table)

    if top_topics:
        table2 = Table(title="Top Topics")
        table2.add_column("Topic", style="cyan")
        table2.add_column("Emails", justify="right")
        for row in top_topics:
            table2.add_row(row["name"], str(row["cnt"]))
        console.print(table2)


# ═══════════════════════════════════════════════════════════════════════════
#  ANALYZE MARK-UNCOVERED — tag unclassifiable emails as trop_court / non_classifiable
# ═══════════════════════════════════════════════════════════════════════════

@analyze.command("mark-uncovered")
@click.option("--short-threshold", default=50, show_default=True, type=int,
              help="Max delta_text length (chars) to classify as trop_court.")
@click.option("--dry-run", is_flag=True, help="Show what would be tagged without writing.")
def analyze_mark_uncovered(short_threshold, dry_run):
    """Tag remaining unclassified emails as trop_court or non_classifiable.

    Excludes oversized emails (>32,767 chars) which are reserved for Groq.
    Results count toward classification coverage %.
    """
    from src.storage.database import get_db
    with get_db() as conn:
        # Ensure special topics exist
        for name, desc in [
            ("trop_court", "Email trop court ou vide pour être classifié"),
            ("non_classifiable", "Contenu ambigu, réponse automatique ou non classifiable"),
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO topics (name, description) VALUES (?, ?)",
                (name, desc),
            )

        # Find unclassified emails — exclude oversized (waiting for Groq)
        unclassified = conn.execute(
            """SELECT id, LENGTH(delta_text) as len
               FROM emails
               WHERE id NOT IN (SELECT DISTINCT email_id FROM email_topics)
               AND delta_text IS NOT NULL
               AND LENGTH(delta_text) <= 32767
               ORDER BY id"""
        ).fetchall()

        if not unclassified:
            console.print("[green]✓ No unclassified emails to tag.[/green]")
            return

        short = [r for r in unclassified if r["len"] < short_threshold]
        ambiguous = [r for r in unclassified if r["len"] >= short_threshold]

        console.print(f"Found [bold]{len(unclassified)}[/bold] unclassified emails:")
        console.print(f"  trop_court       : {len(short)} (delta_text < {short_threshold} chars)")
        console.print(f"  non_classifiable : {len(ambiguous)}")

        if dry_run:
            console.print("[yellow]Dry-run — no changes written.[/yellow]")
            return

        # Create a manual run for traceability
        import hashlib, json as _json
        prompt_hash = hashlib.sha256(b"mark-uncovered-v1").hexdigest()[:16]
        cur = conn.execute(
            """INSERT INTO analysis_runs
               (analysis_type, provider_name, model_id, prompt_hash, prompt_version, status, notes)
               VALUES ('classify', 'manual', 'rule-based', ?, 'v1', 'running', 'auto-tagged by mark-uncovered')""",
            (prompt_hash,),
        )
        run_id = cur.lastrowid

        tagged = 0
        for r in unclassified:
            topic_name = "trop_court" if r["len"] < short_threshold else "non_classifiable"
            topic_row = conn.execute(
                "SELECT id FROM topics WHERE name = ?", (topic_name,)
            ).fetchone()
            if topic_row:
                conn.execute(
                    "INSERT OR IGNORE INTO email_topics (email_id, topic_id, confidence, run_id) "
                    "VALUES (?, ?, 1.0, ?)",
                    (r["id"], topic_row["id"], run_id),
                )
                result_json = _json.dumps(
                    {"topics": [{"name": topic_name, "confidence": 1.0}], "source": "rule-based"}
                )
                conn.execute(
                    "INSERT OR IGNORE INTO analysis_results (run_id, email_id, result_json) VALUES (?, ?, ?)",
                    (run_id, r["id"], result_json),
                )
                tagged += 1

        conn.execute(
            "UPDATE analysis_runs SET status='complete', email_count=? WHERE id=?",
            (tagged, run_id),
        )
        conn.commit()
        console.print(f"[green]✓ Tagged {tagged} emails (run #{run_id}).[/green]")


@analyze.command("mark-tone-reviewed")
@click.option("--short-threshold", default=50, show_default=True, type=int,
              help="Max delta_text length (chars) to tag as trop_court.")
@click.option("--dry-run", is_flag=True, help="Show what would be tagged without writing.")
def analyze_mark_tone_reviewed(short_threshold, dry_run):
    """Persist neutral tone for emails left blank by ChatGPT (reviewed but no clear tone).

    Blank tone rows are skipped on import, leaving emails unanalyzed.
    This command stores a rule-based neutral result so coverage reaches 100%
    (excluding oversized emails >32,767 chars, which are reserved for Groq).
    """
    from src.storage.database import get_db
    import hashlib, json as _json

    with get_db() as conn:
        unanalyzed = conn.execute(
            """SELECT id, LENGTH(delta_text) as len
               FROM emails
               WHERE NOT EXISTS (
                   SELECT 1 FROM analysis_results ar
                   JOIN analysis_runs r ON ar.run_id = r.id
                   WHERE ar.email_id = emails.id AND r.analysis_type = 'tone'
               )
               AND (delta_text IS NULL OR LENGTH(delta_text) <= 32767)
               ORDER BY id"""
        ).fetchall()

        if not unanalyzed:
            console.print("[green]✓ No unanalyzed tone emails to tag.[/green]")
            return

        short = [r for r in unanalyzed if r["len"] is None or r["len"] < short_threshold]
        ambiguous = [r for r in unanalyzed if r["len"] is not None and r["len"] >= short_threshold]

        console.print(f"Found [bold]{len(unanalyzed)}[/bold] unanalyzed tone emails:")
        console.print(f"  trop_court (< {short_threshold} chars) : {len(short)}")
        console.print(f"  neutre/ambigu                         : {len(ambiguous)}")

        oversized_count = conn.execute(
            """SELECT COUNT(*) FROM emails
               WHERE NOT EXISTS (
                   SELECT 1 FROM analysis_results ar
                   JOIN analysis_runs r ON ar.run_id = r.id
                   WHERE ar.email_id = emails.id AND r.analysis_type = 'tone'
               )
               AND delta_text IS NOT NULL AND LENGTH(delta_text) > 32767"""
        ).fetchone()[0]
        if oversized_count:
            console.print(f"  [dim]oversized (>32,767 chars, skipped): {oversized_count}[/dim]")

        if dry_run:
            console.print("[yellow]Dry-run — no changes written.[/yellow]")
            return

        prompt_hash = hashlib.sha256(b"mark-tone-reviewed-v1").hexdigest()[:16]
        cur = conn.execute(
            """INSERT INTO analysis_runs
               (analysis_type, provider_name, model_id, prompt_hash, prompt_version, status, notes)
               VALUES ('tone', 'manual', 'rule-based', ?, 'v1', 'running',
                       'auto-tagged by mark-tone-reviewed: blank rows from ChatGPT import')""",
            (prompt_hash,),
        )
        run_id = cur.lastrowid

        tagged = 0
        for r in unanalyzed:
            if r["len"] is None or r["len"] < short_threshold:
                result = {
                    "tone": None,
                    "aggression_level": 0.0,
                    "manipulation_score": 0.0,
                    "legal_posturing": False,
                    "emotional_states": [],
                    "key_phrases": [],
                    "notes": "Trop court pour analyser le ton.",
                    "source": "rule-based",
                }
            else:
                result = {
                    "tone": "neutre",
                    "aggression_level": 0.0,
                    "manipulation_score": 0.0,
                    "legal_posturing": False,
                    "emotional_states": [],
                    "key_phrases": [],
                    "notes": "Révisé par ChatGPT — ton non déterminé (contenu ambigu ou neutre).",
                    "source": "rule-based",
                }
            conn.execute(
                "INSERT OR IGNORE INTO analysis_results (run_id, email_id, result_json) VALUES (?, ?, ?)",
                (run_id, r["id"], _json.dumps(result)),
            )
            tagged += 1

        conn.execute(
            "UPDATE analysis_runs SET status='complete', email_count=? WHERE id=?",
            (tagged, run_id),
        )
        conn.commit()
        console.print(f"[green]✓ Tagged {tagged} emails as reviewed (run #{run_id}).[/green]")


# ═══════════════════════════════════════════════════════════════════════════
#  ANALYZE EXPORT / IMPORT — Excel round-trip for ChatGPT / Claude web UI
# ═══════════════════════════════════════════════════════════════════════════

@analyze.command("export")
@click.option(
    "--type", "analysis_type",
    default="classify", show_default=True,
    type=click.Choice(["classify", "tone", "timeline", "manipulation", "contradictions"]),
    help="Type of analysis to prepare.",
)
@click.option("--limit", default=None, type=int,
              help="Max number of emails to include (default: all unanalyzed).")
@click.option("--offset", default=0, type=int,
              help="Skip the first N unanalyzed emails (for pagination across batches).")
@click.option("--all", "all_emails", is_flag=True,
              help="Include already-analyzed emails (re-export).")
@click.option("--include-large", is_flag=True,
              help="Include emails over 32,767 chars (will be truncated in Excel). "
                   "By default these are excluded and left for Groq.")
@click.option("--output", "output_path", default=None,
              help="Output .xlsx path (default: data/exports/export_<type>_<date>.xlsx).")
@click.option("--topic", default=None,
              help="[contradictions only] Filter by topic (e.g. enfants, finances).")
@click.option("--date-from", default=None, help="[contradictions only] Start date YYYY-MM-DD.")
@click.option("--date-to", default=None, help="[contradictions only] End date YYYY-MM-DD.")
def analyze_export(analysis_type, limit, offset, all_emails, include_large, output_path,
                   topic, date_from, date_to):
    """Export unanalyzed emails to Excel for manual analysis via ChatGPT or Claude.

    Emails over 32,767 chars are excluded by default — they are left for Groq,
    which can handle them natively (128k context window). Use --include-large to
    override (content will be truncated with a visible marker).

    For contradictions: exports email summaries grouped by topic (no delta_text).
    Use --topic, --date-from, --date-to to slice large topic groups.
    """
    from pathlib import Path
    from src.storage.database import get_db
    from src.analysis.excel_export import export_for_analysis, export_contradictions_batch, _EXCEL_CELL_LIMIT

    if output_path is None:
        date_str = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M")
        output_path = f"data/exports/export_{analysis_type}_{date_str}.xlsx"

    out = Path(output_path)
    exclude_large = not include_large

    # Contradictions uses a separate export function
    if analysis_type == "contradictions":
        with get_db() as conn:
            try:
                path, count = export_contradictions_batch(
                    conn, out,
                    topic=topic,
                    date_from=date_from,
                    date_to=date_to,
                    limit=limit or 600,
                )
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
                return
        console.print(f"\n[bold green]✓ Exported {count} email summaries[/bold green]")
        console.print(f"  Topic  : {topic or 'all'}")
        console.print(f"  Period : {date_from or 'start'} → {date_to or 'end'}")
        console.print(f"  File   : [cyan]{path}[/cyan]")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print("  1. Upload to ChatGPT — it reads the 'Emails' sheet and fills 'Contradictions' sheet")
        console.print(f"  2. Run: [cyan]python cli.py analyze import-results <file.xlsx> "
                      f"--type contradictions --provider openai --model gpt-5.4-thinking[/cyan]")
        return

    with get_db() as conn:
        # Count how many will be excluded so we can report it
        excluded_count = 0
        if exclude_large:
            excluded_count = conn.execute(
                f"SELECT COUNT(*) FROM emails "
                f"WHERE delta_text IS NOT NULL AND LENGTH(delta_text) > {_EXCEL_CELL_LIMIT}"
            ).fetchone()[0]

        try:
            path, count, truncated = export_for_analysis(
                conn,
                analysis_type,
                out,
                limit=limit,
                offset=offset,
                unanalyzed_only=not all_emails,
                exclude_large=exclude_large,
            )
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            return

    console.print(f"\n[bold green]✓ Exported {count} emails[/bold green]")
    if excluded_count:
        console.print(
            f"  [cyan]ℹ {excluded_count} email(s) over 32,767 chars excluded — "
            f"Groq will handle them (fits in 128k context).[/cyan]"
        )
    if truncated:
        console.print(
            f"  [yellow]⚠ {truncated} email(s) exceeded Excel's 32,767 char limit "
            f"and were truncated. A marker was added so the AI knows.[/yellow]"
        )
    console.print(f"  File : [cyan]{path}[/cyan]")
    console.print(f"  Type : {analysis_type}")
    console.print()
    console.print("[bold]Next steps:[/bold]")
    console.print("  1. Upload the file to [cyan]ChatGPT[/cyan] or [cyan]Claude.ai[/cyan]")
    console.print("  2. Ask it to fill in the yellow columns following the Instructions sheet")
    console.print("  3. Download the completed file")
    console.print(f"  4. Run: [cyan]python cli.py analyze import-results <file.xlsx> "
                  f"--type {analysis_type} --provider openai --model gpt-5.4-thinking[/cyan]")


@analyze.command("import-results")
@click.argument("excel_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--type", "analysis_type",
    required=True,
    type=click.Choice(["classify", "tone", "timeline", "manipulation", "contradictions"]),
    help="Analysis type that was filled in.",
)
@click.option("--provider", required=True,
              help="LLM provider used: openai | claude | google | mistral | etc.")
@click.option("--model", default=None,
              help="Model name, e.g. gpt-5.4-thinking or claude-opus-4-5. "
                   "If omitted, a sensible default is used per provider.")
def analyze_import_results(excel_file, analysis_type, provider, model):
    """Import a filled Excel analysis file back into the database."""
    from src.analysis.excel_import import import_results

    console.print(f"\nImporting [cyan]{excel_file.name}[/cyan] …")
    console.print(f"  Type     : {analysis_type}")
    console.print(f"  Provider : {provider}")
    if model:
        console.print(f"  Model    : {model}")

    try:
        stats = import_results(
            excel_path=excel_file,
            analysis_type=analysis_type,
            provider=provider,
            model=model,
        )
    except Exception as e:
        console.print(f"[red]Import failed: {e}[/red]")
        return

    console.print()
    if stats["imported"]:
        console.print(f"[bold green]✓ Imported {stats['imported']} results[/bold green]"
                      f"  (run #{stats['run_id']}, status: {stats['status']})")
    if stats["skipped"]:
        console.print(f"  Skipped  : {stats['skipped']} rows (empty output columns)")
    if stats["errors"]:
        console.print(f"\n[yellow]Errors ({len(stats['errors'])}):[/yellow]")
        for err in stats["errors"][:10]:
            console.print(f"  {err}")

    console.print(f"\nRun [cyan]python cli.py analyze stats[/cyan] to verify updated coverage.")


# ═══════════════════════════════════════════════════════════════════════════
#  WEB — Launch the FastAPI dashboard
# ═══════════════════════════════════════════════════════════════════════════

@cli.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind.")
@click.option("--port", default=8000, show_default=True, help="Port to listen on.")
@click.option("--reload", is_flag=True, help="Auto-reload on code changes (dev mode).")
def web_dashboard(host, port, reload):
    """Launch the web dashboard on http://HOST:PORT."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Run: pip install uvicorn[standard][/red]")
        raise SystemExit(1)
    console.print(f"[green]Starting dashboard at http://{host}:{port}[/green]")
    uvicorn.run("src.web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
