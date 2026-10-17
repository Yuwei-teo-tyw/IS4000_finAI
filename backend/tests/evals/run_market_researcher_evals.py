"""
Run the market researcher eval set (tests/evals/market_researcher.yaml)
against live APIs and report per-case checks. Not part of pytest - it
costs API calls and an LLM call per case (two with a narrative).

    cd backend && python tests/evals/run_market_researcher_evals.py

Checks per case:
  schema      output re-validates as MarketResearchOutput
  citations   every indicator/price has a source_url, every news item a URL,
              and every event's evidence ids exist in the output
  regime      phase set, probabilities sum to ~1, recession_prob_12m set
  relevance   at least one news item mentions an expected term (if given)
  numbers     narrative passes the number/label validator and is not the
              template fallback (narrative cases only)
  extras      the plan picked at least one expected catalog extra (if
              `expect_extras_any` is given)
  catalog     the planner proposed nothing outside the catalogs
  explained   every `explained` event cites URLs, and no explanation was
              rejected by the validator (no "unavailable: draft ..." note)
  quality     the final quality gate did not mark the run `unusable`
"""
import asyncio
import sys
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))


async def run_case(service, case: dict) -> dict:
    from app.agents.market_researcher.schemas import MarketResearchOutput, MarketResearchRequest
    from app.agents.market_researcher.synthesis import allowed_numbers, build_payload, problems

    result = await service.run(MarketResearchRequest(**case["request"]))
    out = MarketResearchOutput.model_validate_json(result.json_path.read_text())
    checks = {"schema": True}

    known_ids = {i.id for i in out.indicators} | {m.id for m in out.market_snapshot} | {"UNRATE"}
    checks["citations"] = (
        all(i.source_url for i in out.indicators + out.market_snapshot)
        and all(n.url.startswith("http") for n in out.news)
        and all(set(e.evidence) <= known_ids for e in out.events)
    )
    probs = out.regime.probabilities
    checks["regime"] = bool(out.regime.phase) and abs(sum(probs.values()) - 1) < 0.01 and out.regime.recession_prob_12m is not None

    terms = [t.lower() for t in case.get("expect_news_terms") or []]
    if terms:
        text = " ".join(f"{n.title} {n.summary}".lower() for n in out.news)
        checks["relevance"] = any(t in text for t in terms)

    if out.plan is not None:
        checks["catalog"] = not any("not in catalog" in d for d in out.plan.dropped)
    expected_extras = set(case.get("expect_extras_any") or [])
    if expected_extras:
        picked = {i.id for i in out.planned_indicators} | {m.id for m in out.planned_market}
        checks["extras"] = bool(picked & expected_extras)
    if out.event_explanations:
        checks["explained"] = (
            all(x.cited_urls for x in out.event_explanations if x.status == "explained")
            and not any("unavailable: draft" in n for n in out.data_quality.notes)
        )

    checks["quality"] = out.quality is not None and out.quality.status != "unusable"

    if case["request"].get("include_narrative"):
        payload = build_payload(out)
        texts = [out.narrative or "", *(out.key_themes or []), *(out.risks or []), *(out.implications or {}).values()]
        is_template = any("deterministic template" in n for n in out.data_quality.notes)
        checks["numbers"] = not problems(texts, allowed_numbers(payload), payload) and not is_template
    plan = out.plan.plan.extra_series + out.plan.plan.extra_symbols if out.plan and out.plan.plan else []
    return {"id": case["id"], "checks": checks, "phase": out.regime.phase, "news": len(out.news),
            "failed_sources": out.data_quality.failed_sources, "plan": plan,
            "explanations": [f"{x.event_id}:{x.status}" for x in out.event_explanations],
            "quality": out.quality.status if out.quality else None}


async def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(BACKEND.parent / ".env")
    from app.agents.market_researcher import MarketResearchService
    from app.agents.market_researcher.cache import InMemoryCache

    cases = yaml.safe_load((Path(__file__).parent / "market_researcher.yaml").read_text())["cases"]
    if "--narrative-only" in sys.argv:
        cases = [c for c in cases if c["request"].get("include_narrative")]
    out_dir = BACKEND / "data" / "market_research" / "evals"
    service = MarketResearchService(cache=InMemoryCache(), out_dir=out_dir)  # shared cache: macro data fetched once

    failures = 0
    for case in cases:
        try:
            r = await run_case(service, case)
        except Exception as e:
            failures += 1
            print(f"FAIL {case['id']}: {type(e).__name__}: {e}")
            continue
        ok = all(r["checks"].values())
        failures += not ok
        marks = " ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in r["checks"].items())
        extra = f" failed_sources={r['failed_sources']}" if r["failed_sources"] else ""
        print(f"{'PASS' if ok else 'FAIL'} {r['id']:<18} phase={r['phase']} news={r['news']} {marks}{extra}")
        print(f"     quality={r['quality']} plan={r['plan']} explanations={r['explanations']}")
    print(f"\n{len(cases) - failures}/{len(cases)} cases passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
