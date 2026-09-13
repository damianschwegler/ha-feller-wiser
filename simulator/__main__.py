"""Run the fake µGateway: ``python -m simulator --port 8080 --auto-press 3``."""

from __future__ import annotations

import argparse
import logging

from aiohttp import web

from .app import create_app
from .model import FIXTURES, GatewayModel, SimConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Wiser by Feller µGateway simulator")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--fixture", default=str(FIXTURES / "home.json"))
    parser.add_argument(
        "--full-travel", type=float, default=60.0, help="seconds for a full blind travel"
    )
    parser.add_argument(
        "--tilt-ms", type=int, default=250, help="default duration of one tilt step"
    )
    parser.add_argument("--claim-timeout", type=float, default=30.0)
    parser.add_argument(
        "--auto-press",
        type=float,
        default=None,
        help="press the claim button automatically after N seconds",
    )
    parser.add_argument("--sn", default=None, help="override the gateway serial number")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = SimConfig(
        full_travel_s=args.full_travel,
        tilt_ms_default=args.tilt_ms,
        claim_timeout_s=args.claim_timeout,
        auto_press_after_s=args.auto_press,
    )
    model = GatewayModel.from_fixture(args.fixture, config)
    if args.sn:
        model.info["sn"] = args.sn
        model.net["hostname"] = f"wiser-{args.sn}"
    app = create_app(model, ticker=True, fixture_path=args.fixture)
    logging.getLogger(__name__).info(
        "Simulated µGateway sn=%s on http://%s:%s (%d loads)",
        model.info.get("sn"),
        args.host,
        args.port,
        len(model.loads),
    )
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
