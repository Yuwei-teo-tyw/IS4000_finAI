"""
Product Recommender LLM layer: reasons and asset-class narratives.

Offline: every LLM call goes to a FakeLLM with canned structured outputs.
The engine decides what is recommended; these tests check that the LLM
only changes text, that the guardrail catches each rule, and that every
failure falls back to the rule-based text.
"""
import asyncio
import re

import pytest
from conftest import FakeLLM, run_async
from portfolio_helpers import market_fetcher_from, mock_market
from test_product_recommender import CLIENTS, FIXED_NOW, request

from app.agents.portfolio_manager.explain.llm_client import LLMUnavailable
from app.agents.portfolio_manager.taxonomy import ASSET_CLASS_ORDER
from app.agents.product_recommender import guardrails
from app.agents.product_recommender.asset_views.narrative import NarrativeOut, SlotText, view_facts
from app.agents.product_recommender.config import Settings
from app.agents.product_recommender.explain import ProductReasonOut, ReasonsOut, fee_line, llm_reasons, reasons_facts
from app.agents.product_recommender.service import ProductRecommenderService
from app.prompts.prompt_builder import get_prompt_version

SETTINGS = Settings(llm_enabled=True, llm_timeout_seconds=5)


def llm_service(fake, **kw) -> ProductRecommenderService:
    kw.setdefault("market_fetcher", market_fetcher_from(mock_market()))
    kw.setdefault("llm_factory", lambda s: fake)
    return ProductRecommenderService(settings=SETTINGS, clock=lambda: FIXED_NOW, **kw)


def rules_only(client_id="ser", **kw):
    return llm_service(None).recommend(request(client_id, **kw))


def drafts_as_llm(resp) -> ReasonsOut:
    """An LLM answer that repeats the rule-based drafts: the guardrail must accept its own drafts."""
    return ReasonsOut(reasons=[ProductReasonOut(product_id=p["product_id"], bullets=p["draft_bullets"][:5])
                               for p in reasons_facts(resp)["products"]])


def with_bullet(out: ReasonsOut, pid: str, bullet: str) -> ReasonsOut:
    out = out.model_copy(deep=True)
    r = next(r for r in out.reasons if r.product_id == pid)
    r.bullets = [bullet, *r.bullets[1:]]
    return out


def _order(resp):
    return [(s.rank, s.product.product_id, s.score.total) for s in resp.shortlist]


# --- Reasons -----------------------------------------------------------------

@pytest.mark.parametrize("client_id", sorted(CLIENTS))
def test_rule_based_drafts_pass_the_guardrail(client_id):
    resp = rules_only(client_id)
    fake = FakeLLM(drafts_as_llm(resp))
    out, status = run_async(llm_reasons(resp, SETTINGS, lambda s: fake))
    assert status.source == "LLM" and status.llm_succeeded
    assert all(s.reason.source == "llm" for s in out.shortlist)
    assert len(fake.calls) == 1


def test_llm_reasons_change_text_only():
    resp = rules_only("teo")
    llm_text = drafts_as_llm(resp)
    for r in llm_text.reasons:
        r.bullets = [f"Reworded: {b}" for b in r.bullets]
    out, _ = run_async(llm_reasons(resp, SETTINGS, lambda s: FakeLLM(llm_text)))
    assert _order(out) == _order(resp)
    assert out.excluded == resp.excluded and out.eligible_not_shortlisted == resp.eligible_not_shortlisted
    for before, after in zip(resp.shortlist, out.shortlist):
        assert after.costs == before.costs and after.reason.citations == before.reason.citations
        lines = after.reason.text.splitlines()
        assert all(line.startswith("• Reworded: ") for line in lines[:-1])
        assert lines[-1] == f"• {fee_line(after.product.product_id)}"


def test_calls_are_traced_with_prompt_versions_and_no_client_id():
    resp = rules_only("dso")
    fake = FakeLLM(drafts_as_llm(resp))
    run_async(llm_reasons(resp, SETTINGS, lambda s: fake))
    meta = fake.configs[0]["metadata"]
    keys = ["product_recommender.reasons_system", "product_recommender.reasons_user"]
    assert meta["prompt_versions"] == {k: get_prompt_version(k) for k in keys}
    assert meta["langfuse_session_id"] == resp.request_id and "dso" not in str(fake.configs[0])


def test_prompt_carries_no_client_identifier_and_no_fees():
    resp = rules_only("dso")
    fake = FakeLLM(drafts_as_llm(resp))
    run_async(llm_reasons(resp, SETTINGS, lambda s: fake))
    sent = str(fake.calls[0])
    assert "dso" not in sent and "management_fee" not in sent
    assert "fee is shown" not in sent


