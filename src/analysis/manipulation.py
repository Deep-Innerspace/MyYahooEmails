"""
Manipulation pattern detection task.

Identifies specific manipulation tactics (gaslighting, coercion, projection, etc.)
in each email. Runs one email at a time for precision.
Uses 'manipulation' provider from config (default: Groq).
"""
import json
from datetime import datetime
from typing import Dict, Optional

from rich.console import Console
from tqdm import tqdm

from src.analysis.runner import (
    create_run, finish_run, get_emails_for_analysis,
    load_prompt, parse_json_response, store_result,
)
from src.config import analysis_skip_if_done
from src.llm.groq_provider import GroqDailyLimitError
from src.llm.router import get_provider
from src.storage.database import get_db

console = Console()


def _get_tone_context(email_id: int) -> Optional[Dict]:
    """Fetch tone analysis results for enrichment (most recent tone run)."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT ar.result_json FROM analysis_results ar
               JOIN analysis_runs r ON r.id = ar.run_id
               WHERE ar.email_id = ? AND r.analysis_type = 'tone'
               ORDER BY r.run_date DESC LIMIT 1""",
            (email_id,),
        ).fetchone()
        if row:
            data = json.loads(row["result_json"])
            return {
                "tone": data.get("tone"),
                "aggression_level": data.get("aggression_level"),
                "manipulation_score": data.get("manipulation_score"),
            }
    return None


def run_manipulation_detection(
    provider_override: Optional[str] = None,
    since: Optional[datetime] = None,
    force: bool = False,
    limit: Optional[int] = None,
    direction: Optional[str] = None,
    min_score: float = 0.0,
) -> dict:
    """
    Detect manipulation patterns in each email.

    Returns stats dict: {run_id, total, analyzed, patterns_found, errors}
    """
    provider = get_provider("manipulation", override=provider_override)
    skip = not force and analysis_skip_if_done()

    system_prompt = load_prompt("manipulation")

    run_id = create_run(
        analysis_type="manipulation",
        provider_name=provider.name,
        model_id=provider._model,
        prompt_text=system_prompt,
        prompt_version="v1-french-legal",
        notes=f"min_score={min_score}, direction={direction}",
    )

    console.print(
        f"[bold]Manipulation detection run #{run_id}[/bold] — "
        f"provider: {provider.name} / {provider._model}"
    )

    emails = get_emails_for_analysis(
        skip_if_analyzed=skip,
        run_id=run_id,
        since=since,
        direction=direction,
        limit=limit,
    )
    total = len(emails)
    console.print(f"  {total} emails to process (one at a time for precision)")

    analyzed = errors = patterns_found = 0

    with tqdm(total=total, desc="  Detecting manipulation", unit="email") as pbar:
        for email in emails:
            tone_ctx = _get_tone_context(email["id"])

            email_input = json.dumps({
                "id": email["id"],
                "date": str(email["date"])[:10],
                "direction": email["direction"],
                "subject": email["subject"],
                "delta_text": email["delta_text"][:3000],
                "tone_context": tone_ctx,
            }, ensure_ascii=False)

            try:
                response = provider.complete_with_retry(
                    prompt=email_input,
                    system=system_prompt,
                    max_tokens=1500,
                )
                result = parse_json_response(response.content)

                # Filter by min_score
                total_score = float(result.get("total_score", 0.0))
                if total_score >= min_score:
                    store_result(
                        run_id, email["id"],
                        json.dumps(result),
                        sender_contact_id=email.get("contact_id"),
                    )
                    if result.get("patterns"):
                        patterns_found += 1
                else:
                    # Store even below threshold for completeness (marks as analyzed)
                    store_result(
                        run_id, email["id"],
                        json.dumps(result),
                        sender_contact_id=email.get("contact_id"),
                    )

                analyzed += 1

            except GroqDailyLimitError as e:
                mins = int(e.retry_after_secs // 60)
                console.print(
                    f"\n  [bold red]⛔ Groq daily token limit reached.[/bold red] "
                    f"Retry in ~{mins} min. Run #{run_id} saved as partial "
                    f"({analyzed} emails processed so far)."
                )
                finish_run(run_id, status="partial", email_count=analyzed)
                return {
                    "run_id": run_id, "total": total, "analyzed": analyzed,
                    "patterns_found": patterns_found, "errors": errors,
                    "aborted": True,
                }

            except Exception as e:
                console.print(f"\n  [red]Error on email #{email['id']}: {e}[/red]")
                errors += 1

            pbar.update(1)

    finish_run(
        run_id,
        status="complete" if errors == 0 else "partial",
        email_count=analyzed,
    )

    console.print(
        f"\n[bold green]✓ Manipulation detection complete.[/bold green] "
        f"Run #{run_id}: {analyzed} emails processed, "
        f"{patterns_found} with patterns, {errors} errors"
    )
    return {
        "run_id": run_id, "total": total, "analyzed": analyzed,
        "patterns_found": patterns_found, "errors": errors,
    }
