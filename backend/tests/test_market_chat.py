"""
Optional chat trigger for the market researcher: the MarketResearcher
graph node, the end-to-end triage -> market_researcher path, the
deterministic renderer, and the General Assistant staying separate (it
has no access to the market researcher).
The pipeline runs for real against the stubbed providers from
test_market_service; every LLM is a FakeLLM.
"""
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver

import app.agents.market_researcher.news_tagging as tagging_module
import app.agents.market_researcher.synthesis as synthesis_module
import app.agents.nodes.market_researcher as node_module
import app.agents.nodes.general as general_module
import app.agents.tools as tools_module
from app.agents.graph import build_graph
from app.agents.market_researcher.audit import InMemoryAuditLog, sha256_of
from app.agents.market_researcher.news_tagging import NewsTagBatch
from app.agents.market_researcher.render import render_markdown
from app.agents.market_researcher.schemas import Event, EventExplanation, Indicator, MarketResearchRequest, QualityReport
from app.agents.market_researcher.synthesis import use_template
from app.agents.nodes.market_researcher import MarketResearcher, MarketScope
from app.agents.nodes.triage import RoutingDecision

from conftest import FakeLLM, run_async
from test_graph_integration import _patch_all_llms
from test_market_service import make_service, quiet_planner_and_explainer
from test_market_synthesis import make_output


def _quiet_pipeline_llms(monkeypatch):
    monkeypatch.setattr(tagging_module, "get_groq_model", lambda: FakeLLM(NewsTagBatch(items=[])))
    # synthesis LLM unavailable -> deterministic template narrative
    monkeypatch.setattr(synthesis_module, "get_groq_model", lambda: FakeLLM(RuntimeError("no LLM in tests")))
    quiet_planner_and_explainer(monkeypatch)


def test_node_out_of_scope_hands_back_to_triage(monkeypatch, tmp_path):
    monkeypatch.setattr(node_module, "get_groq_model", lambda: FakeLLM(MarketScope(in_scope=False)))
    node = MarketResearcher(service=make_service(tmp_path))
    result = run_async(node.run({"messages": [HumanMessage(content="write me a poem")]}))
    assert result["next_agent"] == "triage" and "messages" not in result


def test_node_does_not_hand_back_after_triage_routed_here(monkeypatch, tmp_path):
    # triage already chose this node - a disagreeing scope call must not bounce it back
    _quiet_pipeline_llms(monkeypatch)
    monkeypatch.setattr(node_module, "get_groq_model", lambda: FakeLLM(MarketScope(in_scope=False)))
    node = MarketResearcher(service=make_service(tmp_path))
    state = {"messages": [HumanMessage(content="how is oil affecting inflation?")], "scope_checked": True}
    result = run_async(node.run(state))
    assert result["current_agent"] == "market_researcher" and result["messages"]

def test_node_runs_pipeline_and_renders(monkeypatch, tmp_path):
    _quiet_pipeline_llms(monkeypatch)
    monkeypatch.setattr(node_module, "get_groq_model", lambda: FakeLLM(MarketScope(in_scope=True, focus=["yields"])))
    service = make_service(tmp_path)
    node = MarketResearcher(service=service)

    result = run_async(node.run({"messages": [HumanMessage(content="what's driving yields?")]}))

    content = result["messages"][0].content
    assert result["current_agent"] == "market_researcher"
    assert "Cycle phase" in content and "| Indicator |" in content and "not investment advice" in content
    data = result["market_research_response"]["data"]
    assert data["run_id"] and (tmp_path / f"{data['run_id']}.json").is_file()
    saved = json.loads((tmp_path / f"{data['run_id']}.json").read_text())
    assert saved["request"]["focus"] == ["yields"] and saved["narrative"]


def test_node_reports_pipeline_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(node_module, "get_groq_model", lambda: FakeLLM(MarketScope(in_scope=True)))

    class Broken:
        async def run(self, request, origin=None):
            raise RuntimeError("FRED down")

    result = run_async(MarketResearcher(service=Broken()).run({"messages": [HumanMessage(content="rates?")]}))
    assert "couldn't pull current market data" in result["messages"][0].content
    assert result["market_research_response"]["data"]["error"] == "FRED down"


