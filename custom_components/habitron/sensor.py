"""Platform for sensor integration."""


from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


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
            if mod_sensor.name == "Temperature":
                new_devices.append(
                    TemperatureSensor(
                        hbt_module, mod_sensor.nmbr, hbtn_cord, len(new_devices)
                    )
                )
            elif mod_sensor.name == "Humidity":
                new_devices.append(
                    HumiditySensor(
                        hbt_module, mod_sensor.nmbr, hbtn_cord, len(new_devices)
                    )
                )
            elif mod_sensor.name == "Illuminance":
                new_devices.append(
                    IlluminanceSensor(
                        hbt_module, mod_sensor.nmbr, hbtn_cord, len(new_devices)
                    )
                )
            elif mod_sensor.name == "Wind":
                new_devices.append(
                    WindSensor(hbt_module, mod_sensor.nmbr, hbtn_cord, len(new_devices))
                )
            elif mod_sensor.name == "Rain":
                new_devices.append(
                    RainSensor(hbt_module, mod_sensor.nmbr, hbtn_cord, len(new_devices))
                )
            elif mod_sensor.name == "Windpeak":
                new_devices.append(
                    WindpeakSensor(
                        hbt_module, mod_sensor.nmbr, hbtn_cord, len(new_devices)
                    )
                )
            elif mod_sensor.name == "Airquality":
                new_devices.append(
                    AirqualitySensor(
                        hbt_module, mod_sensor.nmbr, hbtn_cord, len(new_devices)
                    )
                )
        for mod_logic in hbt_module.logic:
            new_devices.append(
                LogicSensor(hbt_module, mod_logic, hbtn_cord, len(new_devices))
            )
        for mod_diag in hbt_module.diags:
            if mod_diag.name == "Status":
                new_devices.append(
                    StatusSensor(hbt_module, mod_diag.nmbr, hbtn_cord, len(new_devices))
                )
            elif mod_diag.name == "PowerTemp":
                new_devices.append(
                    TemperatureDSensor(
                        hbt_module, mod_diag.nmbr, hbtn_cord, len(new_devices)
                    )
                )

    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)


# This base class shows the common properties and methods for a sensor as used in this
# example. See each sensor for further details about properties and methods that
# have been overridden.
class HbtnSensor(CoordinatorEntity, SensorEntity):
    """Base representation of a Habitron sensor."""

    state_class = "measurement"

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize a Habitron sensor, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._module = module
        self._sensor_idx = nmbr
        self._attr_state = 0
        self._value = 0

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.sensors[self._sensor_idx].value
        self.async_write_ha_state()


class TemperatureSensor(HbtnSensor):
    """Representation of a Sensor."""

    device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = "°C"
    _attr_unit_of_measurement = "°C"

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_temperature"
        self._attr_name = f"{self._module.name}: Temperature"


class HumiditySensor(HbtnSensor):
    """Representation of a Sensor."""

    device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = "%"
    _attr_unit_of_measurement = "%"

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_humidity"
        self._attr_name = f"{self._module.name}: Humidity"


class IlluminanceSensor(HbtnSensor):
    """Representation of an illuminance sensor."""

    device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = "lx"
    _attr_unit_of_measurement = "lx"

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_illuminance"
        self._attr_name = f"{self._module.name}: Illuminance"


class WindSensor(HbtnSensor):
    """Representation of a wind sensor."""

    # device_class = SensorDeviceClass.WIND_SPEED
    _attr_native_unit_of_measurement = "m/s"
    _attr_unit_of_measurement = "m/s"

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_wind"
        self._attr_name = f"{self._module.name}: Wind"


class RainSensor(HbtnSensor):
    """Representation of a rain sensor."""

    # device_class = DEVICE_CLASS_BOOL
    _attr_native_unit_of_measurement = ""
    _attr_unit_of_measurement = ""

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_rain"
        self._attr_name = f"{self._module.name}: Rain"


class WindpeakSensor(HbtnSensor):
    """Representation of a wind sensor."""

    # device_class = SensorDeviceClass.WIND_SPEED
    _attr_native_unit_of_measurement = "m/s"
    _attr_unit_of_measurement = "m/s"

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_windpeak"
        self._attr_name = f"{self._module.name}: Wind Peak"


class AirqualitySensor(HbtnSensor):
    """Representation of a airquality sensor."""

    device_class = SensorDeviceClass.AQI

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_airquality"
        self._attr_name = f"{self._module.name}: Airquality"


class HbtnDiagSensor(CoordinatorEntity, SensorEntity):
    """Base representation of a Habitron sensor."""

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize a Habitron sensor, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._module = module
        self._diag_idx = nmbr
        self._attr_state = 0
        self._value = 0
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_entity_registry_enabled_default = (
            False  # Entity will initally be disabled
        )

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo | None:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.diags[self._diag_idx].value
        self.async_write_ha_state()


class TemperatureDSensor(HbtnDiagSensor):
    """Representation of a Sensor."""

    device_class = SensorDeviceClass.TEMPERATURE
    state_class = "measurement"

    _attr_native_unit_of_measurement = "°C"
    _attr_unit_of_measurement = "°C"

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_powtemperature"
        self._attr_name = f"{self._module.name}: Power Unit Temperature"


class StatusSensor(HbtnDiagSensor):
    """Representation of a Sensor."""

    def __init__(self, module, nmbr, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_module_status"
        self._attr_name = f"{self._module.name}: Module Status"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.diags[self._diag_idx].value
        self.async_write_ha_state()
        if self._attr_native_value:
            self._attr_icon = "mdi:lan-disconnect"
        else:
            self._attr_icon = "mdi:lan-check"


class LogicSensor(HbtnSensor):
    """Representation of a logic state sensor."""

    _attr_native_unit_of_measurement = ""
    _attr_unit_of_measurement = ""

    def __init__(self, module, logic, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, logic.nmbr, coord, idx)
        self.nmbr = logic.nmbr
        self._attr_unique_id = f"{self._module.id}_logic_{logic.nmbr}"
        self._attr_name = f"{self._module.name} Cnt{logic.nmbr + 1}: {logic.name}"
        self._attr_icon = "mdi:counter"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.logic[self.nmbr].value
        self.async_write_ha_state()
