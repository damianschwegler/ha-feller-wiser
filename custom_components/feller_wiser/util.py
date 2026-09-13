"""Scale conversions between Home Assistant and the Wiser API.

Half-up rounding keeps round trips stable: every tilt step 0..9 maps to a distinct percent
value and back to the same step (``int()`` truncation would lose steps).
"""

from __future__ import annotations

from .api import BRI_MAX, LEVEL_MAX, TILT_MAX


def _half_up(value: float) -> int:
    return int(value + 0.5)


def level_to_position(level: int | None) -> int | None:
    """Wiser ``level`` (0 = open, 10000 = closed) -> HA position (100 = open)."""
    if level is None:
        return None
    return max(0, min(100, 100 - _half_up(level / 100)))


def position_to_level(position: int) -> int:
    """HA position (100 = open) -> Wiser ``level`` (0 = open)."""
    return max(0, min(LEVEL_MAX, (100 - int(position)) * 100))


def step_to_tilt_pct(step: int | None) -> int | None:
    """Wiser tilt step 0..9 -> HA tilt percent (100 = horizontal / open)."""
    if step is None:
        return None
    step = max(0, min(TILT_MAX, step))
    return _half_up(step * 100 / TILT_MAX)


def tilt_pct_to_step(pct: int) -> int:
    """HA tilt percent -> Wiser tilt step 0..9."""
    pct = max(0, min(100, int(pct)))
    return _half_up(pct * TILT_MAX / 100)


def bri_to_brightness(bri: int | None) -> int | None:
    """Wiser ``bri`` 0..10000 -> HA brightness 0..255."""
    if bri is None:
        return None
    return max(0, min(255, _half_up(bri * 255 / BRI_MAX)))


def brightness_to_bri(brightness: int) -> int:
    """HA brightness 0..255 -> Wiser ``bri`` 0..10000."""
    return max(0, min(BRI_MAX, _half_up(int(brightness) * BRI_MAX / 255)))


def parse_version(version: str) -> tuple[int, ...]:
    """``"6.0.41"`` -> ``(6, 0, 41)``; non-numeric parts become 0."""
    parts: list[int] = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)
