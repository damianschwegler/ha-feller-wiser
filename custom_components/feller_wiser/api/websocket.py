"""Reconnecting websocket client for push updates from the µGateway.

The gateway has no application-level keepalive; we rely on protocol pings (``heartbeat``)
plus an inactivity watchdog. After every (re)connect ``dump_loads`` is sent so the caller
receives a full snapshot of all load states.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass, field
import json
import logging
import random
import time
from typing import Any

import aiohttp

from .const import WS_HEARTBEAT, WS_IDLE_TIMEOUT
from .events import WsEvent, parse_ws_frame

_LOGGER = logging.getLogger(__name__)

RECONNECT_MIN = 1.0
RECONNECT_MAX = 60.0


@dataclass
class WsStats:
    """Counters exposed in diagnostics."""

    connects: int = 0
    disconnects: int = 0
    frames: int = 0
    last_frame_at: float | None = None
    last_error: str | None = None
    connected_since: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serializable view."""
        return {
            "connects": self.connects,
            "disconnects": self.disconnects,
            "frames": self.frames,
            "last_frame_at": self.last_frame_at,
            "last_error": self.last_error,
            "connected_since": self.connected_since,
        }


class WiserWebSocket:
    """Maintain one websocket connection and dispatch parsed events."""

    def __init__(
        self,
        url: str,
        token: str,
        session: aiohttp.ClientSession,
        *,
        on_event: Callable[[WsEvent], None],
        on_connection: Callable[[bool], None] | None = None,
        on_auth_failed: Callable[[], None] | None = None,
        idle_timeout: float = WS_IDLE_TIMEOUT,
        heartbeat: float = WS_HEARTBEAT,
    ) -> None:
        """Create the client; nothing is connected until :meth:`async_start`."""
        self._url = url
        self.token = token
        self._session = session
        self._on_event = on_event
        self._on_connection = on_connection
        self._on_auth_failed = on_auth_failed
        self._idle_timeout = idle_timeout
        self._heartbeat = heartbeat
        self._task: asyncio.Task[None] | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._connected = False
        self._closing = False
        self._last_pong = 0.0
        self.stats = WsStats()

    @property
    def connected(self) -> bool:
        """True while the socket is open."""
        return self._connected

    async def async_start(self) -> None:
        """Start the background connection loop."""
        if self._task is not None:
            return
        self._closing = False
        self._task = asyncio.create_task(self._run(), name="feller_wiser-websocket")

    async def async_stop(self) -> None:
        """Close the socket and stop the loop."""
        self._closing = True
        if self._ws is not None and not self._ws.closed:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        self._set_connected(False)

    async def send_command(self, command: str, **payload: Any) -> None:
        """Send a command frame such as ``dump_loads``."""
        if self._ws is None or self._ws.closed:
            return
        await self._ws.send_json({"command": command, **payload})

    async def dump_loads(self) -> None:
        """Ask for a full snapshot (one ``load`` frame per load)."""
        await self.send_command("dump_loads")

    def _set_connected(self, value: bool) -> None:
        if value == self._connected:
            return
        self._connected = value
        if value:
            self.stats.connects += 1
            self.stats.connected_since = time.time()
        else:
            self.stats.disconnects += 1
            self.stats.connected_since = None
        if self._on_connection:
            try:
                self._on_connection(value)
            except Exception:
                _LOGGER.exception("Websocket connection callback failed")

    async def _run(self) -> None:
        backoff = RECONNECT_MIN
        while not self._closing:
            try:
                await self._connect_and_listen()
                backoff = RECONNECT_MIN
            except asyncio.CancelledError:
                raise
            except aiohttp.WSServerHandshakeError as err:
                self.stats.last_error = f"handshake {err.status}"
                if err.status in (401, 403):
                    _LOGGER.warning("Websocket rejected the token (HTTP %s)", err.status)
                    self._set_connected(False)
                    if self._on_auth_failed:
                        self._on_auth_failed()
                    return
                _LOGGER.debug("Websocket handshake failed: %s", err)
            except (aiohttp.ClientError, OSError, TimeoutError) as err:
                self.stats.last_error = str(err) or type(err).__name__
                _LOGGER.debug("Websocket connection error: %s", self.stats.last_error)
            except Exception as err:
                self.stats.last_error = f"{type(err).__name__}: {err}"
                _LOGGER.exception("Unexpected websocket error")
            finally:
                self._set_connected(False)
                self._ws = None
            if self._closing:
                return
            delay = backoff * random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not crypto
            _LOGGER.debug("Websocket reconnect in %.1f s", delay)
            await asyncio.sleep(delay)
            backoff = min(backoff * 2, RECONNECT_MAX)

    async def _connect_and_listen(self) -> None:
        headers = {"Authorization": f"Bearer {self.token}"}
        # Ping/pong is handled here instead of aiohttp's ``heartbeat`` so that no
        # loop timers outlive the connection (and dead links are detected by missing pongs).
        async with self._session.ws_connect(
            self._url,
            headers=headers,
            timeout=aiohttp.ClientWSTimeout(ws_close=10.0),
            autoping=False,
        ) as ws:
            self._ws = ws
            self._last_pong = time.monotonic()
            _LOGGER.info("Websocket connected to %s", self._url)
            self._set_connected(True)
            pinger = asyncio.create_task(self._pinger(ws), name="feller_wiser-ws-ping")
            try:
                await self.dump_loads()
                while True:
                    try:
                        msg = await ws.receive(timeout=self._idle_timeout)
                    except TimeoutError:
                        _LOGGER.warning(
                            "No websocket frame for %.0f s, reconnecting", self._idle_timeout
                        )
                        return
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        self._handle_text(msg.data)
                    elif msg.type == aiohttp.WSMsgType.PING:
                        await ws.pong(msg.data)
                    elif msg.type == aiohttp.WSMsgType.PONG:
                        self._last_pong = time.monotonic()
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                    ):
                        _LOGGER.info("Websocket closed by gateway")
                        return
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        self.stats.last_error = str(ws.exception())
                        _LOGGER.warning("Websocket error: %s", self.stats.last_error)
                        return
            finally:
                pinger.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pinger

    async def _pinger(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        """Send protocol pings; close the socket when pongs stop coming back."""
        while not ws.closed:
            await asyncio.sleep(self._heartbeat)
            if time.monotonic() - self._last_pong > self._heartbeat * 2.5:
                _LOGGER.warning("Websocket pong missing, reconnecting")
                self.stats.last_error = "pong timeout"
                await ws.close()
                return
            with contextlib.suppress(Exception):
                await ws.ping()

    def _handle_text(self, data: str) -> None:
        self.stats.frames += 1
        self.stats.last_frame_at = time.time()
        # the gateway may send several JSON objects separated by newlines in one frame
        for raw_line in data.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except ValueError:
                _LOGGER.debug("Ignoring non-JSON websocket frame: %s", line[:200])
                continue
            event = parse_ws_frame(raw)
            if event is None:
                continue
            try:
                self._on_event(event)
            except Exception:
                _LOGGER.exception("Websocket event handler failed for %s", raw)
