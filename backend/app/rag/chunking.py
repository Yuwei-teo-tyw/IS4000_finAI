"""
Document chunking for RAG ingestion - PLACEHOLDER.

Splits raw document text into overlapping chunks ahead of embedding, via
LangChain's `RecursiveCharacterTextSplitter` left at its library defaults
(chunk_size=4000, chunk_overlap=200) rather than picking custom numbers -
tune these once real source documents and a target embedding model's
context window are decided.

No ingestion pipeline, vector store write-path, or retrieval/search exists
yet - this only turns text into chunks. See `embeddings.py` for the next
step (turning chunks into vectors).
"""
from typing import List
from langchain_text_splitters import RecursiveCharacterTextSplitter

_splitter = RecursiveCharacterTextSplitter()


def chunk_text(text: str) -> List[str]:
    """
    Split raw document text into overlapping chunks ready for embedding.

    PLACEHOLDER: uses RecursiveCharacterTextSplitter's library defaults
    (chunk_size=4000, chunk_overlap=200) - not yet tuned to a specific
    document type or embedding model.

    Args:
        text: raw document text to split.

    Returns:
        Chunk strings, in order. Empty list for empty input.
    """
    if not text:
        return []
    return _splitter.split_text(text)
