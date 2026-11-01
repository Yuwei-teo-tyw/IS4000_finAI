"""
HTTP interface for the Client Profiling Agent.

    POST /agents/client-profiling/chat   run one profiling tool for the client in the query/context

Read-only: never updates IPS documents, client records or allocations. Validation errors do not echo
submitted values (client data).
"""
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.agents.client_profiling.ips_assist import ips_assist
from app.agents.client_profiling.ips_generate import SECTIONS as IPS_GEN_SECTIONS, generate_ips_section
from app.agents.client_profiling.strategies import allowed_strategies, load_strategies
from app.agents.client_profiling.threel import discuss_allocation
from app.agents.client_profiling.proportion import validate_proportion
from app.agents.client_profiling.schemas import SourceRef, ToolResult
from app.agents.client_profiling.ingest import IngestError, ingest_note
from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.ips_model import empty_sections, merge_section, new_ips_data, normalize_data, render_parts
from app.agents.client_profiling.store import DEFAULT_RM, IPS_CHAT_CAP, SENT_STATUS, StoreUnavailableError, get_default_store

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
    # IS-89/90 allocation dialogue: all optional. allocation = {"buckets": [{id, strategy, justification}]} (default: the client's
    # latest saved IPS threeL); history = [{role, text, proposal?}] (default: this RM's stored IPS chat); pending_proposal is echoed.
    allocation: Optional[dict] = None
    history: Optional[list[dict]] = Field(default=None, max_length=100)
    pending_proposal: Optional[dict] = None


def _allocation_from_ips(store, client_id: Optional[str]) -> Optional[dict]:
    """The client's current 3L allocation from the newest saved IPS (structured data.threeL), else None."""
    if not client_id:
        return None
    try:
        for v in store.get_ips_versions(client_id):
            if v.data and v.data.get("threeL"):
                return {"buckets": [{"id": b["portfolio"].lower(), "strategy": b["strategy"], "justification": b.get("reason", "")}
                                    for b in v.data["threeL"]]}
    except Exception:
        return None
    return None


def _stored_history(store, client_id: Optional[str], rm: str) -> Optional[list]:
    fn = getattr(store, "list_ips_chat", None)
    if not client_id or not callable(fn):
        return None
    try:
        rows = fn(client_id, limit=IPS_CHAT_CAP, rm_id=rm)
    except Exception:
        return None
    return [{"role": r["role"], "text": r["text"], **({"proposal": r["meta"]["proposal"]} if (r.get("meta") or {}).get("proposal") else {})}
            for r in rows] or None


@router.post("/chat", response_model=ToolResult)
def chat(body: ProfilingChatRequest, x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)) -> ToolResult:
    store = get_default_store()
    book = store.book_ids()  # StoreUnavailableError -> guard; client-supplied `book` is ignored
    allocation = body.allocation or _allocation_from_ips(store, body.client_id)
    history = body.history if body.history is not None else _stored_history(store, body.client_id, _rm(x_rm_id, rm_id))
    return handle_chat(body.message, body.client_id, book=book, source=body.source, allocation=allocation, history=history,
                       pending_proposal=body.pending_proposal)


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
def ips_assist_endpoint(body: IpsAssistRequest) -> IpsAssistResponse:
    """Draft or professionalise one IPS section for the edit page. Read-only suggestion; nothing is saved."""
    store = get_default_store()
    if store.get_client(body.client_id) is None:
        raise HTTPException(status_code=404, detail="Unknown client")
    _require_in_book(store, body.client_id)
    return IpsAssistResponse(**ips_assist(store, body.client_id, body.section, body.mode, body.current_text, body.message,
                                    selection=body.selection))


class IpsGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    client_id: str = Field(min_length=1, max_length=40, validation_alias=AliasChoices("client_id", "clientId"))
    section: Literal["demographics", "philosophy", "goals", "risk", "allocation"]
    version: Optional[int] = Field(default=None, ge=1)  # continue saving into this (draft) version; None = start a new one


class IpsGenerateAllRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    client_id: str = Field(min_length=1, max_length=40, validation_alias=AliasChoices("client_id", "clientId"))


