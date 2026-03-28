"""
Tone analysis task.

Analyses emotional tone, aggression level, manipulation, and legal posturing
for each email. Uses 'tone' provider from config (default: Groq).
"""
import json
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from tqdm import tqdm

from src.analysis.runner import (
    batch, create_run, finish_run, get_emails_for_analysis,
    load_prompt, parse_json_response, store_result,
)
from src.config import analysis_batch_size, analysis_skip_if_done
from src.llm.groq_provider import GroqDailyLimitError
from src.llm.router import get_provider

console = Console()


def run_tone_analysis(
    provider_override: Optional[str] = None,
    batch_size: Optional[int] = None,
    since: Optional[datetime] = None,
    force: bool = False,
    limit: Optional[int] = None,
) -> dict:
    """
    Analyse tone/emotion for all unanalyzed emails.
    Returns stats dict: {run_id, total, analyzed, errors}
    """
    provider = get_provider("tone", override=provider_override)
    bs = batch_size or analysis_batch_size()
    skip = not force and analysis_skip_if_done()

    system_prompt = load_prompt("tone")

    run_id = create_run(
        analysis_type="tone",
        provider_name=provider.name,
        model_id=provider._model,
        prompt_text=system_prompt,
        prompt_version="v1-french-legal",
        notes=f"batch_size={bs}",
    )

    console.print(f"[bold]Tone analysis run #{run_id}[/bold] — provider: {provider.name} / {provider._model}")

    emails = get_emails_for_analysis(
        skip_if_analyzed=skip,
        run_id=run_id,
        since=since,
        limit=limit,
    )
    total = len(emails)
    console.print(f"  {total} emails to analyse (batch size: {bs})")

    analyzed = errors = 0

    with tqdm(total=total, desc="  Analysing tone", unit="email") as pbar:
        for email_batch in batch(emails, bs):
            batch_input = json.dumps([
                {
                    "id": e["id"],
                    "date": str(e["date"])[:10],
                    "direction": e["direction"],
                    "subject": e["subject"],
                    "delta_text": e["delta_text"][:2000],
                }
                for e in email_batch
            ], ensure_ascii=False)

            try:
                response = provider.complete_with_retry(
                    prompt=batch_input,
                    system=system_prompt,
                    max_tokens=1024 + (len(email_batch) * 150),
                )
                results = parse_json_response(response.content)

                for item in results:
                    store_result(run_id, item["id"], json.dumps(item))
                    analyzed += 1

            except GroqDailyLimitError as e:
                mins = int(e.retry_after_secs // 60)
                console.print(
                    f"\n  [bold red]⛔ Groq daily token limit reached.[/bold red] "
                    f"Retry in ~{mins} min. Run #{run_id} saved as partial "
                    f"({analyzed} emails analysed so far)."
                )
                finish_run(run_id, status="partial", email_count=analyzed)
                return {"run_id": run_id, "total": total, "analyzed": analyzed,
                        "errors": errors, "aborted": True}

            except Exception as e:
                console.print(f"\n  [red]Batch error: {e}[/red]")
                errors += len(email_batch)

            pbar.update(len(email_batch))

    finish_run(run_id, status="complete" if errors == 0 else "partial", email_count=analyzed)

    console.print(
        f"\n[bold green]✓ Tone analysis complete.[/bold green] "
        f"Run #{run_id}: {analyzed} analysed, {errors} errors"
    )
    return {"run_id": run_id, "total": total, "analyzed": analyzed, "errors": errors}
