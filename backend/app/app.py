from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Everything below must import after load_dotenv() - several of these
# modules (or things they import) read env vars (GROQ_API_KEY, DATABASE_URL,
# ...) at import time.
from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # noqa: E402
from app.core import db  # noqa: E402
from app.agents.graph import MultiAgentGraph  # noqa: E402
from app.endpoints import router as endpoints_router  # noqa: E402
from app.endpoints.market_researcher import router as market_researcher_router  # noqa: E402
from app.endpoints.market_researcher import ui_router as market_researcher_ui_router  # noqa: E402
from app.endpoints.portfolio_manager import router as portfolio_manager_router  # noqa: E402
from app.endpoints.portfolio_manager import install_validation_handler as install_pm_validation_handler  # noqa: E402
from app.endpoints.product_recommender import PREFIX as PRODUCT_RECOMMENDER_PREFIX  # noqa: E402
from app.endpoints.product_recommender import router as product_recommender_router  # noqa: E402
from app.agents.market_researcher.cache import PostgresCache, init_market_tables  # noqa: E402
from app.agents.market_researcher.runs import MarketResearchRunner, PostgresRunRegistry  # noqa: E402
from app.agents.market_researcher.service import MarketResearchService  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # AsyncPostgresSaver.from_conn_string is itself an async context manager
    # (it owns one open connection) - kept open for the app's entire
    # lifetime here rather than per-request, then closed on shutdown when
    # this `async with` exits.
    async with AsyncPostgresSaver.from_conn_string(db.DATABASE_URL) as checkpointer:
        await checkpointer.setup()
        pool = await db.init_pool()

        app.state.agent_graph = MultiAgentGraph(checkpointer)

        # Market researcher: Postgres-backed cache, regime state and run
        # registry; any run a previous process left mid-flight is marked failed.
        await init_market_tables(pool)
        app.state.market_research = MarketResearchRunner(
            PostgresRunRegistry(pool), MarketResearchService(cache=PostgresCache(pool))
        )
        await app.state.market_research.registry.mark_interrupted()

        yield

        await app.state.market_research.shutdown()
        await db.close_pool()


app = FastAPI(title="Multi-Agent Triage System", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(endpoints_router)
app.include_router(market_researcher_router)
app.include_router(market_researcher_ui_router)
app.include_router(portfolio_manager_router)
app.include_router(product_recommender_router)
install_pm_validation_handler(app, extra_prefixes=(PRODUCT_RECOMMENDER_PREFIX,))


@app.get("/")
async def root():
    return {
        "message": "Multi-Agent Triage System",
        "websocket": "/agents/langgraph",
        "market_researcher": "/agents/market-researcher",
        "portfolio_manager": "/agents/portfolio-manager",
        "product_recommender": "/agents/product-recommender",
    }