@router.get("/ips-generate/sections")
async def ips_generate_sections() -> list[dict]:
    """The AI IPS generation sections, in the order the frontend should call them."""
    return [{"id": i, "label": l} for i, l in IPS_GEN_SECTIONS]


def _autosave(store, client_id: str, results: list[dict], version: Optional[int], extra: Optional[dict] = None) -> Optional[dict]:
    """Merge generated section results into the structured IPS and persist it (new Draft version, or `version` in place).
    `extra`: top-level IPS data set alongside (e.g. the Market Analysis Agent's `market` block).
    Returns None when nothing was generated (no notes / no model): no empty version is created."""
    if not any(r.get("status") == "ok" for r in results):
        return None
    cur = next((v for v in store.get_ips_versions(client_id) if v.version == version), None) if version else None
    if version and cur is None:
        raise HTTPException(status_code=404, detail="IPS version not found for this client")
    data = normalize_data(cur.data if cur and cur.data else new_ips_data())
    for r in results:
        merge_section(data, r)
    data.update(extra or {})
    from app.agents.client_profiling.store import IpsPartDoc
    parts = [IpsPartDoc(**p) for p in render_parts(data)]
    saved = store.save_ips(client_id, parts, version=version, summary="AI-generated draft from meeting notes",
                           author="AI draft", status="Draft", data=data)
    return _ips_json(saved) if saved else None


@router.post("/ips-generate")
def ips_generate(body: IpsGenerateRequest) -> dict:
    """Draft one IPS section from the client's meeting notes (local model) and save it: no manual save needed.
    Response = the section result (+ `model`) and, when something was generated, `saved: true`, `version` and `ips`."""
    store = get_default_store()
    _require_in_book(store, body.client_id)
    res = generate_ips_section(store, body.client_id, body.section)
    ips = _autosave(store, body.client_id, [res], body.version)
    res.update({"saved": ips is not None, "version": ips["version"] if ips else None, "ips": ips, "saved_ips": ips})
    return res


@router.post("/ips-generate/all")
def ips_generate_all(body: IpsGenerateAllRequest) -> dict:
    """Generate every section in order, save ONE new draft IPS version and return it with per-section progress events."""
    store = get_default_store()
    _require_in_book(store, body.client_id)
    results = [generate_ips_section(store, body.client_id, sid) for sid, _l in IPS_GEN_SECTIONS]
    ips = _autosave(store, body.client_id, results, None)
    events = [{"section": r["section"], "status": r["status"], "message": r["message"], "model": r.get("model"),
               "reasoning": r.get("reasoning") or []} for r in results]
    model = next((r["model"] for r in results if r.get("model")), None)
    return {"sections": results, "events": events, "model": model,
            "modelMessage": "" if model else next((r.get("modelMessage", "") for r in results if r.get("modelMessage")), ""),
            "saved": ips is not None, "version": ips["version"] if ips else None, "ips": ips, "saved_ips": ips}


MARKET_WAIT_SECONDS = 180  # a fresh market run has a 90s budget plus queueing


def _stream_workers() -> int:
    """Concurrent section generations. LM Studio (4 parallel slots) measured ~1.5x faster with 2-4 concurrent requests."""
    try:
        return max(1, min(3, int(os.getenv("IPS_GENERATE_WORKERS", "3"))))
    except ValueError:
        return 3


def _ndjson(obj: dict) -> bytes:
    return (json.dumps(obj, default=str) + "\n").encode("utf-8")


def _safe_generate(store, client_id: str, section: str) -> dict:
    try:
        return generate_ips_section(store, client_id, section)
    except Exception:  # one failing section must not kill the others; never echo client data in the message
        return {"section": section, "status": "error", "message": "This section could not be generated.",
                "fields": {}, "bullets": [], "sources": [], "reasoning": [], "model": None}


