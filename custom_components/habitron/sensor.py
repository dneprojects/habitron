"""Platform for sensor integration."""
# This file shows the setup for the sensors associated with a module.
# They are setup in the same way with the call to the async_setup_entry function
# via HA from the module __init__. Each sensor has a device_class, this tells HA how
# to display it in the UI (for know types). The unit_of_measurement property tells HA
# what the unit is, so it can display the correct range. For predefined types (such as
# battery), the unit_of_measurement should match what's expected.


from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    def device_info(self):
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.mod_id)}}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.sensors[self._sensor_idx].value
        self.async_write_ha_state()


class TemperatureSensor(HbtnSensor):
    """Representation of a Sensor."""

    device_class = SensorDeviceClass.TEMPERATURE
    _attr_unit_of_measurement = "°C"

    def __init__(self, module, nmbr, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_temperature"
        self._attr_name = f"{self._module.name} Temperature"


class HumiditySensor(HbtnSensor):
    """Representation of a Sensor."""

    device_class = SensorDeviceClass.HUMIDITY
    _attr_unit_of_measurement = "%"

    def __init__(self, module, nmbr, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_humidity"
        self._attr_name = f"{self._module.name} Humidity"


class IlluminanceSensor(HbtnSensor):
    """Representation of an illuminance sensor."""

    device_class = SensorDeviceClass.ILLUMINANCE
    _attr_unit_of_measurement = "lx"

    def __init__(self, module, nmbr, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_illuminance"
        self._attr_name = f"{self._module.name} Illuminance"


class WindSensor(HbtnSensor):
    """Representation of a wind sensor."""

    # device_class = SensorDeviceClass.WIND_SPEED
    _attr_unit_of_measurement = "m/s"

    def __init__(self, module, nmbr, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_wind"
        self._attr_name = f"{self._module.name} Wind"


class RainSensor(HbtnSensor):
    """Representation of a rain sensor."""

    # device_class = DEVICE_CLASS_BOOL
    _attr_unit_of_measurement = ""

    def __init__(self, module, nmbr, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_rain"
        self._attr_name = f"{self._module.name} Rain"


class WindpeakSensor(HbtnSensor):
    """Representation of a wind sensor."""

    # device_class = SensorDeviceClass.WIND_SPEED
    _attr_unit_of_measurement = "m/s"

    def __init__(self, module, nmbr, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_windpeak"
        self._attr_name = f"{self._module.name} Wind Peak"


class MovementSensor(HbtnSensor):
    """Representation of a movement sensor."""

    # device_class = SensorDeviceClass.WIND_SPEED
    _attr_unit_of_measurement = ""

    def __init__(self, module, nmbr, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_movement"
        self._attr_name = f"{self._module.name} Movement"


class AirqualitySensor(HbtnSensor):
    """Representation of a airquality sensor."""

    device_class = SensorDeviceClass.AQI
    _attr_unit_of_measurement = ""

    def __init__(self, module, nmbr, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, nmbr, coord, idx)
        self._attr_unique_id = f"{self._module.id}_airquality"
        self._attr_name = f"{self._module.name} Airquality"


class LogicSensor(HbtnSensor):
    """Representation of a airquality sensor."""

    # device_class = SensorDeviceClass.AQI
    _attr_unit_of_measurement = ""

    def __init__(self, module, logic, coord, idx):
        """Initialize the sensor."""
        super().__init__(module, logic.nmbr, coord, idx)
        self.nmbr = logic.nmbr
        self._attr_unique_id = f"{self._module.id}_logic_{logic.nmbr}"
        self._attr_name = f"{self._module.name} Cnt{logic.nmbr + 1} {logic.name}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.logic[self.nmbr].value
        self.async_write_ha_state()
