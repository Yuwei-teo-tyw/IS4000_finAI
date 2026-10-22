"""
LLM client factory for narrative generation. Configuration comes only from
environment variables (see config.py); the Groq SDK is imported lazily so
the service runs - deterministically - without it.
"""
from typing import Protocol


class LLMSettings(Protocol):
    """The fields get_llm reads. The PM's and the Product Recommender's Settings both have them."""
    llm_enabled: bool
    llm_model: str
    llm_max_tokens: int

    @property
    def groq_api_key(self) -> str | None: ...


class LLMUnavailable(RuntimeError):
    """Raised when the LLM is disabled or not configured; triggers fallback."""


_cache: dict = {}


def get_llm(settings: LLMSettings):
    if not settings.llm_enabled:
        raise LLMUnavailable("LLM explanations are disabled by configuration.")
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