@router.post("/ips-generate/stream")
async def ips_generate_stream(body: IpsGenerateAllRequest, request: Request) -> StreamingResponse:
    """Generate all sections concurrently (bounded pool) and stream one NDJSON line per section as it finishes:
    `{"type":"start","sections":[...]}`, then `{"type":"section", ...section result}` lines (any order), then the Market Analysis
    Agent's `{"type":"market","market":{...}}` line, then ONE autosave of a single new Draft version (with the market block
    as `data.market`) and a final `{"type":"done","saved","version","ips","model","modelMessage"}` line.
    The market block is fetched alongside the sections: a run from the last 24h is reused, else one run is started."""
    from app.agents.market_researcher.ips_context import ips_market_context, unavailable
    store = get_default_store()
    _require_in_book(store, body.client_id)
    ids = [sid for sid, _l in IPS_GEN_SECTIONS]
    order = sorted(ids, key=lambda s: s != "allocation")  # the slowest section first so it overlaps the narrative ones
    loop = asyncio.get_running_loop()
    market_fut = asyncio.run_coroutine_threadsafe(ips_market_context(getattr(request.app.state, "market_research", None)), loop)

    def market_block() -> dict:
        try:
            return market_fut.result(timeout=MARKET_WAIT_SECONDS)
        except Exception:  # noqa: BLE001 - a slow or failed market run never blocks the IPS
            market_fut.cancel()
            return unavailable("The Market Analysis Agent did not finish in time; regenerate the IPS to try again.")

    def gen():
        yield _ndjson({"type": "start", "sections": ids, "workers": _stream_workers()})
        ex = ThreadPoolExecutor(max_workers=_stream_workers(), thread_name_prefix="ips-gen")
        results: dict[str, dict] = {}
        finished = False
        try:
            futs = {ex.submit(_safe_generate, store, body.client_id, sid): sid for sid in order}
            for f in as_completed(futs):
                r = f.result()
                results[r.get("section", futs[f])] = r
                yield _ndjson({"type": "section", **r})
            finished = True
        finally:
            ex.shutdown(wait=False, cancel_futures=True)  # client went away: stop queued work, skip the save
            if not finished:
                market_fut.cancel()
        if not finished:
            return
        market = market_block()
        yield _ndjson({"type": "market", "market": market})
        ordered = [results[s] for s in ids if s in results]
        model = next((r["model"] for r in ordered if r.get("model")), None)
        out: dict = {"type": "done", "model": model,
                     "modelMessage": "" if model else next((r.get("modelMessage", "") for r in ordered if r.get("modelMessage")), "")}
        try:
            ips = _autosave(store, body.client_id, ordered, None, extra={"market": market})
            out.update({"saved": ips is not None, "version": ips["version"] if ips else None, "ips": ips})
        except Exception:
            out.update({"saved": False, "version": None, "ips": None, "error": "The generated draft could not be saved."})
        yield _ndjson(out)

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _strategy_json(s: dict) -> dict:
    g = lambda *keys: next((s[k] for k in keys if k in s), None)  # noqa: E731  (accept snake_case or camelCase rows)
    return {"code": g("code"), "name": g("name"), "riskLabel": g("riskLabel", "risk_label"), "allocation": g("allocation"),
            "expectedReturnPct": g("expectedReturnPct", "expected_return_pct"), "volatilityPct": g("volatilityPct", "volatility_pct"),
            "maxDrawdownPct": g("maxDrawdownPct", "max_drawdown_pct"),
            "longestDrawdownYears": g("longestDrawdownYears", "longest_drawdown_years"), **_ror_json(g("code"))}


def _ror_json(code) -> dict:
    """Portfolio rate of return for a strategy code (camelCase): numeric fields + rateOfReturnText."""
    from app.agents.client_profiling.strategies import rate_of_return
    r = rate_of_return(code or "")
    if not r:
        return {"nominalLowPct": None, "nominalHighPct": None, "realLowPct": None, "realHighPct": None, "inflationPct": None,
                "rateOfReturnText": ""}
    return {**{k: v for k, v in r.items() if k != "text"}, "rateOfReturnText": r["text"]}


@router.get("/strategies")
async def get_strategies() -> dict:
    """Model investment strategies A-F (asset-class mix, expected return, volatility, drawdowns) for the 3L allocation."""
    store, rows = get_default_store(), None
    fn = getattr(store, "list_strategies", None)
    if callable(fn):
        rows = fn()
    rows = rows or load_strategies()
    from app.agents.client_profiling import strategies as _s
    return {"source": _s._raw().get("source", ""), "liquidityAllowed": allowed_strategies("liquidity"),
            "strategies": [_strategy_json(dict(r) if isinstance(r, dict) else vars(r)) for r in rows]}


