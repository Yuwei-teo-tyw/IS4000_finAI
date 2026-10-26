"""IS-91: third-person IPS wording, unsafe sentences listed under notIncluded, evidence quotes verbatim."""
from app.agents.client_profiling.ips_generate import generate_ips_section, third_person
from ips_helpers import Chat, FakeStore, note

N = note(1, "2026-10-20", "Jane: I am very risk averse. We agreed to review together. I want to keep my capital safe.")


def test_conversion():
    assert third_person("I am very risk averse") == "The client is very risk averse"
    assert third_person("I want to keep my capital safe") == "The client wants to keep the client's capital safe"


def test_unsafe_sentence_returns_empty():
    assert third_person("We want to keep our capital safe") == ""


def test_generation_converts_lists_unsafe_and_keeps_quote_verbatim():
    payload = {"fields": [], "bullets": [
        {"text": "I am very risk averse", "cite": "N1", "quote": "I am very risk averse"},
        {"text": "We agreed to review together", "cite": "N1", "quote": "We agreed to review together"}]}
    r = generate_ips_section(FakeStore([N]), "x", "risk", Chat(payload))
    assert r["bullets"] == ["The client is very risk averse"]
    assert r["notIncluded"] == ["We agreed to review together"]
    assert r["evidence"][0]["passage"] == "I am very risk averse" and r["evidence"][0]["passage"] in N.text  # verbatim, first person


def test_not_included_empty_when_all_convertible():
    r = generate_ips_section(FakeStore([N]), "x", "risk", Chat({"fields": [], "bullets": [
        {"text": "I want to keep my capital safe", "cite": "N1", "quote": ""}]}))
    assert r["notIncluded"] == []


# --- later bullets in a section use she/he/they (gender only from the client record) ---
from app.agents.client_profiling.ips_pronouns import apply_pronouns, drop_duplicates, pronounize  # noqa: E402

NG = note(2, "2026-10-20", "Client wants a steady return. Client accepts low risk. Client holds the 700M target within 8 years. "
                           "Capital must stay safe.")


def _store(gender=None):
    s = FakeStore([NG])
    s.client.gender = gender
    return s


def _risk(gender):
    payload = {"fields": [], "bullets": [
        {"text": "The client wants a steady return", "cite": "N1", "quote": "Client wants a steady return"},
        {"text": "The client accepts low risk", "cite": "N1", "quote": "Client accepts low risk"},
        {"text": "The client's capital must stay safe", "cite": "N1", "quote": "Capital must stay safe"}]}
    return generate_ips_section(_store(gender), "x", "risk", Chat(payload))


def test_first_bullet_the_client_then_she():
    r = _risk("female")
    assert r["bullets"] == ["The client wants a steady return", "She accepts low risk", "Her capital must stay safe"]


def test_male_pronouns():
    assert _risk("male")["bullets"][1:] == ["He accepts low risk", "His capital must stay safe"]


def test_no_gender_falls_back_to_they():
    assert _risk(None)["bullets"][1:] == ["They accept low risk", "Their capital must stay safe"]
    assert pronounize("The client is cautious", "neutral") == "They are cautious"
    assert pronounize("The client has a plan", "neutral") == "They have a plan"


def test_risky_grammar_left_alone():
    assert pronounize("The client accepted it", "neutral") == "The client accepted it"
    assert apply_pronouns(["The client is calm"], "female") == ["The client is calm"]


def test_evidence_items_follow_and_quotes_stay_verbatim():
    r = _risk("female")
    assert [e["item"] for e in r["evidence"]] == r["bullets"]
    assert all(e["passage"] in NG.text for e in r["evidence"])


def test_not_included_still_reported_with_pronouns():
    p = {"fields": [], "bullets": [{"text": "The client wants a steady return", "cite": "N1", "quote": ""},
                                   {"text": "We accept low risk", "cite": "N1", "quote": ""}]}
    r = generate_ips_section(_store("female"), "x", "risk", Chat(p))
    assert r["bullets"] == ["The client wants a steady return"] and r["notIncluded"] == ["We accept low risk"]


def test_near_duplicates_dropped():
    a = "The client wants her assets to grow steadily towards the 700M target within 8 years"
    b = "The target is for the portfolio to reach 700M within 8 years"
    assert drop_duplicates([a, b, "The client wants a 5% return"]) == [a, "The client wants a 5% return"]


def test_goals_group_first_bullet_the_client():
    p = {"bullets": [
        {"label": "Return requirements", "text": "The client wants a steady return", "cite": "N1", "quote": ""},
        {"label": "Return requirements", "text": "The client accepts low risk", "cite": "N1", "quote": ""},
        {"label": "Risk tolerance", "text": "The client accepts low risk", "cite": "N1", "quote": ""}]}
    r = generate_ips_section(_store("female"), "x", "goals", Chat(p))
    assert "Return requirements: The client wants a steady return" in r["bullets"]
    assert "Return requirements: She accepts low risk" in r["bullets"]


def test_unify_pronouns_known_gender_and_they_for_unknown():
    from app.agents.client_profiling.ips_pronouns import unify_pronouns
    t = "They would not need to touch most of the capital for ten years, so she is a long-term investor"
    assert unify_pronouns(t, "female") == "She would not need to touch most of the capital for ten years, so she is a long-term investor"
    assert unify_pronouns("They have a long horizon and their capital is safe", "male") == "He has a long horizon and his capital is safe"
    assert unify_pronouns(t, None) == t
    assert apply_pronouns(["x", "They are cautious"], "female") == ["x", "She is cautious"]


def test_target_bullets_pronoun_and_latest_meeting_wins():
    first = note(1, "2026-10-13", "Jane: My target is for the portfolio to reach 700M within 8 years. I want to keep my capital safe. I expect to stay invested for ten years.", title="First meeting")
    later = note(2, "2026-10-20", "Jane: I want to hit 800M in my investment portfolio in 5 years.", title="Follow-up")
    p = {"bullets": [
        {"label": "Primary goals", "text": "I want to keep my capital safe", "cite": "N1", "quote": ""},
        {"label": "Return requirements", "text": "The client wants the portfolio to reach 700M within 8 years", "cite": "N1", "quote": ""},
        {"label": "Investment time horizon", "text": "They expect to stay invested for ten years, so she is a long-term investor",
         "cite": "N1", "quote": ""}]}
    st = FakeStore([first, later])
    st.client.gender = "female"
    r = generate_ips_section(st, "x", "goals", Chat(p))
    g = {x["key"]: x["bullets"] for x in r["goals"]}
    assert g["returnRequirements"] == ["The client wants the portfolio to reach 800M within 5 years"]
    assert g["primaryGoals"][0].startswith("The client") and g["primaryGoals"][1:] == ["She wants the portfolio to reach 800M within 5 years"]
    assert g["investmentTimeHorizon"][0].startswith("They") is False
    assert not any("700" in b for x in r["goals"] for b in x["bullets"])
    assert not any("700" in b for b in r["bullets"])
    (t,) = r["targets"]
    assert t["amount"] == 800_000_000 and t["source_note"]["id"] == "note_2" and t["source_note"]["date"] == "2026-10-20"
    assert t["superseded"][0]["amount"] == 700_000_000 and t["superseded"][0]["source_note"]["id"] == "note_1"
