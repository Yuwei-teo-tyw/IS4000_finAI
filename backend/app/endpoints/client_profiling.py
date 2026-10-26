"""
HTTP interface for the Client Profiling Agent.

    POST /agents/client-profiling/chat   run one profiling tool for the client in the query/context

Read-only: never updates IPS documents, client records or allocations. Validation errors do not echo
submitted values (client data).
"""
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator

from app.agents.client_profiling.ips_assist import ips_assist
from app.agents.client_profiling.schemas import SourceRef, ToolResult
from app.agents.client_profiling.ingest import IngestError, ingest_note
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import StoreUnavailableError, get_default_store

PREFIX = "/agents/client-profiling"


# --- store availability guard (applies to every route on this router) ---
class _StoreGuardRoute(APIRoute):
    """Postgres down -> clean JSON, never a silent JSON-file fallback. /chat keeps HTTP 200 with a
    routing_unavailable ToolResult so the frontend falls through; every other route returns 503."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except StoreUnavailableError as e:
                if request.url.path == f"{PREFIX}/chat":
                    return JSONResponse({
                        "status": "insufficient_information", "tool": "routing_unavailable",
                        "message": "The client database (Postgres) is unavailable.",
                        "data": {"routing": {"method": "unavailable"}}})
                detail = "The client database is unavailable." if request.url.path == f"{PREFIX}/book" else str(e)
                return JSONResponse({"detail": detail}, status_code=503)

        return handler


router = APIRouter(prefix=PREFIX, tags=["client-profiling"], route_class=_StoreGuardRoute)


def _require_in_book(store, client_id: str) -> None:
    """The client must be in the (single) RM's book, read server-side from the DB; else 403."""
    if client_id not in store.book_ids():
        raise HTTPException(status_code=403, detail="Client is not in your book")


@router.get("/book")
async def get_book() -> dict:
    """The RM's book from the DB (cp_clients.in_book) with onboarding (0-5) and monitoring (0-100) progress."""
    clients = [{"id": c.id, "name": c.name, "surname": c.surname, "risk_category": c.risk_category,
                "aum_sgd": c.aum_sgd, "status": c.status, "onboarding_progress": c.onboarding_progress,
                "monitoring_progress": c.monitoring_progress} for c in get_default_store().list_book()]
    out: dict = {"clients": clients}
    if not clients:
        out["message"] = "No clients in your book"
    return out


class ProfilingChatRequest(BaseModel):
    message: str = Field(default="", max_length=5000)  # empty / over-1000 handled by the service with a friendly answer
    client_id: Optional[str] = Field(default=None, max_length=40)
    book: Optional[list[Annotated[str, Field(max_length=40)]]] = Field(default=None, max_length=200)
    # Deprecated and IGNORED: the server always applies the DB book. Still accepted so old callers do not get a 422.
    source: Optional[Literal["notes", "ips", "both"]] = None  # explicit source choice (answers a "which source?" clarification)


@router.post("/chat", response_model=ToolResult)
async def chat(body: ProfilingChatRequest) -> ToolResult:
    book = get_default_store().book_ids()  # StoreUnavailableError -> guard; client-supplied `book` is ignored
    return handle_chat(body.message, body.client_id, book=book, source=body.source)


class IpsAssistRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=40)
    section: str = Field(default="", max_length=80)  # '' = general request about the IPS
    selection: str = Field(default="", max_length=4000)
    mode: Literal["auto", "professionalize", "write", "retrieve"] = "auto"
    current_text: str = Field(default="", max_length=6000)
    message: str = Field(default="", max_length=500)


class IpsAssistResponse(BaseModel):
    status: Literal["ok", "insufficient_information", "unavailable", "out_of_scope"]
    message: str
    original: str
    revised: str
    kind: Literal["rewrite", "retrieve", "none"] = "none"
    target: Literal["selection", "section", "document"] = "section"
    notes: list[str] = Field(default_factory=list, max_length=3)
    sources: list[SourceRef] = Field(default_factory=list)


@router.post("/ips-assist", response_model=IpsAssistResponse)
async def ips_assist_endpoint(body: IpsAssistRequest) -> IpsAssistResponse:
    """Draft or professionalise one IPS section for the edit page. Read-only suggestion; nothing is saved."""
    store = get_default_store()
    if store.get_client(body.client_id) is None:
        raise HTTPException(status_code=404, detail="Unknown client")
    _require_in_book(store, body.client_id)
    return IpsAssistResponse(**ips_assist(store, body.client_id, body.section, body.mode, body.current_text, body.message,
                                    selection=body.selection))


def _client_name(store, client_id: str) -> str:
    c = store.get_client(client_id)
    return (getattr(c, "name", "") or "").strip() or client_id


def _note_json(n) -> dict:
    return {"id": n.id, "clientId": n.client_id, "clientName": _client_name(get_default_store(), n.client_id), "date": n.date, "title": n.title, "sourceFile": n.source_file,
            "originalText": n.text, "summary": [s.strip() for s in n.text.replace("\n", " ").split(". ")[:3] if s.strip()], "checklist": []}


