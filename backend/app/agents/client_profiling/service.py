"""Client Profiling Agent service (meeting notes only): resolves the client, retrieves notes, answers.

ONE local-model call both decides scope (`in_scope`) and answers (see answer.py); there is no keyword/regex
routing. Out-of-scope questions return tool `out_of_scope` (the frontend falls through to the old agents); if the
model is off, unreachable or invalid the result is `routing_unavailable` with no client data.
Private to this agent, NOT the app's intent parser/triage (untouched). Read-only: nothing here writes anything.
"""
import re
from typing import Optional

from .alloc_dialogue import allocation_intent, handle_allocation_turn, pending_from_history
from .answer import answer_question
from .guide import answer_guide_question, is_guide_question
from .extract import extract_key_facts
from .llm import ChatFn, fallback_active, last_model, model_name
from .presentation import build_sections, short_message
from .retrieval import get_meeting_note, read_meeting_note, resolve_client
from .schemas import SourceRef, ToolResult
from .source_router import MIN_CONFIDENCE, route_source
from .store import DocumentStore, StoreUnavailableError, get_default_store

_NOTE_ID = re.compile(r"\bnote_\w+\b", re.I)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

MAX_QUESTION_CHARS = 1000
# Safety net for the model's probabilistic `summary_request` flag, and the only routing available when the model is down.
_SUMMARY_WORDS = re.compile(r"\b(summar(?:y|ies|i[sz]e[sd]?|i[sz]ing)|recap|sum up|overview of (?:the |all )?(?:meeting|notes?))\b", re.I)
REFUSAL_TEXT = "I can't answer that from this client's records."


