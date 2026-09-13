"""Smart relative tilt for venetian blinds.

The Wiser actuator does not know the absolute slat angle; ``tilt`` is a step counter 0..9.
``target_state {"tilt": n}`` always performs a reference run (down to 0, then up to n), which
is slow and visible. One ``ctrl`` click on up/down moves exactly one step without a reference
run - but single clicks may get lost, so the controller reads back and corrects.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
from enum import StrEnum
import logging
import time

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .api import TILT_MAX, CtrlButton, CtrlEvent, LoadState, WiserApiError, WiserConnectionError
from .const import (
    DEFAULT_CLICK_MARGIN_MS,
    DEFAULT_FALLBACK_CLICK_PAUSE_MS,
    DEFAULT_TILT_FALLBACK_REFERENCE,
    DEFAULT_TILT_MAX_ROUNDS,
    DEFAULT_TILT_MODE,
    DEFAULT_TILT_SETTLE_MS,
    DOMAIN,
    OPT_CLICK_MARGIN_MS,
    OPT_FALLBACK_CLICK_PAUSE_MS,
    OPT_TILT_FALLBACK_REFERENCE,
    OPT_TILT_MAX_ROUNDS,
    OPT_TILT_MODE,
    OPT_TILT_SETTLE_MS,
)
from .coordinator import WiserCoordinator

_LOGGER = logging.getLogger(__name__)

LEVEL_DRIFT_ABORT = 500
"""Level change (of 10000) between rounds that means someone else moved the blind."""
STOP_WAIT_S = 1.0
OVERALL_TIMEOUT_S = 120.0
MOVING_WAIT_BEFORE_START_S = 10.0
REFERENCE_RUN_TIMEOUT_S = 60.0


class TiltMode(StrEnum):
    """How to reach the target."""

    AUTO = "auto"
    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    REFERENCE = "reference"


class TiltResult(StrEnum):
    """Outcome of a tilt command."""

    OK = "ok"
    DONE_REFERENCE = "done_reference"
    MISMATCH = "mismatch"
    SKIPPED_MOVING = "skipped_moving"
    SKIPPED_LOCKED = "skipped_locked"
    SKIPPED_LEARNING = "skipped_learning"
    ABORTED_EXTERNAL_MOVE = "aborted_external_move"
    STARTED = "started"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TiltOutcome:
    """Service response."""

    result: TiltResult
    tilt_steps: int | None
    rounds: int

    def as_dict(self) -> dict[str, int | str | None]:
        """Serializable form."""
        return {"result": str(self.result), "tilt_steps": self.tilt_steps, "rounds": self.rounds}


@dataclass(frozen=True, slots=True)
class TiltOptions:
    """Snapshot of the relevant config entry options."""

    mode: str = DEFAULT_TILT_MODE
    click_margin_ms: int = DEFAULT_CLICK_MARGIN_MS
    fallback_click_pause_ms: int = DEFAULT_FALLBACK_CLICK_PAUSE_MS
    settle_ms: int = DEFAULT_TILT_SETTLE_MS
    max_rounds: int = DEFAULT_TILT_MAX_ROUNDS
    fallback_reference: bool = DEFAULT_TILT_FALLBACK_REFERENCE

    @classmethod
    def from_options(cls, options: dict[str, object]) -> TiltOptions:
        """Read the options with defaults."""
        return cls(
            mode=str(options.get(OPT_TILT_MODE, DEFAULT_TILT_MODE)),
            click_margin_ms=int(options.get(OPT_CLICK_MARGIN_MS, DEFAULT_CLICK_MARGIN_MS)),  # type: ignore[call-overload]
            fallback_click_pause_ms=int(
                options.get(OPT_FALLBACK_CLICK_PAUSE_MS, DEFAULT_FALLBACK_CLICK_PAUSE_MS)  # type: ignore[call-overload]
            ),
            settle_ms=int(options.get(OPT_TILT_SETTLE_MS, DEFAULT_TILT_SETTLE_MS)),  # type: ignore[call-overload]
            max_rounds=int(options.get(OPT_TILT_MAX_ROUNDS, DEFAULT_TILT_MAX_ROUNDS)),  # type: ignore[call-overload]
            fallback_reference=bool(
                options.get(OPT_TILT_FALLBACK_REFERENCE, DEFAULT_TILT_FALLBACK_REFERENCE)
            ),
        )


class TiltController:
    """One per tiltable load; serialises tilt commands and implements the click loop."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: WiserCoordinator,
        load_id: int,
        options_getter: Callable[[], TiltOptions],
    ) -> None:
        """Create the controller; ``options_getter`` is read on every command."""
        self._hass = hass
        self._coordinator = coordinator
        self._client = coordinator.client
        self._load_id = load_id
        self._options_getter = options_getter
        self._lock = asyncio.Lock()
        self._job: asyncio.Task[TiltOutcome] | None = None
        self._state_event = asyncio.Event()
        self._latest: LoadState | None = coordinator.data.load_states.get(load_id)
        self._unsub = coordinator.async_add_load_listener(load_id, self._on_state)
        self.last_outcome: TiltOutcome | None = None

    # ------------------------------------------------------------------ properties
    @property
    def tilt_ms(self) -> int | None:
        """Duration of one tilt step from the device configuration, if known."""
        data = self._coordinator.data
        load = data.loads.get(self._load_id)
        if load is None:
            return None
        config = data.motor_config(load)
        if config is None or not config.tilt_ms:
            return None
        return config.tilt_ms

    @property
    def running(self) -> bool:
        """True while a tilt job is active."""
        return self._job is not None and not self._job.done()

    # ------------------------------------------------------------------ lifecycle
    @callback
    def _on_state(self) -> None:
        self._latest = self._coordinator.data.load_states.get(self._load_id)
        self._state_event.set()

    async def cancel(self) -> None:
        """Abort a running job (between two clicks; clicks are atomic)."""
        if self._job is not None and not self._job.done():
            self._job.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._job
        self._job = None

    def close(self) -> None:
        """Detach from the coordinator."""
        self._unsub()

    # ------------------------------------------------------------------ public API
    async def set_steps(
        self,
        target: int,
        mode: TiltMode = TiltMode.AUTO,
        *,
        wait: bool = True,
        max_rounds: int | None = None,
    ) -> TiltOutcome:
        """Tilt to ``target`` (absolute 0..9, or signed delta in RELATIVE mode)."""
        await self.cancel()
        self._job = self._hass.async_create_task(
            self._run(target, mode, max_rounds), f"{DOMAIN}-tilt-{self._load_id}"
        )
        if not wait:
            return TiltOutcome(TiltResult.STARTED, self._current_tilt(), 0)
        try:
            return await asyncio.wait_for(asyncio.shield(self._job), OVERALL_TIMEOUT_S)
        except TimeoutError as err:
            await self.cancel()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="tilt_timeout"
            ) from err
        except asyncio.CancelledError:
            if self._job is not None and self._job.cancelled():
                return TiltOutcome(TiltResult.CANCELLED, self._current_tilt(), 0)
            raise

    # ------------------------------------------------------------------ internals
    def _current_tilt(self) -> int | None:
        return self._latest.tilt if self._latest is not None else None

    async def _run(self, target: int, mode: TiltMode, max_rounds: int | None) -> TiltOutcome:
        async with self._lock:
            outcome = await self._run_locked(target, mode, max_rounds)
            self.last_outcome = outcome
            return outcome

    async def _run_locked(self, target: int, mode: TiltMode, max_rounds: int | None) -> TiltOutcome:
        options = self._options_getter()
        rounds_limit = max_rounds or options.max_rounds
        state = await self._fresh_state()
        if state.flags.locked:
            return TiltOutcome(TiltResult.SKIPPED_LOCKED, state.tilt, 0)
        if state.flags.learning:
            return TiltOutcome(TiltResult.SKIPPED_LEARNING, state.tilt, 0)
        if mode is TiltMode.RELATIVE:
            if state.tilt is None:
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="tilt_unknown")
            target = state.tilt + target
        target = max(0, min(TILT_MAX, target))
        if state.is_moving:
            waited = await self._wait_for_stop(MOVING_WAIT_BEFORE_START_S)
            if waited is None or waited.is_moving:
                return TiltOutcome(TiltResult.SKIPPED_MOVING, state.tilt, 0)
            state = await self._fresh_state()
        use_reference = (
            mode is TiltMode.REFERENCE
            or options.mode == "reference"
            or state.tilt is None
            or (mode is TiltMode.AUTO and target == 0 and state.tilt != 0)
        )
        if use_reference:
            await self._reference_run(target)
            return TiltOutcome(TiltResult.DONE_REFERENCE, self._current_tilt(), 0)
        result, rounds, state = await self._click_loop(target, state, options, rounds_limit)
        if result is TiltResult.MISMATCH and mode is TiltMode.AUTO and options.fallback_reference:
            _LOGGER.warning(
                "Load %s: tilt is %s after %s rounds, falling back to a reference run to %s",
                self._load_id,
                state.tilt,
                rounds,
                target,
            )
            await self._reference_run(target)
            return TiltOutcome(TiltResult.DONE_REFERENCE, self._current_tilt(), rounds)
        return TiltOutcome(result, state.tilt, rounds)

    async def _reference_run(self, target: int) -> None:
        try:
            await self._client.set_target_state(self._load_id, tilt=target)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err
        # give the actuator a moment to report "moving" before we wait for "stop"
        await asyncio.sleep(0.5)
        await self._wait_for_stop(REFERENCE_RUN_TIMEOUT_S)
        with contextlib.suppress(HomeAssistantError):
            await self._fresh_state()

    async def _click_loop(
        self, target: int, state: LoadState, options: TiltOptions, rounds_limit: int
    ) -> tuple[TiltResult, int, LoadState]:
        tilt_ms = self.tilt_ms
        pause_s = (
            (tilt_ms + options.click_margin_ms) / 1000
            if tilt_ms
            else options.fallback_click_pause_ms / 1000
        )
        level0 = state.level if state.level is not None else 0
        rounds = 0
        for rounds in range(1, rounds_limit + 1):
            if state.tilt is None:
                return TiltResult.MISMATCH, rounds, state
            diff = target - state.tilt
            if diff == 0:
                return TiltResult.OK, rounds - 1, state
            button = CtrlButton.UP if diff > 0 else CtrlButton.DOWN
            _LOGGER.debug(
                "Load %s: round %s, tilt %s -> %s (%d clicks %s, pause %.2f s)",
                self._load_id,
                rounds,
                state.tilt,
                target,
                abs(diff),
                button,
                pause_s,
            )
            for _ in range(abs(diff)):
                current = await self._wait_for_stop(STOP_WAIT_S)
                if current is None or current.is_moving:
                    return TiltResult.ABORTED_EXTERNAL_MOVE, rounds, current or state
                if current.level is not None and abs(current.level - level0) > LEVEL_DRIFT_ABORT:
                    return TiltResult.ABORTED_EXTERNAL_MOVE, rounds, current
                if current.flags.locked:
                    return TiltResult.SKIPPED_LOCKED, rounds, current
                try:
                    await self._client.ctrl(self._load_id, button, CtrlEvent.CLICK)
                except (WiserApiError, WiserConnectionError) as err:
                    # never retry a click blindly (it could double-step); verify instead
                    _LOGGER.debug("Load %s: click failed (%s), verifying", self._load_id, err)
                    break
                await asyncio.sleep(pause_s)
            await self._wait_for_stop(pause_s)
            await asyncio.sleep(options.settle_ms / 1000)
            state = await self._fresh_state()
        if state.tilt == target:
            return TiltResult.OK, rounds, state
        return TiltResult.MISMATCH, rounds, state

    async def _wait_for_stop(self, timeout_s: float) -> LoadState | None:
        """Return the state once ``moving == stop`` or ``None`` on timeout."""
        deadline = time.monotonic() + timeout_s
        while True:
            latest = self._latest
            if latest is not None and not latest.is_moving:
                return latest
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if self._coordinator.data.ws_connected:
                self._state_event.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._state_event.wait(), min(1.0, remaining))
            else:
                await asyncio.sleep(min(1.0, remaining))
                with contextlib.suppress(HomeAssistantError):
                    await self._fresh_state()

    async def _fresh_state(self) -> LoadState:
        try:
            state = await self._client.get_load_state(self._load_id)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err
        self._coordinator.async_set_load_state(self._load_id, state)
        self._latest = state
        return state
