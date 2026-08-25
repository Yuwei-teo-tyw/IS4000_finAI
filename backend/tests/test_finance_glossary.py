"""Financial shorthand expansion used to make the finance scope check jargon-tolerant."""
from app.agents.finance_glossary import normalize_financial_terms


def test_expands_known_shorthand():
    assert (
        normalize_financial_terms("is this a good p/e?")
        == "is this a good p/e (price-to-earnings ratio)?"
    )


def test_prefers_longest_match_over_substring():
    # "div yield" must expand as a whole phrase, not fall through unmatched.
    result = normalize_financial_terms("what's the div yield on this stock?")
    assert "div yield (dividend yield)" in result


def test_is_case_insensitive():
    assert "ROI (return on investment)" in normalize_financial_terms("What's my ROI?")


def test_leaves_unknown_terms_untouched():
    text = "what's a good stock to buy right now?"
    assert normalize_financial_terms(text) == text


def test_empty_string_is_noop():
    assert normalize_financial_terms("") == ""


def test_does_not_expand_substring_inside_another_word():
    # "ira" shouldn't fire inside "irate" - the pattern is word-boundaried.
    text = "the customer sounded irate"
    assert normalize_financial_terms(text) == text
