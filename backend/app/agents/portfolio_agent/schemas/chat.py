"""
Contract for asking the Portfolio Agent a question about a stored proposal
(POST /agents/portfolio-agent/portfolio/{request_id}/ask), used by the
Geneva chat.

The answer is grounded in the proposal the engine already computed plus the
workspace context the chat sends (the PM's chosen portfolio and adjusted
weights, the client's current holdings). Nothing is saved or executed.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

OptionLetter = Literal["A", "B", "C", "D", "E", "F"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatTurn(_In):
    question: str = Field(max_length=1000)
    answer: str = Field(max_length=4000)


class HoldingLine(_In):
    name: str = Field(max_length=120)
    asset_class: str = Field(max_length=60)
    weight_pct: float = Field(ge=0, le=100)


class WorkspaceContext(_In):
    """What the Geneva workspace knows beyond the proposal itself."""
    selected_option: Optional[OptionLetter] = Field(default=None, description="Portfolio the PM picked, if any")
    adjusted_weights: Optional[dict[str, float]] = Field(
        default=None, description="The PM's edited asset-class weights for the selected portfolio"
    )
    sent_to_rm: bool = False
    holdings: list[HoldingLine] = Field(default_factory=list, max_length=100)


class PortfolioQuestion(_In):
    question: str = Field(min_length=1, max_length=1000)
    workspace: Optional[WorkspaceContext] = None
    history: list[ChatTurn] = Field(default_factory=list, max_length=6, description="Earlier turns, oldest first")


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PortfolioAnswer(_Out):
    request_id: str
    answer: str
    source: Literal["LLM", "DETERMINISTIC_FALLBACK", "DETERMINISTIC"]
    model: Optional[str]
    detail: str
    options_referenced: list[str]
    requires_rm_review: Literal[True] = True
    execution_status: Literal["NOT_EXECUTED"] = "NOT_EXECUTED"
