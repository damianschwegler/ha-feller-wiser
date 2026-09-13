"""JSend response helpers (the real gateway answers HTTP 200 for errors too)."""

from __future__ import annotations

from typing import Any

from aiohttp import web

LOCKED_MESSAGE = "api is locked, log in to receive an authentication cookie OR unlock the device."
UNAUTHORIZED_MESSAGE = "unauthorized user"


def success(data: Any = None) -> web.Response:
    return web.json_response({"status": "success", "data": data})


def error(message: str) -> web.Response:
    return web.json_response({"status": "error", "message": message})
