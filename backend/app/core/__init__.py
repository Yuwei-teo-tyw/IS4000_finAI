import os
from langchain_groq import ChatGroq
from app.core.constants import CURRENT_MODEL

_llm: ChatGroq | None = None


def get_groq_model() -> ChatGroq:
    """
    Return a shared ChatGroq instance (a real LangChain chat model, so it
    supports .bind_tools(), .with_structured_output(), streaming, etc. -
    unlike the old hand-rolled SimpleLLM wrapper).
    """
    global _llm
    if _llm is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not found in environment variables")

        _llm = ChatGroq(
            model=CURRENT_MODEL,
            api_key=api_key,
            temperature=0.1,
            max_tokens=1024,
        )
    return _llm
