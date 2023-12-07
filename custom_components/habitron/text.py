"""Platform for sensor integration."""


from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .interfaces import TYPE_DIAG


# See cover.py for more details.
# Note how both entities for each module sensor (battry and illuminance) are added at
# the same time to the same list. This way only a single async_add_devices call is
# required.
async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_sensor in hbt_module.sensors:
            if mod_sensor.name == "Identifier":
                new_devices.append(
                    EKeySensor(hbt_module, mod_sensor.nmbr, hbtn_cord, len(new_devices))
                )
    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)


class HbtnText(CoordinatorEntity, SensorEntity):
    """Base representation of a Habitron sensor."""

    _attr_has_entity_name = True
    should_poll = True  # for push updates

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize a Habitron text entity, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._module = module
        self._sensor_idx = nmbr
        self._attr_native_value = ""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._module.sensors[self._sensor_idx].register_callback(
            self._handle_coordinator_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._module.sensors[self._sensor_idx].remove_callback(
            self._handle_coordinator_update
        )

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this sensor."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        id_val = self._module.sensors[self._sensor_idx].value
        if id_val == 0:
            self._attr_native_value = "None"
        elif id_val == 255:
            self._attr_native_value = "Error"
        elif (id_val - 1) in range(len(self._module.ids)):
            self._attr_native_value = self._module.ids[id_val - 1].name
        else:
            self._attr_native_value = "Unknown"
        self.async_write_ha_state()


class EKeySensor(HbtnText):
    """Representation of an ekey identifier sensor."""

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.uid}_ekey_ident"
        self._attr_name = "Identifier Name"
        self._attr_icon = "mdi:fingerprint"
