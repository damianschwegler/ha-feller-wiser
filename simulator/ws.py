"""Websocket hub of the simulator (``ws://host/api``)."""

from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import WSMsgType, web

from .faults import FaultConfig
from .model import GatewayModel

_LOGGER = logging.getLogger(__name__)


class WsHub:
    def __init__(self, model: GatewayModel, faults: FaultConfig) -> None:
        self.model = model
        self.faults = faults
        self.conns: set[web.WebSocketResponse] = set()
        self.sent_frames: list[dict[str, Any]] = []
        self.received_commands: list[dict[str, Any]] = []
        model.listeners.append(self.broadcast)

    @staticmethod
    def _token_from(request: web.Request) -> str | None:
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer"):
            return header.split(None, 1)[1].strip() if " " in header else None
        return None

    async def handler(self, request: web.Request) -> web.StreamResponse:
        token = self._token_from(request)
        if self.faults.ws_reject_token or not self.model.valid_token(token):
            return web.Response(status=401, text="unauthorized")
        ws = web.WebSocketResponse(heartbeat=None)
        await ws.prepare(request)
        self.conns.add(ws)
        _LOGGER.debug("ws client connected (%d total)", len(self.conns))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except ValueError:
                        continue  # the real gateway ignores garbage silently
                    await self.on_command(ws, data)
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self.conns.discard(ws)
            _LOGGER.debug("ws client disconnected (%d total)", len(self.conns))
        return ws

    async def on_command(self, ws: web.WebSocketResponse, data: dict[str, Any]) -> None:
        self.received_commands.append(data)
        command = data.get("command")
        if command == "dump_loads":
            for load_id in self.model.loads:
                await ws.send_json(self.model.load_frame(load_id))
        elif command == "ctrl_loads":
            load_id = data.get("id")
            if load_id in self.model.loads and "button" in data and "event" in data:
                await self.model.apply_ctrl(int(load_id), data["button"], data["event"])
        # anything else is silently ignored, like the real gateway

    async def broadcast(self, frame: dict[str, Any]) -> None:
        self.sent_frames.append(frame)
        text = json.dumps(frame)
        for ws in list(self.conns):
            if ws.closed:
                self.conns.discard(ws)
                continue
            try:
                await ws.send_str(text)
            except ConnectionError:
                self.conns.discard(ws)
        if self.faults.frame_sent():
            await self.disconnect_all()

    async def disconnect_all(self, code: int = 1012) -> None:
        for ws in list(self.conns):
            try:
                await ws.close(code=code, message=b"simulated")
            finally:
                self.conns.discard(ws)
