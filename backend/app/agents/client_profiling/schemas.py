"""Shared contract for the Client Profiling Agent (all modules import from here)."""
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

FactKind = Literal["documented", "calculated", "inferred", "missing"]
Status = Literal["ok", "needs_clarification", "insufficient_information", "not_found"]


class SourceRef(BaseModel):
    """Provenance pointer; the frontend resolves it to an IPS version or meeting note."""
    type: Literal["ips", "meeting_note"]
    id: str                       # ips: "<client_id>:v<version>", note: note id e.g. "note_0318"
    client_id: str
    version: Optional[int] = None  # IPS only
    date: Optional[str] = None
    label: str = ""
    passage: Optional[str] = None  # verbatim supporting text


class Fact(BaseModel):
    field: str                    # e.g. "risk_tolerance", "aum_managed_sgd"
    category: Literal["client_financial", "objectives", "risk", "preferences"]
    value: Any = None
    kind: FactKind                # documented | calculated | inferred | missing
    sources: list[SourceRef] = Field(default_factory=list)
    note: Optional[str] = None    # e.g. calculation basis, why inferred, what to confirm


class Conflict(BaseModel):
    field: str
    statements: list[SourceRef]
    explanation: str


class ClientProfile(BaseModel):
    client_id: str
    client_name: str
    ips_version_used: Optional[int] = None
    ips_status: Optional[str] = None
    facts: list[Fact] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)       # field names needing confirmation
    outdated: list[str] = Field(default_factory=list)      # human-readable staleness notes
    sources: list[SourceRef] = Field(default_factory=list)

    def get(self, field: str) -> Optional[Fact]:
        return next((f for f in self.facts if f.field == field), None)


class ToolResult(BaseModel):
    """Every tool returns this envelope; `data` is tool-specific, JSON-serialisable."""
    tool: str
    status: Status = "ok"
    client_id: Optional[str] = None
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    sources: list[SourceRef] = Field(default_factory=list)
    candidates: list[dict[str, str]] = Field(default_factory=list)  # for needs_clarification: [{id,name}]