def _indexing(store, note) -> dict:
    """Indexing report for a saved note; the note is saved either way (pending = not yet searchable, retried lazily)."""
    info = store.note_indexing(note.client_id, note.id)
    n = info.get("chunks")
    if info["status"] == "indexed":
        msg = f"Indexed: {n} chunk{'s' if n != 1 else ''}" if n is not None else "Saved and searchable"
    else:
        msg = "Note saved, but not yet searchable"
    return {"status": info["status"], "chunks": n, "message": msg}


@router.post("/meeting-notes")
async def upload_meeting_note(client_id: str = Form(...), file: UploadFile = File(...)) -> dict:
    """Ingest an uploaded PDF/TXT into the meeting-notes database for one client (the agent reads it immediately)."""
    store = get_default_store()
    _require_in_book(store, client_id)
    data = await file.read()
    try:
        note = ingest_note(store, client_id, file.filename or "upload", data)
        return {**_note_json(note), "indexing": _indexing(store, note)}
    except IngestError as e:
        raise HTTPException(status_code=e.status, detail=str(e))


@router.get("/meeting-notes/{client_id}")
async def list_meeting_notes(client_id: str) -> list[dict]:
    """The client's meeting notes in the frontend MeetingNote shape (one client only)."""
    store = get_default_store()
    _require_in_book(store, client_id)
    return [_note_json(n) for n in store.get_notes(client_id)]


class NoteEditRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    original_text: str = Field(min_length=1, max_length=20000)

    @field_validator("title", "original_text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


@router.put("/meeting-notes/{client_id}/{note_id}")
async def update_meeting_note(client_id: str, note_id: str, body: NoteEditRequest) -> dict:
    """Edit a note's title and text; 404 unless the note belongs to that client."""
    store = get_default_store()
    _require_in_book(store, client_id)
    note = store.update_note(client_id, note_id, title=body.title, text=body.original_text)
    if note is None:
        raise HTTPException(status_code=404, detail="Meeting note not found for this client")
    return {**_note_json(note), "indexing": _indexing(store, note)}


# --- IPS read API (Postgres/JSON store is the source of truth; no writes here) ---
def _ips_json(v) -> dict:
    return {"version": v.version, "issuedOn": v.issued_on, "status": v.status, "author": v.author, "summary": v.summary,
            "parts": [{"part": p.part, "title": p.title, "owner": p.owner, "status": p.status, "body": p.body}
                      for p in sorted(v.parts, key=lambda p: p.part)]}


@router.get("/ips/{client_id}")
async def get_client_ips(client_id: str) -> dict:
    """The client's IPS versions (newest first) in the frontend IpsVersion shape; 404 for an unknown client."""
    store = get_default_store()
    if store.get_client(client_id) is None:
        raise HTTPException(status_code=404, detail="Unknown client")
    versions = store.get_ips_versions(client_id)
    current = next((v.version for v in versions if v.status == "Active"), None)
    return {"client_id": client_id, "client_name": _client_name(store, client_id), "current_version": current, "versions": [_ips_json(v) for v in versions]}


# --- IPS write API: save, then index the current version so it is searchable immediately (US-17) ---
class IpsPartIn(BaseModel):
    part: int = Field(ge=1, le=20)
    title: str = Field(max_length=200)
    owner: str = Field(default="", max_length=80)
    status: str = Field(default="", max_length=40)
    body: str = Field(default="", max_length=20000)


class IpsSaveRequest(BaseModel):
    version: Optional[int] = Field(default=None, ge=1)  # None = create the next version; set = edit that version in place
    parts: list[IpsPartIn] = Field(min_length=1, max_length=20)
    summary: Optional[str] = Field(default=None, max_length=1000)
    author: Optional[str] = Field(default=None, max_length=80)
    status: Literal["Active", "Draft"] = "Active"  # only used when creating a new version


def _index_after_save(store, client_id: str, saved_version: int) -> dict:
    """Index the client's current IPS; older versions' chunks are removed. Never raises: failure -> status pending."""
    current = store.latest_ips(client_id)[0]
    current_v = current.version if current else None
    store.drop_stale_ips_chunks(client_id, current_v)
    ok = bool(current_v == saved_version and store.index_ips(client_id, saved_version))
    if ok:
        return {"status": "indexed", "chunks": store.count_ips_chunks(client_id, saved_version),
                "message": f"IPS v{saved_version} indexed"}
    return {"status": "pending", "chunks": 0, "message": "IPS saved, but not yet searchable"}


@router.post("/ips/{client_id}")
async def save_client_ips(client_id: str, body: IpsSaveRequest) -> dict:
    """Save an IPS (new version, or edit of an existing one) and index it. 403 if the client is not in the book."""
    store = get_default_store()
    _require_in_book(store, client_id)
    from app.agents.client_profiling.store import IpsPartDoc
    parts = [IpsPartDoc(**p.model_dump()) for p in body.parts]
    saved = store.save_ips(client_id, parts, version=body.version, summary=body.summary, author=body.author, status=body.status)
    if saved is None:
        raise HTTPException(status_code=404, detail="IPS version not found for this client")
    return {"client_id": client_id, "ips": _ips_json(saved), "indexing": _index_after_save(store, client_id, saved.version)}
