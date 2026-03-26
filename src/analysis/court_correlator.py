"""
Court event correlation task.

Correlates email patterns (volume, tone, topics) around court event dates.
Primarily SQL-based; optional LLM narrative synthesis.

Uses 'court_correlation' provider from config (default: Groq).
"""
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from rich.console import Console
from tqdm import tqdm

from src.analysis.runner import (
    create_run, finish_run, load_prompt, parse_json_response, store_result,
)
from src.llm.groq_provider import GroqDailyLimitError
from src.llm.router import get_provider
from src.storage.database import get_db

console = Console()


def _get_court_events(limit: Optional[int] = None) -> List[Dict]:
    """Fetch all court events ordered by date."""
    with get_db() as conn:
        limit_clause = f"LIMIT {limit}" if limit else ""
        rows = conn.execute(
            f"""SELECT id, event_date, event_type, jurisdiction,
                       description, outcome, notes
                FROM court_events
                ORDER BY event_date ASC
                {limit_clause}"""
        ).fetchall()
        return [dict(r) for r in rows]


def _get_baseline_tone() -> Dict:
    """Corpus-wide average aggression and manipulation from tone analysis."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT
                 AVG(json_extract(ar.result_json, '$.aggression_level')) AS avg_aggression,
                 AVG(json_extract(ar.result_json, '$.manipulation_score')) AS avg_manipulation
               FROM analysis_results ar
               JOIN analysis_runs r ON r.id = ar.run_id
               WHERE r.analysis_type = 'tone'
                 AND r.status IN ('complete', 'partial')"""
        ).fetchone()
        return {
            "avg_aggression": round(row["avg_aggression"] or 0.0, 3),
            "avg_manipulation": round(row["avg_manipulation"] or 0.0, 3),
        }


def _get_window_stats(date_start: str, date_end: str) -> Dict:
    """Email volume and tone stats for a date window."""
    with get_db() as conn:
        # Volume by direction
        rows = conn.execute(
            """SELECT e.direction, COUNT(*) AS cnt
               FROM emails e
               WHERE e.date BETWEEN ? AND ?
               GROUP BY e.direction""",
            (date_start, date_end),
        ).fetchall()

        sent = received = 0
        for r in rows:
            if r["direction"] == "sent":
                sent = r["cnt"]
            elif r["direction"] == "received":
                received = r["cnt"]

        # Tone averages
        tone_row = conn.execute(
            """SELECT
                 AVG(json_extract(ar.result_json, '$.aggression_level')) AS avg_aggression,
                 AVG(json_extract(ar.result_json, '$.manipulation_score')) AS avg_manipulation
               FROM analysis_results ar
               JOIN analysis_runs r ON r.id = ar.run_id
               JOIN emails e ON e.id = ar.email_id
               WHERE r.analysis_type = 'tone'
                 AND e.date BETWEEN ? AND ?""",
            (date_start, date_end),
        ).fetchone()

        # Topic distribution
        topic_rows = conn.execute(
            """SELECT t.name, COUNT(*) AS cnt
               FROM email_topics et
               JOIN topics t ON t.id = et.topic_id
               JOIN emails e ON e.id = et.email_id
               WHERE e.date BETWEEN ? AND ?
               GROUP BY t.name ORDER BY cnt DESC""",
            (date_start, date_end),
        ).fetchall()

        return {
            "count": sent + received,
            "sent": sent,
            "received": received,
            "avg_aggression": round(tone_row["avg_aggression"] or 0.0, 3),
            "avg_manipulation": round(tone_row["avg_manipulation"] or 0.0, 3),
            "topics": {r["name"]: r["cnt"] for r in topic_rows},
        }


def _get_notable_emails(date_start: str, date_end: str, max_count: int = 5) -> List[Dict]:
    """Fetch the most aggressive emails in a date window (for LLM narrative)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT e.id, e.date, e.direction, e.subject,
                      SUBSTR(e.delta_text, 1, 500) AS delta_text,
                      json_extract(ar.result_json, '$.aggression_level') AS aggression
               FROM emails e
               LEFT JOIN analysis_results ar ON ar.email_id = e.id
               LEFT JOIN analysis_runs r ON r.id = ar.run_id AND r.analysis_type = 'tone'
               WHERE e.date BETWEEN ? AND ?
               ORDER BY aggression DESC NULLS LAST, e.date ASC
               LIMIT ?""",
            (date_start, date_end, max_count),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "date": str(r["date"])[:10],
                "direction": r["direction"],
                "subject": r["subject"],
                "delta_text": r["delta_text"],
            }
            for r in rows
        ]


