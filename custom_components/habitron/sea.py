"""Smart Energy Agent (SEA) device, fed by the ``sea_update`` service."""

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, Final

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SEA_ID: Final = "sea"
SEA_TIMEOUT: Final = timedelta(minutes=30)
PLATFORM_SENSOR: Final = "sensor"
PLATFORM_BINARY_SENSOR: Final = "binary_sensor"
DATA_SEA: HassKey[SeaManager] = HassKey(f"{DOMAIN}_sea")
_STORE_KEY: Final = f"{DOMAIN}.sea"
_STORE_VERSION: Final = 1
_SIGNAL: Final = f"{DOMAIN}_sea_update"
_URL_SCHEMES: Final = ("http://", "https://", "homeassistant://")


@dataclass
class SeaMeta:
    """Static description of one SEA entity."""

    key: str
    platform: str
    name: str | None
    unit: str | None
    device_class: str | None
    icon: str | None

    @classmethod
    def from_payload(cls, item: dict[str, Any]) -> SeaMeta:
        """Build the description from one entity of a ``sea_update`` call."""
        return cls(
            key=item["key"],
            platform=item["platform"],
            name=item.get("name"),
            unit=item.get("unit"),
            device_class=item.get("device_class"),
            icon=item.get("icon"),
        )


class SeaManager:
    """Hold SEA's entities, their states and the device they belong to."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the manager."""
        self.hass = hass
        self.metas: dict[str, SeaMeta] = {}
        self.version: str | None = None
        self.url: str | None = None
        self._store: Store[dict[str, Any]] = Store(hass, _STORE_VERSION, _STORE_KEY)
        self._states: dict[str, str | None] = {}
        self._attributes: dict[str, dict[str, Any]] = {}
        self._present: set[str] = set()
        self._alive = False
        self._adders: dict[str, dict[str, AddConfigEntryEntitiesCallback]] = {}
        self._owner: str | None = None
        self._created: set[str] = set()
        self._cancel_timeout: CALLBACK_TYPE | None = None

    async def async_load(self) -> None:
        """Restore the last full entity list from storage."""
        if (data := await self._store.async_load()) is None:
            return
        self.metas = {item["key"]: SeaMeta(**item) for item in data.get("entities", [])}
        self.version = data.get("version")
        self.url = data.get("url")

    @callback
    def async_shutdown(self) -> None:
        """Stop the timeout."""
        if self._cancel_timeout is not None:
            self._cancel_timeout()
            self._cancel_timeout = None

    def is_available(self, key: str) -> bool:
        """Return whether the entity has a current value."""
        return self._alive and key in self._present

    def state(self, key: str) -> str | None:
        """Return the raw state of an entity."""
        return self._states.get(key)

    def attributes(self, key: str) -> dict[str, Any]:
        """Return the extra attributes of an entity."""
        return self._attributes.get(key, {})

    @property
    def configuration_url(self) -> str | None:
        """Return the url if the device registry accepts it."""
        if self.url and self.url.startswith(_URL_SCHEMES):
            return self.url
        return None

    @callback
    def async_register(
        self,
        entry_id: str,
        platform: str,
        add_entities: AddConfigEntryEntitiesCallback,
    ) -> CALLBACK_TYPE:
        """Register a platform of a config entry; return the unregister callback."""
        self._adders.setdefault(entry_id, {})[platform] = add_entities
        if self._owner is None:
            self._owner = entry_id
        if self._owner == entry_id:
            self._create(
                meta for meta in self.metas.values() if meta.platform == platform
            )

        @callback
        def _unregister() -> None:
            adders = self._adders.get(entry_id, {})
            adders.pop(platform, None)
            if adders:
                return
            self._adders.pop(entry_id, None)
            if self._owner != entry_id:
                return
            # Move the device to the next loaded entry, so SEA keeps working.
            self._created.clear()
            self._owner = next(iter(self._adders), None)
            self._create(self.metas.values())

        return _unregister

    @callback
    def _create(self, metas: Any) -> None:
        """Create entities for metas the owner entry does not have yet."""
        if self._owner is None:
            return
        adders = self._adders[self._owner]
        registry = er.async_get(self.hass)
        new: dict[str, list[Entity]] = {}
        for meta in metas:
            if meta.key in self._created or meta.platform not in adders:
                continue
            entity: Entity = (
                SeaSensor(self, meta)
                if meta.platform == PLATFORM_SENSOR
                else SeaBinarySensor(self, meta)
            )
            # Drop a state the old REST way left, or the entity id gets a suffix.
            if self.hass.states.get(entity.entity_id) and not registry.async_get(
                entity.entity_id
            ):
                self.hass.states.async_remove(entity.entity_id)
            self._created.add(meta.key)
            new.setdefault(meta.platform, []).append(entity)
        for platform, entities in new.items():
            adders[platform](entities)

    async def async_update(self, data: dict[str, Any]) -> None:
        """Apply a ``sea_update`` call."""
        full: bool = data["full"]
        changed: set[str] = set()
        new_metas: list[SeaMeta] = []
        for item in data["entities"]:
            meta = SeaMeta.from_payload(item)
            known = self.metas.get(meta.key)
            if known is not None and known.platform != meta.platform:
                _LOGGER.warning(
                    "SEA entity %s cannot change its platform to %s",
                    meta.key,
                    meta.platform,
                )
                continue
            if known is None:
                new_metas.append(meta)
            self.metas[meta.key] = meta
            state = item.get("state")
            self._states[meta.key] = None if state is None else str(state)
            self._attributes[meta.key] = item.get("attributes") or {}
            self._present.add(meta.key)
            changed.add(meta.key)
        if full:
            missing = self._present - changed
            self._present -= missing
            changed |= missing
        if not self._alive:
            self._alive = True
            changed |= set(self.metas)
        self._update_device(data.get("version"), data.get("url"))
        self._create(new_metas)
        self._restart_timeout()
        for key in changed:
            async_dispatcher_send(self.hass, f"{_SIGNAL}_{key}")
        if full:
            await self._store.async_save(
                {
                    "version": self.version,
                    "url": self.url,
                    "entities": [
                        asdict(meta)
                        for key, meta in self.metas.items()
                        if key in self._present
                    ],
                }
            )

    @callback
    def _update_device(self, version: str | None, url: str | None) -> None:
        """Update version and link of the device."""
        if version is not None:
            self.version = version
        if url is not None:
            self.url = url
        registry = dr.async_get(self.hass)
        if (device := registry.async_get_device({(DOMAIN, SEA_ID)})) is None:
            return
        if (
            device.sw_version != self.version
            or device.configuration_url != self.configuration_url
        ):
            registry.async_update_device(
                device.id,
                sw_version=self.version,
                configuration_url=self.configuration_url,
            )

    @callback
    def _restart_timeout(self) -> None:
        """Mark all entities unavailable when SEA stays silent."""
        self.async_shutdown()
        self._cancel_timeout = async_call_later(self.hass, SEA_TIMEOUT, self._expire)

    @callback
    def _expire(self, _now: datetime) -> None:
        """Handle the timeout."""
        self._cancel_timeout = None
        self._alive = False
        for key in self.metas:
            async_dispatcher_send(self.hass, f"{_SIGNAL}_{key}")


