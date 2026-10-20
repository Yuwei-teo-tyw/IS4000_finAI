"""
Product Recommender service: shelf -> suitability gate -> ranking -> reasons.

Deterministic end to end. Every product considered ends up in exactly one
of shortlist, eligible_not_shortlisted or excluded.
"""
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from app.agents.portfolio_manager.engine.profile_assessment import assess_profile
from app.agents.portfolio_manager.schemas.upstream import UpstreamResult
from app.agents.portfolio_manager.taxonomy import RISK_LEVEL_LABELS, parse_asset_class
from app.agents.product_recommender import ranking
from app.agents.product_recommender.config import Settings, get_settings
from app.agents.product_recommender.explain import deterministic_reason
from app.agents.product_recommender.house_view import HOUSE_VIEW_SOURCE, load_house_view
from app.agents.product_recommender.schemas import (
    ClientSummary,
    Costs,
    EligibleItem,
    Exclusion,
    HouseView,
    NamedProductResult,
    ProductSummary,
    RecommendRequest,
    RecommendResponse,
    ScoreBreakdown,
    ShelfProduct,
    ShortlistItem,
)
from app.agents.product_recommender.shelf import load_shelf
from app.agents.product_recommender.suitability import gate


class ShelfUnavailable(RuntimeError):
    """No usable product shelf, so nothing can be recommended."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def summarise(prod: ShelfProduct) -> ProductSummary:
    return ProductSummary(**{f: getattr(prod, f, None) for f in ProductSummary.model_fields})


def costs(prod: ShelfProduct) -> Costs:
    return Costs(management_fee_pct=prod.management_fee, transaction_fee_pct=prod.transaction_fee)


class ProductRecommenderService:
    def __init__(
        self,
        settings: Optional[Settings] = None,
        clock: Callable[[], datetime] = _utcnow,
        shelf_loader: Callable[[], UpstreamResult] = load_shelf,
        house_view_loader: Callable[[], HouseView] = load_house_view,
    ):
        self.settings = settings or get_settings()
        self.clock = clock
        self.shelf_loader = shelf_loader
        self.house_view_loader = house_view_loader

    def shelf(self) -> UpstreamResult:
        return self.shelf_loader()

    def house_view(self) -> HouseView:
        return self.house_view_loader()

    def recommend(self, req: RecommendRequest) -> RecommendResponse:
        now = self.clock()
        profile = req.client_profile
        opts = req.options
        a = assess_profile(profile, None, now.date())

        shelf_res = self.shelf_loader()
        if shelf_res.status == "UNAVAILABLE" or shelf_res.data is None:
            raise ShelfUnavailable("; ".join(shelf_res.issues) or "The product shelf is unavailable.")
        hv = self.house_view_loader()

        products: list[ShelfProduct] = list(shelf_res.data.products)
        if opts.asset_classes:
            wanted = {parse_asset_class(c) for c in opts.asset_classes} - {None}
            products = [p for p in products if parse_asset_class(p.asset_class) in wanted]

        result = gate(
            products, profile, a, a.reference_date, self.settings.product_stale_after_days,
            liquidity_need_months=self.settings.liquidity_need_months,
            drawdown_hard_limit=self.settings.drawdown_hard_limit,
        )
        level = a.effective_level
        objective = ranking.derive_objective(profile, a)
        ranked = ranking.rank(result.eligible, objective, hv, level, a.shortest_horizon_years, profile.base_currency)
        picked, rest = ranking.shortlist(ranked, opts.top_n, opts.max_per_asset_class)

        shortlist = [
            ShortlistItem(
                rank=i + 1,
                product=summarise(r.sp.product),
                score=ScoreBreakdown(total=r.total, components=r.components),
                notes=r.sp.notes,
                reason=deterministic_reason(r, hv, objective, level, profile.base_currency),
                costs=costs(r.sp.product),
            )
            for i, r in enumerate(picked)
        ]
        eligible_rest = [
            EligibleItem(product_id=r.sp.product_id, product_name=r.sp.product.product_name,
                         asset_class=r.sp.asset_class.value, total=r.total)
            for r in rest
        ]
        excluded = [
            Exclusion(product_id=x.product.product_id, product_name=x.product.product_name,
                      asset_class=x.product.asset_class, code=x.code, reason=x.reason)
            for x in result.excluded
        ]

        return RecommendResponse(
            request_id=req.request_id or f"PR-{uuid.uuid4().hex[:12].upper()}",
            client_id=req.client_id,
            generated_at=now,
            is_illustrative=bool(shelf_res.data.is_illustrative or hv.is_illustrative),
            sources={"shelf": shelf_res.source, "house_view": HOUSE_VIEW_SOURCE},
            client_summary=ClientSummary(
                risk_level=level,
                risk_category=RISK_LEVEL_LABELS.get(level) if level else None,
                objective=objective,
                shortest_horizon_years=a.shortest_horizon_years,
                base_currency=profile.base_currency,
            ),
            house_view=hv,
            shortlist=shortlist,
            eligible_not_shortlisted=eligible_rest,
            excluded=excluded,
            named_products=[self._named(q, shortlist, eligible_rest, excluded, products) for q in opts.named_products],
            missing_information=sorted({m.field for m in a.missing}),
            limitations=[*shelf_res.data.limitations, *hv.limitations, *shelf_res.issues],
        )

    @staticmethod
    def _named(query, shortlist, eligible_rest, excluded, products) -> NamedProductResult:
        q = query.strip().lower()
        match = next((p for p in products if p.product_id.lower() == q), None) or next(
            (p for p in products if q and q in p.product_name.lower()), None)
        if match is None:
            return NamedProductResult(query=query, status="not_found", reason="No product on the shelf matches this name.")
        pid = match.product_id
        if s := next((s for s in shortlist if s.product.product_id == pid), None):
            return NamedProductResult(query=query, product_id=pid, status="shortlisted", reason=f"Ranked {s.rank} on the shortlist.")
        if e := next((e for e in eligible_rest if e.product_id == pid), None):
            return NamedProductResult(query=query, product_id=pid, status="eligible",
                                      reason=f"Suitable, but outside the shortlist (score {e.total:g}).")
        x = next(x for x in excluded if x.product_id == pid)
        return NamedProductResult(query=query, product_id=pid, status="excluded", reason=x.reason)
