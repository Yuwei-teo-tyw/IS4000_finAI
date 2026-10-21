"""
Market Researcher node - the optional chat trigger for the market
researcher agent (app/agents/market_researcher/). The agent's primary
interface is HTTP for a main agent; this node lets a chat user reach the
same pipeline via triage.

Mirrors the other specialists: a structured scope check (which here also
parses the request's focus terms) hands off-topic messages back to triage;
in-scope messages run the pipeline with the validated narrative on, and the
result is rendered deterministically (render.py) - no free-form LLM answer,
so every number shown comes from the data.

All prompt text lives in app/prompts/prompts.yaml, loaded via prompt_builder.
"""
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.market_researcher import MarketResearchRequest, MarketResearchService
from app.agents.market_researcher.render import render_markdown
from app.agents.state import AgentState
from app.core import get_groq_model
from app.prompts.prompt_builder import get_prompt


class MarketScope(BaseModel):
    in_scope: bool = Field(
        description="True if this message asks about current macro/economic conditions, interest rates or yields, "
                    "inflation, jobs data, the economic cycle or recession risk, or overall market conditions."
    )
    focus: list[str] = Field(
        default_factory=list,
        description='0-3 short focus terms from the message, e.g. ["treasury yields", "oil prices"].',
    )


class MarketResearcher:
    """Specialist node wrapping the market researcher pipeline."""

    def __init__(self, service: Optional[MarketResearchService] = None):
        self.llm = get_groq_model()
        self.scope_checker = self.llm.with_structured_output(MarketScope)
        self._service = service

    @property
    def service(self) -> MarketResearchService:
        # Built lazily so it picks up the app's Postgres cache once the pool is open.
        if self._service is None:
            self._service = MarketResearchService()
        return self._service

    async def run(self, state: AgentState) -> Dict[str, Any]:
        human_messages = [m for m in state["messages"] if m.type == "human"]
        latest_message = human_messages[-1].content if human_messages else ""

        prompt = [SystemMessage(content=get_prompt("market_researcher.scope_check_system"))]
        if state.get("client_context"):
            prompt.append(SystemMessage(content=state["client_context"]))
        try:
            scope = await self.scope_checker.ainvoke(prompt + [HumanMessage(content=latest_message)])
        except Exception as e:
            print(f"MARKET_RESEARCHER: scope check failed: {e}")
            scope = MarketScope(in_scope=True)

        # The call still runs once routing is settled (it also extracts the focus
        # terms), but only hands back when triage hasn't just routed here.
        if not scope.in_scope and not state.get("scope_checked"):
            return {
                "current_agent": "triage",
                "next_agent": "triage",
                "conversation_ended": False,
                "handoff_message": "That's outside my area - let me hand you back to the triage agent.",
            }

        request = MarketResearchRequest(query=latest_message, focus=scope.focus[:3], include_narrative=True)
        disclaimer = get_prompt("market_researcher.disclaimer")
        try:
            result = await self.service.run(request)
            output = result.output
            content = render_markdown(output, disclaimer)
            response_data = {
                "message_result": content[:150],
                "data": {
                    "query_type": "market_research",
                    "run_id": output.run_id,
                    "phase": output.regime.phase,
                    "confidence": output.regime.confidence,
                    "recession_prob_12m": output.regime.recession_prob_12m,
                    "events": [e.id for e in output.events],
                    "failed_sources": output.data_quality.failed_sources,
                    "disclaimer": disclaimer,
                },
            }
        except Exception as e:
            print(f"MARKET_RESEARCHER: pipeline failed: {type(e).__name__}: {e}")
            content = "I couldn't pull current market data right now - please try again in a moment."
            response_data = {"message_result": content, "data": {"query_type": "market_research", "error": str(e)}}

        return {
            "messages": [AIMessage(content=content)],
            "current_agent": "market_researcher",
            "next_agent": None,
            "scope_checked": True,
            "conversation_ended": False,
            "market_research_response": response_data,
            "handoff_message": None,
            "skip_eval": False,
        }