def get_court_event_correlation(event_id: int, window_days: int = 14) -> Optional[Dict]:
    """
    Pure SQL correlation for a single court event.
    Returns structured stats or None if event not found.
    """
    with get_db() as conn:
        ev_row = conn.execute(
            "SELECT * FROM court_events WHERE id = ?", (event_id,)
        ).fetchone()
        if not ev_row:
            return None

    event_date = datetime.fromisoformat(str(ev_row["event_date"])[:10])
    before_start = (event_date - timedelta(days=window_days)).isoformat()[:10]
    before_end = event_date.isoformat()[:10]
    after_start = event_date.isoformat()[:10]
    after_end = (event_date + timedelta(days=window_days)).isoformat()[:10]

    before = _get_window_stats(before_start, before_end)
    after = _get_window_stats(after_start, after_end)
    baseline = _get_baseline_tone()

    # Compute deltas
    delta = {}
    if before["count"] > 0:
        delta["volume_change_pct"] = round(
            ((after["count"] - before["count"]) / before["count"]) * 100, 1
        )
    else:
        delta["volume_change_pct"] = None
    delta["aggression_change"] = round(
        after["avg_aggression"] - before["avg_aggression"], 3
    )
    delta["manipulation_change"] = round(
        after["avg_manipulation"] - before["avg_manipulation"], 3
    )

    return {
        "event": {
            "id": ev_row["id"],
            "date": str(ev_row["event_date"])[:10],
            "type": ev_row["event_type"],
            "jurisdiction": ev_row["jurisdiction"],
            "description": ev_row["description"],
            "outcome": ev_row["outcome"] or "",
        },
        "window_days": window_days,
        "before": before,
        "after": after,
        "baseline": baseline,
        "delta": delta,
    }


def run_court_correlation(
    provider_override: Optional[str] = None,
    window_days: int = 14,
    include_narrative: bool = False,
    limit: Optional[int] = None,
) -> dict:
    """
    Correlate email patterns around court event dates.

    Returns: {court_events_processed, correlations, errors}
    """
    court_events = _get_court_events(limit=limit)

    if not court_events:
        console.print(
            "[bold red]No court events found.[/bold red] "
            "Use 'python cli.py events add' or 'events import' first."
        )
        return {"court_events_processed": 0, "correlations": [], "errors": 0}

    run_id = None
    if include_narrative:
        provider = get_provider("court_correlation", override=provider_override)
        narrative_prompt = load_prompt("court_correlation")
        run_id = create_run(
            analysis_type="court_correlation",
            provider_name=provider.name,
            model_id=provider._model,
            prompt_text=narrative_prompt,
            prompt_version="v1-french-legal",
            notes=f"window_days={window_days}",
        )
        console.print(
            f"[bold]Court correlation run #{run_id}[/bold] — "
            f"provider: {provider.name} / {provider._model}"
        )

    console.print(
        f"  {len(court_events)} court events to correlate "
        f"(window: ±{window_days} days)"
    )

    correlations = []
    errors = 0

    with tqdm(total=len(court_events), desc="  Correlating", unit="event") as pbar:
        for ce in court_events:
            correlation = get_court_event_correlation(ce["id"], window_days)
            if not correlation:
                errors += 1
                pbar.update(1)
                continue

            # Optional LLM narrative
            if include_narrative and run_id:
                event_date = datetime.fromisoformat(str(ce["event_date"])[:10])
                window_start = (event_date - timedelta(days=window_days)).isoformat()[:10]
                window_end = (event_date + timedelta(days=window_days)).isoformat()[:10]
                notable = _get_notable_emails(window_start, window_end)

                narrative_input = json.dumps({
                    "court_event": correlation["event"],
                    "stats": {
                        "before": {k: v for k, v in correlation["before"].items() if k != "topics"},
                        "after": {k: v for k, v in correlation["after"].items() if k != "topics"},
                        "baseline": correlation["baseline"],
                        "topics_before": correlation["before"]["topics"],
                        "topics_after": correlation["after"]["topics"],
                    },
                    "notable_emails": notable,
                }, ensure_ascii=False)

                try:
                    response = provider.complete_with_retry(
                        prompt=narrative_input,
                        system=narrative_prompt,
                        max_tokens=1000,
                    )
                    narrative_result = parse_json_response(response.content)
                    correlation["narrative"] = narrative_result

                    # Find the most relevant email in the window for storage
                    if notable:
                        store_result(
                            run_id, notable[0]["id"],
                            json.dumps({
                                "court_event_id": ce["id"],
                                "correlation": correlation,
                            }),
                        )

                except GroqDailyLimitError as e:
                    mins = int(e.retry_after_secs // 60)
                    console.print(
                        f"\n  [bold red]⛔ Groq daily token limit reached.[/bold red] "
                        f"Retry in ~{mins} min."
                    )
                    if run_id:
                        finish_run(run_id, status="partial",
                                   email_count=len(correlations))
                    return {
                        "run_id": run_id,
                        "court_events_processed": len(correlations),
                        "correlations": correlations, "errors": errors,
                        "aborted": True,
                    }

                except Exception as e:
                    console.print(f"\n  [red]Narrative error: {e}[/red]")
                    errors += 1

            correlations.append(correlation)
            pbar.update(1)

    if run_id:
        finish_run(run_id, status="complete" if errors == 0 else "partial",
                   email_count=len(correlations))

    console.print(
        f"\n[bold green]✓ Court correlation complete.[/bold green] "
        f"{len(correlations)} events correlated, {errors} errors"
    )
    return {
        "run_id": run_id,
        "court_events_processed": len(correlations),
        "correlations": correlations,
        "errors": errors,
    }
