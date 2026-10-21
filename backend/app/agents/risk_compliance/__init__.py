"""
Risk & Compliance checks agent: a deterministic, independent second line.

- `check_readiness` (step 4): is the confirmed client context good enough
  to advise on, and what limits must the advice respect?
- `check_review_pack` (Review Gate, before G4): does the assembled review
  pack respect those limits and the policy, across every agent's part?

No LLM decides pass/fail, every finding cites a policy rule and version,
and anything unknown, stale or broken fails closed. See NOTES.md.
"""
from app.agents.risk_compliance.readiness import check_readiness
from app.agents.risk_compliance.service import RiskComplianceService, check_review_pack

__all__ = ["RiskComplianceService", "check_readiness", "check_review_pack"]
