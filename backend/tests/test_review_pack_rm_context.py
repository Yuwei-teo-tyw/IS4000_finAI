"""RM context response helpers: pure functions, no LLM, no store."""
import copy

from app.reports import pack_generator as pg
from app.reports.pack_generator import rm_context_response


def _h(name, ticker, sector, asset_class, mv, portfolio="longevity", priced=True):
    return {"name": name, "ticker": ticker, "sector": sector, "asset_class": asset_class, "portfolio": portfolio,
            "market_value": mv if priced else None, "price_available": priced}


PORT = {"holdings": [
    _h("Tech Leader Inc", "TLI", "Information Technology", "Equities", 300),
    _h("Alpha Bond ETF", "AAA", "Government", "Fixed Income", 500),
    _h("Gamma Fund", "CCC", "Diversified", "Alternatives", 200),
    _h("Cash ETF", "CASH", "Cash", "Cash", 100, portfolio="liquidity"),
    _h("Unpriced Thing", "UNP", "Other", "Equities", None, priced=False),
]}
SHELF = [
    {"product_id": "GSBOND", "product_name": "Global Bond Fund", "issuer": "Goldman Sachs", "asset_class": "Fixed Income"},
    {"product_id": "ACME1", "product_name": "Acme Equity Fund", "issuer": "Acme", "asset_class": "Equities"},
]
STATUS = {"GSBOND": "shortlisted, rank 2", "ACME1": "excluded by the suitability gate: out of scope"}


def _joined(bullets):
    return "\n".join(bullets)


def test_no_rm_context_gives_none():
    assert rm_context_response(None, PORT, SHELF, STATUS) is None
    assert rm_context_response("   ", PORT, SHELF, STATUS) is None


def test_issuer_on_shelf_is_listed_with_status_and_holding_state():
    out = rm_context_response("Client is interested in looking into additional holdings like Goldman Sachs",
                              PORT, SHELF, STATUS)
    text = _joined(out)
    assert "Global Bond Fund (GSBOND, shortlisted, rank 2)" in text
    assert "matches this name or issuer" not in text
    assert "does not hold a matching holding" in text


def test_issuer_matching_is_case_insensitive():
    out = _joined(rm_context_response("maybe goldman sachs?", PORT, SHELF, STATUS))
    assert "Global Bond Fund (GSBOND" in out


def test_issuer_not_on_shelf_is_stated_not_invented():
    out = _joined(rm_context_response("Consider Morgan Stanley", PORT, SHELF, STATUS))
    assert "'Morgan Stanley': no product on the product shelf matches this name or issuer." in out
    assert "does not hold a matching holding" in out
    assert "Acme" not in out and "Global Bond" not in out


def test_held_product_reports_weight():
    out = _joined(rm_context_response("Thinking about adding more Alpha Bond ETF", PORT, SHELF, STATUS))
    assert "the client already holds it: Alpha Bond ETF (AAA), 50.0% of priced non-cash holdings" in out


def test_sector_concentration_compared_with_threshold():
    out = _joined(rm_context_response("Unsure what to do about portfolio concentration in tech", PORT, SHELF, STATUS))
    assert "Sector Technology: the client holds 1 priced holding(s) classified in this sector, 30.0% of priced non-cash holdings, " \
           "at or above the 20.0% concentration flag." in out


def test_asset_class_weight_below_threshold():
    out = _joined(rm_context_response("Bonds look high", PORT, SHELF, STATUS))
    assert "Asset class Bonds: the client holds 1 priced holding(s), 50.0% of priced non-cash holdings, " \
           "at or above the 20.0% concentration flag." in out
    out2 = _joined(rm_context_response("Check the alternatives sleeve", PORT, SHELF, STATUS))
    assert "Asset class Alternative Investments: the client holds 1 priced holding(s), 20.0%" in out2


def test_sector_absent_from_holdings_reports_zero():
    out = _joined(rm_context_response("Client wants more healthcare exposure", PORT, SHELF, STATUS))
    assert "Sector Healthcare: the client holds 0 priced holding(s)" in out
    assert "below the 20.0% concentration flag" in out


def test_generic_concentration_reports_largest_holding_and_sector():
    out = _joined(rm_context_response("Worried about concentration", PORT, SHELF, STATUS))
    assert "Largest single holding: Alpha Bond ETF (AAA), 50.0%" in out
    assert "Largest sector in the holdings data: Government, 50.0%" in out


def test_other_point_is_noted_as_advisory_with_no_change():
    out = _joined(rm_context_response("Please review the cash flow timetable next quarter", PORT, SHELF, STATUS))
    assert "noted as advisory. No figure was changed on the basis of this point." in out


def test_shelf_unavailable_is_stated():
    out = _joined(rm_context_response("Client likes Goldman Sachs", PORT, None, {}))
    assert "the product shelf is unavailable, so products cannot be checked." in out


def test_unpriced_holding_has_no_weight_and_helper_never_mutates_inputs():
    before = copy.deepcopy(PORT)
    out = _joined(rm_context_response("Unpriced Thing matters to the client", PORT, SHELF, STATUS))
    assert "no stored price so no weight" in out
    assert PORT == before


def test_bullets_lead_with_the_no_change_statement():
    out = rm_context_response("Consider Goldman Sachs. Bonds are a concern.", PORT, SHELF, STATUS)
    assert out[0].startswith("The points below are computed from the data held.")
    assert len(out) > 2


def test_lowercase_only_text_does_not_invent_entities():
    out = _joined(rm_context_response("please review the plan", PORT, SHELF, STATUS))
    assert "matches this name or issuer" not in out
    assert "noted as advisory" in out


def test_entity_candidates_skip_sentence_case_and_stopwords():
    assert pg._entity_candidates("Ignore the IPS") == []
    assert pg._entity_candidates("Client is interested in Goldman Sachs") == ["Goldman Sachs"]


def test_alias_matches_whole_words_only():
    out = _joined(rm_context_response("Client is interested in Goldman Sachs", PORT, SHELF, STATUS))
    assert "Asset class Alternative Investments" not in out
    assert "Sector" not in out
