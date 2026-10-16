"""
Run registry + background runner behind the HTTP endpoint.

`MarketResearchRunner.submit()` registers a run and executes the pipeline
as a background asyncio task, so the main agent gets a run_id immediately
(cold runs take 30-60s) and polls for the result. Identical in-flight
requests are coalesced onto one run, concurrency is capped by a
semaphore, and the queue is bounded (QueueFullError -> HTTP 429).

The registry is Postgres-backed in the app (`market_research_runs`, created
by cache.init_market_tables) and in-memory for tests. On startup, runs
left queued/running by a previous process are marked failed.
"""
import asyncio
from datetime import datetime, timezone
from typing import Literal, Optional, Protocol

from pydantic import BaseModel

from app.agents.market_researcher.config import SUPPORTED_REGIONS
from app.agents.market_researcher.schemas import MarketResearchRequest
from app.agents.market_researcher.service import MarketResearchService, UnsupportedRegionError, new_run_id

RunStatus = Literal["queued", "running", "succeeded", "partial", "failed"]
FINISHED: tuple[str, ...] = ("succeeded", "partial", "failed")


class RunRecord(BaseModel):
    run_id: str
    status: RunStatus
    region: str
    request: dict
    json_path: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


class QueueFullError(RuntimeError):
    pass


class MissingConfigurationError(RuntimeError):
    pass


class RunRegistry(Protocol):
    async def create(self, record: RunRecord) -> None: ...
    async def update(self, run_id: str, **fields) -> None: ...
    async def get(self, run_id: str) -> Optional[RunRecord]: ...
    async def latest_success(self, region: str, since: datetime) -> Optional[RunRecord]: ...
    async def mark_interrupted(self) -> int: ...


class InMemoryRunRegistry:
    def __init__(self):
        self._runs: dict[str, RunRecord] = {}

    async def create(self, record: RunRecord) -> None:
        self._runs[record.run_id] = record

    async def update(self, run_id: str, **fields) -> None:
        self._runs[run_id] = self._runs[run_id].model_copy(update=fields)

    async def get(self, run_id: str) -> Optional[RunRecord]:
        return self._runs.get(run_id)

    async def latest_success(self, region: str, since: datetime) -> Optional[RunRecord]:
        done = [
            r for r in self._runs.values()
            if r.region == region and r.status in ("succeeded", "partial") and r.finished_at and r.finished_at >= since
        ]
        return max(done, key=lambda r: r.finished_at, default=None)

    async def mark_interrupted(self) -> int:
        stuck = [r for r in self._runs.values() if r.status in ("queued", "running")]
        for r in stuck:
            await self.update(r.run_id, status="failed", error="interrupted by restart",
                              finished_at=datetime.now(timezone.utc))
        return len(stuck)


_COLUMNS = "id, status, region, request, json_path, error, created_at, finished_at"


def _row_to_record(row) -> RunRecord:
    import json

    rid, status, region, request, json_path, error, created_at, finished_at = row
    return RunRecord(run_id=rid, status=status, region=region, request=json.loads(request), json_path=json_path,
                     error=error, created_at=created_at, finished_at=finished_at)


