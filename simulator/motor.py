"""Motor (blind) physics for the simulator.

Semantics (from the Feller tutorial and field experience):
* ``level`` 0 = fully open/up, 10000 = fully closed/down; moves at ``speed`` units/s.
* ``tilt`` is a step counter 0..9; one ``click`` on up/down is exactly one step and keeps the
  motor "moving" for ``tilt_ms``.
* a ``click`` while moving stops whatever is running.
* ``press`` on up/down starts a full travel to the end position.
* ``target_state`` with ``tilt`` first drives the slats to 0 (reference run) and then up to
  the requested step; with ``level`` it runs to that level first.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .model import Load

TILT_MAX = 9
LEVEL_MAX = 10000


@dataclass
class LevelRun:
    target: int


@dataclass
class TiltStep:
    direction: int  # +1 = up (towards 9), -1 = down (towards 0)
    remaining_s: float | None = None


@dataclass
class MotorLoad(Load):
    """A motor output channel."""

    level: int = 0
    tilt: int = 0
    moving: str = "stop"
    tilt_ms: int = 250
    speed: float = 10000 / 60
    tiltable: bool = True
    flags: dict[str, int] = field(
        default_factory=lambda: {
            "direction": 0,
            "learning": 0,
            "moving": 0,
            "under_current": 0,
            "over_current": 0,
            "timeout": 0,
            "locked": 0,
        }
    )
    plan: deque[LevelRun | TiltStep] = field(default_factory=deque)
    clicks_received: int = 0
    ctrl_log: list[tuple[str, str]] = field(default_factory=list)

    # ------------------------------------------------------------------ state
    def state(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "tilt": self.tilt,
            "moving": self.moving,
            "flags": dict(self.flags),
        }

    def _set_moving(self, moving: str) -> None:
        self.moving = moving
        self.flags["moving"] = 0 if moving == "stop" else 1
        if moving != "stop":
            self.flags["direction"] = 1 if moving == "down" else 0

    def _stop(self) -> None:
        self.plan.clear()
        self._set_moving("stop")

    # ------------------------------------------------------------------ commands
    def ctrl(self, button: str, event: str) -> None:
        self.ctrl_log.append((button, event))
        if self.flags.get("locked"):
            return
        if button == "stop":
            self._stop()
            return
        if event == "click":
            self.clicks_received += 1
            if self.moving != "stop":
                self._stop()
                return
            if button == "up":
                self.plan.append(TiltStep(+1))
            elif button == "down":
                self.plan.append(TiltStep(-1))
            return
        if event == "press":
            if button == "up":
                self.plan.clear()
                self.plan.append(LevelRun(0))
            elif button == "down":
                self.plan.clear()
                self.plan.append(LevelRun(LEVEL_MAX))
        # release: nothing to do for motors

    def target_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.flags.get("locked"):
            return {}
        self.plan.clear()
        applied: dict[str, Any] = {}
        if "level" in payload:
            level = max(0, min(LEVEL_MAX, int(payload["level"])))
            self.plan.append(LevelRun(level))
            applied["level"] = level
        if "tilt" in payload and self.tiltable:
            target = max(0, min(TILT_MAX, int(payload["tilt"])))
            # reference run: down to 0, then up to target
            for _ in range(self.tilt):
                self.plan.append(TiltStep(-1))
            for _ in range(target):
                self.plan.append(TiltStep(+1))
            applied["tilt"] = target
        if not self.plan:
            self._set_moving("stop")
        return applied

    # ------------------------------------------------------------------ physics
    def tick(self, dt: float) -> dict[str, Any] | None:
        """Advance ``dt`` seconds; return the changed state fields (or None).

        ``tick(0)`` starts the pending phase (sets ``moving``) without advancing time.
        """
        before = self.state()
        remaining = dt
        while self.plan:
            phase = self.plan[0]
            if isinstance(phase, LevelRun):
                if phase.target == self.level:
                    self.plan.popleft()
                    continue
                self._set_moving("down" if phase.target > self.level else "up")
                if remaining <= 0:
                    break
                remaining = self._tick_level(phase, remaining)
            else:
                if phase.remaining_s is None:
                    phase.remaining_s = self.tilt_ms / 1000
                    self._set_moving("up" if phase.direction > 0 else "down")
                if remaining <= 0:
                    break
                remaining = self._tick_tilt(phase, remaining)
        if not self.plan and self.moving != "stop":
            self._set_moving("stop")
        after = self.state()
        changed = {k: v for k, v in after.items() if before.get(k) != v}
        return changed or None

    def _tick_level(self, phase: LevelRun, remaining: float) -> float:
        direction = "down" if phase.target > self.level else "up"
        distance = abs(phase.target - self.level)
        needed_s = distance / self.speed
        if remaining >= needed_s:
            self.level = phase.target
            self.plan.popleft()
            return remaining - needed_s
        step = int(self.speed * remaining)
        self.level += step if direction == "down" else -step
        return 0.0

    def _tick_tilt(self, phase: TiltStep, remaining: float) -> float:
        assert phase.remaining_s is not None
        if remaining >= phase.remaining_s:
            remaining -= phase.remaining_s
            self.tilt = max(0, min(TILT_MAX, self.tilt + phase.direction))
            self.plan.popleft()
            return remaining
        phase.remaining_s -= remaining
        return 0.0

    @property
    def is_idle(self) -> bool:
        return not self.plan and self.moving == "stop"
