"""Loader: upsert the seed CSVs into portfolio_instruments / portfolio_holdings.

    python -m app.agents.client_portfolio.load            (idempotent; reconciles: rows not in holdings.csv are deleted)

Every row is validated first; a holding whose ticker is not in instruments (or any other bad row) makes the whole load
fail with SeedError listing the problems - nothing is defaulted or fabricated, and nothing is written.
"""
from __future__ import annotations

import csv
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from .store import INSTRUMENT_TYPES, PORTFOLIOS, PortfolioStore, _DDL

DATA_DIR = Path(__file__).parent / "data"


class SeedError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems[:10]) + (f" (+{len(problems) - 10} more)" if len(problems) > 10 else ""))


def _read(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def _dec(v: str, what: str, problems: list[str], where: str, required: bool = True) -> Optional[Decimal]:
    if v == "":
        if required:
            problems.append(f"{where}: {what} is empty")
        return None
    try:
        d = Decimal(v)
        if not d.is_finite():
            raise InvalidOperation
        return d
    except InvalidOperation:
        problems.append(f"{where}: {what} '{v}' is not a number")
        return None


def _date(v: str, what: str, problems: list[str], where: str, required: bool = True) -> Optional[date]:
    if v == "":
        if required:
            problems.append(f"{where}: {what} is empty")
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        problems.append(f"{where}: {what} '{v}' is not a YYYY-MM-DD date")
        return None


def validate_rows(instruments: list[dict], holdings: list[dict]) -> tuple[list[tuple], list[tuple]]:
    """-> (instrument tuples, holding tuples) or raise SeedError. Pure: no database."""
    problems: list[str] = []
    inst_out, seen = [], set()
    for n, r in enumerate(instruments, start=2):
        w = f"instruments row {n} ({r.get('ticker', '')})"
        t = r.get("ticker", "")
        if not t:
            problems.append(f"{w}: ticker is empty"); continue
        if t in seen:
            problems.append(f"{w}: duplicate ticker"); continue
        seen.add(t)
        for col in ("name", "sector", "asset_class"):
            if not r.get(col):
                problems.append(f"{w}: {col} is empty")
        if r.get("instrument_type") not in INSTRUMENT_TYPES:
            problems.append(f"{w}: instrument_type '{r.get('instrument_type')}' not in {INSTRUMENT_TYPES}")
        price = _dec(r.get("price", ""), "price", problems, w, required=False)
        as_at = _date(r.get("price_as_at", ""), "price_as_at", problems, w, required=False)
        if price is not None and price < 0:
            problems.append(f"{w}: price is negative")
        if price is not None and as_at is None:
            problems.append(f"{w}: price given without price_as_at")
        if price is None and as_at is not None:
            as_at = None  # no price -> no snapshot date; the instrument simply has no stored price
        inst_out.append((t, r.get("name", ""), r.get("instrument_type", ""), r.get("sector", ""), r.get("asset_class", ""),
                         price, as_at, r.get("price_source", "")))
    hold_out, hseen = [], set()
    for n, r in enumerate(holdings, start=2):
        w = f"holdings row {n} ({r.get('client_id', '')}/{r.get('ticker', '')})"
        if not r.get("client_id"):
            problems.append(f"{w}: client_id is empty")
        if r.get("ticker", "") not in seen:
            problems.append(f"{w}: ticker is not in instruments (refused, not defaulted)")
        bought = _date(r.get("date_bought", ""), "date_bought", problems, w)
        qty = _dec(r.get("quantity", ""), "quantity", problems, w)
        cost = _dec(r.get("cost_per_unit", ""), "cost_per_unit", problems, w)
        if qty is not None and qty <= 0:
            problems.append(f"{w}: quantity must be positive")
        if cost is not None and cost < 0:
            problems.append(f"{w}: cost_per_unit is negative")
        if r.get("portfolio") not in PORTFOLIOS:
            problems.append(f"{w}: portfolio '{r.get('portfolio')}' not in {PORTFOLIOS}")
        k = (r.get("client_id"), r.get("ticker"), bought)
        if k in hseen:
            problems.append(f"{w}: duplicate holding for the same date")
        hseen.add(k)
        hold_out.append((r.get("client_id", ""), r.get("ticker", ""), bought, qty, cost, r.get("portfolio", "")))
    if problems:
        raise SeedError(problems)
    return inst_out, hold_out


def load_seeds(store: Optional[PortfolioStore] = None, data_dir: Optional[Path] = None) -> dict:
    """Validate then upsert both CSVs in one transaction. Returns row counts."""
    store = store or PortfolioStore(autoload=False)
    d = Path(data_dir or DATA_DIR)
    inst, hold = validate_rows(_read(d / "instruments.csv"), _read(d / "holdings.csv"))
    with store.connect() as conn:
        if store.schema:
            from psycopg import sql
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(store.schema)))
        for ddl in _DDL:
            conn.execute(ddl)
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO portfolio_instruments (ticker,name,instrument_type,sector,asset_class,price,price_as_at,price_source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (ticker) DO UPDATE SET name=EXCLUDED.name, instrument_type=EXCLUDED.instrument_type,
                     sector=EXCLUDED.sector, asset_class=EXCLUDED.asset_class, price=EXCLUDED.price,
                     price_as_at=EXCLUDED.price_as_at, price_source=EXCLUDED.price_source""", inst)
            cur.executemany(
                """INSERT INTO portfolio_holdings (client_id,ticker,date_bought,quantity,cost_per_unit,portfolio)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (client_id,ticker,date_bought) DO UPDATE SET quantity=EXCLUDED.quantity,
                     cost_per_unit=EXCLUDED.cost_per_unit, portfolio=EXCLUDED.portfolio""", hold)
            # Reconcile: the DB must match the CSV, so drop every holding whose key is not in holdings.csv
            # (clients removed from the file, and positions removed from a remaining client).
            cur.execute(
                """DELETE FROM portfolio_holdings h WHERE NOT EXISTS (
                     SELECT 1 FROM unnest(%s::text[], %s::text[], %s::date[]) AS k(c, t, d)
                     WHERE k.c = h.client_id AND k.t = h.ticker AND k.d = h.date_bought)""",
                ([h[0] for h in hold], [h[1] for h in hold], [h[2] for h in hold]))
            deleted = cur.rowcount
    return {"instruments": len(inst), "holdings": len(hold), "deleted": deleted}


def main() -> int:
    try:
        r = load_seeds()
    except SeedError as e:
        print("Seed load refused, nothing written:", file=sys.stderr)
        for p in e.problems:
            print(" -", p, file=sys.stderr)
        return 1
    except Exception as e:  # unreachable DB etc.
        print(f"Seed load failed: {e}", file=sys.stderr)
        return 2
    print(f"Loaded {r['instruments']} instruments and {r['holdings']} holdings; removed {r['deleted']} stale holdings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
