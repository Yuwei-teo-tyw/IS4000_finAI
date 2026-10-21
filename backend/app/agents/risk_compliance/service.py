"""
Risk & Compliance service: the readiness check (step 4) and the final
review-pack check (before the RM's G4 approval).

Deterministic end to end, with no LLM anywhere in a pass/fail decision.
It fails closed:
- a policy that cannot be loaded, or is not the version the caller
  expects, gives a BLOCKED report;
- any unexpected error inside a check gives a BLOCKED report;
- unknown, stale or unverifiable data gives NEEDS_INFO.
Nothing is ever approved by default; compare the eval agent, which approves
when its own call fails. Dependencies (policy loader, shelf, clock) are
injected so tests are reproducible.
"""
import logging
from datetime import datetime, timezone
from typing import Callable, Optional, Union

from app.agents.portfolio_manager.schemas.upstream import UpstreamResult
from app.agents.product_recommender.schemas import ShelfProduct
from app.agents.product_recommender.shelf import load_shelf
from app.agents.risk_compliance import pack_checks
from app.agents.risk_compliance.config import Settings, get_settings
from app.agents.risk_compliance.policy import (
    SEVERITY_BY_EFFECT,
    SYS_INTERNAL,
    SYS_POLICY,
    LoadedPolicy,
    PolicyError,
    load_policy,
)
from app.agents.risk_compliance.readiness import (
    assess_readiness,
    check_readiness,
    fingerprint,
    resolve_status,
)
from app.agents.risk_compliance.schemas import (
    PackCheckReport,
    ReadinessReport,
    ReadinessRequest,
    ReviewPackCheckRequest,
    RiskFinding,
)

logger = logging.getLogger(__name__)

SIGNOFF_ALLOWED = {"PASS", "PASS_WITH_CONDITIONS"}


def check_review_pack(
    req: ReviewPackCheckRequest,
    policy: LoadedPolicy,
    shelf: Optional[list[ShelfProduct]],
    settings: Settings,
    now: datetime,
) -> PackCheckReport:
    """`shelf` is None when the product shelf is unavailable; every product is then unverified."""
    out = assess_readiness(
        req.client_profile, req.trigger, req.reference_date, req.data_as_of.profile, policy, settings,
    )
    a, c = out.assessment, out.constraints
    findings = list(out.findings)
    findings += pack_checks.check_market_freshness(req.data_as_of.market, a.reference_date, policy)
    findings += pack_checks.check_allocation(req.allocation, a, c, policy)
    findings += pack_checks.check_products(
        req.products, shelf, req.client_profile, a, c, req.allocation, policy, settings,
    )
    findings += pack_checks.check_sections(req.sections, req.gates, policy)
    findings += pack_checks.check_text(req.sections, pack_checks.allowed_numbers(req, out), policy)

    status = resolve_status(findings, out.missing, out.conflicts)
    return PackCheckReport(
        status=status, rm_signoff_allowed=status in SIGNOFF_ALLOWED,
        request_id=req.request_id, client_id=req.client_id, pack_version=req.pack_version,
        findings=findings, missing_information=out.missing, conflicts=out.conflicts, constraints=c,
        inputs_fingerprint=fingerprint(req, policy.digest),
        policy_id=policy.policy.policy_id, policy_version=policy.version, computed_at=now,
    )


def _system_finding(rule_id: str, code: str, message: str, policy_version: Optional[str]) -> RiskFinding:
    return RiskFinding(
        code=code, severity=SEVERITY_BY_EFFECT["BLOCK"], effect="BLOCK", rule_id=rule_id,
        policy_version=policy_version, message=message,
    )


class RiskComplianceService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        policy_loader: Optional[Callable[[], LoadedPolicy]] = None,
        shelf_loader: Callable[[], UpstreamResult] = load_shelf,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.settings = settings or get_settings()
        self._policy_loader = policy_loader or (lambda: load_policy(self.settings.policy_path))
        self._shelf_loader = shelf_loader
        self.clock = clock

    def policy(self) -> LoadedPolicy:
        return self._policy_loader()

    def _policy_for(self, expected_version: Optional[str]) -> LoadedPolicy:
        loaded = self.policy()
        if expected_version is not None and expected_version != loaded.version:
            raise PolicyError(
                f"The caller expects policy version {expected_version}; the loaded policy is {loaded.version}."
            )
        return loaded

    def _shelf(self) -> Optional[list[ShelfProduct]]:
        result = self._shelf_loader()
        if result.status == "UNAVAILABLE" or result.data is None:
            return None
        return list(result.data.products)

    def readiness(self, req: ReadinessRequest) -> ReadinessReport:
        now = self.clock()
        loaded: Optional[LoadedPolicy] = None
        try:
            loaded = self._policy_for(req.policy_version)
            report = check_readiness(req, loaded, self.settings, now)
        except Exception as e:
            return self._blocked(ReadinessReport, req, loaded, now, e)
        logger.info("Risk readiness for request %s: status=%s findings=%d",
                    req.request_id or "-", report.status, len(report.findings))
        return report

    def check_pack(self, req: ReviewPackCheckRequest) -> PackCheckReport:
        now = self.clock()
        loaded: Optional[LoadedPolicy] = None
        try:
            loaded = self._policy_for(req.policy_version)
            report = check_review_pack(req, loaded, self._shelf(), self.settings, now)
        except Exception as e:
            return self._blocked(PackCheckReport, req, loaded, now, e)
        logger.info("Review pack check for request %s: status=%s findings=%d",
                    req.request_id or "-", report.status, len(report.findings))
        return report

    def _blocked(
        self,
        report_type: type[Union[ReadinessReport, PackCheckReport]],
        req: Union[ReadinessRequest, ReviewPackCheckRequest],
        loaded: Optional[LoadedPolicy],
        now: datetime,
        error: Exception,
    ):
        # Log the error type only: messages can carry client data.
        if isinstance(error, PolicyError):
            logger.error("Risk check blocked: policy unavailable (%s)", type(error).__name__)
            finding = _system_finding(SYS_POLICY, "POLICY_UNAVAILABLE", str(error), None)
        else:
            logger.error("Risk check blocked: internal error (%s)", type(error).__name__)
            finding = _system_finding(
                SYS_INTERNAL, "INTERNAL_ERROR",
                "The check could not be completed, so nothing is passed. Retry, or escalate if it persists.",
                loaded.version if loaded else None,
            )
        common = {
            "status": "BLOCKED", "request_id": req.request_id, "client_id": req.client_id,
            "findings": [finding], "missing_information": [], "conflicts": [], "constraints": None,
            "inputs_fingerprint": fingerprint(req, loaded.digest if loaded else None),
            "policy_id": loaded.policy.policy_id if loaded else None,
            "policy_version": loaded.version if loaded else None, "computed_at": now,
        }
        if report_type is ReadinessReport:
            return ReadinessReport(
                **common, next_step="BLOCK", effective_risk=None, eligible_value=None, liquidity=None, assumptions=[],
            )
        return PackCheckReport(**common, pack_version=req.pack_version, rm_signoff_allowed=False)
