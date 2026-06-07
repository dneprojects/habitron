"""Habitron integration using DataUpdateCoordinator."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

if TYPE_CHECKING:
    from .communicate import HbtnComm
    from .smart_hub import SmartHub

type HabitronConfigEntry = ConfigEntry["SmartHub"]
"""Typed config entry alias. ``entry.runtime_data`` holds the SmartHub.

Defined here rather than in ``smart_hub`` to avoid a circular import:
platforms need this type, and several core modules in the import graph
(``router`` → ``module`` → ``binary_sensor``) already pull from
platform files.
"""

_LOGGER = logging.getLogger(__name__)


class HbtnCoordinator(DataUpdateCoordinator[None]):
    """Habitron data update coordinator.

    The coordinator does not cache its own payload: ``async_system_update``
    writes the bus status directly into the module/input/output objects,
    and the entities read from those object attributes via their
    ``_handle_coordinator_update`` callbacks. The coordinator therefore
    acts as a heartbeat that fans out update events on each tick.

    Because of this ``always_update=True`` is required: with
    ``always_update=False`` the change-detection would compare
    ``None == None`` between ticks and never propagate the heartbeat,
    leaving entities frozen at their initial values.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HabitronConfigEntry,
        hbtn_comm: HbtnComm,
    ) -> None:
        """Initialize Habitron update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Habitron updates",
            config_entry=entry,
            update_interval=timedelta(
                seconds=hbtn_comm._config.data["update_interval"]  # noqa: SLF001
            ),
            always_update=True,
        )
        self.comm = hbtn_comm
        self.config = hbtn_comm._config  # noqa: SLF001
        self.rtr_id = 1
        self.previous_devices: set[str] = set()

    def set_update_interval(self, interval: int, updates: bool) -> None:
        """Update interval for integration re-configuration."""
        self.update_interval = timedelta(seconds=interval)
        self.comm.update_suspended = not updates

    async def _async_setup(self) -> None:
        """Run a first fetch during ``async_config_entry_first_refresh``."""
        await self._async_update_data()

    async def _async_update_data(self) -> None:
        """Fetch the current Habitron status.

        The returned value is unused; ``async_system_update`` writes
        directly into module/input/output objects. Connection-level
        failures (timeouts, network errors, refused connections) are
        converted to ``UpdateFailed`` so the coordinator flips
        ``last_update_success`` to False and every ``CoordinatorEntity``
        is automatically marked unavailable in the frontend.
        """
        try:
            async with asyncio.timeout(20):
                await self.comm.async_system_update()
        except TimeoutError as err:
            raise UpdateFailed(
                "Timeout fetching system status from SmartHub"
            ) from err
        except (OSError, ConnectionError) as err:
            raise UpdateFailed(
                f"Network error fetching status from SmartHub: {err}"
            ) from err
