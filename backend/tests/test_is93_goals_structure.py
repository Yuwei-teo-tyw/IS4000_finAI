"""IS-93: goals are 7 ordered sub-headings with bullets; empty ones kept as 'Not yet completed'."""
from app.agents.client_profiling.ips_generate import generate_ips_section
from app.agents.client_profiling.ips_model import GOAL_KEYS, PLACEHOLDER, goals_from_bullets, normalize_goals
from ips_helpers import Chat, FakeStore, note

N = note(1, "2026-10-02", "Jane wants low risk but steady growth and to keep capital safe. She is a long-term investor for ten years.\n"
                          "She prefers ESG funds.")
TITLES = ["Return Requirements", "Investment Time Horizon", "Primary Goals", "Secondary Goals", "Liquidity Needs",
          "Tax Considerations", "Unique Circumstances and Preferences"]


def test_order_titles_and_keys():
    g = normalize_goals(None)
    assert [x["title"] for x in g] == TITLES
    assert [x["key"] for x in g] == ["returnRequirements", "investmentTimeHorizon", "primaryGoals", "secondaryGoals",
                                     "liquidityNeeds", "taxConsiderations", "uniqueCircumstances"] == [k for k, _ in GOAL_KEYS]


def test_empty_subheadings_kept_with_placeholder():
    g = goals_from_bullets(["Primary goals: Keep capital safe"])
    assert len(g) == 7 and g[2]["bullets"] == ["Keep capital safe"] and not g[2]["empty"]
    assert all(x["empty"] and x["bullets"] == [] and x["placeholder"] == PLACEHOLDER == "Not yet completed" for x in g if x["key"] != "primaryGoals")


def test_content_fitting_no_heading_goes_to_unique_circumstances():
    g = goals_from_bullets(["Something odd: wants a yacht", "plain sentence"])
    assert g[6]["bullets"] == ["Something odd: wants a yacht", "plain sentence"]


def test_generation_returns_goals_shape():
    payload = {"bullets": [
        {"label": "Primary goals", "text": "Keep capital safe", "cite": "N1", "quote": "keep capital safe"},
        {"label": "Made up", "text": "Prefers ESG funds", "cite": "N1", "quote": "prefers ESG funds"},
        {"label": "Investment time horizon", "text": "A long-term investor for ten years", "cite": "N1", "quote": ""}]}
    r = generate_ips_section(FakeStore([N]), "x", "goals", Chat(payload))
    g = {x["key"]: x for x in r["goals"]}
    assert [x["title"] for x in r["goals"]] == TITLES
    assert g["primaryGoals"]["bullets"] == ["Keep capital safe"]
    assert g["uniqueCircumstances"]["bullets"] == ["Prefers ESG funds"]
    assert g["investmentTimeHorizon"]["bullets"] and g["taxConsiderations"]["empty"] and g["secondaryGoals"]["bullets"] == []


def test_backward_compat_old_shapes():
    old = normalize_goals(["Return requirements: 4% a year", "Tax considerations: top bracket"])
    assert old[0]["bullets"] == ["4% a year"] and old[5]["bullets"] == ["top bracket"]
    d = normalize_goals({"primaryGoals": ["a"], "Liquidity needs": ["b"]})
    assert d[2]["bullets"] == ["a"] and d[4]["bullets"] == ["b"]
    again = normalize_goals(old)  # new shape round-trips
    assert again == old
