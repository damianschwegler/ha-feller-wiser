"""Admin endpoints of the simulator (``/sim/...``, never authenticated)."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from .faults import FaultConfig
from .jsend import error, success
from .model import GatewayModel
from .ws import WsHub


def _model(request: web.Request) -> GatewayModel:
    return request.app["model"]  # type: ignore[no-any-return]


async def _json(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def press_button(request: web.Request) -> web.Response:
    _model(request).press_button()
    return success({"pressed": True})


async def state(request: web.Request) -> web.Response:
    model = _model(request)
    return success(
        {
            "clock": model.clock,
            "loads": {lid: load.state() for lid, load in model.loads.items()},
            "tokens": list(model.tokens),
            "open_configs": dict(model.open_configs),
            "claim_active": model.claim.active,
            "ws_clients": len(request.app["hub"].conns),
            "faults": request.app["faults"].as_dict(),
        }
    )


async def advance(request: web.Request) -> web.Response:
    body = await _json(request)
    seconds = float(body.get("seconds", 1.0))
    frames = await _model(request).advance_and_emit(seconds)
    return success({"advanced": seconds, "frames": frames})


async def set_load_state(request: web.Request) -> web.Response:
    model = _model(request)
    load_id = int(request.match_info["id"])
    if load_id not in model.loads:
        return error("load not found")
    await model.set_load_state(load_id, await _json(request))
    return success(model.loads[load_id].state())


async def set_sensor_value(request: web.Request) -> web.Response:
    model = _model(request)
    sensor_id = int(request.match_info["id"])
    if sensor_id not in model.sensors:
        return error("sensor not found")
    body = await _json(request)
    await model.set_sensor_value(sensor_id, body.get("value"))
    return success(model.sensors[sensor_id])


async def press_physical_button(request: web.Request) -> web.Response:
    model = _model(request)
    button_id = int(request.match_info["id"])
    body = await _json(request)
    await model.press_physical_button(
        button_id, body.get("event", "click"), body.get("type", "up down")
    )
    return success({"id": button_id})


async def faults(request: web.Request) -> web.Response:
    cfg: FaultConfig = request.app["faults"]
    if request.method == "POST":
        cfg.update(await _json(request))
    return success(cfg.as_dict())


async def ws_disconnect(request: web.Request) -> web.Response:
    hub: WsHub = request.app["hub"]
    await hub.disconnect_all()
    return success({"disconnected": True})


async def reboot(request: web.Request) -> web.Response:
    """Close websockets and reject the API for ``downtime_s`` seconds."""
    import asyncio

    body = await _json(request)
    downtime = float(body.get("downtime_s", 2.0))
    hub: WsHub = request.app["hub"]
    cfg: FaultConfig = request.app["faults"]
    await hub.disconnect_all()
    cfg.reject_api = True

    def _up() -> None:
        cfg.reject_api = False

    asyncio.get_running_loop().call_later(downtime, _up)
    return success({"downtime_s": downtime})


async def revoke_tokens(request: web.Request) -> web.Response:
    model = _model(request)
    model.revoke_all_tokens()
    hub: WsHub = request.app["hub"]
    await hub.disconnect_all()
    return success({"revoked": True})


async def reset(request: web.Request) -> web.Response:
    model = _model(request)
    fixture = request.app.get("fixture_path")
    fresh = GatewayModel.from_fixture(fixture, model.config)
    model.__dict__.update({k: v for k, v in fresh.__dict__.items() if k != "listeners"})
    return success({"reset": True})


def setup_sim_routes(app: web.Application) -> None:
    r = app.router
    r.add_post("/sim/press_button", press_button)
    r.add_get("/sim/state", state)
    r.add_post("/sim/advance", advance)
    r.add_post("/sim/loads/{id}/state", set_load_state)
    r.add_post("/sim/sensors/{id}/value", set_sensor_value)
    r.add_post("/sim/buttons/{id}/press", press_physical_button)
    r.add_get("/sim/faults", faults)
    r.add_post("/sim/faults", faults)
    r.add_post("/sim/ws/disconnect", ws_disconnect)
    r.add_post("/sim/reboot", reboot)
    r.add_post("/sim/revoke_tokens", revoke_tokens)
    r.add_post("/sim/reset", reset)
