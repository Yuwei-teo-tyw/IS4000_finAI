"""
Optional chat trigger for the market researcher: the MarketResearcher
graph node, the end-to-end triage -> market_researcher -> eval path, the
deterministic renderer, and the Finance Expert staying separate (it has
no access to the market researcher).
The pipeline runs for real against the stubbed providers from
test_market_service; every LLM is a FakeLLM.
"""
import json

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

import app.agents.market_researcher.news_tagging as tagging_module
import app.agents.market_researcher.synthesis as synthesis_module
import app.agents.nodes.market_researcher as node_module
import app.agents.nodes.finance as finance_module
import app.agents.tools as tools_module
from app.agents.graph import build_graph
from app.agents.market_researcher.news_tagging import NewsTagBatch
from app.agents.market_researcher.render import render_markdown
from app.agents.market_researcher.schemas import Event, EventExplanation, MarketResearchRequest
from app.agents.nodes.eval_agent import ComplianceCheck, EvalVerdict
from app.agents.nodes.market_researcher import MarketResearcher, MarketScope
from app.agents.nodes.triage import RoutingDecision

from conftest import FakeLLM, run_async
from test_graph_integration import _patch_all_llms
from test_market_service import make_service, quiet_planner_and_explainer


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
        async def run(self, request):
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
    fakes["eval"].queue(EvalVerdict(verdict="approve", feedback=""), ComplianceCheck(compliant=True, severity="none"))

    app = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "market-e2e"}}
    result = run_async(app.ainvoke({"messages": [HumanMessage(content="are recession risks rising?")]}, config=config))

    final_ai = [m for m in result["messages"] if m.type == "ai" and m.content][-1]
    assert "Cycle phase" in final_ai.content
    assert result["current_agent"] == "market_researcher"
    assert result["market_research_response"]["data"]["query_type"] == "market_research"
    # compliance pass ran on the market researcher's answer
    assert any("Assistant response to review" in str(call) for call in fakes["eval"].calls)


def test_finance_has_no_access_to_market_researcher(monkeypatch):
    bound = []

    class RecordingLLM(FakeLLM):
        def bind_tools(self, tools):
            bound.extend(t.name for t in tools)
            return super().bind_tools(tools)

    _patch_all_llms(monkeypatch)  # build_graph() constructs every node
    monkeypatch.setattr(finance_module, "get_groq_model", lambda: RecordingLLM())
    finance_module.FinanceExpert()
    assert "market_research" not in bound and "tavily_search" in bound
    assert not hasattr(tools_module, "market_research")

    graph = build_graph(InMemorySaver())
    finance_tool_node = graph.nodes["finance_tools"].bound
    assert "market_research" not in finance_tool_node.tools_by_name


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
