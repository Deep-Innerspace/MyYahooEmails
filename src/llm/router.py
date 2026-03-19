"""
Provider router — returns the right LLMProvider instance for a given task.

Reads config.yaml llm.task_providers to select provider per task type.
Provider instances are cached (one instance per provider name).
"""
from typing import Dict, Optional

from src.config import llm_provider_for, llm_provider_settings
from src.llm.base import LLMProvider

_cache: Dict[str, LLMProvider] = {}


def get_provider(task: str, override: Optional[str] = None) -> LLMProvider:
    """
    Return the configured LLMProvider for a task type.

    Args:
        task: One of 'classify', 'tone', 'timeline', 'contradictions', 'manipulation', 'reply_draft'
        override: If set, use this provider name instead of the config default.
    """
    provider_name = override or llm_provider_for(task)

    if provider_name in _cache:
        return _cache[provider_name]

    settings = llm_provider_settings(provider_name)
    model = settings.get("model", _default_model(provider_name))

    provider = _create_provider(provider_name, model, settings)
    _cache[provider_name] = provider
    return provider


def _create_provider(name: str, model: str, settings: dict) -> LLMProvider:
    if name == "claude":
        from src.llm.claude_provider import ClaudeProvider
        return ClaudeProvider(model=model)

    elif name == "groq":
        from src.llm.groq_provider import GroqProvider
        return GroqProvider(model=model)

    elif name == "openai":
        from src.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)

    elif name == "ollama":
        from src.llm.ollama_provider import OllamaProvider
        base_url = settings.get("base_url", "http://localhost:11434")
        return OllamaProvider(model=model, base_url=base_url)

    else:
        raise ValueError(
            f"Unknown LLM provider '{name}'. "
            f"Valid options: claude, groq, openai, ollama"
        )


def _default_model(provider_name: str) -> str:
    defaults = {
        "claude": "claude-sonnet-4-6",
        "groq": "llama-3.3-70b-versatile",
        "openai": "gpt-4o-mini",
        "ollama": "mistral",
    }
    return defaults.get(provider_name, "unknown")
