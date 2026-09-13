"""Scale conversions."""

import pytest

from custom_components.feller_wiser.util import (
    bri_to_brightness,
    brightness_to_bri,
    level_to_position,
    parse_version,
    position_to_level,
    step_to_tilt_pct,
    tilt_pct_to_step,
)


@pytest.mark.parametrize(
    ("level", "position"),
    [(0, 100), (10000, 0), (5000, 50), (9949, 1), (9950, 0), (49, 100), (50, 99)],
)
def test_level_to_position(level: int, position: int) -> None:
    assert level_to_position(level) == position


@pytest.mark.parametrize(("position", "level"), [(100, 0), (0, 10000), (60, 4000)])
def test_position_to_level(position: int, level: int) -> None:
    assert position_to_level(position) == level


def test_tilt_round_trips_are_stable() -> None:
    for step in range(10):
        pct = step_to_tilt_pct(step)
        assert tilt_pct_to_step(pct) == step, (step, pct)
    assert step_to_tilt_pct(9) == 100
    assert step_to_tilt_pct(0) == 0
    assert tilt_pct_to_step(50) == 5  # 4.5 rounds half-up
    assert tilt_pct_to_step(44) == 4
    assert step_to_tilt_pct(None) is None
    assert level_to_position(None) is None


def test_brightness() -> None:
    assert bri_to_brightness(0) == 0
    assert bri_to_brightness(10000) == 255
    assert bri_to_brightness(5000) == 128
    assert brightness_to_bri(255) == 10000
    assert brightness_to_bri(128) == 5020
    assert bri_to_brightness(None) is None


def test_parse_version() -> None:
    assert parse_version("6.0.41") == (6, 0, 41)
    assert parse_version("6.0.41-beta") == (6, 0, 41)
    assert parse_version("6.0.40") < (6, 0, 41)