def handle_chat(
    message: str,
    client_id: Optional[str] = None,
    ips_version: Optional[int] = None,  # kept for the endpoint signature; unused (notes only)
    draft_sections: Optional[dict[str, str]] = None,  # unused
    allocation_overrides: Optional[dict[str, int]] = None,  # unused
    store: Optional[DocumentStore] = None,
    answer_chat: Optional[ChatFn] = None,
    router_chat: Optional[ChatFn] = None,  # fake for the source router (tests); see the routing comment below
    book: Optional[list[str]] = None,  # client ids the RM oversees; None = no restriction
    source: Optional[str] = None,  # "notes" | "ips" | "both": the adviser's explicit choice; None = route automatically
    allocation: Optional[dict] = None,  # IS-89/90: the current 3L allocation {"buckets": [{id, strategy, justification}]}
    history: Optional[list] = None,  # IS-90: earlier turns [{role, text, proposal?}]
    pending_proposal: Optional[dict] = None,  # IS-90: an unconfirmed proposal from the previous turn
) -> ToolResult:
    # Input guards first: no store access, no model call.
    text = (message or "").strip()
    if not text:
        return ToolResult(tool="invalid_question", status="needs_clarification", message="Please enter a question.")
    if len(message) > MAX_QUESTION_CHARS:
        return ToolResult(tool="invalid_question", status="needs_clarification",
                          message="Your question is over 1,000 characters. Please shorten or rephrase it.")
    store = store or get_default_store()
    # 3L / strategies A-F / risk-budget questions are answered from the Investor Profile guide + strategy table
    # (deterministic fast path: no client resolution needed, no router call). Explicit notes/ips/both choices win.
    alloc_intent = None
    if source not in ("guide", "notes", "ips", "both"):  # IS-89/90: justify / challenge / confirm the 3L allocation
        alloc_intent = allocation_intent(text, history, pending_proposal or pending_from_history(history))
        if alloc_intent == "challenge" and allocation is None and not _is_alloc_followup(history):
            alloc_intent = None  # "does she want more liquidity?" is a notes question unless an allocation is in play
    if source == "guide" or (not alloc_intent and source not in ("notes", "ips", "both") and is_guide_question(text)):
        return _handle_guide(message, store, client_id, answer_chat)
    try:
        res = resolve_client(message, client_id, store=store)
    except StoreUnavailableError:  # same Postgres holds both sources: say so, and never answer from the other one
        down, other = ("IPS", "meeting notes") if source == "ips" else ("meeting-notes", "IPS")
        return _unavailable(down, other)
    if res.status != "ok":  # ambiguous/unknown: never guess, never return client data
        cands = res.candidates if book is None else [c for c in res.candidates if c.get("id") in set(book)]
        return ToolResult(tool="resolve_client", status=res.status, message=res.message, candidates=cands)
    cid = res.data["client_id"]
    if book is not None and cid not in set(book):  # before ANY retrieval or model call
        return ToolResult(tool="access_denied", status="insufficient_information",
                          message="I cannot access this client's meeting notes because they are not in your book.")
    if alloc_intent:
        res_a = handle_allocation_turn(store, cid, message, history, allocation, pending_proposal, answer_chat)
        if res_a is not None:
            return ToolResult(tool="allocation_dialogue", status="ok" if res_a["status"] == "ok" else "insufficient_information",
                              client_id=cid, message=res_a["text"], data={"allocation_dialogue": res_a})
    # Source routing (IS-78/79/80). Order: guards -> client -> book check (above) -> source -> retrieval.
    # An explicit `source` is the adviser's choice (confidence 1). Summaries are always notes (no router call).
    # Compatibility: tests inject only `answer_chat` (a fake for the notes call); with no router_chat and no
    # explicit source that means notes at confidence 1, so the router is skipped. Production passes neither
    # chat fn, so the real local-model router runs.
    if source in ("notes", "ips", "both"):
        src, conf = source, 1.0
    elif _SUMMARY_WORDS.search(text) or (router_chat is None and answer_chat is not None):
        src, conf = "notes", 1.0
    else:
        routed = route_source(message, router_chat)
        if routed is None:  # never guess
            return _routing_unavailable()
        src, conf = routed["source"], routed["confidence"]
    if src == "out_of_scope":
        return ToolResult(tool="out_of_scope", status="insufficient_information", client_id=cid,
                          message="I can't answer that question.",
                          data={"routing": {"method": "local_llm", "source": "out_of_scope", "confidence": conf},
                                "answer": {"status": "cannot_answer", "text": REFUSAL_TEXT, "sections": [], "sources": []}})
    if src == "unclear" or conf < MIN_CONFIDENCE:  # ask BEFORE retrieving; no client data in the result
        return ToolResult(tool="clarify_source", status="needs_clarification", client_id=cid,
                          message="Do you mean the meeting notes or the IPS?",
                          data={"options": [{"source": "notes", "label": "Meeting notes"}, {"source": "ips", "label": "IPS"},
                                            {"source": "both", "label": "Both"}],
                                "routing": {"method": "local_llm", "source": "unclear", "confidence": conf}})
    info = {"method": "local_llm", "source": src, "confidence": conf}
    if src == "ips":
        return _handle_ips(message, store, cid, answer_chat, info)
    if src == "both":
        return _handle_both(message, store, cid, answer_chat, info)
    try:
        r = _handle_notes(message, text, store, cid, answer_chat)
    except StoreUnavailableError:
        return _unavailable("meeting-notes", "IPS")
    if isinstance(r.data.get("routing"), dict):
        r.data["routing"].update({"source": "notes", "confidence": conf})
    return r


def _is_alloc_followup(history) -> bool:
    for h in reversed(history or []):
        if isinstance(h, dict) and h.get("role") in ("assistant", "agent"):
            return bool(re.search(r"\b(?:Agrees|Disagrees|Partly agrees)\b", str(h.get("text"))))
    return False


def _handle_guide(message, store, cid, chat) -> ToolResult:
    ans = answer_guide_question(message, store, chat)
    ok = ans["status"] == "ok"
    return ToolResult(tool="get_guide", status="ok" if ok else "insufficient_information", client_id=cid,
                      message=ans["text"],
                      data={"answer": ans, "routing": {"method": "deterministic", "source": "guide", "confidence": 1.0}})


def _routing_unavailable() -> ToolResult:
    return ToolResult(tool="routing_unavailable", status="insufficient_information",
                      message="The local model is unavailable, so this question was not routed.",
                      data={"routing": {"method": "unavailable", "model": None, "scope": None,
                                        "note": "local model off, unreachable or invalid answer"}})


def _unavailable(down: str, not_used: str, cid: Optional[str] = None) -> ToolResult:
    return ToolResult(tool="source_unavailable", status="insufficient_information", client_id=cid,
                      message=f"The {down} database is unavailable, so I can't answer this. I have not used the {not_used} instead.")


