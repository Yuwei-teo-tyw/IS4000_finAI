"""IPS-only answers: cited to the IPS version/part, number-safe, never read meeting notes."""
import json

import pytest

from app.agents.client_profiling.ips_answer import answer_ips_question
from app.agents.client_profiling.store import StoreUnavailableError, get_default_store


def chat_returning(**kw):
    out = {"in_scope": True, "answerable": True, "answer": "", "cites": []}
    out.update(kw)
    return lambda system, user: json.dumps(out)


class SpyStore:
    def __init__(self, real):
        self.real, self.notes_calls = real, 0

    def latest_ips(self, cid):
        return self.real.latest_ips(cid)

    def get_notes(self, cid):
        self.notes_calls += 1
        raise AssertionError("meeting notes must not be read")


def test_ok_answer_cites_ips_version_and_part():
    r = answer_ips_question("What are the assets?", get_default_store(), "jfr",
                            chat_returning(answer="Investable assets are S$500m (I1).", cites=["I1"]))
    assert r["status"] == "ok" and "I1" not in r["text"] and r["sections"] == []
    assert r["sources"] and all(s["type"] == "ips" for s in r["sources"])
    assert r["sources"][0]["version"] == 1 and "IPS v1" in r["sources"][0]["label"] and "Part 1" in r["sources"][0]["label"]


def test_invented_figure_dropped():
    r = answer_ips_question("q", get_default_store(), "jfr", chat_returning(answer="Assets are S$999m.", cites=["I1"]))
    assert r["status"] == "cannot_answer" and r["sources"] == [] and r["text"] == "The IPS does not state this."


@pytest.mark.parametrize("kw", [dict(answer="Safe capital.", cites=["I99"]), dict(answer="Safe capital.", cites=["N1"]),
                                dict(answer="Safe capital.", cites=[]), dict(answerable=False)])
def test_unknown_or_missing_cite_or_unanswerable_is_cannot_answer(kw):
    assert answer_ips_question("q", get_default_store(), "jfr", chat_returning(**kw))["status"] == "cannot_answer"


def test_no_ips_no_model_call_and_no_notes():
    calls = []
    store = SpyStore(get_default_store())
    r = answer_ips_question("q", store, "nobody", lambda s, u: calls.append(1) or "{}")
    assert r == {"status": "no_ips", "text": "This client has no IPS yet.", "sources": [], "sections": []}
    assert calls == [] and store.notes_calls == 0


def test_notes_never_read_on_normal_path():
    store = SpyStore(get_default_store())
    answer_ips_question("q", store, "ser", chat_returning(answerable=False))
    assert store.notes_calls == 0


def test_model_down_or_junk_returns_none():
    def down(s, u):
        raise ConnectionError
    assert answer_ips_question("q", get_default_store(), "jfr", down) is None
    assert answer_ips_question("q", get_default_store(), "jfr", lambda s, u: "not json") is None
    assert answer_ips_question("q", get_default_store(), "jfr", lambda s, u: "[1]") is None


def test_out_of_scope():
    r = answer_ips_question("weather?", get_default_store(), "jfr", chat_returning(in_scope=False))
    assert r["status"] == "out_of_scope" and r["sources"] == []


def test_active_preferred_over_draft_and_context_only_ips():
    seen = {}

    def spy(s, u):
        seen["u"] = u
        return json.dumps({"in_scope": True, "answerable": False, "answer": "", "cites": []})
    store = get_default_store()
    answer_ips_question("q", store, "ser", spy)
    assert "IPS v2 (Active" in seen["u"] and "IPS v1" not in seen["u"] and "note_" not in seen["u"]
    answer_ips_question("q", store, "jfr", spy)
    assert "IPS v1 (Draft" in seen["u"]


def test_store_unavailable_propagates():
    class Down:
        def latest_ips(self, cid):
            raise StoreUnavailableError("db down")
    with pytest.raises(StoreUnavailableError):
        answer_ips_question("q", Down(), "jfr", chat_returning())


def test_question_truncated():
    seen = {}

    def spy(s, u):
        seen["u"] = u
        return "{}"
    answer_ips_question("x" * 5000, get_default_store(), "jfr", spy)
    assert "x" * 1000 in seen["u"] and "x" * 1001 not in seen["u"]


