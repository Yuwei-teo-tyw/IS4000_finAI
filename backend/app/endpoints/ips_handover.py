"""Onboarding hand-over after the RM's "Send to PM": PM working copy, PM return, RM activation.

  GET  /agents/client-profiling/pm-ips/{client_id}            PM's working 3L + SAA (seeded from the RM-sent snapshot)
  PUT  /agents/client-profiling/pm-ips/{client_id}            PM edits the 3L split and the Longevity/Legacy strategy (persisted)
  POST /agents/client-profiling/pm-ips/{client_id}/return     PM signs off -> status "Returned by PM"; edits written into the IPS version
  POST /agents/client-profiling/ips/{client_id}/{version}/activate   RM approves: Active, older superseded, indexed, client -> Monitoring
  POST /agents/client-profiling/ips/{client_id}/{version}/deactivate RM switches the Active version to Superseded; no Active left -> Onboarding 0%

Liquidity never has an SAA or strategy, anywhere here. The Portfolio Agent's option ids A-F are the strategy codes A-F, so the
RM-chosen strategy is the pre-selected option for that bucket.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.agents.client_profiling.ips_model import normalize_data, render_parts
from app.agents.client_profiling.store import IpsPartDoc, get_default_store
from app.agents.client_profiling.strategies import get_strategy
from app.endpoints.client_profiling import PREFIX, _client_name, _index_after_save, _ips_json, _require_in_book, _rm

router = APIRouter(prefix=PREFIX, tags=["ips-handover"])
RETURNED_STATUS = "Returned by PM"
ACTIVE_CLIENT_STATUS = "Monitoring Phase"
ALL = ("liquidity", "longevity", "legacy")
SAA_BUCKETS = ("longevity", "legacy")
LABEL = {"liquidity": "Liquidity", "longevity": "Longevity", "legacy": "Legacy"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _strategy_or_422(code: str) -> dict:
    s = get_strategy(code)
    if s is None:
        raise HTTPException(status_code=422, detail="Only strategies A to F exist")
    return s


def _seed(client, rec: dict) -> dict:
    """Working copy = what the RM sent: 3L proportions (amount = % x the client's assets) and the strategy per Longevity/Legacy."""
    d = normalize_data(rec["snapshot"].get("data"))
    prop = d.get("threeLProportion") if isinstance(d.get("threeLProportion"), dict) else {}
    total = float(client.aum_sgd or 0)
    three = {}
    for b in ALL:
        pct = (prop.get(b) or {}).get("pct")
        three[b] = {"pct": pct, "amount": round(total * pct / 100) if pct is not None and total else None,
                    "reason": (prop.get(b) or {}).get("reason", "")}
    by = {str(x.get("portfolio", "")).lower(): x for x in d.get("threeL") or []}
    saa = {}
    for b in SAA_BUCKETS:
        code = (by.get(b) or {}).get("strategy")
        s = get_strategy(code) if code else None
        saa[b] = {"strategy": s["code"] if s else None, "optionId": s["code"] if s else None, "source": "rm",
                  "weights": dict(s["allocation"]) if s else None, "reason": (by.get(b) or {}).get("reason", "")}
    return {"snapshotVersion": rec["version"], "sentAt": rec["sentAt"], "total": total, "threeL": three, "saa": saa,
            "edited": False, "updatedAt": _now()}


def _working(store, client_id: str, rec: dict) -> dict:
    w = store.get_pm_working(client_id)
    if w is None or w.get("snapshotVersion") != rec["version"] or w.get("sentAt") != rec["sentAt"]:  # re-sent -> start again from the new send
        w = _seed(store.get_client(client_id), rec)
        store.put_pm_working(client_id, w)
    return w


def _sent_or_404(store, client_id: str) -> dict:
    rec = store.get_ips_send(client_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="No IPS has been sent to the PM")
    return rec


def _out(store, client_id: str, rec: dict, w: dict) -> dict:
    return {"client_id": client_id, "clientName": _client_name(store, client_id), "status": rec["status"], "version": rec["version"],
            "returned": rec["status"] == RETURNED_STATUS, **w}


@router.get("/pm-ips/{client_id}")
async def get_pm_ips(client_id: str) -> dict:
    store = get_default_store()
    _require_in_book(store, client_id)
    rec = _sent_or_404(store, client_id)
    return _out(store, client_id, rec, _working(store, client_id, rec))


class BucketPct(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pct: float = Field(ge=0, le=100)


class SaaEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: str = Field(min_length=1, max_length=1)
    weights: Optional[dict[str, float]] = None  # PM-adjusted asset-class weights (% of the bucket); omit for the strategy's own
    reason: Optional[str] = Field(default=None, max_length=2000)


class PmIpsEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    threeL: Optional[dict[str, BucketPct]] = None
    saa: Optional[dict[str, SaaEdit]] = None
    reason: str = Field(default="", max_length=500)


def _check_weights(w: dict[str, float]) -> None:
    if any(v < 0 for v in w.values()) or abs(sum(w.values()) - 100) > 0.5:
        raise HTTPException(status_code=422, detail=f"Asset-class weights must be 0 or more and add up to 100% (now {sum(w.values()):g}%)")


@router.put("/pm-ips/{client_id}")
async def put_pm_ips(client_id: str, body: PmIpsEdit, x_rm_id: Optional[str] = Header(default=None), rm_id: Optional[str] = Query(default=None)) -> dict:
    store = get_default_store()
    _require_in_book(store, client_id)
    rec = _sent_or_404(store, client_id)
    if rec["status"] == RETURNED_STATUS:
        raise HTTPException(status_code=409, detail="Already returned to the RM. The RM must send the IPS again to reopen it.")
    w = _working(store, client_id, rec)
    if body.threeL is not None:
        if set(body.threeL) - set(ALL):
            raise HTTPException(status_code=422, detail="3L buckets are liquidity, longevity and legacy")
        pcts = {b: (body.threeL[b].pct if b in body.threeL else w["threeL"][b]["pct"]) for b in ALL}
        if any(v is None for v in pcts.values()) or abs(sum(pcts.values()) - 100) > 0.01:
            raise HTTPException(status_code=422, detail=f"The three buckets must add up to 100% (now {sum(v or 0 for v in pcts.values()):g}%)")
        for b in ALL:
            w["threeL"][b].update(pct=pcts[b], amount=round(w["total"] * pcts[b] / 100) if w["total"] else None)
    for b, e in (body.saa or {}).items():
        if b == "liquidity":
            raise HTTPException(status_code=422, detail="Liquidity has no SAA or strategy")
        if b not in SAA_BUCKETS:
            raise HTTPException(status_code=422, detail="SAA buckets are longevity and legacy")
        s = _strategy_or_422(e.strategy)
        if e.weights is not None:
            _check_weights(e.weights)
        old = w["saa"][b].get("strategy")
        if old != s["code"]:
            store.log_strategy_override(client_id, LABEL[b], old or "", s["code"], body.reason or "PM edit", _rm(x_rm_id, rm_id))
        w["saa"][b] = {"strategy": s["code"], "optionId": s["code"], "source": "pm",
                       "weights": e.weights if e.weights is not None else dict(s["allocation"]),
                       "reason": e.reason if e.reason is not None else w["saa"][b].get("reason", "")}
    w["edited"] = True
    w["updatedAt"] = _now()
    store.put_pm_working(client_id, w)
    return _out(store, client_id, rec, w)


def _apply_to_ips(data: dict, w: dict) -> dict:
    """Write the PM's 3L split and strategies into the IPS data. Every other section is left exactly as the RM wrote it."""
    d = json.loads(json.dumps(normalize_data(data)))
    prop = d.get("threeLProportion") if isinstance(d.get("threeLProportion"), dict) else {}
    d["threeLProportion"] = {b: {**(prop.get(b) or {}), "pct": w["threeL"][b]["pct"],
                                 "reason": (prop.get(b) or {}).get("reason") or w["threeL"][b].get("reason", "")} for b in ALL}
    by = {str(x.get("portfolio", "")).lower(): x for x in d.get("threeL") or []}
    rows = []
    for b in ALL:
        cur = dict(by.get(b) or {"portfolio": LABEL[b], "reason": "", "source": None, "default": False, "conflict": None})
        if b == "liquidity":
            cur.update(strategy=None, strategyName="")
        else:
            s = get_strategy(w["saa"][b]["strategy"])
            cur.update(strategy=s["code"], strategyName=s["name"], default=False)
            if w["saa"][b].get("source") == "pm":
                cur["reason"] = w["saa"][b].get("reason") or cur.get("reason", "")
        rows.append(cur)
    d["threeL"] = rows
    d["saa"] = {b: {"strategy": w["saa"][b]["strategy"], "weights": w["saa"][b]["weights"], "amount": w["threeL"][b]["amount"]} for b in SAA_BUCKETS}
    d["pmReturn"] = {"at": _now(), "edited": bool(w.get("edited"))}
    return normalize_data(d)


@router.post("/pm-ips/{client_id}/return")
async def return_ips_to_rm(client_id: str) -> dict:
    """PM signs off. Needs a complete working copy (100% split, a strategy for Longevity and Legacy)."""
    store = get_default_store()
    _require_in_book(store, client_id)
    rec = _sent_or_404(store, client_id)
    if rec["status"] == RETURNED_STATUS:
        raise HTTPException(status_code=409, detail="Already returned to the RM")
    w = _working(store, client_id, rec)
    pcts = [w["threeL"][b]["pct"] for b in ALL]
    if any(p is None for p in pcts) or abs(sum(pcts) - 100) > 0.01:
        raise HTTPException(status_code=409, detail="Set the 3L split so it adds up to 100% before returning")
    if any(not w["saa"][b].get("strategy") for b in SAA_BUCKETS):
        raise HTTPException(status_code=409, detail="Choose a strategy for Longevity and Legacy before returning")
    target = next((v for v in store.get_ips_versions(client_id) if v.version == rec["version"]), None)
    if target is None:
        raise HTTPException(status_code=409, detail="The sent IPS version no longer exists")
    data = _apply_to_ips(target.data, w)
    parts = [IpsPartDoc(**p) for p in render_parts(data)]
    saved = store.save_ips(client_id, parts, version=target.version, data=data)
    snap = {**_ips_json(saved), "status": RETURNED_STATUS, "clientId": client_id}
    new = store.update_ips_send(client_id, status=RETURNED_STATUS, snapshot=snap)
    w["returnedAt"] = _now()
    store.put_pm_working(client_id, w)
    return {"status": new["status"], "version": saved.version, "returnedAt": w["returnedAt"], "ips": _ips_json(saved)}


@router.post("/ips/{client_id}/{version}/activate")
async def activate_ips(client_id: str, version: int) -> dict:
    """G1 approval by the RM: only an IPS the PM returned can be activated."""
    store = get_default_store()
    _require_in_book(store, client_id)
    rec = store.get_ips_send(client_id)
    if rec is None or rec["status"] != RETURNED_STATUS or rec["version"] != version:
        raise HTTPException(status_code=409, detail="The PM has not returned this IPS version yet")
    if not store.activate_ips(client_id, version):
        raise HTTPException(status_code=404, detail="IPS version not found for this client")
    store.set_client_status(client_id, ACTIVE_CLIENT_STATUS)
    store.set_progress(client_id, onboarding=5)
    versions = store.get_ips_versions(client_id)
    return {"client_id": client_id, "version": version, "status": "Active", "clientStatus": ACTIVE_CLIENT_STATUS,
            "superseded": [v.version for v in versions if v.status == "Superseded"],
            "indexing": _index_after_save(store, client_id, version)}


@router.post("/ips/{client_id}/{version}/deactivate")
async def deactivate_ips(client_id: str, version: int) -> dict:
    """RM switches the Active IPS back to non-active (Superseded). With no Active IPS left, the client goes back to Onboarding at 0%."""
    store = get_default_store()
    _require_in_book(store, client_id)
    cur = next((v for v in store.get_ips_versions(client_id) if v.version == version), None)
    if cur is None:
        raise HTTPException(status_code=404, detail=f"IPS v{version} not found")
    if cur.status != "Active":
        raise HTTPException(status_code=409, detail=f"IPS v{version} is not the active version")
    if not store.deactivate_ips(client_id, version):
        raise HTTPException(status_code=409, detail=f"IPS v{version} is not the active version")
    # No active IPS left: the review pack goes with it and the client falls back to Onboarding at 0%, as in delete_client_ips.
    reset = not any(v.status == "Active" for v in store.get_ips_versions(client_id))
    if reset:
        store.delete_review_pack_state(client_id)
        store.withdraw_ips_send(client_id)
        store.set_client_status(client_id, "Onboarding Phase")
        store.set_progress(client_id, onboarding=0, monitoring=0)
    return {"client_id": client_id, "version": version, "status": "Superseded", "reset": reset}
