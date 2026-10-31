"""Document stores for the Client Profiling Agent.

Two backends share one interface (BaseStore): the Postgres store (default, see store_pg.py) and a
JSON-file store for offline tests / no-DB dev (CLIENT_PROFILING_STORE=json). Both are seeded from the
FICTIONAL JSON in data/. Every accessor is keyed by client_id and never returns another client's documents.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

DEFAULT_DATA_DIR = Path(__file__).parent / "data"
UPLOADS_FILE = "uploaded_meeting_notes.json"
UPLOAD_ID_PREFIX = "note_up_"
SENT_STATUS = "Sent to PM"


class Client(BaseModel):
    id: str
    name: str
    surname: str = ""
    risk_category: Optional[str] = None
    risk_cap: Optional[int] = None
    gender: Optional[str] = None  # recorded gender ("female"/"male"); never inferred from the name
    aum_sgd: Optional[float] = None
    status: Optional[str] = None
    in_book: bool = False
    onboarding_progress: int = 0  # steps done of 5
    monitoring_progress: int = 0  # review-pack percent, 0..100


class IpsPartDoc(BaseModel):
    part: int
    title: str
    owner: str = ""
    status: str = ""
    body: str = ""


class IpsVersion(BaseModel):
    client_id: str
    version: int
    status: Literal["Active", "Superseded", "Draft"]
    issued_on: str
    author: str = ""
    summary: str = ""
    parts: list[IpsPartDoc] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)  # structured IPS JSON (see schemas.py); {} for versions saved as text only

    def part(self, n: int) -> Optional[IpsPartDoc]:
        return next((p for p in self.parts if p.part == n), None)


def _check_progress(onboarding, monitoring) -> None:
    if onboarding is not None and not 0 <= onboarding <= 5:
        raise ValueError("onboarding_progress must be 0..5")
    if monitoring is not None and not 0 <= monitoring <= 100:
        raise ValueError("monitoring_progress must be 0..100")


DEFAULT_RM = "rm_default"
IPS_CHAT_CAP = 100  # messages kept per (client, RM); the oldest are dropped beyond this
CHAT_ROLES = ("user", "assistant")
CHAT_KINDS = ("chat", "generation", "discuss")


def _check_chat(role: str, kind: str) -> None:
    if role not in CHAT_ROLES:
        raise ValueError(f"role must be one of {CHAT_ROLES}")
    if kind not in CHAT_KINDS:
        raise ValueError(f"kind must be one of {CHAT_KINDS}")


class MeetingNoteDoc(BaseModel):
    id: str
    client_id: str
    date: str
    title: str
    source_file: str = ""
    text: str


class ClientResolution(BaseModel):
    status: Literal["resolved", "ambiguous", "not_found"]
    client: Optional[Client] = None
    candidates: list[Client] = Field(default_factory=list)
    reason: str = ""


# Capitalised words that follow "for/about/with/client" but are not person names.
_NOT_NAMES = {
    "the", "this", "that", "his", "her", "their", "our", "my", "ips", "saa", "taa", "isabel", "rm", "pm", "ps",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "singapore", "balanced", "conservative", "moderate", "growth", "aggressive", "liquidity", "longevity",
    "legacy", "draft", "active", "superseded", "version", "note", "notes", "meeting", "what", "when", "which",
    "who", "how", "why", "can", "could", "show", "tell", "give", "please", "client", "clients", "latest",
    "current", "last", "first", "next", "all", "any", "each", "both", "usd", "sgd", "esg", "us",
}
_NAME_CTX = re.compile(r"\b(?:client|customer|mr|mrs|ms|dr|for|about|on|with|of|regarding|from)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)")


class StoreUnavailableError(RuntimeError):
    """The configured document store (Postgres) cannot be reached. Never silently falls back."""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


class BaseStore:
    """Shared client resolution and IPS selection. Subclasses implement the storage primitives.
    Accessors return deep copies so callers cannot mutate the store."""

    def list_clients(self) -> list[Client]:
        raise NotImplementedError

    def get_client(self, client_id: str) -> Optional[Client]:
        return next((c for c in self.list_clients() if c.id == client_id), None)

    def get_ips_versions(self, client_id: str) -> list[IpsVersion]:
        raise NotImplementedError

    def get_notes(self, client_id: str) -> list[MeetingNoteDoc]:
        raise NotImplementedError

    def get_note(self, client_id: str, note_id: str) -> Optional[MeetingNoteDoc]:
        return next((n for n in self.get_notes(client_id) if n.id == note_id), None)

    def add_note(self, note: MeetingNoteDoc) -> MeetingNoteDoc:
        raise NotImplementedError

    def update_note(self, client_id: str, note_id: str, title: Optional[str] = None,
                    text: Optional[str] = None, date: Optional[str] = None) -> Optional[MeetingNoteDoc]:
        raise NotImplementedError

    def note_indexing(self, client_id: str, note_id: str) -> dict:
        """Search-index state of one note: {"status": "indexed"|"pending", "chunks": int|None}. The JSON store has
        no vectors (keyword retrieval reads the note directly), so it is searchable at once with no chunk count."""
        return {"status": "indexed", "chunks": None}

    # ---- client book (the single RM's clients: cp_clients.in_book) ----
    def list_book(self) -> list[Client]:
        return sorted((c for c in self.list_clients() if c.in_book), key=lambda c: c.id)

    def book_ids(self) -> list[str]:
        return [c.id for c in self.list_book()]

    def set_in_book(self, client_id: str, flag: bool) -> bool:
        raise NotImplementedError

    def set_progress(self, client_id: str, onboarding: Optional[int] = None, monitoring: Optional[int] = None) -> bool:
        raise NotImplementedError

    # ---- semantic search (None = unsupported) ----
    def index_ips(self, client_id: str, version: int) -> Optional[bool]:
        return None

    def search_ips(self, client_id: str, query: str, k: int = 4) -> Optional[list[dict]]:
        return None

    def drop_stale_ips_chunks(self, client_id: str, keep_version: Optional[int]) -> None:
        """Remove IPS chunks of every version except keep_version (None = remove all). No-op without a vector store."""
        return None

    def count_ips_chunks(self, client_id: str, version: int) -> int:
        return 0

    # ---- model strategies A-F and the investor-profile guide (RAG context) ----
    def list_strategies(self) -> list[dict]:
        """Strategies in the shape of data/strategies.json (code, name, risk_label, allocation, ..., stress)."""
        from . import strategies
        return [json.loads(json.dumps(s)) for s in strategies.load_strategies()]

    def search_guide(self, query: str, k: int = 4) -> Optional[list[dict]]:
        """Semantic top-k guide chunks [{text, heading, score}], or None when unsupported (keyword fallback in guide.py)."""
        return None

    # ---- IPS chat history (dedicated IPS assistant), per client AND per RM; JSON store keeps it in memory ----
    def _chat_rows(self) -> dict:
        if not hasattr(self, "_ips_chat"):
            self._ips_chat = {}
        return self._ips_chat

    def list_ips_chat(self, client_id: str, limit: int = IPS_CHAT_CAP, rm_id: str = DEFAULT_RM) -> list[dict]:
        """This RM's messages for the client, oldest first, at most `limit` (the most recent ones)."""
        rows = self._chat_rows().get((client_id, rm_id or DEFAULT_RM), [])
        return [json.loads(json.dumps(r)) for r in rows[-limit:]] if limit > 0 else []

    def append_ips_chat(self, client_id: str, role: str, text: str, kind: str = "chat", meta: Optional[dict] = None,
                        rm_id: str = DEFAULT_RM) -> dict:
        """Append one message; beyond IPS_CHAT_CAP the oldest are dropped and the returned row has truncated=True."""
        _check_chat(role, kind)
        rows = self._chat_rows().setdefault((client_id, rm_id or DEFAULT_RM), [])
        row = {"id": f"ipsc_{uuid.uuid4().hex[:12]}", "role": role, "kind": kind, "text": text,
               "ts": datetime.now(timezone.utc).isoformat(), "meta": meta}
        rows.append(row)
        dropped = max(0, len(rows) - IPS_CHAT_CAP)
        if dropped:
            del rows[:dropped]
        return {**json.loads(json.dumps(row)), "truncated": bool(dropped)}

    def clear_ips_chat(self, client_id: str, rm_id: str = DEFAULT_RM) -> int:
        return len(self._chat_rows().pop((client_id, rm_id or DEFAULT_RM), []))

    # ---- audit log of manual 3L strategy overrides ----
    def log_strategy_override(self, client_id: str, portfolio: str, from_strategy: str, to_strategy: str, reason: str = "",
                              rm_id: str = DEFAULT_RM) -> dict:
        if not hasattr(self, "_overrides"):
            self._overrides = []
        row = {"clientId": client_id, "portfolio": portfolio, "from": from_strategy, "to": to_strategy, "reason": reason,
               "rmId": rm_id or DEFAULT_RM, "ts": datetime.now(timezone.utc).isoformat()}
        self._overrides.append(row)
        return dict(row)

    def list_strategy_overrides(self, client_id: str) -> list[dict]:
        return [dict(r) for r in getattr(self, "_overrides", []) if r["clientId"] == client_id]

    # ---- send-to-PM (IS-101): one immutable snapshot + sent state per client; JSON store keeps it in memory ----
    def _send_rows(self) -> dict:
        if not hasattr(self, "_ips_sends"):
            self._ips_sends = {}
        return self._ips_sends

    def send_ips_to_pm(self, client_id: str, version: int, rm_id: str, sent_at: str, snapshot: dict,
                       before_commit=None) -> dict:
        """Atomically store the snapshot and flip the client's IPS to "Sent to PM", replacing any earlier send.
        `before_commit(record)` runs inside the transaction; if it raises, nothing is stored (state stays Draft)."""
        rec = {"clientId": client_id, "version": version, "status": SENT_STATUS, "sentAt": sent_at, "rmId": rm_id or DEFAULT_RM,
               "snapshot": json.loads(json.dumps(snapshot))}
        if before_commit is not None:
            before_commit(json.loads(json.dumps(rec)))
        self._send_rows()[client_id] = rec
        return json.loads(json.dumps(rec))

    def get_ips_send(self, client_id: str) -> Optional[dict]:
        rec = self._send_rows().get(client_id)
        return json.loads(json.dumps(rec)) if rec else None

    def withdraw_ips_send(self, client_id: str) -> bool:
        """Remove the sent state (IPS content untouched). True if there was a send."""
        return self._send_rows().pop(client_id, None) is not None

    # ---- IPS writes ----
    def save_ips(self, client_id: str, parts: list[IpsPartDoc], version: Optional[int] = None, summary: Optional[str] = None,
                 author: Optional[str] = None, status: str = "Active", data: Optional[dict] = None) -> Optional[IpsVersion]:
        """Edit IPS `version` in place (None if it does not exist) or, when version is None, create the next version.
        A new Active version supersedes the previously Active one. Returns the saved version."""
        raise NotImplementedError

    def resolve_client(self, query_text: str, context_client_id: Optional[str] = None) -> ClientResolution:
        """Resolve which client a request is about. Never guesses.

        An explicit name/id in the text wins over the context client. Two or more
        different clients named, or a name that matches nobody, gives candidates.
        """
        clients = self.list_clients()
        text = query_text or ""
        low = text.lower()
        hits: dict[str, Client] = {}
        for c in clients:
            tokens = {c.id.lower(), _norm(c.name)} | {t for t in re.split(r"\s+", _norm(c.name)) if len(t) > 1}
            if c.surname:
                tokens.add(c.surname.lower())
            if any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low) for t in tokens):
                hits[c.id] = c
        if len(hits) == 1:
            c = next(iter(hits.values()))
            return ClientResolution(status="resolved", client=c.model_copy(deep=True), reason="named in request")
        if len(hits) > 1:
            # A test twin ("Jane Fraser (test)") shares every name token with the real client: when the context
            # client is the one whose name prefixes all the other hits, it wins instead of being ambiguous.
            ctx = hits.get(context_client_id) if context_client_id else None
            if ctx and all(_norm(c.name).startswith(_norm(ctx.name)) for c in hits.values()):
                return ClientResolution(status="resolved", client=ctx.model_copy(deep=True), reason="context client")
            return ClientResolution(status="ambiguous", candidates=[c.model_copy(deep=True) for c in hits.values()],
                                    reason="more than one client named in the request")
        known = {t for c in clients for t in re.split(r"\s+", _norm(c.name))} | {c.id for c in clients}
        for m in _NAME_CTX.finditer(text):
            words = m.group(1).lower().split()
            if words[0] in _NOT_NAMES or words[0] in known:
                continue
            return ClientResolution(status="not_found", candidates=self.list_clients(),
                                    reason=f"'{m.group(1)}' does not match any client")
        ctx = self.get_client(context_client_id) if context_client_id else None
        if ctx:
            return ClientResolution(status="resolved", client=ctx, reason="context client")
        return ClientResolution(status="ambiguous", candidates=self.list_clients(), reason="no client named and no context client")


    def latest_ips(self, client_id: str) -> tuple[Optional[IpsVersion], bool]:
        """(ips, is_current). Current = highest-version Active. If none Active, the
        highest Draft is returned with is_current=False. Superseded is never current."""
        versions = self.get_ips_versions(client_id)
        active = next((v for v in versions if v.status == "Active"), None)
        if active:
            return active, True
        draft = next((v for v in versions if v.status == "Draft"), None)
        return draft, False