# ---- IPS-only semantic retrieval ----
class SemStore:
    """Wraps the JSON store; search_ips returns `hits` (or raises); notes access is forbidden."""
    def __init__(self, hits, with_attr=True):
        self.real, self.hits, self.search_calls, self.notes_search_calls = get_default_store(), hits, [], 0
        if not with_attr:
            self.__class__ = NoSearchStore

    def latest_ips(self, cid):
        return self.real.latest_ips(cid)

    def search_ips(self, cid, query, k=4):
        self.search_calls.append((cid, query, k))
        return self.hits

    def get_notes(self, cid):
        raise AssertionError("notes must not be read")

    def search_notes(self, *a, **k):
        self.notes_search_calls += 1
        raise AssertionError("notes search must not be called")


class NoSearchStore(SemStore):
    search_ips = property(lambda self: (_ for _ in ()).throw(AttributeError("search_ips")))


def _spy_chat(seen, **kw):
    out = {"in_scope": True, "answerable": True, "answer": "", "cites": []}
    out.update(kw)

    def chat(s, u):
        seen["u"] = u
        return json.dumps(out)
    return chat


def _parts(cid="jfr"):
    ips, _ = get_default_store().latest_ips(cid)
    return ips, [p for p in ips.parts if (p.body or "").strip()]


def test_semantic_path_uses_only_returned_chunks():
    ips, parts = _parts()
    assert len(parts) >= 2
    keep, other = parts[0], parts[-1]
    store, seen = SemStore([{"part_n": keep.part, "version": ips.version, "text": "UNIQUE-CHUNK-TEXT S$12m", "score": 0.9}]), {}
    answer_ips_question("q", store, "jfr", _spy_chat(seen, answerable=False))
    assert "UNIQUE-CHUNK-TEXT" in seen["u"] and other.body.strip()[:40] not in seen["u"]
    assert "[I1]" in seen["u"] and "[I2]" not in seen["u"]
    assert store.search_calls and store.search_calls[0][0] == "jfr" and store.notes_search_calls == 0


def test_semantic_citation_points_to_chunk_part_and_version():
    ips, parts = _parts()
    target = parts[-1]
    store = SemStore([{"part_n": target.part, "version": ips.version, "text": "Cap is S$12m.", "score": 0.9}])
    r = answer_ips_question("q", store, "jfr", chat_returning(answer="The cap is S$12m (I1).", cites=["I1"]))
    assert r["status"] == "ok" and len(r["sources"]) == 1
    s = r["sources"][0]
    assert s["type"] == "ips" and s["version"] == ips.version and f"Part {target.part}" in s["label"] and s["passage"] == "Cap is S$12m."


def test_semantic_figures_must_be_in_returned_chunks():
    ips, parts = _parts()
    store = SemStore([{"part_n": parts[0].part, "version": ips.version, "text": "Cap is S$12m.", "score": 0.9}])
    r = answer_ips_question("q", store, "jfr", chat_returning(answer="The cap is S$999m.", cites=["I1"]))
    assert r["status"] == "cannot_answer"
    r = answer_ips_question("q", store, "jfr", chat_returning(answer="Cap.", cites=["I2"]))
    assert r["status"] == "cannot_answer"


@pytest.mark.parametrize("hits", [None, []])
def test_fallback_when_search_ips_returns_none_or_empty(hits):
    ips, parts = _parts()
    store, seen = SemStore(hits), {}
    answer_ips_question("q", store, "jfr", _spy_chat(seen, answerable=False))
    assert all(p.body.strip()[:40] in seen["u"] for p in parts)


def test_fallback_when_attribute_missing():
    ips, parts = _parts()
    store, seen = SemStore(None, with_attr=False), {}
    assert getattr(store, "search_ips", None) is None
    answer_ips_question("q", store, "jfr", _spy_chat(seen, answerable=False))
    assert all(p.body.strip()[:40] in seen["u"] for p in parts)


def test_search_ips_store_unavailable_propagates():
    store = SemStore(None)
    store.search_ips = lambda *a, **k: (_ for _ in ()).throw(StoreUnavailableError("down"))
    with pytest.raises(StoreUnavailableError):
        answer_ips_question("q", store, "jfr", chat_returning())
