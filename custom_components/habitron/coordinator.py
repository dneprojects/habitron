"""Habitron integration using DataUpdateCoordinator."""

import asyncio
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from habitron_client import HabitronError, HabitronTimeoutError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL

if TYPE_CHECKING:
    from .communicate import HbtnComm
    from .module import HbtnModule
    from .router import HbtnRouter
    from .smart_hub import SmartHub

# Firmware is quasi-static and the bus read is comparatively slow, so it is
# polled round-robin (one module per tick) on a slow, separate coordinator.
FW_POLL_INTERVAL = timedelta(seconds=60)

type HabitronConfigEntry = ConfigEntry["SmartHub"]
"""Typed config entry alias. ``entry.runtime_data`` holds the SmartHub.

Defined here rather than in ``smart_hub`` to avoid a circular import:
platforms need this type, and several core modules in the import graph
(``router`` → ``module`` → ``binary_sensor``) already pull from
platform files.
"""

_LOGGER = logging.getLogger(__name__)


class HbtnCoordinator(DataUpdateCoordinator[bytes]):
    """Habitron data update coordinator.

    ``async_system_update`` writes the bus status directly into the
    module/input/output objects, and the entities read from those object
    attributes via their ``_handle_coordinator_update`` callbacks. The
    coordinator acts as a heartbeat that fans out update events.

    ``async_system_update`` returns the raw compact-status bytes, which serve
    as the change-detection key. With ``always_update=False`` the coordinator
    only fans out to the entities when the bus status actually changed between
    ticks, avoiding a needless write of every entity on every tick.
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
            update_interval=SCAN_INTERVAL,
            always_update=False,
        )
        self.comm = hbtn_comm
        self.config = hbtn_comm._config  # noqa: SLF001
        self.rtr_id = 1
        self.previous_devices: set[str] = set()

    async def _async_setup(self) -> None:
        """Run a first fetch during ``async_config_entry_first_refresh``."""
        await self._async_update_data()

    async def _async_update_data(self) -> bytes:
        """Fetch the current Habitron status.

        Returns the compact-status bytes used for change detection;
        ``async_system_update`` also writes directly into the
        module/input/output objects. Connection-level failures (timeouts,
        network errors, refused connections) are converted to ``UpdateFailed``
        so the coordinator flips ``last_update_success`` to False and every
        ``CoordinatorEntity`` is automatically marked unavailable.
        """
        try:
            async with asyncio.timeout(20):
                return await self.comm.async_system_update()
        except (TimeoutError, HabitronTimeoutError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_timeout",
            ) from err
        except (OSError, ConnectionError, HabitronError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_network_error",
                translation_placeholders={"error": str(err)},
            ) from err


class HbtnFirmwareCoordinator(DataUpdateCoordinator[dict[str, tuple[str, str]]]):
    """Poll module firmware versions round-robin, one module per refresh.

    Firmware versions are quasi-static and the bus read is comparatively slow,
    so they are kept off the fast status coordinator. Each refresh reads a
    single target (rotating through router + modules), keeping every cycle to at
    most one serial bus read. Results are stored as ``{uid: (installed, latest)}``
    and the firmware update entities reflect them in their coordinator callback.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: HabitronConfigEntry,
        hbtn_comm: HbtnComm,
    ) -> None:
        """Initialize the firmware coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Habitron firmware",
            config_entry=entry,
            update_interval=FW_POLL_INTERVAL,
        )
        self.comm = hbtn_comm
        self._index = 0
        self.data = {}

    async def _async_update_data(self) -> dict[str, tuple[str, str]]:
        """Read one target's firmware (round-robin) and merge it into data."""
        targets: list[HbtnRouter | HbtnModule] = [
            self.comm.router,
            *self.comm.router.modules,
        ]
        if targets:
            target = targets[self._index % len(targets)]
            self._index += 1
            await self._read_target(target)
        return self.data

    async def _read_target(self, target: HbtnRouter | HbtnModule) -> None:
        """Read installed/latest firmware for a single target into data."""
        addr = getattr(target, "raddr", 0)
        try:
            resp = await self.comm.handle_firmware(addr)
        except (OSError, ConnectionError, HabitronError) as err:
            _LOGGER.debug("Firmware read failed for %s: %s", target.name, err)
            return
        if not resp:
            return  # unchanged (crc match) or read error
        versions = resp.decode("iso8859-1").split("\n")
        if len(versions) != 2:
            return
        installed, latest = versions[0], versions[1]
        if self.data.get(target.uid) == (installed, latest):
            return
        self.data[target.uid] = (installed, latest)
        if latest != installed:
            _LOGGER.info("Firmware %s: %s -> %s", target.name, installed, latest)