@pytest.mark.parametrize("bullet, problem", [
    ("Its low fee makes it attractive [{pid}].", "mentions fees"),
    ("It is cheaper than its peers [{pid}].", "mentions cost"),
    ("You should buy this for steady income [{pid}].", "advice wording"),
    ("This is the best fit on the shelf [{pid}].", "superlative"),
    ("Returns are guaranteed over the horizon [{pid}].", "guarantee"),
    ("It has returned 14.7% a year since launch [{pid}].", "number 14.7"),
    ("It suits the client's objective [HV-1999-01-p1].", "unknown citation"),
    ("It suits the client's objective.", "does not end in a citation"),
    ("It pairs well with {other} [{pid}].", "names another product"),
])
def test_guardrail_rejects_each_rule(bullet, problem):
    resp = rules_only("ser")
    pid, other = resp.shortlist[0].product.product_id, resp.shortlist[1].product.product_id
    bad = with_bullet(drafts_as_llm(resp), pid, bullet.format(pid=pid, other=other))
    fake = FakeLLM(bad, bad)
    out, status = run_async(llm_reasons(resp, SETTINGS, lambda s: fake))
    assert out.shortlist[0].reason == resp.shortlist[0].reason  # rule-based text kept
    assert all(s.reason.source == "llm" for s in out.shortlist[1:])
    assert status.source == "LLM" and pid in status.detail
    assert problem in str(fake.calls[1][-1])  # the retry is told what was wrong


def test_retry_fixes_a_rejected_product():
    resp = rules_only("ser")
    pid = resp.shortlist[0].product.product_id
    good = drafts_as_llm(resp)
    fake = FakeLLM(with_bullet(good, pid, f"Fees are low [{pid}]."), good)
    out, status = run_async(llm_reasons(resp, SETTINGS, lambda s: fake))
    assert all(s.reason.source == "llm" for s in out.shortlist)
    assert len(fake.calls) == 2 and "Rule-based text kept" not in status.detail


def test_missing_product_counts_as_rejected():
    resp = rules_only("ser")
    partial = drafts_as_llm(resp)
    partial.reasons = partial.reasons[1:]
    out, _ = run_async(llm_reasons(resp, SETTINGS, lambda s: FakeLLM(partial, partial)))
    assert out.shortlist[0].reason.source == "deterministic"


@pytest.mark.parametrize("failure, source", [
    (LLMUnavailable("GROQ_API_KEY is not set."), "DETERMINISTIC"),
    (asyncio.TimeoutError(), "DETERMINISTIC_FALLBACK"),
    (RuntimeError("provider down"), "DETERMINISTIC_FALLBACK"),
    ("not json", "DETERMINISTIC_FALLBACK"),
])
def test_failures_fall_back_to_rule_based_reasons(failure, source):
    resp = rules_only("ser")

    def factory(s):
        if isinstance(failure, LLMUnavailable):
            raise failure
        return FakeLLM(failure, failure)
    out, status = run_async(llm_reasons(resp, SETTINGS, factory))
    assert status.source == source and not status.llm_succeeded
    assert [s.reason for s in out.shortlist] == [s.reason for s in resp.shortlist]


def test_a_provider_error_is_retried_once_but_a_timeout_is_not():
    resp = rules_only("ser")
    flaky = FakeLLM(RuntimeError("tool_use_failed"), drafts_as_llm(resp))
    out, status = run_async(llm_reasons(resp, SETTINGS, lambda s: flaky))
    assert status.source == "LLM" and len(flaky.calls) == 2
    slow = FakeLLM(asyncio.TimeoutError(), drafts_as_llm(resp))
    _, status = run_async(llm_reasons(resp, SETTINGS, lambda s: slow))
    assert status.source == "DETERMINISTIC_FALLBACK" and len(slow.calls) == 1


def test_bullet_full_stop_moves_after_the_tag():
    resp = rules_only("ser")
    pid = resp.shortlist[0].product.product_id
    out, _ = run_async(llm_reasons(resp, SETTINGS, lambda s: FakeLLM(with_bullet(drafts_as_llm(resp), pid, f"Daily dealing. [{pid}]."))))
    assert out.shortlist[0].reason.text.splitlines()[0] == f"• Daily dealing [{pid}]."


def test_recommend_explained_ranks_exactly_like_recommend():
    resp = rules_only("jfr")
    out = run_async(llm_service(FakeLLM(drafts_as_llm(resp))).recommend_explained(request("jfr")))
    assert _order(out) == _order(resp)
    assert out.explanation_status.source == "LLM"


def test_llm_disabled_by_setting():
    svc = ProductRecommenderService(settings=Settings(llm_enabled=False), clock=lambda: FIXED_NOW)
    out = run_async(svc.recommend_explained(request("ser")))
    assert out.explanation_status.source == "DETERMINISTIC"
    assert all(s.reason.source == "deterministic" for s in out.shortlist)


# --- Asset-class narratives --------------------------------------------------

def rules_view(ac="Equities"):
    return run_async(llm_service(None, llm_factory=_unavailable).asset_class_view(ac))


