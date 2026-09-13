"""Fault injection knobs for the simulator."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class FaultConfig:
    """All faults are off by default."""

    drop_every_nth_click: int | None = None
    """Silently ignore every n-th ctrl click (models lost tilt commands)."""

    latency_ms: int = 0
    """Delay every REST response by this many milliseconds."""

    ws_disconnect_after_frames: int | None = None
    """Close all websockets after this many broadcast frames."""

    reject_api: bool = False
    """Answer every REST request with HTTP 503 (gateway rebooting)."""

    ws_reject_token: bool = False
    """Reject websocket handshakes even for valid tokens."""

    _clicks: int = 0
    _frames: int = 0

    def update(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if key.startswith("_") or not hasattr(self, key):
                continue
            setattr(self, key, value)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}

    def should_drop_click(self) -> bool:
        if not self.drop_every_nth_click:
            return False
        self._clicks += 1
        return self._clicks % self.drop_every_nth_click == 0

    def frame_sent(self) -> bool:
        """Return True if the websocket should be dropped now."""
        if not self.ws_disconnect_after_frames:
            return False
        self._frames += 1
        if self._frames >= self.ws_disconnect_after_frames:
            self._frames = 0
            self.ws_disconnect_after_frames = None
            return True
        return False
