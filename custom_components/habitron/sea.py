"""Smart Energy Agent (SEA) add-on: coordinator and entities."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Final

from habitron_client.sea import SeaClient, SeaCommandError, SeaError

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SEA_ID

_LOGGER = logging.getLogger(__name__)

SEA_PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]
SEA_NAME: Final = "Smart Energy Agent"
_RETRY_MIN: Final = 5
_RETRY_MAX: Final = 300
_URL_SCHEMES: Final = ("http://", "https://", "homeassistant://")

type SeaConfigEntry = ConfigEntry[SeaCoordinator]


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

    async def async_command(self, key: str, value: str | bool) -> None:
        """Send a command; the push update brings the new state."""
        try:
            await self.client.command(key, value)
        except SeaCommandError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="sea_command_refused"
            ) from err
        except SeaError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="sea_unreachable"
            ) from err


async def async_setup_sea_entry(hass: HomeAssistant, entry: SeaConfigEntry) -> bool:
    """Set up the SEA add-on entry."""
    coordinator = SeaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
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


SEA_STRATEGIES: Final = (
    "self_consumption",
    "setpoint_boost",
    "tariff_shift",
    "setback",
    "circuit_guide",
    "battery_cover",
    "optimizer",
    "grid_limits",
    "peak_shaving",
    "feed_in_limit",
    "emergency_reserve",
    "battery_care",
    "rules",
)
# Strategies with their own on/off in SEA.
SEA_SWITCHABLE: Final = (
    "self_consumption",
    "setpoint_boost",
    "tariff_shift",
    "setback",
    "circuit_guide",
    "battery_cover",
    "peak_shaving",
    "feed_in_limit",
)

SEA_SENSORS: Final[tuple[SeaSensorEntityDescription, ...]] = (
    *(
        SeaSensorEntityDescription(
            key=key,
            translation_key=translation_key,
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=1,
        )
        for key, translation_key in (
            ("pv_prognose_heute", "pv_forecast_today"),
            ("pv_prognose_heute_rest", "pv_forecast_today_remaining"),
            ("pv_prognose_morgen", "pv_forecast_tomorrow"),
        )
    ),
    SeaSensorEntityDescription(
        key="strompreis",
        translation_key="electricity_price",
        native_unit_of_measurement="ct/kWh",
        suggested_display_precision=1,
    ),
    *(
        SeaSensorEntityDescription(
            key=key,
            translation_key=translation_key,
            device_class=SensorDeviceClass.TIMESTAMP,
        )
        for key, translation_key in (
            ("naechstes_guenstiges_fenster", "next_cheap_window"),
            ("naechstes_guenstiges_fenster_ende", "next_cheap_window_end"),
            ("akku_plan_bis", "battery_plan_until"),
            ("naechstes_pv_fenster", "next_pv_window"),
            ("naechstes_pv_fenster_ende", "next_pv_window_end"),
        )
    ),
    SeaSensorEntityDescription(
        key="strom_ampel",
        translation_key="power_traffic_light",
        device_class=SensorDeviceClass.ENUM,
        options=["green", "yellow", "red"],
    ),
    SeaSensorEntityDescription(
        key="akku_plan",
        translation_key="battery_plan",
        device_class=SensorDeviceClass.ENUM,
        options=["charge_pv", "charge_grid", "discharge", "hold", "spare", "idle"],
    ),
    *(
        SeaSensorEntityDescription(
            key=f"strategie_{strategy}",
            translation_key=f"strategy_{strategy}",
            device_class=SensorDeviceClass.ENUM,
            options=["off", "missing", "ready", "acting"],
        )
        for strategy in SEA_STRATEGIES
    ),
    SeaSensorEntityDescription(
        key="tarif",
        translation_key="tariff",
        device_class=SensorDeviceClass.ENUM,
        options=["fixed", "ht_nt", "dynamic"],
    ),
    *(
        SeaSensorEntityDescription(
            key=key,
            translation_key=translation_key,
            device_class=SensorDeviceClass.MONETARY,
            native_unit_of_measurement=CURRENCY_EURO,
            suggested_display_precision=2,
        )
        for key, translation_key in (
            ("kosten_heute", "cost_today"),
            ("einsparung_heute", "savings_today"),
        )
    ),
    SeaSensorEntityDescription(key="hinweise", translation_key="open_hints"),
)

SEA_BINARY_SENSORS: Final[tuple[BinarySensorEntityDescription, ...]] = tuple(
    BinarySensorEntityDescription(key=key, translation_key=translation_key)
    for key, translation_key in (
        ("guenstig", "cheap_now"),
        ("einspeisung_gesperrt", "feed_in_blocked"),
        ("14a_gedimmt", "dimmed_14a"),
    )
)

SEA_SWITCHES: Final[tuple[SwitchEntityDescription, ...]] = tuple(
    SwitchEntityDescription(
        key=f"strategie_{strategy}", translation_key=f"strategy_{strategy}"
    )
    for strategy in SEA_SWITCHABLE
)

SEA_SELECTS: Final[tuple[SelectEntityDescription, ...]] = (
    SelectEntityDescription(
        key="regelung",
        translation_key="control_mode",
        options=["auto", "assisted", "rules", "manual"],
    ),
)


class SeaEntity(CoordinatorEntity[SeaCoordinator]):
    """Base class of the SEA entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SeaCoordinator, key: str, suffix: str = "") -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{SEA_ID}_{key}{suffix}"
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
        return (self.coordinator.data or {}).get(self._key)

    @property
    def available(self) -> bool:
        """Return whether SEA is connected and reports this key."""
        return super().available and self._key in (self.coordinator.data or {})


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
            return raw if raw in (self.entity_description.options or []) else None
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


class SeaSwitch(SeaEntity, SwitchEntity):
    """SEA strategy on or off."""

    def __init__(
        self, coordinator: SeaCoordinator, description: SwitchEntityDescription
    ) -> None:
        """Initialize the switch."""
        self.entity_description = description
        super().__init__(coordinator, description.key, "_switch")

    @property
    def is_on(self) -> bool | None:
        """Return whether the strategy is on, whatever its state."""
        raw = self._raw
        return None if raw is None else raw != "off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the strategy on."""
        await self.coordinator.async_command(self._key, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Switch the strategy off; SEA keeps its settings."""
        await self.coordinator.async_command(self._key, False)


class SeaSelect(SeaEntity, SelectEntity):
    """SEA control level."""

    def __init__(
        self, coordinator: SeaCoordinator, description: SelectEntityDescription
    ) -> None:
        """Initialize the select."""
        self.entity_description = description
        super().__init__(coordinator, description.key, "_select")

    @property
    def current_option(self) -> str | None:
        """Return the current level."""
        raw = self._raw
        return raw if raw in self.options else None

    async def async_select_option(self, option: str) -> None:
        """Set the level."""
        await self.coordinator.async_command(self._key, option)