def _unavailable(s):
    raise LLMUnavailable("off")


_TAGS = re.compile(r"\s*\[[A-Za-z0-9-]+\]")


def view_drafts_as_llm(v) -> NarrativeOut:
    return NarrativeOut(items=[SlotText(id=i["id"], text=_TAGS.sub("", i["draft"])) for i in view_facts(v)["items"]])


@pytest.mark.parametrize("ac", [a.value for a in ASSET_CLASS_ORDER])
def test_view_drafts_pass_the_guardrail(ac):
    v = rules_view(ac)
    fake = FakeLLM(view_drafts_as_llm(v))
    out = run_async(llm_service(fake).asset_class_view(ac))
    assert out.narrative_source == "llm" and "Rule-based text kept" not in out.explanation_status.detail
    assert out.agent_view.view == v.agent_view.view and out.agent_view.confidence == v.agent_view.confidence
    assert [s.view for s in out.segments] == [s.view for s in v.segments]
    assert [r.refs for r in out.risks] == [r.refs for r in v.risks]
    if out.agreement and out.agreement.explanation:
        assert out.agreement.explanation.endswith(f"[{v.cio_view.citation_id}].")


def _with_slot(out: NarrativeOut, sid: str, text: str) -> NarrativeOut:
    out = out.model_copy(deep=True)
    next(i for i in out.items if i.id == sid).text = text
    return out


def test_view_guardrail_keeps_engine_stances():
    v = rules_view("Equities")
    other = next(s for s in ("Buy", "Hold", "Sell") if s not in (v.agent_view.view, v.cio_view.view))
    bad = _with_slot(view_drafts_as_llm(v), "thesis", f"{other} with high confidence on the back of strong data.")
    out = run_async(llm_service(FakeLLM(bad, bad)).asset_class_view("Equities"))
    assert out.agent_view.thesis == v.agent_view.thesis
    assert out.narrative_source == "llm"  # the other slots were accepted


@pytest.mark.parametrize("text, problem", [
    ("Equities will rise as earnings grow.", "forecast"),
    ("Our view is constructive on the asset class.", "bank's own"),
    ("Investors should add exposure here.", "advice"),
])
def test_view_guardrail_rejects_each_rule(text, problem):
    v = rules_view("Equities")
    allowed = guardrails.numbers_in(str(view_facts(v)))
    problems = guardrails.check_view_slot("risk", text, allowed, agent_view=v.agent_view.view,
                                          agent_confidence=v.agent_view.confidence, cio_view=v.cio_view.view,
                                          cio_term=v.cio_view.cio_term)
    assert any(problem in p for p in problems)


def test_typographic_hyphens_do_not_hide_evidence_names():
    v = next(v for v in map(rules_view, [a.value for a in ASSET_CLASS_ORDER]) if v.agreement and v.agreement.status != "aligned")
    name = next(s.name for s in v.snapshot if s.effect != "neutral" and "-" in s.name)
    text = (f"The CIO rates it {v.cio_view.cio_term}; the agent view differs, driven by the "
            f"{name.replace('-', chr(0x2011))}.")
    out = run_async(llm_service(FakeLLM(_with_slot(view_drafts_as_llm(v), "agreement", text))).asset_class_view(v.asset_class))
    assert out.agreement.explanation.startswith(f"The CIO rates it {v.cio_view.cio_term}; the agent view differs, driven by the {name}")


def test_a_scenario_may_name_the_stance_it_would_move_to():
    v = next(v for v in map(rules_view, [a.value for a in ASSET_CLASS_ORDER])
             if any(guardrails.stances_in(s.stance_implication) - {v.agent_view.view, v.cio_view.view} for s in v.scenarios))
    s = next(s for s in v.scenarios if guardrails.stances_in(s.stance_implication) - {v.agent_view.view, v.cio_view.view})
    new = (guardrails.stances_in(s.stance_implication) - {v.agent_view.view, v.cio_view.view}).pop()
    text = f"If conditions shift as the trigger describes, the agent view would move to {new}."
    out = run_async(llm_service(FakeLLM(_with_slot(view_drafts_as_llm(v), f"scenario_{s.case}", text))).asset_class_view(v.asset_class))
    assert next(x for x in out.scenarios if x.case == s.case).description == text


def test_view_narrative_is_cached_per_market_run():
    v = rules_view("Fixed Income")
    fake = FakeLLM(view_drafts_as_llm(v))
    svc = llm_service(fake)
    first = run_async(svc.asset_class_view("Fixed Income"))
    second = run_async(svc.asset_class_view("Fixed Income"))
    assert len(fake.calls) == 1
    assert second.agent_view.thesis == first.agent_view.thesis and second.narrative_source == "llm"


def test_view_falls_back_when_llm_unavailable():
    v = rules_view("Equities")
    assert v.narrative_source == "deterministic" and v.explanation_status.source == "DETERMINISTIC"
