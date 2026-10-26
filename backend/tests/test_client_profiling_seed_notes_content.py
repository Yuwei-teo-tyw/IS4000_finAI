"""The seeded Jane Fraser meeting notes carry the facts an IPS is built from (offline, reads the seed JSON)."""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "app/agents/client_profiling/data/meeting_notes.json"


def _text(client_id: str) -> str:
    notes = json.loads(DATA.read_text())["meeting_notes"]
    return "\n".join(n["text"] for n in notes if n["client_id"] == client_id).lower()


def test_jane_notes_cover_ips_inputs():
    for cid in ("jft", "jfr"):
        t = _text(cid)
        assert "she is currently 45 years old, and wants her investment portfolio to hit 700m within 8 years" in t
        for must in ("chief executive officer", "s$10m", "s$500m",                        # occupation, income, AUM
                     "investment", "blue-chip", "stay away from",                         # philosophy
                     "low risk, but steady growth", "capital safe", "steady income", "ten years",  # goals, horizon
                     "leave something for my family",              # secondary goals
                     "cash reserve of s$30m", "s$150,000 a month",                        # liquidity
                     "tax resident", "tax-loss harvesting", "24%",                        # tax
                     "esg", "thermal coal", "tobacco", "hedge funds", "private markets",  # values / restricted
                     "willingness to take risk is low", "ability", "very risk averse"):  # risk tolerance / capacity
            assert must in t, (cid, must)
