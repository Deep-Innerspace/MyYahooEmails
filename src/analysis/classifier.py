"""
Topic classification task.

Sends emails to the LLM in batches and assigns topics + confidence scores.
Uses the 'classify' provider from config (default: Groq — cheap/fast).
"""
import json
from datetime import datetime
from typing import List, Optional

from rich.console import Console
from tqdm import tqdm

from src.analysis.runner import (
    batch, create_run, finish_run, get_emails_for_analysis,
    load_prompt, parse_json_response, store_result, store_topics_for_email,
)
from src.config import analysis_batch_size, analysis_skip_if_done, topics as cfg_topics
from src.llm.groq_provider import GroqDailyLimitError
from src.llm.router import get_provider

console = Console()


def run_classification(
    provider_override: Optional[str] = None,
    batch_size: Optional[int] = None,
    since: Optional[datetime] = None,
    force: bool = False,
    limit: Optional[int] = None,
    max_chars: int = 2000,
    email_ids: Optional[List[int]] = None,
) -> dict:
    """
    Classify all unanalyzed emails by topic.

    Returns stats dict: {run_id, total, classified, skipped, errors}
    """
    provider = get_provider("classify", override=provider_override)
    bs = batch_size or analysis_batch_size()
    skip = not force and analysis_skip_if_done()

    # Build topics list string for prompt injection
    topic_list = "\n".join(
        f"- {t['name']}: {t.get('description', '')}"
        for t in cfg_topics()
    )
    prompt_template = load_prompt("classify")
    system_prompt = prompt_template.replace("{topics_list}", topic_list)

    # Create run record
    run_id = create_run(
        analysis_type="classify",
        provider_name=provider.name,
        model_id=provider._model,
        prompt_text=system_prompt,
        prompt_version="v1-french-legal",
        notes=f"batch_size={bs}, since={since}",
    )

    console.print(f"[bold]Classification run #{run_id}[/bold] — provider: {provider.name} / {provider._model}")

    # Fetch emails to process
    emails = get_emails_for_analysis(
        skip_if_analyzed=skip,
        run_id=run_id,
        since=since,
        limit=limit,
        email_ids=email_ids,
        skip_classified=skip and not email_ids,  # skip already-classified unless targeting IDs
    )
    total = len(emails)
    console.print(f"  {total} emails to classify (batch size: {bs})")

    classified = skipped = errors = 0

    with tqdm(total=total, desc="  Classifying", unit="email") as pbar:
        for email_batch in batch(emails, bs):
            # Build the user prompt
            batch_input = json.dumps([
                {
                    "id": e["id"],
                    "date": str(e["date"])[:10],
                    "direction": e["direction"],
                    "subject": e["subject"],
                    "delta_text": e["delta_text"][:max_chars],  # Cap per email to control tokens
                }
                for e in email_batch
            ], ensure_ascii=False)

            try:
                response = provider.complete_with_retry(
                    prompt=batch_input,
                    system=system_prompt,
                    max_tokens=1024 + (len(email_batch) * 200),
                )
                results = parse_json_response(response.content)

                for item in results:
                    email_id = item["id"]
                    # Store full result
                    store_result(run_id, email_id, json.dumps(item))
                    # Link topics
                    store_topics_for_email(email_id, item.get("topics", []), run_id)
                    classified += 1

            except GroqDailyLimitError as e:
                mins = int(e.retry_after_secs // 60)
                console.print(
                    f"\n  [bold red]⛔ Groq daily token limit reached.[/bold red] "
                    f"Retry in ~{mins} min. Run #{run_id} saved as partial "
                    f"({classified} emails classified so far)."
                )
                finish_run(run_id, status="partial", email_count=classified)
                return {"run_id": run_id, "total": total, "classified": classified,
                        "skipped": skipped, "errors": errors, "aborted": True}

            except Exception as e:
                console.print(f"\n  [red]Batch error: {e}[/red]")
                errors += len(email_batch)

            pbar.update(len(email_batch))

    finish_run(run_id, status="complete" if errors == 0 else "partial", email_count=classified)

    stats = {"run_id": run_id, "total": total, "classified": classified,
             "skipped": skipped, "errors": errors}
    console.print(
        f"\n[bold green]✓ Classification complete.[/bold green] "
        f"Run #{run_id}: {classified} classified, {errors} errors"
    )
    return stats
