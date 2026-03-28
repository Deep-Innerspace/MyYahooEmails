#!/usr/bin/env python3
"""Groq rate-limit status checker.

Makes a minimal API call and reads the x-ratelimit-* headers that Groq
returns on EVERY response (not just 429s).  Useful to know at a glance
how much quota is left before starting or resuming a long analysis run.

Usage:
    .venv/bin/python tools/groq_rate_check.py
    .venv/bin/python tools/groq_rate_check.py --model llama-3.3-70b-versatile
    .venv/bin/python tools/groq_rate_check.py --verbose   # also prints raw headers

Rate-limit headers returned by Groq on every response
──────────────────────────────────────────────────────
  x-ratelimit-limit-requests      RPD cap  (requests / day)
  x-ratelimit-limit-tokens        TPM cap  (tokens   / minute)
  x-ratelimit-remaining-requests  Requests still available this day
  x-ratelimit-remaining-tokens    Tokens   still available this minute
  x-ratelimit-reset-requests      Countdown to RPD reset (e.g. "23h59m")
  x-ratelimit-reset-tokens        Countdown to TPM reset (e.g. "5s")

On 429 responses Groq additionally sends:
  retry-after                     Seconds to wait before retrying
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

# ── make sure project root is on sys.path ────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from groq import Groq, RateLimitError


# ── tiny probe prompt (absolute minimum tokens) ───────────────────────────────
_PROBE_PROMPT = "Reply with the single word: OK"
_PROBE_MODEL  = "llama-3.3-70b-versatile"


def _fmt_header(val: Optional[str], label: str) -> str:
    return val if val is not None else f"<{label} header missing>"


def check_rate_limits(model: str = _PROBE_MODEL, verbose: bool = False) -> dict:
    """
    Make a minimal API call and return a dict with rate-limit header values.

    Keys:
        limit_requests, limit_tokens,
        remaining_requests, remaining_tokens,
        reset_requests, reset_tokens,
        status  ("ok" | "rate_limited"),
        retry_after  (seconds, only when status == "rate_limited"),
        error_body   (raw error message, only on 429)
    """
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        print("ERROR: GROQ_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    client = Groq(api_key=api_key)

    try:
        # with_raw_response gives us the httpx Response so we can read headers
        raw = client.with_raw_response.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": _PROBE_PROMPT}],
            max_tokens=5,
            temperature=0.0,
        )
        headers = dict(raw.headers)

        if verbose:
            print("\n── Raw response headers ─────────────────────────────")
            for k, v in sorted(headers.items()):
                if "ratelimit" in k.lower() or k.lower() in ("retry-after", "x-groq-id"):
                    print(f"  {k}: {v}")
            print()

        result = {
            "status":             "ok",
            "limit_requests":     headers.get("x-ratelimit-limit-requests"),
            "limit_tokens":       headers.get("x-ratelimit-limit-tokens"),
            "remaining_requests": headers.get("x-ratelimit-remaining-requests"),
            "remaining_tokens":   headers.get("x-ratelimit-remaining-tokens"),
            "reset_requests":     headers.get("x-ratelimit-reset-requests"),
            "reset_tokens":       headers.get("x-ratelimit-reset-tokens"),
        }

        # Parse the probe response just to confirm content
        parsed = raw.parse()
        result["probe_reply"] = (
            parsed.choices[0].message.content.strip()
            if parsed.choices else ""
        )
        result["usage"] = {
            "prompt_tokens":     parsed.usage.prompt_tokens     if parsed.usage else 0,
            "completion_tokens": parsed.usage.completion_tokens if parsed.usage else 0,
        }
        return result

    except RateLimitError as exc:
        # Even on 429, Groq returns rate-limit headers
        headers: dict = {}
        retry_after: Optional[float] = None
        error_body = str(exc)

        try:
            headers = dict(exc.response.headers)
            ra = (headers.get("retry-after") or headers.get("Retry-After"))
            retry_after = float(ra) if ra else None
        except Exception:
            pass

        if verbose:
            print("\n── 429 response headers ─────────────────────────────")
            for k, v in sorted(headers.items()):
                if "ratelimit" in k.lower() or k.lower() in ("retry-after",):
                    print(f"  {k}: {v}")
            print()

        return {
            "status":             "rate_limited",
            "limit_requests":     headers.get("x-ratelimit-limit-requests"),
            "limit_tokens":       headers.get("x-ratelimit-limit-tokens"),
            "remaining_requests": headers.get("x-ratelimit-remaining-requests"),
            "remaining_tokens":   headers.get("x-ratelimit-remaining-tokens"),
            "reset_requests":     headers.get("x-ratelimit-reset-requests"),
            "reset_tokens":       headers.get("x-ratelimit-reset-tokens"),
            "retry_after":        retry_after,
            "error_body":         error_body,
        }


def _bar(remaining: Optional[str], limit: Optional[str], width: int = 30) -> str:
    """Simple ASCII progress bar showing remaining/limit."""
    try:
        r = int(remaining or 0)
        l = int(limit or 1)
        filled = int(width * r / l)
        pct = int(100 * r / l)
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {pct:3d}%  ({r:,} / {l:,})"
    except Exception:
        return "(no data)"


def print_report(info: dict, model: str) -> None:
    status_icon = "✅" if info["status"] == "ok" else "🚫"
    print(f"\n{'─'*56}")
    print(f"  Groq rate-limit status  •  model: {model}")
    print(f"{'─'*56}")
    print(f"  Status : {status_icon}  {info['status'].upper()}")

    if info["status"] == "ok":
        print(f"  Probe  : \"{info.get('probe_reply', '')}\"  "
              f"(used {info['usage']['prompt_tokens']}+{info['usage']['completion_tokens']} tokens)")

    print()
    print(f"  Tokens / minute (TPM)")
    print(f"    Remaining : {_bar(info['remaining_tokens'], info['limit_tokens'])}")
    print(f"    Resets in : {_fmt_header(info['reset_tokens'], 'reset_tokens')}")
    print()
    print(f"  Requests / day (RPD)")
    print(f"    Remaining : {_bar(info['remaining_requests'], info['limit_requests'])}")
    print(f"    Resets in : {_fmt_header(info['reset_requests'], 'reset_requests')}")

    if info["status"] == "rate_limited":
        ra = info.get("retry_after")
        if ra is not None:
            mins, secs = divmod(int(ra), 60)
            hours, mins = divmod(mins, 60)
            wait_str = (
                f"{hours}h {mins}m {secs}s" if hours
                else f"{mins}m {secs}s" if mins
                else f"{secs}s"
            )
            print(f"\n  ⏳ Retry-After : {wait_str}")
            if ra > 300:
                print(f"  ⚠️  This looks like a DAILY limit (TPD) — wait {wait_str} before resuming.")
            else:
                print(f"  ℹ️  Per-minute limit (TPM) — short wait, can retry soon.")
        print(f"\n  Error : {info.get('error_body', '')[:200]}")

    print(f"{'─'*56}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Groq API rate-limit status")
    parser.add_argument("--model",   default=_PROBE_MODEL, help="Groq model to probe")
    parser.add_argument("--verbose", action="store_true",  help="Print raw headers")
    args = parser.parse_args()

    print(f"Probing Groq API with model: {args.model} …", end=" ", flush=True)
    info = check_rate_limits(model=args.model, verbose=args.verbose)
    print("done.")

    print_report(info, args.model)

    # Exit code: 0 = ok, 1 = rate limited (useful for scripting)
    sys.exit(0 if info["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
