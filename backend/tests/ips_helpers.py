"""Shared fakes for the IS-87..IS-94 / IPS-extras tests (no real LLM, no DB)."""
import json

from app.agents.client_profiling.store import Client, MeetingNoteDoc


def note(i, date, text, title="Meeting"):
    return MeetingNoteDoc(id=f"note_{i}", client_id="x", date=date, title=title, text=text)


class FakeStore:
    def __init__(self, notes=(), risk_cap=None, category=None):
        self.notes = list(notes)
        self.client = Client(id="x", name="Test Client", risk_cap=risk_cap, risk_category=category)

    def get_notes(self, cid):
        return sorted(self.notes, key=lambda n: (n.date, n.id), reverse=True)

    def get_client(self, cid):
        return self.client


class Chat:
    """Fake ChatFn returning a canned JSON payload."""
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def __call__(self, system, user):
        self.calls += 1
        return json.dumps(self.payload) if not isinstance(self.payload, str) else self.payload


def alloc_payload(strategies=("A", "B", "C"), cite="N1", quote="", just="The client has a long horizon and low risk willingness."):
    return {"riskCategory": "Conservative", "summary": "The client is conservative.", "buckets": [
        {"id": b, "strategy": s, "justification": just, "cite": cite, "quote": quote}
        for b, s in zip(("liquidity", "longevity", "legacy"), strategies)]}
