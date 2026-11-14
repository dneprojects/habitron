"""Smart Energy Agent (SEA) add-on: client, coordinator and entities."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from typing import Any, Final

import aiohttp

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    CURRENCY_EURO,
    Platform,
    UnitOfEnergy,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SEA_ID

_LOGGER = logging.getLogger(__name__)

SEA_PLATFORMS: Final = [Platform.BINARY_SENSOR, Platform.SENSOR]
SEA_NAME: Final = "Smart Energy Agent"
_RETRY_MIN: Final = 5
_RETRY_MAX: Final = 300
_HEARTBEAT: Final = 30
_TIMEOUT: Final = aiohttp.ClientTimeout(total=10)
_URL_SCHEMES: Final = ("http://", "https://", "homeassistant://")

type SeaConfigEntry = ConfigEntry[SeaCoordinator]


class SeaError(Exception):
    """SEA could not be reached or answered unusably."""


class SeaClient:
    """HTTP and WebSocket access to the SEA add-on API."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, port: int, token: str
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base = f"http://{host}:{port}/api/v1"
        self._headers = {"Authorization": f"Bearer {token}"}

    async def _get(self, path: str) -> Any:
        try:
            async with self._session.get(
                f"{self._base}/{path}", headers=self._headers, timeout=_TIMEOUT
            ) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise SeaError(f"{path}: {err!r}") from err

    async def _get_object(self, path: str) -> dict[str, Any]:
        data = await self._get(path)
        if not isinstance(data, dict):
            raise SeaError(f"{path}: not an object")
        return data

    async def get_info(self) -> dict[str, Any]:
        """Return version, name and url of the add-on."""
        return await self._get_object("info")

    async def get_state(self) -> dict[str, Any]:
        """Return all current values."""
        return await self._get_object("state")

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        """Yield the push messages until the connection ends."""
        try:
            async with self._session.ws_connect(
                f"{self._base}/ws", headers=self._headers, heartbeat=_HEARTBEAT
            ) as ws:
                async for msg in ws:
                    if msg.type is not aiohttp.WSMsgType.TEXT:
                        break
                    try:
                        yield json.loads(msg.data)
                    except ValueError:
                        _LOGGER.debug("Ignoring unreadable SEA message")
        except aiohttp.ClientError as err:
            raise SeaError(f"ws: {err!r}") from err
        raise SeaError("ws: connection closed")


class SeaCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Hold the values SEA pushes."""

    config_entry: SeaConfigEntry

    def __init__(self, hass: HomeAssistant, entry: SeaConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass, _LOGGER, config_entry=entry, name=SEA_NAME, update_interval=None
        )
        self.client = SeaClient(
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.data[CONF_PORT],
            entry.data[CONF_TOKEN],
        )
        self.info: dict[str, Any] = {}

    @property
    def configuration_url(self) -> str | None:
        """Return the url if the device registry accepts it."""
        url = self.info.get("url")
        return url if isinstance(url, str) and url.startswith(_URL_SCHEMES) else None

    async def _async_update_data(self) -> dict[str, Any]:
        """Read info and the full state once."""
        try:
            self.info = await self.client.get_info()
            return await self.client.get_state()
        except SeaError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="sea_unreachable"
            ) from err

    async def async_listen(self) -> None:
        """Follow the push channel, reconnecting with backoff."""
        retry = _RETRY_MIN
        while True:
            try:
                async for message in self.client.messages():
                    retry = _RETRY_MIN
                    self._handle(message)
            except SeaError as err:
                _LOGGER.debug("SEA connection lost: %s", err)
                self.async_set_update_error(err)
            await asyncio.sleep(retry)
            retry = min(retry * 2, _RETRY_MAX)
            try:
                self.info = await self.client.get_info()
            except SeaError:
                continue
            self._update_device()

    def _handle(self, message: dict[str, Any]) -> None:
        values = message.get("values")
        if not isinstance(values, dict):
            return
        if message.get("type") == "snapshot":
            self.async_set_updated_data(values)
        elif message.get("type") == "update":
            self.async_set_updated_data({**(self.data or {}), **values})

    def _update_device(self) -> None:
        registry = dr.async_get(self.hass)
        if device := registry.async_get_device({(DOMAIN, SEA_ID)}):
            registry.async_update_device(
                device.id,
                sw_version=self.info.get("version"),
                configuration_url=self.configuration_url,
            )


async def async_setup_sea_entry(hass: HomeAssistant, entry: SeaConfigEntry) -> bool:
    """Set up the SEA add-on entry."""
    coordinator = SeaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    # The b1 service stored its entity list here; nothing reads it any more.
    await Store(hass, 1, f"{DOMAIN}.sea").async_remove()
    await hass.config_entries.async_forward_entry_setups(entry, SEA_PLATFORMS)
    entry.async_create_background_task(
        hass, coordinator.async_listen(), "habitron_sea_listen"
    )
    return True


async def async_unload_sea_entry(hass: HomeAssistant, entry: SeaConfigEntry) -> bool:
    """Unload the SEA add-on entry."""
    return await hass.config_entries.async_unload_platforms(entry, SEA_PLATFORMS)


@dataclass(frozen=True, kw_only=True)
class SeaSensorEntityDescription(SensorEntityDescription):
    """SEA sensor; ``key`` is the key of the SEA contract."""


SEA_SENSORS: Final[tuple[SeaSensorEntityDescription, ...]] = (
    *(
        SeaSensorEntityDescription(
            key=key,
            translation_key=key,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=1,
        )
        for key in ("pv_prognose_heute", "pv_prognose_heute_rest", "pv_prognose_morgen")
    ),
    SeaSensorEntityDescription(
        key="strompreis",
        translation_key="strompreis",
        native_unit_of_measurement="ct/kWh",
        suggested_display_precision=1,
    ),
    *(
        SeaSensorEntityDescription(
            key=key, translation_key=key, device_class=SensorDeviceClass.TIMESTAMP
        )
        for key in (
            "naechstes_guenstiges_fenster",
            "naechstes_guenstiges_fenster_ende",
            "akku_plan_bis",
        )
    ),
    SeaSensorEntityDescription(
        key="akku_plan",
        translation_key="akku_plan",
        device_class=SensorDeviceClass.ENUM,
        options=["charge_pv", "charge_grid", "discharge", "hold", "spare", "idle"],
    ),
    SeaSensorEntityDescription(
        key="regelung",
        translation_key="regelung",
        device_class=SensorDeviceClass.ENUM,
        options=["auto", "assisted", "rules", "manual"],
    ),
    *(
        SeaSensorEntityDescription(
            key=key,
            translation_key=key,
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement=CURRENCY_EURO,
            suggested_display_precision=2,
        )
        for key in ("kosten_heute", "einsparung_heute")
    ),
    SeaSensorEntityDescription(key="hinweise", translation_key="hinweise"),
)

SEA_BINARY_SENSORS: Final[tuple[BinarySensorEntityDescription, ...]] = tuple(
    BinarySensorEntityDescription(key=key, translation_key=key)
    for key in ("guenstig", "einspeisung_gesperrt", "14a_gedimmt")
)


class SeaEntity(CoordinatorEntity[SeaCoordinator]):
    """Base class of the SEA entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SeaCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        # Same unique id as the b1 service entities, so their entity ids stay.
        self._attr_unique_id = f"{SEA_ID}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, SEA_ID)},
            name="SEA",
            manufacturer="Habitron",
            model=SEA_NAME,
            sw_version=coordinator.info.get("version"),
            configuration_url=coordinator.configuration_url,
        )

    @property
    def _raw(self) -> Any:
        return (self.coordinator.data or {}).get(self.entity_description.key)

    @property
    def available(self) -> bool:
        """Return whether SEA is connected and reports this key."""
        return super().available and self.entity_description.key in (
            self.coordinator.data or {}
        )


class SeaSensor(SeaEntity, SensorEntity):
    """SEA value."""

    entity_description: SeaSensorEntityDescription

    def __init__(
        self, coordinator: SeaCoordinator, description: SeaSensorEntityDescription
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        super().__init__(coordinator, description.key)

    @property
    def native_value(self) -> str | float | datetime | None:
        """Return the value in the type the contract declares."""
        raw = self._raw
        if raw is None:
            return None
        device_class = self.entity_description.device_class
        if device_class is SensorDeviceClass.TIMESTAMP:
            value = dt_util.parse_datetime(str(raw))
            return value if value is not None and value.tzinfo is not None else None
        if device_class is SensorDeviceClass.ENUM:
            options = self.entity_description.options or []
            return raw if raw in options else None
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return None
        return raw


class SeaBinarySensor(SeaEntity, BinarySensorEntity):
    """SEA flag."""

    def __init__(
        self, coordinator: SeaCoordinator, description: BinarySensorEntityDescription
    ) -> None:
        """Initialize the binary sensor."""
        self.entity_description = description
        super().__init__(coordinator, description.key)

    @property
    def is_on(self) -> bool | None:
        """Return the flag."""
        raw = self._raw
        return raw if isinstance(raw, bool) else None
