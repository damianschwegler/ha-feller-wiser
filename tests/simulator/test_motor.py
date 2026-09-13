"""Motor physics of the simulator (no HA, no sockets)."""

from simulator.motor import MotorLoad


def make_motor(level: int = 10000, tilt: int = 4, tilt_ms: int = 100) -> MotorLoad:
    return MotorLoad(
        id=1, name="test", type="motor", level=level, tilt=tilt, tilt_ms=tilt_ms, speed=1000.0
    )


def test_click_is_one_tilt_step_relative() -> None:
    motor = make_motor(tilt=4)
    motor.ctrl("up", "click")
    changed = motor.tick(0.0)
    assert changed == {"moving": "up", "flags": motor.flags}
    assert motor.moving == "up"
    assert motor.tick(0.05) is None  # still within the step
    changed = motor.tick(0.06)
    assert motor.tilt == 5
    assert motor.moving == "stop"
    assert changed is not None
    assert changed["tilt"] == 5


def test_click_while_moving_stops() -> None:
    motor = make_motor(level=0)
    motor.ctrl("down", "press")
    motor.tick(1.0)
    assert motor.moving == "down"
    assert 0 < motor.level < 10000
    level_before = motor.level
    motor.ctrl("down", "click")
    motor.tick(1.0)
    assert motor.moving == "stop"
    assert motor.level == level_before


def test_press_runs_to_end_position() -> None:
    motor = make_motor(level=0)
    motor.ctrl("down", "press")
    motor.tick(5.0)
    assert motor.level == 5000
    motor.tick(5.0)
    assert motor.level == 10000
    assert motor.moving == "stop"


def test_target_state_with_tilt_does_reference_run() -> None:
    motor = make_motor(tilt=4, tilt_ms=100)
    applied = motor.target_state({"tilt": 2})
    assert applied == {"tilt": 2}
    # 4 steps down (reference) + 2 up = 6 steps of 100 ms
    motor.tick(0.0)
    assert motor.moving == "down"
    motor.tick(0.41)
    assert motor.tilt == 0
    motor.tick(0.2)
    assert motor.tilt == 2
    assert motor.moving == "stop"


def test_tilt_clamps() -> None:
    motor = make_motor(tilt=9)
    motor.ctrl("up", "click")
    motor.tick(1.0)
    assert motor.tilt == 9
    motor = make_motor(tilt=0)
    motor.ctrl("down", "click")
    motor.tick(1.0)
    assert motor.tilt == 0


def test_locked_ignores_commands() -> None:
    motor = make_motor(tilt=4)
    motor.flags["locked"] = 1
    motor.ctrl("up", "click")
    motor.tick(1.0)
    assert motor.tilt == 4
    assert motor.target_state({"level": 0}) == {}
