"""aiohttp application factory of the simulator."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from aiohttp import web

from .auth import make_auth_middleware
from .faults import FaultConfig
from .model import GatewayModel
from .routes_api import setup_routes
from .routes_sim import setup_sim_routes
from .ws import WsHub

_LOGGER = logging.getLogger(__name__)


def create_app(
    model: GatewayModel,
    *,
    faults: FaultConfig | None = None,
    ticker: bool = True,
    fixture_path: str | Path | None = None,
) -> web.Application:
    """Build the app. With ``ticker=False`` time only advances via ``/sim/advance``."""
    faults = faults or FaultConfig()
    app = web.Application(middlewares=[make_auth_middleware(model, faults)])
    app["model"] = model
    app["faults"] = faults
    app["hub"] = WsHub(model, faults)
    app["fixture_path"] = fixture_path
    setup_routes(app)
    setup_sim_routes(app)
    app.router.add_get("/api", app["hub"].handler)

    if ticker:

        async def _run_ticker(app: web.Application) -> None:
            async def loop() -> None:
                tick = model.config.tick_s
                while True:
                    await asyncio.sleep(tick)
                    try:
                        await model.advance_and_emit(tick)
                    except Exception:
                        _LOGGER.exception("ticker failed")

            task = asyncio.create_task(loop())
            yield
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        app.cleanup_ctx.append(_run_ticker)
    return app