class PostgresRunRegistry:
    _UPDATABLE = {"status", "json_path", "error", "finished_at"}

    def __init__(self, pool):
        self._pool = pool

    async def create(self, record: RunRecord) -> None:
        import json

        async with self._pool.connection() as conn:
            await conn.execute(
                f"INSERT INTO market_research_runs ({_COLUMNS}) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (record.run_id, record.status, record.region, json.dumps(record.request), record.json_path,
                 record.error, record.created_at, record.finished_at),
            )

    async def update(self, run_id: str, **fields) -> None:
        unknown = set(fields) - self._UPDATABLE
        if unknown:
            raise ValueError(f"cannot update run fields: {sorted(unknown)}")
        assignments = ", ".join(f"{k} = %s" for k in fields)
        async with self._pool.connection() as conn:
            await conn.execute(
                f"UPDATE market_research_runs SET {assignments} WHERE id = %s", (*fields.values(), run_id)
            )

    async def get(self, run_id: str) -> Optional[RunRecord]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(f"SELECT {_COLUMNS} FROM market_research_runs WHERE id = %s", (run_id,))
            row = await cur.fetchone()
        return _row_to_record(row) if row else None

    async def latest_success(self, region: str, since: datetime) -> Optional[RunRecord]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                SELECT {_COLUMNS} FROM market_research_runs
                WHERE region = %s AND status IN ('succeeded', 'partial') AND finished_at >= %s
                ORDER BY finished_at DESC LIMIT 1
                """,
                (region, since),
            )
            row = await cur.fetchone()
        return _row_to_record(row) if row else None

    async def mark_interrupted(self) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                UPDATE market_research_runs
                SET status = 'failed', error = 'interrupted by restart', finished_at = now()
                WHERE status IN ('queued', 'running')
                """
            )
            return cur.rowcount or 0


class MarketResearchRunner:
    def __init__(self, registry: RunRegistry, service: MarketResearchService,
                 max_concurrent: Optional[int] = None, max_queued: Optional[int] = None):
        self.registry = registry
        self.service = service
        settings = service.settings
        self._max_in_flight = (max_concurrent or settings.max_concurrent_runs) + (
            settings.max_queued_runs if max_queued is None else max_queued)
        self._semaphore = asyncio.Semaphore(max_concurrent or settings.max_concurrent_runs)
        self._tasks: dict[str, asyncio.Task] = {}
        self._inflight_by_key: dict[str, str] = {}

    async def submit(self, request: MarketResearchRequest) -> RunRecord:
        if not self.service.settings.fred_api_key:
            raise MissingConfigurationError("FRED_API_KEY is not configured on the server")
        if request.region not in SUPPORTED_REGIONS:
            raise UnsupportedRegionError(
                f"region {request.region!r} is not supported yet (supported: {', '.join(SUPPORTED_REGIONS)})"
            )

        key = request.model_dump_json()
        existing = self._inflight_by_key.get(key)
        if existing:
            record = await self.registry.get(existing)
            if record is not None:
                return record
        if len(self._tasks) >= self._max_in_flight:
            raise QueueFullError(f"{len(self._tasks)} runs already in flight; retry later")

        now = datetime.now(timezone.utc)
        record = RunRecord(
            run_id=new_run_id(now), status="queued", region=request.region,
            request=request.model_dump(mode="json"), created_at=now,
        )
        await self.registry.create(record)
        self._inflight_by_key[key] = record.run_id
        self._tasks[record.run_id] = asyncio.create_task(self._execute(record.run_id, request, key))
        return record

    async def _execute(self, run_id: str, request: MarketResearchRequest, key: str) -> None:
        try:
            async with self._semaphore:
                await self.registry.update(run_id, status="running")
                try:
                    result = await self.service.run(request, run_id=run_id)
                except Exception as e:
                    print(f"MARKET_RESEARCHER: run {run_id} failed: {type(e).__name__}: {e}")
                    await self.registry.update(run_id, status="failed", error=f"{type(e).__name__}: {e}",
                                               finished_at=datetime.now(timezone.utc))
                    return
                status = "partial" if result.output.data_quality.failed_sources else "succeeded"
                await self.registry.update(run_id, status=status, json_path=str(result.json_path),
                                           finished_at=datetime.now(timezone.utc))
        finally:
            self._tasks.pop(run_id, None)
            if self._inflight_by_key.get(key) == run_id:
                self._inflight_by_key.pop(key, None)

    async def wait(self, run_id: str, timeout: float) -> Optional[RunRecord]:
        """Wait up to `timeout` seconds for a run to finish; returns its
        latest record either way (check `status`)."""
        task = self._tasks.get(run_id)
        if task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            except asyncio.TimeoutError:
                pass
        return await self.registry.get(run_id)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
