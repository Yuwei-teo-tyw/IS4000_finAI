"""Client Profiling Agent: retrieval and key-fact extraction over meeting notes (fictional seed data)."""
from .extract import extract_key_facts
from .retrieval import get_meeting_note, read_meeting_note, resolve_client
from .schemas import ClientProfile, Conflict, Fact, SourceRef, ToolResult
from .store import DocumentStore, get_default_store

__all__ = [
    "extract_key_facts", "get_meeting_note", "read_meeting_note", "resolve_client",
    "ClientProfile", "Conflict", "Fact", "SourceRef", "ToolResult", "DocumentStore", "get_default_store",
]
