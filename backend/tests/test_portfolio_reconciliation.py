"""
Numerical reconciliation: rounding, amount/percentage consistency, and
withholding any option whose numbers fail programmatic validation.
"""
import pytest

import app.agents.portfolio_manager.service as service_module
from portfolio_helpers import GENERATE, make_client, offered, option, request_with
from app.agents.portfolio_manager.engine.construction import Position, finalise
from app.agents.portfolio_manager.engine.product_screening import ScreenedProduct
from app.agents.portfolio_manager.engine.validation import validate_option
from app.agents.portfolio_manager.schemas.response import PortfolioOption
from app.agents.portfolio_manager.schemas.upstream import ProductCandidate
from app.agents.portfolio_manager.taxonomy import AssetClass


def _sp(pid: str) -> ScreenedProduct:
    prod = ProductCandidate(product_id=pid, product_name=pid, asset_class="Cash", currency="SGD")
    return ScreenedProduct(prod, AssetClass.CASH)


@pytest.mark.parametrize("value", [350000, 333333.33, 1000.01, 12345678.9, 99999.99])
def test_finalise_sums_exactly(value):
    positions = [Position(_sp(f"P{i}"), 100 / 7) for i in range(7)]
    out = finalise(positions, value)
    assert round(sum(p.pct for p in out), 2) == 100.00
    assert round(sum(p.amount for p in out), 2) == round(value, 2)
    for p in out:
        assert abs(p.amount - value * p.pct / 100) <= 0.08


@pytest.mark.parametrize("withdrawal", [0, 12345.67, 99999.99, 333333])
def test_end_to_end_amounts_reconcile_for_awkward_values(withdrawal):
    body = make_client().post(GENERATE, json=request_with(planned_withdrawals=withdrawal)).json()
    for opt in offered(body):
        sels = opt["product_selections"]
        assert abs(sum(s["allocation_percentage"] for s in sels) - 100) < 0.011
        assert abs(sum(s["investment_amount"] for s in sels) - opt["eligible_portfolio_value"]) < 0.05
        assert validate_option(PortfolioOption.model_validate(opt)) == []


def test_validator_catches_tampered_amount():
    body = make_client().post(GENERATE, json=request_with()).json()
    opt = PortfolioOption.model_validate(option(body, "A"))
    opt.product_selections[0].investment_amount += 500
    errors = validate_option(opt)
    assert any("sum to" in e for e in errors)
    assert any(opt.product_selections[0].product_id in e for e in errors)


def test_validator_catches_percentages_not_summing():
    body = make_client().post(GENERATE, json=request_with()).json()
    opt = PortfolioOption.model_validate(option(body, "A"))
    opt.asset_allocation[0].allocation_percentage += 5
    assert any("Asset-class allocations sum" in e for e in validate_option(opt))


def test_option_failing_validation_is_withheld(monkeypatch):
    real = service_module.validate_option

    def corrupt_b(opt):
        return ["simulated mismatch"] if opt.option_id == "B" else real(opt)

    monkeypatch.setattr(service_module, "validate_option", corrupt_b)
    body = make_client().post(GENERATE, json=request_with()).json()
    b = option(body, "B")
    assert b["suitability_status"] == "INFEASIBLE"
    assert b["product_selections"] == [] and b["asset_allocation"] == []
    assert any("simulated mismatch" in w for w in b["warnings"])
    assert body["preferred_option"] != "B"
