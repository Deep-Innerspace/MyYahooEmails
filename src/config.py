"""Load configuration from config.yaml and .env."""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
_ENV_PATH = _ROOT / ".env"
_CONFIG_PATH = _ROOT / "config.yaml"

load_dotenv(_ENV_PATH)


def _load_yaml() -> Dict[str, Any]:
    if not _CONFIG_PATH.exists():
        example = _ROOT / "config.yaml.example"
        raise FileNotFoundError(
            f"config.yaml not found. Copy {example} to config.yaml and fill in your values."
        )
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_cfg: Optional[Dict[str, Any]] = None


def cfg() -> Dict[str, Any]:
    global _cfg
    if _cfg is None:
        _cfg = _load_yaml()
    return _cfg


# --- Convenience accessors ---

def imap_server() -> str:
    return cfg()["imap"]["server"]

def imap_port() -> int:
    return int(cfg()["imap"].get("port", 993))

def imap_ssl() -> bool:
    return bool(cfg()["imap"].get("ssl", True))

def yahoo_email() -> str:
    v = os.getenv("YAHOO_EMAIL", "")
    if not v:
        raise EnvironmentError("YAHOO_EMAIL not set in .env")
    return v

def yahoo_password() -> str:
    v = os.getenv("YAHOO_APP_PASSWORD", "")
    if not v:
        raise EnvironmentError("YAHOO_APP_PASSWORD not set in .env")
    return v

def db_path() -> Path:
    p = cfg().get("database", {}).get("path", "data/emails.db")
    path = _ROOT / p
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def contacts() -> List[Dict[str, str]]:
    return cfg().get("contacts", [])

def topics() -> List[Dict[str, str]]:
    return cfg().get("topics", [])

def llm_provider_for(task: str) -> str:
    """Return configured LLM provider name for a given task type."""
    task_providers = cfg().get("llm", {}).get("task_providers", {})
    return task_providers.get(task, cfg().get("llm", {}).get("default_provider", "groq"))

def llm_provider_settings(provider: str) -> Dict[str, Any]:
    return cfg().get("llm", {}).get("providers", {}).get(provider, {})

def analysis_batch_size() -> int:
    return int(cfg().get("analysis", {}).get("batch_size", 20))

def analysis_skip_if_done() -> bool:
    return bool(cfg().get("analysis", {}).get("skip_if_analyzed", True))

def contradiction_batch_size() -> int:
    """Summaries per LLM call in contradiction detection Pass 1."""
    return int(cfg().get("analysis", {}).get("contradiction_batch_size", 50))

def court_correlation_window() -> int:
    """Default days before/after court events to examine."""
    return int(cfg().get("analysis", {}).get("court_correlation_window", 14))

def attachment_download_dir() -> Path:
    """Directory for on-demand downloaded attachments."""
    path = _ROOT / "data" / "attachments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lawyer_contacts() -> List[Dict[str, Any]]:
    """Return contacts with role in ('my_lawyer', 'her_lawyer')."""
    return [c for c in contacts() if c.get("role") in ("my_lawyer", "her_lawyer")]


def report_output_dir() -> Path:
    """Default output directory for generated reports."""
    p = cfg().get("reports", {}).get("output_dir", "data/exports")
    path = _ROOT / p
    path.mkdir(parents=True, exist_ok=True)
    return path

def _groq_cfg() -> Dict[str, Any]:
    return cfg().get("llm", {}).get("providers", {}).get("groq", {})

def groq_token_rate_limit() -> int:
    """Max tokens/min (TPM) — proactive token-bucket ceiling."""
    return int(_groq_cfg().get("rate_limit_tokens_per_min", 10000))

def groq_daily_token_limit() -> int:
    """Max tokens/day (TPD) — used to detect daily-limit 429s."""
    return int(_groq_cfg().get("rate_limit_tokens_per_day", 100000))

def groq_request_rate_limit() -> int:
    """Max requests/min (RPM) — informational, rarely the binding constraint."""
    return int(_groq_cfg().get("rate_limit_requests_per_min", 30))

def groq_daily_limit_threshold_secs() -> int:
    """Retry-After seconds above which a 429 is treated as a daily-limit hit."""
    return int(_groq_cfg().get("daily_limit_threshold_secs", 300))
