"""
Contradiction detection task (two-pass).

Pass 1 — Screening: uses classification summaries grouped by topic to find
candidate contradiction pairs via the LLM.
Pass 2 — Confirmation: fetches full delta_text for each candidate pair and
asks the LLM to confirm or reject with verbatim quotes.

Uses 'contradictions' provider from config (default: Groq).
"""
import json
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional

from rich.console import Console
from tqdm import tqdm

from src.analysis.runner import (
    batch, create_run, finish_run, get_classification_summaries,
    load_prompt, parse_json_response, store_contradictions, store_result,
)
from src.config import analysis_skip_if_done
from src.llm.groq_provider import GroqDailyLimitError
from src.llm.router import get_provider
from src.storage.database import get_db

console = Console()


def _group_by_topic(summaries: List[Dict]) -> Dict[str, List[Dict]]:
    """Group email summaries by topic. Emails with multiple topics appear in each group."""
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for s in summaries:
        topics = s.get("topics", [])
        if not topics:
            groups["_uncategorized"].append(s)
        else:
            for t in topics:
                groups[t].append(s)
    return dict(groups)


def _fetch_delta_text(email_id: int) -> Optional[Dict]:
    """Fetch full email record for confirmation pass."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, date, direction, subject, delta_text, from_address
               FROM emails WHERE id = ?""",
            (email_id,),
        ).fetchone()
        if row:
            return {
                "id": row["id"],
                "date": str(row["date"])[:10],
                "direction": row["direction"],
                "subject": row["subject"],
                "delta_text": row["delta_text"][:4000],
                "from_address": row["from_address"],
            }
    return None


