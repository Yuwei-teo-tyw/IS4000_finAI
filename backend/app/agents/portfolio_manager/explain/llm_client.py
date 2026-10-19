"""
LLM client factory for narrative generation. Configuration comes only from
environment variables (see config.py); the Groq SDK is imported lazily so
the service runs - deterministically - without it.
"""
from app.agents.portfolio_manager.config import Settings


class LLMUnavailable(RuntimeError):
    """Raised when the LLM is disabled or not configured; triggers fallback."""


_cache: dict = {}


def get_llm(settings: Settings):
    if not settings.llm_enabled:
        raise LLMUnavailable("LLM explanations disabled via PORTFOLIO_LLM_ENABLED.")
    api_key = settings.groq_api_key
    if not api_key:
        raise LLMUnavailable("GROQ_API_KEY is not set.")
    key = (settings.llm_model, settings.llm_max_tokens, hash(api_key))
    if key not in _cache:
        try:
            from langchain_groq import ChatGroq
        except ImportError as e:  # pragma: no cover - depends on environment
            raise LLMUnavailable("langchain-groq is not installed.") from e
        _cache[key] = ChatGroq(
            model=settings.llm_model,
            api_key=api_key,
            temperature=0.1,
            max_tokens=settings.llm_max_tokens,
        )
    return _cache[key]
