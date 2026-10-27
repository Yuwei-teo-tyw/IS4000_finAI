"""Postgres tables for the client portfolio database (portfolio_instruments, portfolio_holdings).

Created lazily and idempotently on first use (same pattern as app/core/geneva_chats.py). Sync psycopg, one short-lived
connection per call. If the seed tables are empty on first use the bundled CSVs are loaded (see load.py).
Postgres unreachable -> PortfolioUnavailableError (callers answer 503; holdings are never invented).
"""
from __future__ import annotations

import os
import threading
from decimal import Decimal
from typing import Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

INSTRUMENT_TYPES = ("stock", "etf", "mutual_fund")
PORTFOLIOS = ("liquidity", "longevity", "legacy")

_DDL = [
    """CREATE TABLE IF NOT EXISTS portfolio_instruments (
        ticker TEXT PRIMARY KEY, name TEXT NOT NULL,
        instrument_type TEXT NOT NULL CHECK (instrument_type IN ('stock','etf','mutual_fund')),
        sector TEXT NOT NULL, asset_class TEXT NOT NULL,
        price NUMERIC(18,4), price_as_at DATE, price_source TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS portfolio_holdings (
        client_id TEXT NOT NULL, ticker TEXT NOT NULL REFERENCES portfolio_instruments(ticker),
        date_bought DATE NOT NULL, quantity NUMERIC(18,4) NOT NULL CHECK (quantity > 0),
        cost_per_unit NUMERIC(18,4) NOT NULL CHECK (cost_per_unit >= 0),
        portfolio TEXT NOT NULL CHECK (portfolio IN ('liquidity','longevity','legacy')),
        PRIMARY KEY (client_id, ticker, date_bought))""",
    "CREATE INDEX IF NOT EXISTS portfolio_holdings_client_idx ON portfolio_holdings (client_id)",
]


class PortfolioUnavailableError(RuntimeError):
    """The portfolio database cannot be reached."""


_READY: set[tuple[str, str]] = set()
_LOCK = threading.Lock()


class PortfolioStore:
    def __init__(self, dsn: Optional[str] = None, schema: Optional[str] = None, autoload: bool = True):
        self.dsn = dsn or os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fin_ai_agents")
        self.schema = schema or os.getenv("PORTFOLIO_PG_SCHEMA") or ""
        self.autoload = autoload

    def connect(self) -> psycopg.Connection:
        try:
            conn = psycopg.connect(self.dsn, connect_timeout=3, row_factory=dict_row)
        except psycopg.OperationalError as e:
            raise PortfolioUnavailableError(f"Portfolio database is not reachable ({str(e).strip()[:120]})") from e
        if self.schema:
            conn.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(self.schema)))
        return conn

    def ensure_ready(self) -> None:
        """Create tables if missing; load the bundled seeds if there are no instruments yet. Idempotent."""
        key = (self.dsn, self.schema)
        with _LOCK:
            if key in _READY:
                return
            try:
                with self.connect() as conn:
                    if self.schema:
                        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
                    for ddl in _DDL:
                        conn.execute(ddl)
                    empty = conn.execute("SELECT count(*) AS n FROM portfolio_instruments").fetchone()["n"] == 0
            except psycopg.Error as e:
                if isinstance(e, psycopg.OperationalError):
                    raise PortfolioUnavailableError(f"Portfolio database error ({str(e).strip()[:120]})") from e
                raise
            if empty and self.autoload:
                from .load import SeedError, load_seeds
                try:
                    load_seeds(self)
                except (SeedError, FileNotFoundError):
                    pass  # bad/missing seeds: leave the tables empty rather than loading anything unchecked
            _READY.add(key)

    def instruments(self) -> dict[str, dict]:
        self.ensure_ready()
        try:
            with self.connect() as conn:
                rows = conn.execute("SELECT * FROM portfolio_instruments").fetchall()
        except psycopg.OperationalError as e:
            raise PortfolioUnavailableError(str(e)[:120]) from e
        return {r["ticker"]: r for r in rows}

    def holdings(self, client_id: str) -> list[dict]:
        """Holding rows joined with their instrument, oldest purchase first."""
        self.ensure_ready()
        try:
            with self.connect() as conn:
                return conn.execute(
                    """SELECT h.client_id, h.ticker, h.date_bought, h.quantity, h.cost_per_unit, h.portfolio,
                              i.name, i.instrument_type, i.sector, i.asset_class, i.price, i.price_as_at, i.price_source
                       FROM portfolio_holdings h JOIN portfolio_instruments i ON i.ticker = h.ticker
                       WHERE h.client_id = %s ORDER BY h.date_bought, h.ticker""", (client_id,)).fetchall()
        except psycopg.OperationalError as e:
            raise PortfolioUnavailableError(str(e)[:120]) from e


_default: Optional[PortfolioStore] = None


def get_default_store() -> PortfolioStore:
    global _default
    if _default is None:
        _default = PortfolioStore()
    return _default


def D(v) -> Optional[Decimal]:
    return None if v is None or v == "" else Decimal(str(v))
