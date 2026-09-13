"""Scene platform: Wiser scenes (executed through their job)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WiserApiError, WiserConnectionError
from .const import DOMAIN, SIGNAL_STRUCTURE_UPDATED
from .coordinator import WiserCoordinator
from .data import WiserConfigEntry
from .entity import WiserGatewayEntity

PARALLEL_UPDATES = 1


def _job_for_scene(coordinator: WiserCoordinator, scene_id: int) -> int | None:
    data = coordinator.data
    scene = data.scenes.get(scene_id)
    if scene is None:
        return None
    if scene.job is not None:
        return scene.job
    for job in data.jobs.values():
        if scene_id in job.scenes:
            return job.id
    return None


async def async_setup_entry(
    hass: HomeAssistant, entry: WiserConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create scene entities."""
    coordinator = entry.runtime_data.coordinator
    known: set[int] = set()

    @callback
    def _add_new() -> None:
        new = []
        for scene in coordinator.data.scenes.values():
            if scene.id in known or _job_for_scene(coordinator, scene.id) is None:
                continue
            known.add(scene.id)
            new.append(WiserScene(coordinator, scene.id))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_STRUCTURE_UPDATED.format(entry.entry_id), _add_new)
    )


class WiserScene(WiserGatewayEntity, Scene):
    """Activating runs the job linked to the scene."""

    _attr_entity_category = None
    _attr_icon = "mdi:palette"

    def __init__(self, coordinator: WiserCoordinator, scene_id: int) -> None:
        """Unique id ``{sn}_scene_{id}``."""
        super().__init__(coordinator, f"scene_{scene_id}")
        self._scene_id = scene_id

    @property
    def name(self) -> str:
        """Scene name."""
        scene = self.data.scenes.get(self._scene_id)
        return scene.name if scene and scene.name else f"Scene {self._scene_id}"

    @property
    def available(self) -> bool:
        """Only while the scene exists."""
        return super().available and self._scene_id in self.data.scenes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Ids for reference."""
        return {
            "scene_id": self._scene_id,
            "job_id": _job_for_scene(self.coordinator, self._scene_id),
        }

    async def async_activate(self, **kwargs: Any) -> None:
        """Run the job."""
        job_id = _job_for_scene(self.coordinator, self._scene_id)
        if job_id is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="scene_without_job")
        try:
            await self.coordinator.client.run_job(job_id)
        except (WiserApiError, WiserConnectionError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="gateway_error",
                translation_placeholders={"error": str(err)},
            ) from err