def run_contradiction_detection(
    provider_override: Optional[str] = None,
    batch_size: Optional[int] = None,
    since: Optional[datetime] = None,
    force: bool = False,
    limit: Optional[int] = None,
    skip_confirmation: bool = False,
    topic_filter: Optional[str] = None,
    min_severity: str = "low",
    classify_run_id: Optional[int] = None,
) -> dict:
    """
    Detect contradictions across the email corpus (two-pass).

    Pass 1: Screen summaries grouped by topic for candidate contradictions.
    Pass 2: Confirm each candidate using full delta_text (unless skip_confirmation).

    Returns: {run_id, total_summaries, candidates_found, confirmed, errors}
    """
    provider = get_provider("contradictions", override=provider_override)
    bs = batch_size or 50

    # ── Load summaries from classification ──────────────────────────────
    summaries = get_classification_summaries(
        run_id=classify_run_id,
        since=since,
        topic_filter=topic_filter,
    )
    if not summaries:
        console.print(
            "[bold red]No classification summaries found.[/bold red] "
            "Run 'python cli.py analyze classify' first, then retry."
        )
        return {"run_id": None, "total_summaries": 0, "candidates_found": 0,
                "confirmed": 0, "errors": 0}

    if limit:
        summaries = summaries[:limit]

    total_summaries = len(summaries)

    # ── Create run ──────────────────────────────────────────────────────
    screening_prompt = load_prompt("contradictions")

    run_id = create_run(
        analysis_type="contradictions",
        provider_name=provider.name,
        model_id=provider._model,
        prompt_text=screening_prompt,
        prompt_version="v1-french-legal",
        notes=f"batch_size={bs}, skip_confirm={skip_confirmation}, "
              f"topic={topic_filter}, min_severity={min_severity}",
    )

    console.print(
        f"[bold]Contradiction detection run #{run_id}[/bold] — "
        f"provider: {provider.name} / {provider._model}"
    )
    console.print(f"  {total_summaries} email summaries loaded from classification")

    # ── Pass 1: Screening by topic group ────────────────────────────────
    topic_groups = _group_by_topic(summaries)
    console.print(f"  {len(topic_groups)} topic groups to screen")

    sev_levels = {"low": 0, "medium": 1, "high": 2}
    min_sev = sev_levels.get(min_severity, 0)

    all_candidates: List[Dict] = []
    errors = 0
    total_batches = sum(
        (len(group) + bs - 1) // bs for group in topic_groups.values()
    )

    with tqdm(total=total_batches, desc="  Pass 1 — Screening", unit="batch") as pbar:
        for topic_name, group in topic_groups.items():
            for email_batch in batch(group, bs):
                batch_input = json.dumps(email_batch, ensure_ascii=False)

                try:
                    response = provider.complete_with_retry(
                        prompt=batch_input,
                        system=screening_prompt,
                        max_tokens=2048,
                    )
                    result = parse_json_response(response.content)
                    candidates = result.get("contradictions", [])

                    # Filter by min severity
                    candidates = [
                        c for c in candidates
                        if sev_levels.get(c.get("severity", "low"), 0) >= min_sev
                    ]

                    all_candidates.extend(candidates)

                except GroqDailyLimitError as e:
                    mins = int(e.retry_after_secs // 60)
                    console.print(
                        f"\n  [bold red]⛔ Groq daily token limit reached.[/bold red] "
                        f"Retry in ~{mins} min. Run #{run_id} saved as partial."
                    )
                    finish_run(run_id, status="partial", email_count=0)
                    return {
                        "run_id": run_id, "total_summaries": total_summaries,
                        "candidates_found": len(all_candidates),
                        "confirmed": 0, "errors": errors, "aborted": True,
                    }

                except Exception as e:
                    console.print(f"\n  [red]Batch error ({topic_name}): {e}[/red]")
                    errors += 1

                pbar.update(1)

    console.print(f"  Pass 1 found {len(all_candidates)} candidate contradiction(s)")

    # ── Pass 2: Confirmation ────────────────────────────────────────────
    confirmed_count = 0

    if skip_confirmation:
        # Store all candidates directly
        store_contradictions(run_id, all_candidates)
        confirmed_count = len(all_candidates)
        # Store a summary result for traceability
        store_result(
            run_id, all_candidates[0]["email_id_a"] if all_candidates else 0,
            json.dumps({"pass": "screening_only", "candidates": all_candidates}),
        )
    elif all_candidates:
        confirm_prompt = load_prompt("contradictions_confirm")

        with tqdm(total=len(all_candidates), desc="  Pass 2 — Confirming", unit="pair") as pbar:
            for candidate in all_candidates:
                email_a = _fetch_delta_text(candidate["email_id_a"])
                email_b = _fetch_delta_text(candidate["email_id_b"])

                if not email_a or not email_b:
                    errors += 1
                    pbar.update(1)
                    continue

                confirm_input = json.dumps({
                    "candidate": candidate,
                    "email_a": email_a,
                    "email_b": email_b,
                }, ensure_ascii=False)

                try:
                    response = provider.complete_with_retry(
                        prompt=confirm_input,
                        system=confirm_prompt,
                        max_tokens=800,
                    )
                    result = parse_json_response(response.content)

                    if result.get("confirmed"):
                        # Update candidate with refined data
                        confirmed_c = {
                            "email_id_a": candidate["email_id_a"],
                            "email_id_b": candidate["email_id_b"],
                            "scope": candidate.get("scope", "intra-sender"),
                            "topic": candidate.get("topic"),
                            "explanation": result.get("explanation", candidate.get("explanation", "")),
                            "severity": result.get("severity", candidate.get("severity", "medium")),
                        }
                        store_contradictions(run_id, [confirmed_c])
                        confirmed_count += 1

                    # Store full confirmation result for traceability
                    store_result(
                        run_id, candidate["email_id_a"],
                        json.dumps({
                            "pass": "confirmation",
                            "candidate": candidate,
                            "confirmation": result,
                        }),
                    )

                except GroqDailyLimitError as e:
                    mins = int(e.retry_after_secs // 60)
                    console.print(
                        f"\n  [bold red]⛔ Groq daily token limit reached.[/bold red] "
                        f"Retry in ~{mins} min. Run #{run_id} saved as partial."
                    )
                    finish_run(run_id, status="partial", email_count=confirmed_count)
                    return {
                        "run_id": run_id, "total_summaries": total_summaries,
                        "candidates_found": len(all_candidates),
                        "confirmed": confirmed_count, "errors": errors,
                        "aborted": True,
                    }

                except Exception as e:
                    console.print(f"\n  [red]Confirmation error: {e}[/red]")
                    errors += 1

                pbar.update(1)

    finish_run(
        run_id,
        status="complete" if errors == 0 else "partial",
        email_count=confirmed_count,
    )

    console.print(
        f"\n[bold green]✓ Contradiction detection complete.[/bold green] "
        f"Run #{run_id}: {len(all_candidates)} candidates, "
        f"{confirmed_count} confirmed, {errors} errors"
    )
    return {
        "run_id": run_id, "total_summaries": total_summaries,
        "candidates_found": len(all_candidates),
        "confirmed": confirmed_count, "errors": errors,
    }