async def async_setup_sea(hass: HomeAssistant) -> None:
    """Create the SEA manager once per Home Assistant instance."""
    if DATA_SEA in hass.data:
        return
    manager = SeaManager(hass)
    await manager.async_load()
    hass.data[DATA_SEA] = manager


@callback
def async_unload_sea(hass: HomeAssistant) -> None:
    """Drop the SEA manager when the last config entry is gone."""
    if (manager := hass.data.pop(DATA_SEA, None)) is not None:
        manager.async_shutdown()


@callback
def async_setup_sea_platform(
    hass: HomeAssistant,
    entry_id: str,
    platform: str,
    add_entities: AddConfigEntryEntitiesCallback,
) -> Callable[[], None]:
    """Let SEA add entities through a platform of this entry."""
    if (manager := hass.data.get(DATA_SEA)) is None:
        return lambda: None
    return manager.async_register(entry_id, platform, add_entities)


class SeaEntity(Entity):
    """Base class of the SEA entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: SeaManager, meta: SeaMeta) -> None:
        """Initialize the entity."""
        self._manager = manager
        self._key = meta.key
        self._attr_unique_id = f"{SEA_ID}_{meta.key}"
        # Keeps the ids of the former REST states.
        self.entity_id = f"{meta.platform}.{SEA_ID}_{meta.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, SEA_ID)},
            name="Smart Energy Agent",
            manufacturer="Habitron",
            model="SEA",
            sw_version=manager.version,
            configuration_url=manager.configuration_url,
        )

    @property
    def _meta(self) -> SeaMeta:
        return self._manager.metas[self._key]

    @property
    def name(self) -> str | None:
        """Return the name from SEA."""
        return self._meta.name or self._key

    @property
    def icon(self) -> str | None:
        """Return the icon from SEA."""
        return self._meta.icon

    @property
    def available(self) -> bool:
        """Return whether SEA reported this entity recently."""
        return self._manager.is_available(self._key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the attributes from SEA."""
        return self._manager.attributes(self._key)

    async def async_added_to_hass(self) -> None:
        """Follow the updates of this entity."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{_SIGNAL}_{self._key}", self.async_write_ha_state
            )
        )


class SeaSensor(SeaEntity, SensorEntity):
    """SEA value as a sensor."""

    @property
    def device_class(self) -> SensorDeviceClass | None:
        """Return the device class from SEA."""
        try:
            return SensorDeviceClass(self._meta.device_class or "")
        except ValueError:
            return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit from SEA."""
        return self._meta.unit

    @property
    def native_value(self) -> str | float | datetime | None:
        """Return the state, as a number or time where SEA declares one."""
        if (raw := self._manager.state(self._key)) is None:
            return None
        if self.device_class is SensorDeviceClass.TIMESTAMP:
            value = dt_util.parse_datetime(raw)
            return value if value is not None and value.tzinfo is not None else None
        if self._meta.unit:
            try:
                return float(raw)
            except ValueError:
                return None
        return raw


class SeaBinarySensor(SeaEntity, BinarySensorEntity):
    """SEA flag as a binary sensor."""

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        """Return the device class from SEA."""
        try:
            return BinarySensorDeviceClass(self._meta.device_class or "")
        except ValueError:
            return None

    @property
    def is_on(self) -> bool | None:
        """Return the state from SEA."""
        return {"on": True, "off": False}.get(self._manager.state(self._key) or "")
