"""
CLI for dev - in the full stack the Portfolio Manager is served by the main
app (app/app.py) under /agents/portfolio-manager.

    cd backend
    python -m app.agents.portfolio_manager generate app/agents/portfolio_manager/samples/sample_request.json
    python -m app.agents.portfolio_manager serve          # port 8000, like the main app

`generate` runs one request and prints the response JSON. `serve` starts a
dev server with only the Portfolio Manager routes (same paths as the main
app), which needs no Postgres - handy when the full stack isn't running.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.agents.portfolio_manager",
                                     description="Run the Portfolio Manager agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Generate proposals for one request JSON file and print the response.")
    gen.add_argument("request", type=Path, help="Path to a PortfolioGenerateRequest JSON file")
    gen.add_argument("--no-llm", action="store_true", help="Use deterministic explanations only")
    srv = sub.add_parser("serve", help="Dev server with only the Portfolio Manager routes (no Postgres).")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--no-llm", action="store_true", help="Use deterministic explanations only")
    return parser.parse_args()


async def _generate(path: Path) -> str:
    from app.agents.portfolio_manager.schemas.client import PortfolioGenerateRequest
    from app.agents.portfolio_manager.service import PortfolioService

    request = PortfolioGenerateRequest.model_validate_json(path.read_text(encoding="utf-8"))
    response = await PortfolioService().generate(request)
    return response.model_dump_json(indent=2)


def _dev_app():
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    from app.endpoints.portfolio_manager import install_validation_handler, router

    app = FastAPI(title="Portfolio Manager Agent (dev)", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://{h}:{p}" for h in ("localhost", "127.0.0.1") for p in (5173, 5174, 3000)],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    install_validation_handler(app)
    return app


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[4] / ".env")  # repo-root .env, as app/app.py uses
    args = _parse_args()
    if args.no_llm:
        os.environ["PORTFOLIO_LLM_ENABLED"] = "false"
    if args.command == "generate":
        sys.stdout.write(asyncio.run(_generate(args.request)) + "\n")
    else:
        import uvicorn

        uvicorn.run(_dev_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