def test_triage_to_market_researcher_end_to_end(monkeypatch, tmp_path):
    fakes = _patch_all_llms(monkeypatch)
    _quiet_pipeline_llms(monkeypatch)
    monkeypatch.setattr(node_module, "MarketResearchService", lambda: make_service(tmp_path))
    fakes["triage"].queue(RoutingDecision(destination="market"))
    fakes["market_researcher"].queue(MarketScope(in_scope=True, focus=["recession"]))

    app = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "market-e2e"}}
    result = run_async(app.ainvoke({"messages": [HumanMessage(content="are recession risks rising?")]}, config=config))

    final_ai = [m for m in result["messages"] if m.type == "ai" and m.content][-1]
    assert "Cycle phase" in final_ai.content
    assert result["current_agent"] == "market_researcher"
    assert result["market_research_response"]["data"]["query_type"] == "market_research"
    assert not fakes["eval"].calls  # the eval agent doesn't review market answers
    # the graph hands the node its config, so the run knows its chat session
    run_id = result["market_research_response"]["data"]["run_id"]
    saved = json.loads((tmp_path / f"{run_id}.json").read_text())
    assert saved["origin"]["channel"] == "chat" and saved["origin"]["session_id"] == "market-e2e"


def test_general_has_no_access_to_market_researcher(monkeypatch):
    bound = []

    class RecordingLLM(FakeLLM):
        def bind_tools(self, tools):
            bound.extend(t.name for t in tools)
            return super().bind_tools(tools)

    _patch_all_llms(monkeypatch)  # build_graph() constructs every node
    monkeypatch.setattr(general_module, "get_groq_model", lambda: RecordingLLM())
    general_module.GeneralAssistant()
    assert "market_research" not in bound and "tavily_search" in bound
    assert not hasattr(tools_module, "market_research")

    graph = build_graph(InMemorySaver())
    general_tool_node = graph.nodes["general_tools"].bound
    assert "market_research" not in general_tool_node.tools_by_name


def test_renderer_uses_only_output_values(monkeypatch, tmp_path):
    _quiet_pipeline_llms(monkeypatch)
    out = run_async(make_service(tmp_path).run(MarketResearchRequest())).output
    md = render_markdown(out, "Not advice.")
    assert out.run_id in md and "10-Year Treasury Yield" in md


def test_renderer_shows_explanations_and_decompositions(monkeypatch, tmp_path):
    _quiet_pipeline_llms(monkeypatch)
    out = run_async(make_service(tmp_path).run(MarketResearchRequest())).output
    out.events = [
        Event(id="dgs10_sharp_move_up", severity="notable", description="10Y moved sharply up.", evidence=["DGS10"]),
        Event(id="credit_stress", severity="notable", description="Credit stress.", evidence=["BAA10Y"]),
        Event(id="oil_shock", severity="notable", description="Oil shock.", evidence=["CL=F"]),
    ]
    out.event_explanations = [
        EventExplanation(event_id="dgs10_sharp_move_up", status="explained", explanation="Reports cite heavy supply.",
                         cited_urls=["https://news.example/supply"],
                         decomposition={"description": "Of the +31bp rise, +24bp came from real yields."}),
        EventExplanation(event_id="credit_stress", status="insufficient_evidence"),
        EventExplanation(event_id="oil_shock", status="unavailable"),
    ]
    md = render_markdown(out, "Not advice.")
    assert "  - Why: Reports cite heavy supply. [source](https://news.example/supply)" in md
    assert "  - Of the +31bp rise, +24bp came from real yields." in md
    assert "  - Why: Cause unclear from recent coverage." in md
    assert md.count("Why:") == 2                                    # unavailable shows nothing


def test_render_warns_when_quality_is_not_ok():
    out = make_output()
    assert "Data warning" not in render_markdown(out, "d")
    out.quality = QualityReport(status="degraded")
    assert "read it with care" in render_markdown(out, "d")
    out.quality = QualityReport(status="unusable")
    assert "Do not rely on" in render_markdown(out, "d")
    out.quality = QualityReport(status="ok")
    assert "Data warning" not in render_markdown(out, "d")