def _ips_answer(message, store, cid, chat) -> Optional[dict]:
    """IPS answer dict (may raise StoreUnavailableError). Imported lazily: module owned elsewhere."""
    from .ips_answer import answer_ips_question
    return answer_ips_question(message, store, cid, chat)


def _handle_ips(message, store, cid, chat, info) -> ToolResult:
    try:
        ans = _ips_answer(message, store, cid, chat)
    except StoreUnavailableError:
        return _unavailable("IPS", "meeting notes", cid)
    if ans is None:
        r = _routing_unavailable()
        r.client_id = cid
        r.message = "The local model is unavailable, so I could not answer from the IPS. I have not used the meeting notes instead."
        return r
    st = ans.get("status")
    if st == "no_ips":
        status, msg = "not_found", "This client has no IPS yet."
    elif st == "ok":
        status, msg = "ok", ans.get("text") or ""
    else:
        status, msg = "insufficient_information", ans.get("text") or "I can't answer that from this client's IPS."
    srcs = [SourceRef(**x) for x in (ans.get("sources") or [])] if st == "ok" else []
    return ToolResult(tool="get_ips", status=status, client_id=cid, message=msg,
                      data={"answer": ans, "routing": info}, sources=srcs)


def _notes_block(message, store, cid, chat) -> dict:
    """Notes side of a comparison: plain answer dict; its own unavailable/no-data message, never IPS content."""
    try:
        if not store.get_notes(cid):
            return {"status": "no_data", "text": "No meeting notes found.", "sections": [], "sources": []}
        ans = answer_question(message, store, extract_key_facts(store, cid), chat)
    except StoreUnavailableError:
        return {"status": "unavailable", "text": "The meeting-notes database is unavailable. I have not used the IPS instead.",
                "sections": [], "sources": []}
    if ans is None:
        return {"status": "unavailable", "text": "The local model is unavailable, so the meeting notes were not read.",
                "sections": [], "sources": []}
    if ans.get("status") == "out_of_scope":
        return {"status": "cannot_answer", "text": REFUSAL_TEXT, "sections": [], "sources": []}
    return ans


def _handle_both(message, store, cid, chat, info) -> ToolResult:
    notes = _notes_block(message, store, cid, chat)
    try:
        ips = _ips_answer(message, store, cid, chat)
        if ips is None:
            ips = {"status": "unavailable", "text": "The local model is unavailable, so the IPS was not read.", "sections": [], "sources": []}
        elif ips.get("status") == "no_ips":
            ips = {**ips, "status": "no_data", "text": "This client has no IPS yet."}
    except StoreUnavailableError:
        ips = {"status": "unavailable", "text": "The IPS database is unavailable. I have not used the meeting notes instead.",
               "sections": [], "sources": []}
    srcs = []
    for a in (notes, ips):
        srcs += [SourceRef(**x) for x in (a.get("sources") or []) if isinstance(x, dict)]
    return ToolResult(tool="compare_sources", status="ok", client_id=cid,
                      message="Meeting notes and IPS compared; each statement is labelled with its source.",
                      data={"both": {"notes": {"label": "Meeting notes", "answer": notes}, "ips": {"label": "IPS", "answer": ips}},
                            "routing": info}, sources=srcs)


