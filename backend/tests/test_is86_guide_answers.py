"""IS-86: answers from the Investor Profile guide + strategy table, labelled, number-checked, model-off safe."""
import json

from app.agents.client_profiling import guide
from app.agents.client_profiling.store import DocumentStore


def ask(q, reply=None, raising=False):
    def chat(s, u):
        if raising:
            raise RuntimeError("down")
        return json.dumps({"answer": reply})
    return guide.answer_guide_question(q, DocumentStore(), chat)


def test_table_answer_labelled():
    r = ask("What is the max drawdown of Strategy E?", "Strategy E has a maximum drawdown of 45%.")
    assert r["status"] == "ok" and r["text"].rstrip().endswith("Source: Strategy table") or "Source: Strategy table" in r["text"]


def test_guide_answer_labelled():
    r = ask("What is loss capacity?", "Loss capacity is how much loss the client can bear without changing their lifestyle.")
    assert "Source: Investor Profile guide" in r["text"]


def test_invented_number_stripped():
    r = ask("What is the max drawdown of Strategy E?", "Strategy E has a maximum drawdown of 45%. It will return 99% next year.")
    assert "45%" in r["text"] and "99" not in r["text"]


def test_all_numbers_invented_falls_back_to_table():
    r = ask("What is the max drawdown of Strategy E?", "It will return 99% next year.")
    assert "99" not in r["text"] and "max drawdown -45%" in r["text"]


def test_model_unavailable_shows_stored_text_and_says_so():
    r = ask("What is the max drawdown of Strategy E?", raising=True)
    assert "max drawdown -45%" in r["text"] and "language model is unavailable" in r["text"]
    assert "Source: Strategy table" in r["text"]


def test_model_unavailable_guide_passage_verbatim():
    r = ask("What is loss capacity?", raising=True)
    assert "language model is unavailable" in r["text"] and "Source: Investor Profile guide" in r["text"]


def test_not_covered_says_so_without_model():
    r = ask("What does the guide say about quantum cryptography taxes in Mars colonies?", raising=True)
    assert r["status"] == "cannot_answer" and r["text"] == guide.CANNOT


def test_not_covered_model_says_so():
    r = ask("What does the guide say about crypto?", guide.CANNOT)
    assert r["status"] == "cannot_answer" and r["text"] == guide.CANNOT