class _Turn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=4000)


class _AllocBucketIn(BaseModel):
    id: Literal["liquidity", "longevity", "legacy"]
    strategy: str = Field(min_length=1, max_length=2)
    justification: Optional[str] = Field(default=None, max_length=2000)


class _AllocIn(BaseModel):
    buckets: list[_AllocBucketIn] = Field(max_length=3)


class AllocationDiscussRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    client_id: str = Field(min_length=1, max_length=40, validation_alias=AliasChoices("client_id", "clientId"))
    message: str = Field(min_length=1, max_length=2000)
    history: list[_Turn] = Field(default_factory=list, max_length=40)
    allocation: Optional[_AllocIn] = None

    @field_validator("message")
    @classmethod
    def _msg_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v


@router.post("/ips-allocation/discuss")
def ips_allocation_discuss(body: AllocationDiscussRequest) -> dict:
    """Discuss the 3L allocation with the agent: it follows, partly follows or disagrees (with reasons). Read-only."""
    store = get_default_store()
    _require_in_book(store, body.client_id)
    return discuss_allocation(store, body.client_id, body.message.strip(), [t.model_dump() for t in body.history],
                              body.allocation.model_dump() if body.allocation else None)


class ProportionValidateRequest(BaseModel):
    liquidity: float
    longevity: float
    legacy: float


@router.post("/ips-proportion/validate")
async def ips_proportion_validate(body: ProportionValidateRequest) -> dict:
    """Sum-to-100 check for a manually edited proportion: {ok, total, message}."""
    return validate_proportion(body.model_dump())


# --- IPS chat history: persisted per client AND per RM (Postgres cp_ips_chat or JSON); cap IPS_CHAT_CAP messages ---
class IpsChatIn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=20000)
    kind: Literal["chat", "generation", "discuss"] = "chat"
    meta: Optional[dict] = None


def _rm(x_rm_id: Optional[str], rm_id: Optional[str]) -> str:
    """RM identity: header `X-RM-Id` (or query `rm_id`); a missing one is the default RM."""
    return ((x_rm_id or rm_id or "").strip()[:80]) or DEFAULT_RM


def _chat_store(client_id: str, method: str):
    store = get_default_store()
    _require_in_book(store, client_id)
    fn = getattr(store, method, None)
    if not callable(fn):
        raise HTTPException(status_code=503, detail="IPS chat history is not available")
    return fn


def _history_down(e: Exception) -> JSONResponse:
    """DB unreachable: say so explicitly so the frontend keeps the conversation in the session instead."""
    return JSONResponse({"detail": "IPS chat history is unavailable.", "historyAvailable": False, "messages": []}, status_code=503)


def _msg_json(m) -> dict:
    d = dict(m) if isinstance(m, dict) else {k: getattr(m, k, None) for k in ("id", "role", "kind", "text", "ts", "meta")}
    return {"id": str(d.get("id")), "role": d.get("role"), "kind": d.get("kind") or "chat", "text": d.get("text") or "",
            "ts": str(d.get("ts") or ""), "meta": d.get("meta")}


@router.get("/search-status")
async def search_status() -> dict:
    """Is semantic (embedding) search up? Down = answers about meeting notes and IPS fall back to keyword search / full text."""
    from app.agents.client_profiling import embeddings
    st = await asyncio.to_thread(embeddings.status)
    return {"embeddings": "ok" if st["ok"] else "down", "mode": "hybrid" if st["ok"] else "keyword_only", "model": st["model"],
            "message": "" if st["ok"] else "The embedding service is unreachable, so semantic search is off. Answers use keyword search only and may miss relevant passages."}


