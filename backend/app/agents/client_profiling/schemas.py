"""Shared contract for the Client Profiling Agent (all modules import from here).

=== STRUCTURED IPS JSON (IS-87/91/92/93/94 + extras) - read by the frontend ===
Stored next to the text `parts` of an IPS version as `data`; returned by GET /ips/{client_id} as versions[].data and by
the generation endpoints. Names are stable:

data = {
  "goals": [                       # ALWAYS 7 entries in this order (IS-93); empty ones are kept, never hidden
    {"key": "returnRequirements"|"investmentTimeHorizon"|"primaryGoals"|"secondaryGoals"|"liquidityNeeds"
            |"taxConsiderations"|"uniqueCircumstances",
     "title": "Return Requirements"|"Investment Time Horizon"|"Primary Goals"|"Secondary Goals"|"Liquidity Needs"
              |"Tax Considerations"|"Unique Circumstances and Preferences",
     "bullets": ["third-person sentence", ...],        # [] when empty
     "empty": true|false, "placeholder": "Not yet completed"}   # placeholder shown when empty
  ],
  "targets": [{"amount": 700000000, "currency": "SGD"|null, "horizonYears": 8|null,
               "text": "hit 700M within 8 years", "source_note": {"id","date","title"}}],
  "lifeEvents": [{"id": "le_note_1020_1", "date": "2029-09"|null, "year": 2029|null, "label": "Child starts university",
                  "detail": "third-person sentence", "source_note": {"id","date","title"}|null, "manual": false}],
                  # manual:true = added by the RM; save/load keeps them; the editor may add/remove items
  "reviewRules": [{"title": "Review frequency", "text": "..."}],   # canned, no LLM
  "threeL": [{"portfolio": "Liquidity"|"Longevity"|"Legacy", "strategy": "A".."F", "strategyName": "Fixed Income",
              "reason": "editable text (AI or RM)", "source": {"noteId","date","title","passage"}|null,
              "default": false,      # true = rule-based default from the risk score ("Default" badge)
              "conflict": null|{"note": "human text (same as message)", "message": "...",
                                "dates": ["<latest meeting date>", "<earlier meeting date>"],
                                "latest":{"noteId","date","view"}, "earlier":{"noteId","date","view"}}}],
  "threeLStatus": "ok"|"no_notes"|"unavailable", "threeLMessage": "...",   # no_notes -> ask RM to upload notes
  "riskScore": 1..5|null,
  "model": "name that produced the AI content"|null,   # null + modelMessage when no model was available
  "modelMessage": "...", "notIncluded": ["sentence that could not be safely converted to third person", ...],
  "evidence": {"<section>": [{"item","noteId","date","title","passage"(verbatim)}]},
  "rmSignatureImage": "/signature-isabel.png", "rmSignedDate": "YYYY-MM-DD",
  "demographics": {"fields": {label: value}}, "philosophy": {"approach","believes","avoids"}, "risk": {"fields","bullets"}
}
Generation: POST /agents/client-profiling/ips-generate (one section; auto-saves, returns "version" + "saved") and
POST /ips-generate/all (all sections). Responses/progress events carry "model". IPS chat history:
GET/POST/DELETE /ips-chat/{client_id} (header X-RM-Id, or query rm_id, scopes history per RM; cap 100; GET and POST
return "truncated" + "message"; DB down -> HTTP 503 {"historyAvailable": false} so the UI falls back to the session).
POST /ips-allocation/override {clientId, portfolio, from, to, reason} -> {"ok": true, "ts"} (audit log; Liquidity A/B only).
POST /ips/{client_id} accepts {data: <the structure above>, parts?: [...]} (parts rendered from data when omitted).
"""
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
