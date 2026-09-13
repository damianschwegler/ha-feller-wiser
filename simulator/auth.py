"""Token middleware: token-free endpoints, "api is locked" otherwise."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from aiohttp import web

from .faults import FaultConfig
from .jsend import LOCKED_MESSAGE, UNAUTHORIZED_MESSAGE, error
from .model import GatewayModel

TOKEN_FREE = {
    ("GET", "/api/info"),
    ("GET", "/api/info/debug"),
    ("GET", "/api/site"),
    ("POST", "/api/account/claim"),
}

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def make_auth_middleware(model: GatewayModel, faults: FaultConfig):  # type: ignore[no-untyped-def]
    @web.middleware
    async def auth_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
        path = request.path
        if path.startswith("/sim/"):
            return await handler(request)
        if faults.reject_api:
            return web.Response(status=503, text="rebooting")
        if faults.latency_ms:
            await asyncio.sleep(faults.latency_ms / 1000)
        if (request.method, path) in TOKEN_FREE:
            return await handler(request)
        if path == "/api" and request.headers.get("Upgrade", "").lower() == "websocket":
            return await handler(request)
        header = request.headers.get("Authorization", "")
        if not header:
            return error(LOCKED_MESSAGE)
        parts = header.split(None, 1)
        token = parts[1].strip() if len(parts) == 2 else ""
        if not model.valid_token(token):
            return error(UNAUTHORIZED_MESSAGE)
        request["user"] = model.tokens[token]
        return await handler(request)

    return auth_middleware