@router.delete("/ips/{client_id}/{version}")
async def delete_client_ips(client_id: str, version: int) -> dict:
    store = get_default_store()
    _require_in_book(store, client_id)
    try:
        ok = store.delete_ips(client_id, version)
    except StoreUnavailableError:
        raise HTTPException(status_code=503, detail="IPS database is unavailable")
    if not ok:
        raise HTTPException(status_code=404, detail=f"IPS v{version} not found")
    # No active IPS left: the review pack goes with it and the client falls back to Onboarding at 0%.
    reset = not any(v.status == "Active" for v in store.get_ips_versions(client_id))
    if reset:
        store.delete_review_pack_state(client_id)
        store.withdraw_ips_send(client_id)
        store.set_client_status(client_id, "Onboarding Phase")
        store.set_progress(client_id, onboarding=0, monitoring=0)
    return {"deleted": True, "version": version, "reset": reset}


TRUNCATED_MSG = f"IPS chat history keeps only the latest {IPS_CHAT_CAP} messages; the oldest were removed."


@router.get("/ips-chat/{client_id}")
async def get_ips_chat(client_id: str, x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)) -> dict:
    fn = _chat_store(client_id, "list_ips_chat")
    try:
        rows = fn(client_id, limit=IPS_CHAT_CAP, rm_id=_rm(x_rm_id, rm_id))
    except StoreUnavailableError as e:
        return _history_down(e)
    full = len(rows) >= IPS_CHAT_CAP
    return {"messages": [_msg_json(m) for m in rows], "historyAvailable": True, "cap": IPS_CHAT_CAP, "truncated": full,
            "message": TRUNCATED_MSG if full else ""}


@router.post("/ips-chat/{client_id}")
async def post_ips_chat(client_id: str, body: IpsChatIn, x_rm_id: Optional[str] = Header(default=None),
                        rm_id: Optional[str] = Query(default=None)) -> dict:
    fn = _chat_store(client_id, "append_ips_chat")
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="text must not be blank")
    try:
        row = fn(client_id, body.role, body.text, kind=body.kind, meta=body.meta, rm_id=_rm(x_rm_id, rm_id))
    except StoreUnavailableError as e:
        return _history_down(e)
    trunc = bool(row.get("truncated")) if isinstance(row, dict) else False
    return {**_msg_json(row), "truncated": trunc, "historyAvailable": True, "message": TRUNCATED_MSG if trunc else ""}


@router.delete("/ips-chat/{client_id}")
async def delete_ips_chat(client_id: str, x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)) -> dict:
    fn = _chat_store(client_id, "clear_ips_chat")
    try:
        fn(client_id, rm_id=_rm(x_rm_id, rm_id))
    except StoreUnavailableError as e:
        return _history_down(e)
    return {"cleared": True}


class OverrideIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    client_id: str = Field(min_length=1, max_length=40, validation_alias=AliasChoices("clientId", "client_id"))
    portfolio: str = Field(min_length=1, max_length=20)
    from_strategy: Optional[str] = Field(default="", max_length=2, validation_alias=AliasChoices("from", "from_strategy"))
    to_strategy: str = Field(min_length=1, max_length=2, validation_alias=AliasChoices("to", "to_strategy"))
    reason: str = Field(default="", max_length=2000)


@router.post("/ips-allocation/override")
async def ips_allocation_override(body: OverrideIn, x_rm_id: Optional[str] = Header(default=None),
                                  rm_id: Optional[str] = Query(default=None)) -> dict:
    """Audit-log a manual 3L strategy override by the RM (who, when, from -> to, reason). Liquidity takes no strategy."""
    store = get_default_store()
    _require_in_book(store, body.client_id)
    pf, to = body.portfolio.strip().lower(), body.to_strategy.strip().upper()
    if pf not in ("liquidity", "longevity", "legacy"):
        raise HTTPException(status_code=422, detail="portfolio must be Liquidity, Longevity or Legacy")
    if to not in allowed_strategies(pf):
        raise HTTPException(status_code=422, detail="The Liquidity portfolio has no strategy or SAA" if pf == "liquidity" else "unknown strategy")
    row = store.log_strategy_override(body.client_id, pf.capitalize(), (body.from_strategy or "").strip().upper(), to,
                                      body.reason.strip(), rm_id=_rm(x_rm_id, rm_id))
    from app.agents.client_profiling.strategies import rate_of_return_text
    return {"ok": True, "ts": row["ts"], "override": row, "rateOfReturn": rate_of_return_text(to)}


