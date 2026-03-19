"""
Timeline event extraction task.

Extracts dated facts, commitments, accusations, and legal statements from each email.
Runs one email at a time (precision matters more than speed here).
Uses 'timeline' provider from config (default: Groq, but Claude recommended for best results).
"""
import json
from datetime import datetime
from typing import Optional

from rich.console import Console
from tqdm import tqdm

from src.analysis.runner import (
    create_run, finish_run, get_emails_for_analysis,
    load_prompt, parse_json_response, store_result, store_timeline_events,
)
from src.config import analysis_skip_if_done
from src.llm.router import get_provider

console = Console()


def run_timeline_extraction(
    provider_override: Optional[str] = None,
    since: Optional[datetime] = None,
    force: bool = False,
    limit: Optional[int] = None,
    min_significance: str = "low",
) -> dict:
    """
    Extract timeline events from all unanalyzed emails.
    Returns stats dict: {run_id, total, extracted, events_found, errors}
    """
    provider = get_provider("timeline", override=provider_override)
    skip = not force and analysis_skip_if_done()

    system_prompt = load_prompt("timeline")

    run_id = create_run(
        analysis_type="timeline",
        provider_name=provider.name,
        model_id=provider._model,
        prompt_text=system_prompt,
        prompt_version="v1-french-legal",
        notes=f"min_significance={min_significance}",
    )

    console.print(f"[bold]Timeline extraction run #{run_id}[/bold] — provider: {provider.name} / {provider._model}")

    emails = get_emails_for_analysis(
        skip_if_analyzed=skip,
        run_id=run_id,
        since=since,
        limit=limit,
    )
    total = len(emails)
    console.print(f"  {total} emails to process (one at a time for precision)")

    extracted = errors = events_found = 0
    sig_levels = {"low": 0, "medium": 1, "high": 2}
    min_sig = sig_levels.get(min_significance, 0)

    with tqdm(total=total, desc="  Extracting events", unit="email") as pbar:
        for email in emails:
            email_input = json.dumps({
                "id": email["id"],
                "date": str(email["date"])[:10],
                "direction": email["direction"],
                "subject": email["subject"],
                "delta_text": email["delta_text"][:3000],
            }, ensure_ascii=False)

            try:
                response = provider.complete_with_retry(
                    prompt=email_input,
                    system=system_prompt,
                    max_tokens=1500,
                )
                result = parse_json_response(response.content)

                # Filter events by minimum significance
                events = [
                    ev for ev in result.get("events", [])
                    if sig_levels.get(ev.get("significance", "low"), 0) >= min_sig
                ]
                result["events"] = events

                store_result(run_id, email["id"], json.dumps(result))
                store_timeline_events(run_id, email["id"], events)
                events_found += len(events)
                extracted += 1

            except Exception as e:
                console.print(f"\n  [red]Error on email #{email['id']}: {e}[/red]")
                errors += 1

            pbar.update(1)

    finish_run(run_id, status="complete" if errors == 0 else "partial", email_count=extracted)

    console.print(
        f"\n[bold green]✓ Timeline extraction complete.[/bold green] "
        f"Run #{run_id}: {extracted} emails processed, {events_found} events extracted, {errors} errors"
    )
    return {
        "run_id": run_id, "total": total, "extracted": extracted,
        "events_found": events_found, "errors": errors,
    }
