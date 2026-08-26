"""
Embedding model for RAG - PLACEHOLDER.

Wraps OpenAI's embeddings API via LangChain (`OpenAIEmbeddings`), left at
its library default model ("text-embedding-ada-002") rather than picking
one - revisit once real ingestion volume/cost and a retrieval quality bar
are known.

Mirrors `app/core/__init__.py`'s `get_groq_model()` pattern (shared
singleton, lazy-constructed, raises if the API key is missing) for the
same reason: cheap to call repeatedly without reconstructing a client
each time.

PLACEHOLDER: this only calls the embeddings API and returns vectors -
nothing here persists them (no pgvector table/vector store wired up yet)
and there's no retrieval/search on top of this.
"""
import os
from typing import List, Optional
from langchain_openai import OpenAIEmbeddings

_embeddings: Optional[OpenAIEmbeddings] = None


def get_embeddings_model() -> OpenAIEmbeddings:
    """Return a shared OpenAIEmbeddings instance (library default model)."""
    global _embeddings
    if _embeddings is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        _embeddings = OpenAIEmbeddings(api_key=api_key)
    return _embeddings


def embed_chunks(chunks: List[str]) -> List[List[float]]:
    """
    Embed a list of text chunks (e.g. from `chunking.chunk_text()`).

    PLACEHOLDER: returns raw embedding vectors - nothing persists them to
    a vector store yet, and there's no retrieval/search on top of this.

    Args:
        chunks: chunk strings to embed, in order.

    Returns:
        One embedding vector per input chunk, same order. Empty list for
        empty input.
    """
    if not chunks:
        return []
    return get_embeddings_model().embed_documents(chunks)
