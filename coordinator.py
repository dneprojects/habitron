"""Example integration using DataUpdateCoordinator."""

from datetime import timedelta
import logging

import async_timeout

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator


_LOGGER = logging.getLogger(__name__)


class HbtnCoordinator(DataUpdateCoordinator):
    """Habitron data update coordinator."""

    def __init__(self, hass: HomeAssistant, hbtn_comm) -> None:
        """Initialize Habitron update coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="Habitron updates",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(
                seconds=hbtn_comm._config.data["update_interval"]
            ),
        )
        self.comm = hbtn_comm
        self.config = hbtn_comm._config
        self.rtr_id = 1

    def set_update_interval(self, interval: int, updates: bool):
        """Updating interval for integration re-configuration"""
        self.update_interval = timedelta(seconds=interval)
        self.comm.update_suspended = not (updates)

    async def _async_update_data(self):
        """Fetch data from Habitron comm endpoint, preprocess and store for lookup."""
        # Note: asyncio.TimeoutError and aiohttp.ClientError are already
        # handled by the data update coordinator.
        async with async_timeout.timeout(10):
            # Grab active context variables to limit data required to be fetched from API
            # Note: using context is not required if there is no need or ability to limit
            # data retrieved from API.
            # listening_idx = set(self.async_contexts())

            # not inital update, can be diabled
            return await self.comm.async_system_update()
