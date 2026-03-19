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