def test_render_shows_risks_implications_and_planned_extras():
    out = make_output()
    out.narrative, out.risks, out.implications = "Summary.", ["Oil keeps rising."], {"usd": "Dollar firm.", "equities": "Mixed."}
    out.planned_indicators = [Indicator(id="DCOILWTICO", name="WTI crude", category="energy", value=71.5, unit="$/bbl",
                                        observation_date=out.as_of, changes={"1m": 2.5}, source="FRED", source_url="u")]
    content = render_markdown(out, "d")
    assert "**Risks**\n- Oil keeps rising." in content
    assert "- **USD:** Dollar firm." in content and "- **Equities:** Mixed." in content
    assert "**Relevant to your question**" in content and "| WTI crude | 71.50 $/bbl |" in content
    assert "uncalibrated model scores" in content


def test_render_flags_a_template_narrative_and_drops_its_risks():
    out = make_output()
    use_template(out, "the LLM call failed")
    content = render_markdown(out, "d")
    assert "written analysis was unavailable" in content and "**Risks**" not in content


def test_follow_up_is_rewritten_with_the_earlier_conversation(monkeypatch, tmp_path):
    _quiet_pipeline_llms(monkeypatch)
    fake = FakeLLM(MarketScope(in_scope=True, standalone_query="Why are Treasury yields rising?"))
    monkeypatch.setattr(node_module, "get_groq_model", lambda: fake)
    node = MarketResearcher(service=make_service(tmp_path))
    state = {"messages": [HumanMessage(content="what are treasury yields doing?"), AIMessage(content="Yields are rising."),
                          HumanMessage(content="why is that?")]}

    result = run_async(node.run(state))

    run_id = result["market_research_response"]["data"]["run_id"]
    assert json.loads((tmp_path / f"{run_id}.json").read_text())["request"]["query"] == "Why are Treasury yields rising?"
    context = [m.content for m in fake.calls[0] if isinstance(m, SystemMessage)][-1]
    assert "User: what are treasury yields doing?" in context and "Assistant: Yields are rising." in context
    assert "why is that?" not in context and fake.calls[0][-1].content == "why is that?"


def test_first_message_is_not_rewritten(monkeypatch, tmp_path):
    _quiet_pipeline_llms(monkeypatch)
    fake = FakeLLM(MarketScope(in_scope=True, standalone_query="something else"))
    monkeypatch.setattr(node_module, "get_groq_model", lambda: fake)

    result = run_async(MarketResearcher(service=make_service(tmp_path)).run({"messages": [HumanMessage(content="rates?")]}))

    data = result["market_research_response"]["data"]
    assert json.loads((tmp_path / f"{data['run_id']}.json").read_text())["request"]["query"] == "rates?"
    assert data["quality_status"] in ("ok", "degraded", "unusable") and len(fake.calls[0]) == 2


def test_chat_run_records_origin_and_rendered_hash(monkeypatch, tmp_path):
    _quiet_pipeline_llms(monkeypatch)
    monkeypatch.setattr(node_module, "get_groq_model", lambda: FakeLLM(MarketScope(in_scope=True)))
    service = make_service(tmp_path)
    service.audit = InMemoryAuditLog()
    state = {"messages": [HumanMessage(content="rates?")], "client_id": "c9"}

    result = run_async(MarketResearcher(service=service).run(state, {"configurable": {"thread_id": "s1"}}))

    run_id = result["market_research_response"]["data"]["run_id"]
    saved = json.loads((tmp_path / f"{run_id}.json").read_text())
    assert saved["origin"] == {"channel": "chat", "session_id": "s1", "client_id": "c9"}
    finished, rendered = run_async(service.audit.events(run_id))
    assert finished["event"] == "run_finished"
    assert rendered["details"]["sha256"] == sha256_of(result["messages"][0].content.encode("utf-8"))


def test_long_chat_input_is_clipped_not_crashed(monkeypatch, tmp_path):
    _quiet_pipeline_llms(monkeypatch)
    monkeypatch.setattr(node_module, "get_groq_model", lambda: FakeLLM(MarketScope(in_scope=True, focus=["f" * 200])))
    node = MarketResearcher(service=make_service(tmp_path))
    result = run_async(node.run({"messages": [HumanMessage(content="rates " * 200)]}))
    assert result["market_research_response"]["data"]["run_id"]
