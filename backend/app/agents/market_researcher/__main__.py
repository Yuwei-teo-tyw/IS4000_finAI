"""
CLI for dev and replays - the main agent should use the HTTP endpoint.

    cd backend && python -m app.agents.market_researcher --region US --focus rates,inflation
    python -m app.agents.market_researcher --as-of 2026-06-30 --narrative --out /tmp/mr

Prints the path of the JSON file it wrote. Uses an in-memory cache unless
--use-db is given (then the Postgres cache and regime state, via DATABASE_URL).
"""
import argparse
import asyncio
import logging
from datetime import date
from pathlib import Path

from dotenv import load_dotenv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.agents.market_researcher", description="Run the market researcher once.")
    parser.add_argument("--region", default="US")
    parser.add_argument("--focus", default="", help="Comma-separated focus terms, e.g. rates,energy")
    parser.add_argument("--query", default=None, help="Optional question/focus from the caller")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--lookback-days-news", type=int, default=3)
    parser.add_argument("--narrative", action="store_true", help="Also produce the validated LLM narrative")
    parser.add_argument("--out", type=Path, default=None, help="Output directory (default: MARKET_RESEARCH_OUTPUT_DIR)")
    parser.add_argument("--use-db", action="store_true", help="Use the Postgres cache/regime state")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> Path:
    from app.agents.market_researcher import MarketResearchRequest, MarketResearchService
    from app.agents.market_researcher.cache import init_market_tables
    from app.core import db

    request = MarketResearchRequest(
        query=args.query,
        region=args.region,
        focus=[t.strip() for t in args.focus.split(",") if t.strip()],
        lookback_days_news=args.lookback_days_news,
        as_of=args.as_of,
        include_narrative=args.narrative,
    )
    if args.use_db:
        pool = await db.init_pool()
        await init_market_tables(pool)
    try:
        result = await MarketResearchService(out_dir=args.out).run(request)
    finally:
        if args.use_db:
            await db.close_pool()

    out = result.output
    print(f"phase={out.regime.phase} confidence={out.regime.confidence} "
          f"recession_prob_12m={out.regime.recession_prob_12m} events={len(out.events)} "
          f"indicators={len(out.indicators)} prices={len(out.market_snapshot)} news={len(out.news)}")
    if out.data_quality.failed_sources:
        print("failed sources:", "; ".join(out.data_quality.failed_sources))
    return result.json_path


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[4] / ".env")
    args = _parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")
    print(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