def _handle_notes(message: str, text: str, store, cid: str, answer_chat: Optional[ChatFn]) -> ToolResult:
    if not store.get_notes(cid):  # nothing to retrieve: a clear "no results" at once, no model call, never another source
        return ToolResult(tool="get_meeting_note", status="not_found", client_id=cid, message="No meeting notes found.",
                          data={"routing": {"method": "local_llm", "scope": "notes", "source": "notes"}})
    profile = extract_key_facts(store, cid)
    try:
        ans = answer_question(message, store, profile, answer_chat)  # the single model call
    except StoreUnavailableError:
        raise
    except Exception:
        ans = None
    if ans is None and _SUMMARY_WORDS.search(text):  # model down: deterministic extractive summary, clearly labelled
        from . import summary as summary_mod
        fb = summary_mod.extractive_summary(store, cid)
        if fb.get("status") == "no_notes":
            return ToolResult(tool="get_meeting_note", status="not_found", client_id=cid, message="No meeting notes found.",
                              data={"routing": {"method": "fallback", "model": None, "scope": "notes"}})
        return ToolResult(tool="get_meeting_note", status="ok", client_id=cid, message=fb["notice"],
                          data={"summary": fb, "routing": {"method": "fallback", "model": None, "scope": "notes"},
                                "answer": {"status": "ok", "sources": [], "summary_request": True}})
    if ans is None:  # never guess
        return ToolResult(tool="routing_unavailable", status="insufficient_information",
                          message="The local model is unavailable, so this question was not routed.",
                          data={"routing": {"method": "unavailable", "model": None, "scope": None,
                                            "note": "local model off, unreachable or invalid answer"}})
    routing = {"method": "local_llm", "model": (last_model() if fallback_active() else None) or model_name(),
               "scope": "notes", **({"fallback": True} if fallback_active() else {})}
    if ans["status"] == "out_of_scope":
        return ToolResult(tool="out_of_scope", status="insufficient_information", client_id=cid,
                          message="I can't answer that question.",
                          data={"routing": {**routing, "scope": None},
                                "answer": {"status": "cannot_answer", "text": REFUSAL_TEXT, "sections": [], "sources": []}})
    summary, summary_error = None, None
    if _SUMMARY_WORDS.search(text) and not ans.get("summary_request"):
        ans["summary_request"] = True  # explicit "summarise/recap" wording must not depend on the model's flag
    if ans.get("summary_request"):
        from . import summary as summary_mod  # lazy: owned by another module
        try:
            fmt = (ans.get("summary_format") or "").strip()  # adviser asked for a layout: follow it; else default template
            summary = (summary_mod.summarise_notes(store, cid, answer_chat, instruction=fmt) if fmt
                       else summary_mod.summarise_notes(store, cid, answer_chat))
        except Exception as exc:  # never silent: try the extractive fallback and tell the caller what happened
            summary_error = f"{type(exc).__name__}: {exc}"
            try:
                summary = summary_mod.extractive_summary(store, cid)
            except Exception:
                summary = None
        if summary is not None and summary.get("status") == "no_notes":
            return ToolResult(tool="get_meeting_note", status="not_found", client_id=cid,
                              message="No meeting notes found.", data={"routing": routing})
    nid, d = _NOTE_ID.search(message), _DATE.search(message)
    if nid:  # explicit note id: read that note in full
        r = read_meeting_note(cid, nid.group(0).lower(), None, store=store)
    else:  # explicit date if given, else every note (the grounded answer already focuses on the question)
        r = get_meeting_note(cid, date=d.group(0) if d else None, date_from=None if d else "0000-01-01", limit=10, store=store)
        if r.status == "ok":
            r.data["summarise"] = True
            r.message = f"Summarised {len(r.data.get('notes', []))} meeting note(s)."
    try:
        sections = [sec.model_dump(mode="json") for sec in build_sections(r, profile)]
    except Exception:  # presentation must never break the tool result
        sections = []
    inference = (ans.get("inference") or "").strip() if isinstance(ans.get("inference"), str) else ""
    if summary is not None:
        r.data["summary"] = summary
        ans = {k: v for k, v in ans.items() if k != "inference"}
        ans["status"] = "ok"
        if not (ans.get("text") or "").strip():  # pure summary: no answer text (and no cannot_answer text)
            ans.pop("text", None)
            ans["sources"] = []
        r.data["answer"] = ans
        r.message = ans.get("text") or ""
    else:
        r.data["answer"] = ans
        r.message = "" if ans.get("status") == "cannot_answer" else (ans.get("text") or r.message or "")
    if inference:
        r.data["answer"]["inference"] = {"label": "Inference (not from the notes)", "text": inference}
    elif isinstance(r.data["answer"].get("inference"), str):
        del r.data["answer"]["inference"]
    r.data["routing"] = routing
    if summary_error:
        r.data["summary_error"] = summary_error
        if summary is not None:
            r.message = summary.get("notice") or r.message
        else:
            r.message = "The summary could not be generated. Please try again."
    if sections and summary is None:  # a summary already carries the facts; showing the key-facts sections too repeats them
        r.data["sections"] = sections
    r.message = short_message(r.message) if r.message else ""
    r.client_id = r.client_id or cid
    return r