@router.get("/ips-allocation/overrides/{client_id}")
async def ips_allocation_overrides(client_id: str) -> dict:
    store = get_default_store()
    _require_in_book(store, client_id)
    return {"overrides": store.list_strategy_overrides(client_id)}


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
    date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")  # optional YYYY-MM-DD edit

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
    note = store.update_note(client_id, note_id, title=body.title, text=body.original_text, date=body.date)
    if note is None:
        raise HTTPException(status_code=404, detail="Meeting note not found for this client")
    return {**_note_json(note), "indexing": _indexing(store, note)}


# --- IPS read API (Postgres/JSON store is the source of truth; no writes here) ---
def _ips_json(v) -> dict:
    return {"version": v.version, "issuedOn": v.issued_on, "status": v.status, "author": v.author, "summary": v.summary,
            "data": normalize_data(v.data, signed=v.issued_on),
            "parts": [{"part": p.part, "title": p.title, "owner": p.owner, "status": p.status, "body": p.body}
                      for p in sorted(v.parts, key=lambda p: p.part)]}


def _flag_out_of_date(store, client_id: str, versions: list[dict]) -> None:
    """Mark a stored 3L recommendation `threeLOutOfDate` when the risk profile or meeting notes changed since it was generated."""
    from app.agents.client_profiling.threel import OUT_OF_DATE_MSG, profile_fingerprint
    if not any((v["data"].get("threeLBasis") and v["data"].get("threeL")) for v in versions):
        return
    try:
        now = profile_fingerprint(store.get_client(client_id), store.get_notes(client_id))
    except Exception:
        return
    for v in versions:
        d = v["data"]
        if d.get("threeLBasis") and d.get("threeL"):
            d["threeLOutOfDate"] = d["threeLBasis"] != now
            d["threeLOutOfDateMessage"] = OUT_OF_DATE_MSG if d["threeLOutOfDate"] else ""


@router.get("/ips/{client_id}")
async def get_client_ips(client_id: str) -> dict:
    """The client's IPS versions (newest first) in the frontend IpsVersion shape; 404 for an unknown client."""
    store = get_default_store()
    if store.get_client(client_id) is None:
        raise HTTPException(status_code=404, detail="Unknown client")
    versions = store.get_ips_versions(client_id)
    current = next((v.version for v in versions if v.status == "Active"), None)
    out = [_ips_json(v) for v in versions]
    _flag_out_of_date(store, client_id, out)
    return {"client_id": client_id, "client_name": _client_name(store, client_id),
            "clientName": _client_name(store, client_id), "current_version": current, "versions": out}


# --- IPS write API: save, then index the current version so it is searchable immediately (US-17) ---
class IpsPartIn(BaseModel):
    part: int = Field(ge=1, le=20)
    title: str = Field(max_length=200)
    owner: str = Field(default="", max_length=80)
    status: str = Field(default="", max_length=40)
    body: str = Field(default="", max_length=20000)


class IpsSaveRequest(BaseModel):
    version: Optional[int] = Field(default=None, ge=1)  # None = create the next version; set = edit that version in place
    parts: list[IpsPartIn] = Field(default_factory=list, max_length=20)  # may be empty when `data` is sent (parts are rendered)
    data: Optional[dict] = None  # structured IPS JSON (schemas.py)
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
    if not body.parts and body.data is None:
        raise HTTPException(status_code=422, detail="parts or data is required")
    data = normalize_data(body.data) if body.data is not None else None
    parts = [IpsPartDoc(**p.model_dump()) for p in body.parts] or [IpsPartDoc(**p) for p in render_parts(data)]
    kw = {"data": data} if data is not None else {}
    saved = store.save_ips(client_id, parts, version=body.version, summary=body.summary, author=body.author, status=body.status, **kw)
    if saved is None:
        raise HTTPException(status_code=404, detail="IPS version not found for this client")
    return {"client_id": client_id, "clientName": _client_name(store, client_id), "ips": _ips_json(saved), "indexing": _index_after_save(store, client_id, saved.version)}


