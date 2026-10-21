"""
HTTP interface for the Risk & Compliance checks agent.

    GET  /agents/risk-compliance/health             liveness + policy version in use
    GET  /agents/risk-compliance/policy             the policy the checks run against
    POST /agents/risk-compliance/readiness          step 4: client context readiness + constraints
    POST /agents/risk-compliance/review-pack/check  final check of the review pack before G4

Both checks always answer 200 with a report; a BLOCKED report is a result,
not an error, and nothing here approves anything (the RM approves G4). The
service lives on `app.state.risk_compliance`; without it (e.g. a bare test
app) one is created on first use. Validation errors on these routes never
echo submitted values, which may be client financial data (install the
PM's handler with this PREFIX).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agents.risk_compliance.policy import PolicyError, RiskPolicy
from app.agents.risk_compliance.schemas import (
    PackCheckReport,
    ReadinessReport,
    ReadinessRequest,
    ReviewPackCheckRequest,
)
from app.agents.risk_compliance.service import RiskComplianceService

PREFIX = "/agents/risk-compliance"

router = APIRouter(prefix=PREFIX, tags=["risk-compliance"])


def get_service(request: Request) -> RiskComplianceService:
    service = getattr(request.app.state, "risk_compliance", None)
    if service is None:
        service = RiskComplianceService()
        request.app.state.risk_compliance = service
    return service


@router.get("/health")
async def health(service: RiskComplianceService = Depends(get_service)):
    try:
        version = service.policy().version
    except PolicyError:
        version = None
    return {
        "status": "ok" if version else "degraded",
        "agent": "risk_compliance",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "policy_version": version,
    }


@router.get("/policy", response_model=RiskPolicy, response_model_by_alias=True)
async def policy(service: RiskComplianceService = Depends(get_service)) -> RiskPolicy:
    try:
        return service.policy().policy
    except PolicyError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/readiness", response_model=ReadinessReport)
async def readiness(body: ReadinessRequest, service: RiskComplianceService = Depends(get_service)) -> ReadinessReport:
    """Is the confirmed client context ready for advice, and what limits apply? BLOCKED/NEEDS_INFO -> clarify first."""
    return service.readiness(body)


@router.post("/review-pack/check", response_model=PackCheckReport)
async def check_review_pack(body: ReviewPackCheckRequest,
                            service: RiskComplianceService = Depends(get_service)) -> PackCheckReport:
    """Final independent check of the assembled pack. G4 sign-off only when rm_signoff_allowed."""
    return service.check_pack(body)
