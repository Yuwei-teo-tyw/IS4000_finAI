"""One owned service; graceful shutdown by instance-scoped sentinel."""

import asyncio
import importlib
import sys
from pathlib import Path

import uvicorn


async def main():
    kind, stop_file = sys.argv[1:3]
    modules = {
        "clarifier": ("advisory_agents.clarifier.app", 8811),
        "orchestrator": ("advisory_agents.orchestrator.app", 8812),
        "mocks": ("advisory_agents.mocks.app", 8890),
        "browser": ("server", 8820),
    }
    name, port = modules[kind]
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    app = importlib.import_module(name).app
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            lifespan="on",
            log_level="critical",
            access_log=False,
            workers=1,
        )
    )

    async def watch():
        while not Path(stop_file).exists():
            await asyncio.sleep(0.2)
        server.should_exit = True

    task = asyncio.create_task(watch())
    try:
        await server.serve()
    finally:
        task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:  # noqa: BLE001 - never display raw runtime errors
        sys.stderr.write("SERVICE_START_FAILED\n")
        sys.exit(1)