# --- IS-101: send the draft IPS to the PM (immutable snapshot + sent state, one transaction) ---
NOT_SENT = {"sent": False, "message": "Not sent. Try again."}


def default_notify_pm(client_id: str, record: dict) -> None:
    """Notification seam, called inside the send transaction; raising aborts the send. Tests monkeypatch
    `notify_pm`; setting env IPS_SEND_FAIL=1 simulates a failing notification."""
    if os.getenv("IPS_SEND_FAIL", "").strip().lower() in ("1", "true", "yes"):
        raise RuntimeError("simulated PM notification failure")


notify_pm = default_notify_pm


class IpsSendRequest(BaseModel):
    version: Optional[int] = Field(default=None, ge=1)  # None = latest saved version


def _content(j: dict) -> dict:
    return {"data": j["data"], "parts": j["parts"]}


@router.post("/ips-send/{client_id}")
async def send_ips_to_pm(client_id: str, body: Optional[IpsSendRequest] = None, x_rm_id: Optional[str] = Header(default=None),
                         rm_id: Optional[str] = Query(default=None)):
    store = get_default_store()
    _require_in_book(store, client_id)
    versions = store.get_ips_versions(client_id)
    if not versions:
        raise HTTPException(status_code=409, detail="Generate an IPS first")
    want = body.version if body else None
    target = max(versions, key=lambda v: v.version) if want is None else next((v for v in versions if v.version == want), None)
    if target is None:
        raise HTTPException(status_code=404, detail=f"IPS v{want} not found")
    snap = {**_ips_json(target), "status": SENT_STATUS, "clientId": client_id}
    sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    snap["sentAt"] = sent_at
    try:
        rec = store.send_ips_to_pm(client_id, target.version, _rm(x_rm_id, rm_id), sent_at, snap,
                                   before_commit=lambda r: notify_pm(client_id, r))
    except Exception:  # StoreUnavailableError included: nothing was committed, so the status stays Draft
        return JSONResponse(NOT_SENT, status_code=503)
    return {"status": SENT_STATUS, "version": rec["version"], "sentAt": rec["sentAt"], "emptySections": empty_sections(target.data)}


@router.get("/ips-send/{client_id}")
async def get_ips_send_status(client_id: str) -> dict:
    store = get_default_store()
    _require_in_book(store, client_id)
    versions = store.get_ips_versions(client_id)
    if not versions:
        return {"sent": False, "status": "No IPS", "sentVersion": None, "sentAt": None, "latestVersion": None,
                "outdated": False, "message": "Generate an IPS first"}
    latest = max(versions, key=lambda v: v.version)
    rec = store.get_ips_send(client_id)
    if rec is None:
        return {"sent": False, "status": "Draft", "sentVersion": None, "sentAt": None, "latestVersion": latest.version,
                "outdated": False, "message": "Draft. Not yet sent to the PM."}
    snap = rec["snapshot"]
    outdated = latest.version > rec["version"] or _content(_ips_json(latest)) != _content(snap)
    msg = (f"The PM has an older version (v{rec['version']}). Send the updated version?" if outdated
           else f"Sent to the PM (v{rec['version']}).")
    return {"sent": True, "status": rec["status"], "sentVersion": rec["version"], "sentAt": rec["sentAt"],
            "latestVersion": latest.version, "outdated": outdated, "message": msg}


@router.get("/ips-send/{client_id}/snapshot")
async def get_ips_send_snapshot(client_id: str) -> dict:
    """The exact IPS the PM must open: frozen at send time, unaffected by later RM edits."""
    store = get_default_store()
    _require_in_book(store, client_id)
    rec = store.get_ips_send(client_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No IPS has been sent to the PM")
    return {**rec["snapshot"], "sentAt": rec["sentAt"], "rmId": rec["rmId"]}


@router.delete("/ips-send/{client_id}")
async def withdraw_ips_send(client_id: str) -> dict:
    """Withdraw: allowed any time after sending. Removes the sent state; the IPS content is kept."""
    store = get_default_store()
    _require_in_book(store, client_id)
    store.withdraw_ips_send(client_id)
    return {"status": "Draft"}
