"""Dump the public API of a real µGateway into JSON files (for fixtures and debugging).

Usage:
    uv run python scripts/dump_gateway.py wiser-00429931.local <token> [out_dir]

The token is the raw secret (without "Bearer "). Serial numbers, MAC and instance id are
replaced so the dump can be committed. Devices are fetched one by one (slow endpoint).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import aiohttp

ENDPOINTS = [
    "info",
    "site",
    "net/state",
    "system/health",
    "loads",
    "loads/state",
    "rooms",
    "scenes",
    "jobs",
    "sensors",
    "buttons",
    "hvacgroups",
    "hvacgroups/state",
    "system/flags",
    "devices",
]


async def main(host: str, token: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession(headers=headers) as session:

        async def get(path: str) -> dict:
            async with session.get(f"http://{host}/api/{path}") as resp:
                return await resp.json(content_type=None)

        for path in ENDPOINTS:
            data = await get(path)
            (out_dir / f"{path.replace('/', '_')}.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            print(f"{path}: {data.get('status')}")
        devices = (await get("devices")).get("data") or []
        details = []
        for device in devices:
            detail = await get(f"devices/{device['id']}")
            details.append(detail.get("data"))
            await asyncio.sleep(0.5)
        (out_dir / "devices_detail.json").write_text(
            json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"devices detail: {len(details)}")
    print(f"dump written to {out_dir}. Redact 'sn', 'mac_addr', 'serial_nr' before sharing.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    asyncio.run(
        main(sys.argv[1], sys.argv[2], Path(sys.argv[3] if len(sys.argv) > 3 else "scratch/dump"))
    )