class DocumentStore(BaseStore):
    """JSON-file backed store (offline tests / no-DB dev)."""

    def __init__(self, data_dir: Optional[Path | str] = None):
        d = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self.data_dir = d
        self._clients = [Client(**c) for c in self._load(d / "clients.json", "clients")]
        self._ips = [IpsVersion(**i) for i in self._load(d / "ips.json", "ips_versions")]
        self._notes = [MeetingNoteDoc(**n) for n in self._load(d / "meeting_notes.json", "meeting_notes")]
        # Uploaded notes live in their own file so the seed JSON is never rewritten.
        self._uploads_path = d / UPLOADS_FILE
        if self._uploads_path.exists():
            self._notes += [MeetingNoteDoc(**n) for n in self._load(self._uploads_path, "meeting_notes")]
        # Review Pack state per client: {"state": <opaque obj>, "updated_at": iso}. In memory, like put_pm_working.
        self._review_states: dict[str, dict] = {}

    @staticmethod
    def _load(path: Path, key: str) -> list[dict]:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)[key]
        return [{k: v for k, v in r.items() if k not in ("fictional", "origin", "next_meeting")} for r in rows]

    # ---- clients ----
    def list_clients(self) -> list[Client]:
        return [c.model_copy(deep=True) for c in self._clients]

    def get_client(self, client_id: str) -> Optional[Client]:
        c = next((c for c in self._clients if c.id == client_id), None)
        return c.model_copy(deep=True) if c else None

    # ---- documents (always scoped to one client_id) ----
    def get_ips_versions(self, client_id: str) -> list[IpsVersion]:
        """All IPS versions for the client, highest version first."""
        v = sorted((i for i in self._ips if i.client_id == client_id), key=lambda i: -i.version)
        return [i.model_copy(deep=True) for i in v]

    def get_notes(self, client_id: str) -> list[MeetingNoteDoc]:
        """Meeting notes for the client, newest first."""
        n = sorted((n for n in self._notes if n.client_id == client_id), key=lambda n: (n.date, n.id), reverse=True)
        return [x.model_copy(deep=True) for x in n]

    def get_note(self, client_id: str, note_id: str) -> Optional[MeetingNoteDoc]:
        return next((n for n in self.get_notes(client_id) if n.id == note_id), None)

    def add_note(self, note: MeetingNoteDoc) -> MeetingNoteDoc:
        """Persist an uploaded note (append-only, separate file). The client must exist; ids are unique."""
        if self.get_client(note.client_id) is None:
            raise ValueError(f"unknown client {note.client_id!r}")
        if any(n.id == note.id for n in self._notes):
            raise ValueError(f"note id {note.id!r} already exists")
        self._notes.append(note.model_copy(deep=True))
        self._write_uploads()
        return note

    def _write_uploads(self) -> None:
        uploaded = [n.model_dump() for n in self._notes if n.id.startswith(UPLOAD_ID_PREFIX)]
        tmp = self._uploads_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"_disclaimer": "Notes ingested from user uploads.", "meeting_notes": uploaded}, indent=2), encoding="utf-8")
        tmp.replace(self._uploads_path)

    def update_note(self, client_id: str, note_id: str, title: Optional[str] = None,
                    text: Optional[str] = None, date: Optional[str] = None) -> Optional[MeetingNoteDoc]:
        """Edit title/date/text of one of this client's notes; None if it is not that client's. Persisted for uploads;
        seed notes are edited in memory only (the seed JSON is never rewritten)."""
        n = next((n for n in self._notes if n.id == note_id and n.client_id == client_id), None)
        if n is None:
            return None
        if title is not None:
            n.title = title
        if text is not None:
            n.text = text
        if date is not None:
            n.date = date
        if n.id.startswith(UPLOAD_ID_PREFIX):
            self._write_uploads()
        return n.model_copy(deep=True)

    def save_ips(self, client_id: str, parts: list[IpsPartDoc], version: Optional[int] = None, summary: Optional[str] = None,
                 author: Optional[str] = None, status: str = "Active", data: Optional[dict] = None) -> Optional[IpsVersion]:
        """In-memory only (the seed JSON is never rewritten)."""
        if self.get_client(client_id) is None:
            raise ValueError(f"unknown client {client_id!r}")
        if version is not None:
            cur = next((i for i in self._ips if i.client_id == client_id and i.version == version), None)
            if cur is None:
                return None
            cur.parts = [p.model_copy(deep=True) for p in parts]
            if summary is not None:
                cur.summary = summary
            if author is not None:
                cur.author = author
            if data is not None:
                cur.data = json.loads(json.dumps(data))
            return cur.model_copy(deep=True)
        nxt = max((i.version for i in self._ips if i.client_id == client_id), default=0) + 1
        if status == "Active":
            for i in self._ips:
                if i.client_id == client_id and i.status == "Active":
                    i.status = "Superseded"
        new = IpsVersion(client_id=client_id, version=nxt, status=status, issued_on=date.today().isoformat(),
                         author=author or "", summary=summary or "", parts=[p.model_copy(deep=True) for p in parts],
                         data=json.loads(json.dumps(data or {})))
        self._ips.append(new)
        return new.model_copy(deep=True)

    def delete_ips(self, client_id: str, version: int) -> bool:
        """Remove one IPS version (in memory). If it was Active, the newest remaining version becomes Active."""
        cur = next((i for i in self._ips if i.client_id == client_id and i.version == version), None)
        if cur is None:
            return False
        self._ips.remove(cur)
        rest = sorted((i for i in self._ips if i.client_id == client_id), key=lambda i: -i.version)
        if cur.status == "Active" and rest and not any(i.status == "Active" for i in rest):
            rest[0].status = "Active"
        return True

    def activate_ips(self, client_id: str, version: int) -> bool:
        """Mark one IPS version Active; every other Active version of the client becomes Superseded (in memory)."""
        cur = next((i for i in self._ips if i.client_id == client_id and i.version == version), None)
        if cur is None:
            return False
        for i in self._ips:
            if i.client_id == client_id and i.status == "Active" and i is not cur:
                i.status = "Superseded"
        cur.status = "Active"
        return True

    def update_ips_send(self, client_id: str, status: str, snapshot: dict) -> Optional[dict]:
        """Change the status and snapshot of the client's current send (in memory). None if nothing was sent."""
        rec = self._send_rows().get(client_id)
        if rec is None:
            return None
        rec["status"] = status
        rec["snapshot"] = json.loads(json.dumps(snapshot))
        return json.loads(json.dumps(rec))

    def get_pm_working(self, client_id: str) -> Optional[dict]:
        """PM's working copy of the sent IPS (in memory), or None."""
        if not hasattr(self, "_pm_working"):
            self._pm_working = {}
        w = self._pm_working.get(client_id)
        return json.loads(json.dumps(w)) if w is not None else None

    def put_pm_working(self, client_id: str, working: dict) -> None:
        if not hasattr(self, "_pm_working"):
            self._pm_working = {}
        self._pm_working[client_id] = json.loads(json.dumps(working))

    def set_client_status(self, client_id: str, status: str) -> bool:
        c = self._row(client_id)
        if c is None:
            return False
        c.status = status
        return True

    # ---- client book (in memory; the seed file is never rewritten) ----
    def _row(self, client_id: str) -> Optional[Client]:
        return next((c for c in self._clients if c.id == client_id), None)

    def set_in_book(self, client_id: str, flag: bool) -> bool:
        c = self._row(client_id)
        if c is None:
            return False
        c.in_book = bool(flag)
        return True

    def set_progress(self, client_id: str, onboarding: Optional[int] = None, monitoring: Optional[int] = None) -> bool:
        _check_progress(onboarding, monitoring)
        c = self._row(client_id)
        if c is None:
            return False
        if onboarding is not None:
            c.onboarding_progress = onboarding
        if monitoring is not None:
            c.monitoring_progress = monitoring
        return True

    # ---- Review Pack state (in memory) ----
    def get_review_pack_state(self, client_id: str) -> Optional[dict]:
        r = self._review_states.get(client_id)
        return json.loads(json.dumps(r["state"])) if r is not None else None

    def put_review_pack_state(self, client_id: str, state: dict) -> str:
        now = datetime.now(timezone.utc).isoformat()
        self._review_states[client_id] = {"state": json.loads(json.dumps(state)), "updated_at": now}
        return now

    def list_review_pack_states(self) -> dict[str, dict]:
        return {cid: json.loads(json.dumps(r["state"])) for cid, r in self._review_states.items()}

    def delete_review_pack_state(self, client_id: str) -> bool:
        return self._review_states.pop(client_id, None) is not None


_default: Optional[BaseStore] = None


def get_default_store() -> BaseStore:
    """CLIENT_PROFILING_STORE = 'postgres' (default) | 'json'. Postgres unreachable -> StoreUnavailableError."""
    global _default
    if _default is None:
        kind = os.getenv("CLIENT_PROFILING_STORE", "postgres").strip().lower()
        if kind == "json":
            _default = DocumentStore()
        elif kind == "postgres":
            from .store_pg import PostgresStore
            _default = PostgresStore()
        else:
            raise ValueError(f"unknown CLIENT_PROFILING_STORE {kind!r} (use 'postgres' or 'json')")
    return _default


def reset_default_store() -> None:
    global _default
    _default = None
