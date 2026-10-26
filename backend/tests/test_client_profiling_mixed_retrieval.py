"""MIXED question (source="both"): notes and IPS are retrieved separately, once each, with no cross-contamination."""
import json

from app.agents.client_profiling.service import handle_chat
from app.agents.client_profiling.store import DocumentStore

IPS_MARK = "ZZIPSCHUNKZZ"


class Spy(DocumentStore):
    def __init__(self):
        super().__init__()
        self.calls = {"search_notes": 0, "get_notes": 0, "search_ips": 0, "get_ips_versions": 0, "latest_ips": 0}

    def get_notes(self, cid):
        self.calls["get_notes"] += 1
        return super().get_notes(cid)

    def get_ips_versions(self, cid):
        self.calls["get_ips_versions"] += 1
        return super().get_ips_versions(cid)

    def latest_ips(self, cid):
        self.calls["latest_ips"] += 1
        return super().latest_ips(cid)

    def search_notes(self, *a, **k):
        self.calls["search_notes"] += 1
        return None

    def search_ips(self, cid, query, k=4):
        self.calls["search_ips"] += 1
        ips, _ = super().latest_ips(cid)
        p = next(p for p in ips.parts if (p.body or "").strip())
        return [{"part_n": p.part, "version": ips.version, "text": f"{IPS_MARK} S$5m", "score": 0.9}]


def test_mixed_question_separate_retrieval_no_cross_contamination():
    store, notes_prompts, ips_prompts = Spy(), [], []

    def notes_chat(system, user):
        notes_prompts.append(user)
        return json.dumps({"in_scope": True, "broad": False, "answerable": True, "answer": "Moderate risk was agreed.",
                           "groups": [], "cites": ["N1"], "summary_request": False, "summary_format": "", "inference": ""})

    def ips_chat(system, user):
        ips_prompts.append(user)
        return json.dumps({"in_scope": True, "answerable": True, "answer": "The IPS states S$5m (I1).", "cites": ["I1"]})

    def chat(system, user):  # one chat fn for both sides; dispatch on the system prompt
        return ips_chat(system, user) if "Investment Policy Statement" in system else notes_chat(system, user)

    r = handle_chat("Compare what the client said on risk with the IPS", "jfr", store=store, source="both", answer_chat=chat)
    assert r.tool == "compare_sources"
    assert len(notes_prompts) == 1 and len(ips_prompts) == 1
    assert store.calls["search_ips"] == 1 and store.calls["latest_ips"] == 1
    assert store.calls["search_notes"] <= 1  # semantic notes search only when notes exceed the context budget
    assert "<records>" in notes_prompts[0] and "<records>" in ips_prompts[0]
    assert IPS_MARK not in notes_prompts[0] and "IPS v" not in notes_prompts[0].split("Adviser")[0]
    assert "note_" not in ips_prompts[0] and "Meeting note" not in ips_prompts[0] and IPS_MARK in ips_prompts[0]
    b = r.data["both"]
    assert b["notes"]["answer"]["sources"] and all(s["type"] == "meeting_note" for s in b["notes"]["answer"]["sources"])
    assert b["ips"]["answer"]["sources"] and all(s["type"] == "ips" for s in b["ips"]["answer"]["sources"])
