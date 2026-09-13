"""Async REST client for the Wiser by Feller µGateway.

Design rules:
* one request in flight per gateway (``asyncio.Lock``) - the gateway is a small MicroPython
  device and does not like parallel requests;
* every response is a JSend envelope with HTTP 200, errors are mapped in :mod:`.jsend`;
* the client never owns the ``aiohttp.ClientSession``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
import logging
import time
from typing import Any

import aiohttp

from .const import (
    CLAIM_TIMEOUT,
    DEFAULT_REQUEST_TIMEOUT,
    DEVICE_DETAIL_TIMEOUT,
    CtrlButton,
    CtrlEvent,
)
from .errors import (
    ClaimTimeoutError,
    NotAWiserGatewayError,
    RequestFailedError,
    WiserConnectionError,
)
from .jsend import unwrap
from .models import (
    Account,
    Button,
    Device,
    DeviceConfig,
    Flag,
    Health,
    HvacGroup,
    HvacState,
    Info,
    Job,
    Load,
    LoadState,
    NetState,
    Room,
    Scene,
    Sensor,
    Site,
)

_LOGGER = logging.getLogger(__name__)


def normalize_host(host: str) -> str:
    """Strip scheme, path and whitespace from a user supplied host string."""
    host = host.strip()
    for prefix in ("http://", "https://", "ws://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix) :]
    return host.split("/", 1)[0].rstrip(".")


class WiserClient:
    """REST client for one µGateway."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        token: str | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        """Create a client for ``host`` (``name.local`` or ``ip[:port]``)."""
        self.host = normalize_host(host)
        self._session = session
        self.token = token
        self._timeout = request_timeout
        self._lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        """HTTP base URL of the REST API."""
        return f"http://{self.host}/api"

    @property
    def ws_url(self) -> str:
        """Websocket URL (same path, upgraded)."""
        return f"ws://{self.host}/api"

    def _headers(self, *, with_token: bool) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if with_token and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - per-request override, not a wrapper
        with_token: bool = True,
    ) -> Any:
        """Perform one request and return the JSend ``data`` part."""
        url = f"{self.base_url}/{path.lstrip('/')}"
        client_timeout = aiohttp.ClientTimeout(total=timeout or self._timeout)
        started = time.monotonic()
        async with self._lock:
            try:
                async with self._session.request(
                    method,
                    url,
                    json=json,
                    headers=self._headers(with_token=with_token),
                    timeout=client_timeout,
                ) as resp:
                    if resp.status >= 500:
                        raise WiserConnectionError(f"{method} {path}: HTTP {resp.status}")
                    try:
                        payload = await resp.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError) as err:
                        raise NotAWiserGatewayError(
                            f"{method} {path}: HTTP {resp.status}, body is not JSON"
                        ) from err
            except TimeoutError as err:
                raise WiserConnectionError(f"{method} {path}: timeout") from err
            except aiohttp.ClientError as err:
                raise WiserConnectionError(f"{method} {path}: {err}") from err
        _LOGGER.debug(
            "%s %s -> %s in %.0f ms",
            method,
            path,
            payload.get("status") if isinstance(payload, dict) else "?",
            (time.monotonic() - started) * 1000,
        )
        return unwrap(payload, path)

    # ----------------------------------------------------------------- token-free
    async def get_info(self) -> Info:
        """`GET /api/info`."""
        data = await self._request("GET", "info", with_token=False)
        if not isinstance(data, dict) or "sn" not in data:
            raise NotAWiserGatewayError("GET info: no serial number in response")
        return Info.from_api(data)

    async def get_site(self) -> Site:
        """`GET /api/site`."""
        return Site.from_api(await self._request("GET", "site", with_token=False))

    # ----------------------------------------------------------------- account
    async def claim(self, user: str, source: str | None = None) -> Account:
        """`POST /api/account/claim` - blocks until a gateway button is pressed.

        Raises :class:`SourceNotFoundError` if ``source`` does not exist and
        :class:`ClaimTimeoutError` if nobody pressed a button.
        """
        body: dict[str, Any] = {"user": user}
        if source:
            body["source"] = source
        try:
            data = await self._request(
                "POST", "account/claim", json=body, timeout=CLAIM_TIMEOUT, with_token=False
            )
        except WiserConnectionError as err:
            if "timeout" in str(err):
                raise ClaimTimeoutError("no button pressed", "account/claim") from err
            raise
        except RequestFailedError as err:
            lowered = err.message.lower()
            if "button" in lowered or "timeout" in lowered or "time out" in lowered:
                raise ClaimTimeoutError(err.message, "account/claim") from err
            raise
        account = Account.from_api(data or {})
        if not account.secret:
            raise ClaimTimeoutError("claim returned no secret", "account/claim")
        self.token = account.secret
        return account

    async def get_account(self) -> Account:
        """`GET /api/account` (also used to validate the token)."""
        return Account.from_api(await self._request("GET", "account"))

    async def clone_account(self, user: str) -> Account:
        """`POST /api/account/clone` - a second token without button press."""
        return Account.from_api(await self._request("POST", "account/clone", json={"user": user}))

    async def delete_account(self) -> None:
        """`DELETE /api/account` - revoke our own token."""
        await self._request("DELETE", "account")

    # ----------------------------------------------------------------- structure
    async def get_loads(self) -> list[Load]:
        """`GET /api/loads`."""
        return [Load.from_api(x) for x in await self._request("GET", "loads") or []]

    async def get_rooms(self) -> list[Room]:
        """`GET /api/rooms`."""
        return [Room.from_api(x) for x in await self._request("GET", "rooms") or []]

    async def get_devices(self) -> list[Device]:
        """`GET /api/devices` (basic properties, fast)."""
        return [Device.from_api(x) for x in await self._request("GET", "devices") or []]

    async def get_device(self, device_id: str) -> Device:
        """`GET /api/devices/{id}` (with inputs/outputs, ~1 s on first call)."""
        data = await self._request("GET", f"devices/{device_id}", timeout=DEVICE_DETAIL_TIMEOUT)
        return Device.from_api(data)

    async def read_device_config(self, device_id: str) -> DeviceConfig:
        """Read the device configuration without leaving the device in config mode.

        `GET /api/devices/{id}/config` creates a config object and switches the device into
        configuration mode; `DELETE /api/devices/config/{cfg}` discards it again. The DELETE
        runs in ``finally`` so the device is released even if the caller is cancelled.
        """
        data = await self._request(
            "GET", f"devices/{device_id}/config", timeout=DEVICE_DETAIL_TIMEOUT
        )
        config = DeviceConfig.from_api(data)
        try:
            return config
        finally:
            await asyncio.shield(self._discard_device_config(config.id))

    async def _discard_device_config(self, config_id: int) -> None:
        try:
            await self._request("DELETE", f"devices/config/{config_id}")
        except WiserConnectionError as err:
            _LOGGER.warning("Could not discard device config %s: %s", config_id, err)

    async def get_scenes(self) -> list[Scene]:
        """`GET /api/scenes`."""
        return [Scene.from_api(x) for x in await self._request("GET", "scenes") or []]

    async def get_jobs(self) -> list[Job]:
        """`GET /api/jobs`."""
        return [Job.from_api(x) for x in await self._request("GET", "jobs") or []]

    async def get_sensors(self) -> list[Sensor]:
        """`GET /api/sensors`."""
        return [Sensor.from_api(x) for x in await self._request("GET", "sensors") or []]

    async def get_buttons(self) -> list[Button]:
        """`GET /api/buttons` (firmware >= 6.0.41)."""
        return [Button.from_api(x) for x in await self._request("GET", "buttons") or []]

    async def register_button(self, device: str, channel: int) -> Button:
        """`POST /api/buttons` - make a sleeping button emit websocket events."""
        data = await self._request("POST", "buttons", json={"device": device, "channel": channel})
        return Button.from_api(data)

    async def get_hvac_groups(self) -> list[HvacGroup]:
        """`GET /api/hvacgroups`."""
        return [HvacGroup.from_api(x) for x in await self._request("GET", "hvacgroups") or []]

    async def get_flags(self) -> list[Flag]:
        """`GET /api/system/flags`."""
        return [Flag.from_api(x) for x in await self._request("GET", "system/flags") or []]

    # ----------------------------------------------------------------- state
    async def get_load_states(self) -> dict[int, LoadState]:
        """`GET /api/loads/state` -> {load id: state}."""
        data = await self._request("GET", "loads/state") or []
        return {int(item["id"]): LoadState.from_api(item.get("state")) for item in data}

    async def get_load_state(self, load_id: int) -> LoadState:
        """`GET /api/loads/{id}/state`."""
        data = await self._request("GET", f"loads/{load_id}/state")
        return LoadState.from_api(data.get("state") if isinstance(data, dict) else None)

    async def get_hvac_states(self) -> dict[int, HvacState]:
        """`GET /api/hvacgroups/state` -> {group id: state}."""
        data = await self._request("GET", "hvacgroups/state") or []
        return {int(item["id"]): HvacState.from_api(item.get("state")) for item in data}

    async def get_health(self) -> Health:
        """`GET /api/system/health`."""
        return Health.from_api(await self._request("GET", "system/health"))

    async def get_net_state(self) -> NetState:
        """`GET /api/net/state`."""
        return NetState.from_api(await self._request("GET", "net/state"))

    async def get_rssi(self) -> int | None:
        """`GET /api/net/rssi` (only works in station mode)."""
        data = await self._request("GET", "net/rssi")
        value = data.get("rssi") if isinstance(data, dict) else None
        return int(value) if value is not None else None

    # ----------------------------------------------------------------- control
    async def set_target_state(self, load_id: int, **fields: int) -> dict[str, Any]:
        """`PUT /api/loads/{id}/target_state` with e.g. ``level=``/``tilt=``/``bri=``."""
        data = await self._request("PUT", f"loads/{load_id}/target_state", json=fields)
        return dict(data or {})

    async def ctrl(self, load_id: int, button: CtrlButton | str, event: CtrlEvent | str) -> None:
        """`PUT /api/loads/{id}/ctrl` - simulate a button press on the load."""
        await self._request(
            "PUT",
            f"loads/{load_id}/ctrl",
            json={"button": str(button), "event": str(event)},
        )

    async def ping_load(self, load_id: int, time_ms: int = 5000) -> None:
        """`PUT /api/loads/{id}/ping` - flash the button LED of the load."""
        await self._request(
            "PUT",
            f"loads/{load_id}/ping",
            json={"time_ms": time_ms, "blink_pattern": "ramp", "color": "#0000FF"},
        )

    async def run_job(self, job_id: int) -> None:
        """`GET /api/jobs/{id}/run` - execute the target states of a job (scene)."""
        await self._request("GET", f"jobs/{job_id}/run")

    async def set_flag(self, flag_id: int, value: bool) -> Flag:
        """`PATCH /api/system/flags/{id}`."""
        data = await self._request("PATCH", f"system/flags/{flag_id}", json={"value": value})
        return Flag.from_api(data)

    async def set_hvac_target(self, group_id: int, target_temperature: float) -> None:
        """`PUT /api/hvacgroups/{id}/target_state`."""
        await self._request(
            "PUT",
            f"hvacgroups/{group_id}/target_state",
            json={"target_temperature": target_temperature},
        )
