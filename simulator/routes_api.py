"""REST endpoints of the simulated µGateway (``/api/...``)."""

from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from .faults import FaultConfig
from .jsend import error, success
from .model import GatewayModel

NO_BUTTON_MESSAGE = "no button pressed"


def _model(request: web.Request) -> GatewayModel:
    return request.app["model"]  # type: ignore[no-any-return]


def _faults(request: web.Request) -> FaultConfig:
    return request.app["faults"]  # type: ignore[no-any-return]


async def _json(request: web.Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _load_or_error(request: web.Request) -> tuple[int | None, web.Response | None]:
    model = _model(request)
    try:
        load_id = int(request.match_info["id"])
    except ValueError:
        return None, error("invalid id")
    if load_id not in model.loads:
        return None, error(f"load {load_id} not found")
    return load_id, None


# ---------------------------------------------------------------- info / site
async def get_info(request: web.Request) -> web.Response:
    return success(_model(request).info)


async def get_info_debug(request: web.Request) -> web.Response:
    return success({**_model(request).info, "mpy": "1.22.0"})


async def get_site(request: web.Request) -> web.Response:
    return success(_model(request).site)


# ---------------------------------------------------------------- account
async def post_claim(request: web.Request) -> web.Response:
    model = _model(request)
    body = await _json(request)
    user = body.get("user")
    if not user:
        return error("user missing")
    source = body.get("source")
    if source and source not in model.accounts:
        return error(f"/flash/accounts/{source} is not a directory")
    if not model.site:
        return error("no site info")
    model.claim.pressed.clear()
    model.claim.active = True
    auto = model.config.auto_press_after_s
    press_task = None
    if auto is not None:
        press_task = asyncio.get_running_loop().call_later(auto, model.press_button)
    try:
        await asyncio.wait_for(model.claim.pressed.wait(), model.config.claim_timeout_s)
    except TimeoutError:
        return error(NO_BUTTON_MESSAGE)
    finally:
        model.claim.active = False
        if press_task:
            press_task.cancel()
    account = model.create_token(user, source)
    return success({"user": account["user"], "secret": account["secret"]})


async def get_account(request: web.Request) -> web.Response:
    model = _model(request)
    account = dict(model.accounts.get(request["user"], {"user": request["user"]}))
    account.pop("secret", None)
    return success(account)


async def post_clone(request: web.Request) -> web.Response:
    model = _model(request)
    body = await _json(request)
    user = body.get("user")
    if not user:
        return error("user missing")
    account = model.create_token(user, request["user"])
    return success({"user": user, "secret": account["secret"], "source": request["user"]})


async def delete_account(request: web.Request) -> web.Response:
    model = _model(request)
    user = request["user"]
    for secret, owner in list(model.tokens.items()):
        if owner == user:
            del model.tokens[secret]
    return success(model.accounts.pop(user, {"user": user}))


# ---------------------------------------------------------------- loads
async def get_loads(request: web.Request) -> web.Response:
    return success([load.describe() for load in _model(request).loads.values()])


async def get_load(request: web.Request) -> web.Response:
    load_id, err = _load_or_error(request)
    if err:
        return err
    return success(_model(request).loads[load_id].describe())  # type: ignore[index]


async def get_loads_state(request: web.Request) -> web.Response:
    model = _model(request)
    return success([{"id": lid, "state": load.state()} for lid, load in model.loads.items()])


async def get_load_state(request: web.Request) -> web.Response:
    load_id, err = _load_or_error(request)
    if err:
        return err
    model = _model(request)
    return success({"id": load_id, "state": model.loads[load_id].state()})  # type: ignore[index]


async def put_target_state(request: web.Request) -> web.Response:
    load_id, err = _load_or_error(request)
    if err:
        return err
    payload = await _json(request)
    applied = await _model(request).apply_target_state(load_id, payload)  # type: ignore[arg-type]
    return success({"id": load_id, "target_state": applied})


async def put_ctrl(request: web.Request) -> web.Response:
    load_id, err = _load_or_error(request)
    if err:
        return err
    payload = await _json(request)
    button = payload.get("button")
    event = payload.get("event")
    if button not in ("on", "off", "up", "down", "toggle", "stop"):
        return error("invalid button")
    if event not in ("click", "press", "release"):
        return error("invalid event")
    if event == "click" and _faults(request).should_drop_click():
        return success({"id": load_id, "ctrl": {"button": button, "event": event}})
    await _model(request).apply_ctrl(load_id, button, event)  # type: ignore[arg-type]
    return success({"id": load_id, "ctrl": {"button": button, "event": event}})


async def put_ping(request: web.Request) -> web.Response:
    load_id, err = _load_or_error(request)
    if err:
        return err
    model = _model(request)
    model.pings.append(load_id)  # type: ignore[arg-type]
    return success({"id": load_id})


# ---------------------------------------------------------------- devices
async def get_devices(request: web.Request) -> web.Response:
    model = _model(request)
    return success([model.device_basic(d) for d in model.devices.values()])


async def get_devices_all(request: web.Request) -> web.Response:
    model = _model(request)
    return success([model.device_detailed(d) for d in model.devices.values()])


async def get_device(request: web.Request) -> web.Response:
    model = _model(request)
    device = model.devices.get(request.match_info["id"])
    if device is None:
        return error("device not found")
    return success(model.device_detailed(device))


async def get_device_config(request: web.Request) -> web.Response:
    model = _model(request)
    device_id = request.match_info["id"]
    if device_id not in model.devices:
        return error("device not found")
    return success(model.open_device_config(device_id))


async def delete_device_config(request: web.Request) -> web.Response:
    model = _model(request)
    try:
        cfg_id = int(request.match_info["cfg"])
    except ValueError:
        return error("invalid config id")
    if not model.close_device_config(cfg_id):
        return error("config not found")
    return success({"id": cfg_id})


# ---------------------------------------------------------------- misc collections
async def get_rooms(request: web.Request) -> web.Response:
    return success(list(_model(request).rooms.values()))


async def get_scenes(request: web.Request) -> web.Response:
    return success(list(_model(request).scenes.values()))


async def get_jobs(request: web.Request) -> web.Response:
    return success(list(_model(request).jobs.values()))


async def run_job(request: web.Request) -> web.Response:
    model = _model(request)
    try:
        job_id = int(request.match_info["id"])
    except ValueError:
        return error("invalid id")
    job = model.jobs.get(job_id)
    if job is None:
        return error("job not found")
    model.jobs_run.append(job_id)
    for target in job.get("target_states", []):
        load_id = target.get("load")
        if load_id in model.loads:
            payload = {k: v for k, v in target.items() if k != "load"}
            await model.apply_target_state(load_id, payload)
    return success(job)


async def get_sensors(request: web.Request) -> web.Response:
    return success(list(_model(request).sensors.values()))


async def get_buttons(request: web.Request) -> web.Response:
    return success(list(_model(request).buttons))


async def post_buttons(request: web.Request) -> web.Response:
    body = await _json(request)
    if "device" not in body or "channel" not in body:
        return error("device and channel required")
    return success(_model(request).register_button(body["device"], int(body["channel"])))


async def get_hvacgroups(request: web.Request) -> web.Response:
    return success(list(_model(request).hvacgroups.values()))


async def get_hvacgroups_state(request: web.Request) -> web.Response:
    model = _model(request)
    return success(
        [{"id": gid, "state": model.hvac_states.get(gid, {})} for gid in model.hvacgroups]
    )


async def put_hvac_target(request: web.Request) -> web.Response:
    model = _model(request)
    try:
        group_id = int(request.match_info["id"])
    except ValueError:
        return error("invalid id")
    if group_id not in model.hvacgroups:
        return error("hvacgroup not found")
    body = await _json(request)
    if "target_temperature" not in body:
        return error("target_temperature missing")
    await model.set_hvac_target(group_id, float(body["target_temperature"]))
    return success({"id": group_id, "target_state": body})


async def get_flags(request: web.Request) -> web.Response:
    return success(list(_model(request).flags.values()))


async def patch_flag(request: web.Request) -> web.Response:
    model = _model(request)
    try:
        flag_id = int(request.match_info["id"])
    except ValueError:
        return error("invalid id")
    if flag_id not in model.flags:
        return error("flag not found")
    body = await _json(request)
    if "value" in body:
        await model.set_flag(flag_id, bool(body["value"]))
    return success(model.flags[flag_id])


async def get_health(request: web.Request) -> web.Response:
    model = _model(request)
    health = dict(model.health)
    health["uptime"] = int(model.clock) + int(model.health.get("uptime", 0))
    return success(health)


async def get_net_state(request: web.Request) -> web.Response:
    return success(_model(request).net)


async def get_rssi(request: web.Request) -> web.Response:
    return success({"rssi": _model(request).health.get("wlan_rssi", -60)})


def setup_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/info", get_info)
    r.add_get("/api/info/debug", get_info_debug)
    r.add_get("/api/site", get_site)
    r.add_post("/api/account/claim", post_claim)
    r.add_get("/api/account", get_account)
    r.add_post("/api/account/clone", post_clone)
    r.add_delete("/api/account", delete_account)
    r.add_get("/api/loads", get_loads)
    r.add_get("/api/loads/state", get_loads_state)
    r.add_get("/api/loads/{id}", get_load)
    r.add_get("/api/loads/{id}/state", get_load_state)
    r.add_put("/api/loads/{id}/target_state", put_target_state)
    r.add_put("/api/loads/{id}/ctrl", put_ctrl)
    r.add_put("/api/loads/{id}/ping", put_ping)
    r.add_get("/api/devices", get_devices)
    r.add_get("/api/devices/*", get_devices_all)
    r.add_get("/api/devices/{id}", get_device)
    r.add_get("/api/devices/{id}/config", get_device_config)
    r.add_delete("/api/devices/config/{cfg}", delete_device_config)
    r.add_get("/api/rooms", get_rooms)
    r.add_get("/api/scenes", get_scenes)
    r.add_get("/api/jobs", get_jobs)
    r.add_get("/api/jobs/{id}/run", run_job)
    r.add_get("/api/sensors", get_sensors)
    r.add_get("/api/buttons", get_buttons)
    r.add_post("/api/buttons", post_buttons)
    r.add_get("/api/hvacgroups", get_hvacgroups)
    r.add_get("/api/hvacgroups/state", get_hvacgroups_state)
    r.add_put("/api/hvacgroups/{id}/target_state", put_hvac_target)
    r.add_get("/api/system/flags", get_flags)
    r.add_patch("/api/system/flags/{id}", patch_flag)
    r.add_get("/api/system/health", get_health)
    r.add_get("/api/net/state", get_net_state)
    r.add_get("/api/net/rssi", get_rssi)
