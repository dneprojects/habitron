"""Platform for sensor integration."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfSpeed,
    UnitOfTemperature,
)
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
async def async_setup_entry(  # noqa: C901
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord
    smhub = hass.data[DOMAIN][entry.entry_id]

    new_devices = []
    for smhub_sensor in smhub.sensors:
        if smhub_sensor.name == "Memory free":
            new_devices.append(
                PercSensor(smhub, smhub_sensor, hbtn_cord, len(new_devices))
            )
        if smhub_sensor.name == "Disk free":
            new_devices.append(
                PercSensor(smhub, smhub_sensor, hbtn_cord, len(new_devices))
            )
    for smhub_diag in smhub.diags:
        if smhub_diag.name == "CPU Frequency":
            new_devices.append(
                FrequencySensor(smhub, smhub_diag, hbtn_cord, len(new_devices))
            )
        if smhub_diag.name == "CPU load":
            new_devices.append(
                PercSensor(smhub, smhub_diag, hbtn_cord, len(new_devices))
            )

        if smhub_diag.name == "CPU Temperature":
            new_devices.append(
                TemperatureDSensor(smhub, smhub_diag, hbtn_cord, len(new_devices))
            )
    for hbt_module in hbtn_rt.modules:
        if hbt_module.typ in [b"\x01\x03", b"\x0b\x1f"]:
            for ain in hbt_module.analogins:
                if ain.type == 3:
                    new_devices.append(
                        AnalogSensor(hbt_module, ain, hbtn_cord, len(new_devices))
                    )
        for mod_sensor in hbt_module.sensors:
            if mod_sensor.name[0:11] == "Temperature":
                new_devices.append(
                    TemperatureSensor(
                        hbt_module, mod_sensor, hbtn_cord, len(new_devices)
                    )
                )
            elif mod_sensor.name == "Humidity":
                new_devices.append(
                    HumiditySensor(hbt_module, mod_sensor, hbtn_cord, len(new_devices))
                )
            elif mod_sensor.name == "Illuminance":
                new_devices.append(
                    IlluminanceSensor(
                        hbt_module, mod_sensor, hbtn_cord, len(new_devices)
                    )
                )
            elif mod_sensor.name in ("Wind", "Windpeak"):
                new_devices.append(
                    WindSensor(hbt_module, mod_sensor, hbtn_cord, len(new_devices))
                )
            elif mod_sensor.name == "Airquality":
                new_devices.append(
                    AirqualitySensor(
                        hbt_module, mod_sensor, hbtn_cord, len(new_devices)
                    )
                )
            elif mod_sensor.name == "Identifier":
                new_devices.append(
                    EKeySensorId(hbt_module, mod_sensor, hbtn_cord, len(new_devices))
                )
            elif mod_sensor.name == "Finger":
                new_devices.append(
                    EKeySensorFngr(hbt_module, mod_sensor, hbtn_cord, len(new_devices))
                )
        for mod_logic in hbt_module.logic:
            if mod_logic.type > 0:
                if hbt_module.comm.is_smhub:
                    new_devices.append(
                        LogicSensorPush(
                            hbt_module, mod_logic, hbtn_cord, len(new_devices)
                        )
                    )
                else:
                    new_devices.append(
                        LogicSensor(hbt_module, mod_logic, hbtn_cord, len(new_devices))
                    )
        for mod_diag in hbt_module.diags:
            if mod_diag.name == "Status":
                new_devices.append(
                    StatusSensor(hbt_module, mod_diag, hbtn_cord, len(new_devices))
                )
            elif mod_diag.name == "PowerTemp":
                new_devices.append(
                    TemperatureDSensor(
                        hbt_module, mod_diag, hbtn_cord, len(new_devices)
                    )
                )
    for time_out in hbtn_rt.chan_timeouts:
        new_devices.append(
            TimeOutSensor(hbtn_rt, time_out, hbtn_cord, len(new_devices))
        )
    for ch_curr in hbtn_rt.chan_currents:
        new_devices.append(CurrSensor(hbtn_rt, ch_curr, hbtn_cord, len(new_devices)))
    for rt_vtg in hbtn_rt.voltages:
        new_devices.append(VoltSensor(hbtn_rt, rt_vtg, hbtn_cord, len(new_devices)))

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)


class HbtnSensor(CoordinatorEntity, SensorEntity):
    """Base representation of a Habitron sensor."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_should_poll = True  # for push updates

    def __init__(self, module, sensor, coord, idx) -> None:
        """Initialize a Habitron sensor, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._module = module
        self._sensor_idx = sensor.nmbr
        self._attr_state: float | int
        self._value = 0
        self._attr_unique_id = f"Mod_{self._module.uid}_snsr{self._sensor_idx}"
        self._attr_name = sensor.name

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str | None:
        """Return the display name of this sensor."""
        return self._attr_name

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.sensors[self._sensor_idx].value
        self.async_write_ha_state()


class AnalogSensor(HbtnSensor):
    """Representation of a Sensor."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_should_poll = True  # for push updates

    def __init__(self, module, sensor, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, sensor, coord, idx)
        self._attr_icon = "mdi:chart-bell-curve-cumulative"
        self._attr_unique_id = f"Mod_{self._module.uid}_adin{self._sensor_idx}"
        self._attr_name = self._attr_name
        self.sensor = sensor

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        if self._module.comm.is_smhub:
            self.sensor.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        if self._module.comm.is_smhub:
            self.sensor.remove_callback(self._handle_coordinator_update)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.analogins[self._sensor_idx].value
        self.async_write_ha_state()


class TemperatureSensor(HbtnSensor):
    """Representation of a Sensor."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, module, sensor, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, sensor, coord, idx)
        if sensor.name == "Temperature ext.":
            self._attr_entity_registry_enabled_default = (
                False  # Entity will initally be disabled
            )


class HumiditySensor(HbtnSensor):
    """Representation of a Sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE


class IlluminanceSensor(HbtnSensor):
    """Representation of an illuminance sensor."""

    _attr_device_class = SensorDeviceClass.ILLUMINANCE
    _attr_native_unit_of_measurement = LIGHT_LUX


class EKeySensorId(HbtnSensor):
    """Representation of an ekey identifier sensor."""

    _attr_should_poll = True  # for push updates

    def __init__(self, module, sensor, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, sensor, coord, idx)
        self.sensor = sensor
        self._attr_unique_id = f"Mod_{self._module.uid}_ekey_ident"
        self._attr_name = "Identifier Value"
        self._attr_icon = "mdi:fingerprint"

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        if self._module.comm.is_smhub:
            self.sensor.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        if self._module.comm.is_smhub:
            self.sensor.remove_callback(self._handle_coordinator_update)


class EKeySensorFngr(HbtnSensor):
    """Representation of an ekey finger sensor."""

    _attr_should_poll = True  # for push updates

    def __init__(self, module, sensor, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, sensor, coord, idx)
        self.sensor = sensor
        self._attr_unique_id = f"Mod_{self._module.uid}_ekey_fngr"
        self._attr_name = "Finger Value"
        self._attr_icon = "mdi:fingerprint"

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        if self._module.comm.is_smhub:
            self.sensor.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        if self._module.comm.is_smhub:
            self.sensor.remove_callback(self._handle_coordinator_update)


class WindSensor(HbtnSensor):
    """Representation of a wind sensor."""

    _attr_device_class = SensorDeviceClass.WIND_SPEED
    _attr_native_unit_of_measurement = UnitOfSpeed.METERS_PER_SECOND
    _attr_suggested_display_precision = 1

    def __init__(self, module, sensor, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, sensor, coord, idx)
        self._attr_icon = "mdi:weather-windy-variant"


class AirqualitySensor(HbtnSensor):
    """Representation of a airquality sensor."""

    _attr_device_class = SensorDeviceClass.AQI


class HbtnDiagSensor(CoordinatorEntity, SensorEntity):
    """Base representation of a Habitron sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, module, diag, coord, idx) -> None:
        """Initialize a Habitron sensor, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._module = module
        self._diag_idx = diag.nmbr
        self._attr_state: float | int
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

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, module, diag, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, diag, coord, idx)
        self._attr_unique_id = f"Mod_{self._module.uid}_{diag.name}"
        self._attr_name = diag.name


class StatusSensor(HbtnDiagSensor):
    """Representation of a Sensor."""

    def __init__(self, module, diag, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, diag, coord, idx)
        self._attr_unique_id = f"Mod_{self._module.uid}_module_status"
        self._attr_name = diag.name

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
    _attr_should_poll = True  # for push updates

    def __init__(self, module, logic, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, logic, coord, idx)
        self.idx = logic.idx
        self.logic = logic
        self._attr_unique_id = f"Mod_{self._module.uid}_logic{logic.nmbr}"
        self._attr_name = f"Cnt{logic.nmbr + 1}: {logic.name}"
        self._attr_icon = "mdi:counter"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.logic[self.idx].value
        self.async_write_ha_state()


class LogicSensorPush(LogicSensor):
    """Representation of a logic state sensor for push update."""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self.logic.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self.logic.remove_callback(self._handle_coordinator_update)


class CurrSensor(HbtnSensor):
    """Representation of a current sensor."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.AMPERE

    def __init__(self, module, sensor, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, sensor, coord, idx)
        if abs(sensor.type) == TYPE_DIAG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = (
                False  # Entity will initally be disabled
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.chan_currents[self._sensor_idx].value
        self.async_write_ha_state()


class VoltSensor(HbtnSensor):
    """Representation of a voltage sensor."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT

    def __init__(self, module, sensor, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, sensor, coord, idx)
        if abs(sensor.type) == TYPE_DIAG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = (
                False  # Entity will initally be disabled
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.voltages[self._sensor_idx].value
        self.async_write_ha_state()


class TimeOutSensor(HbtnSensor):
    """Representation of a timeout count sensor."""

    _attr_native_unit_of_measurement = ""

    def __init__(self, module, timeout, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, timeout, coord, idx)
        self._attr_icon = "mdi:timer-alert-outline"
        if abs(timeout.type) == TYPE_DIAG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = (
                False  # Entity will initally be disabled
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self._module.chan_timeouts[self._sensor_idx].value
        self.async_write_ha_state()


class PercSensor(HbtnSensor):
    """Representation of a percentage sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, module, perctg, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, perctg, coord, idx)
        self.type = perctg.type
        self._attr_unique_id = f"Mod_{self._module.uid}_perc{perctg.nmbr}"
        if self._attr_name[:6].lower() == "memory":  # type: ignore  # noqa: PGH003
            self._attr_icon = "mdi:memory"
        elif self._attr_name[:4].lower() == "disk":  # type: ignore  # noqa: PGH003
            self._attr_icon = "mdi:harddisk"
        elif self._attr_name.lower() == "cpu load":  # type: ignore  # noqa: PGH003
            self._attr_icon = "mdi:timer-alert-outline"
        else:
            self._attr_icon = "mdi:percent-circle-outline"
        if abs(perctg.type) == TYPE_DIAG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_unique_id = f"Mod_{self._module.uid}_dperc{perctg.nmbr}"
            self._attr_entity_registry_enabled_default = (
                False  # Entity will initally be disabled
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if abs(self.type) == TYPE_DIAG:
            self._attr_native_value = self._module.diags[self._sensor_idx].value
        else:
            self._attr_native_value = self._module.sensors[self._sensor_idx].value
        self.async_write_ha_state()


class FrequencySensor(HbtnSensor):
    """Representation of a frequency sensor."""

    _attr_device_class = SensorDeviceClass.FREQUENCY
    _attr_native_unit_of_measurement = UnitOfFrequency.HERTZ

    def __init__(self, module, freq, coord, idx) -> None:
        """Initialize the sensor."""
        super().__init__(module, freq, coord, idx)
        self.type = freq.type
        if self._attr_name.lower() == "cpu frequency":  # type: ignore  # noqa: PGH003
            self._attr_icon = "mdi:clock-fast"
        else:
            self._attr_icon = "mdi:sine-wave"
        if abs(self.type) == TYPE_DIAG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            self._attr_entity_registry_enabled_default = (
                False  # Entity will initally be disabled
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if abs(self.type) == TYPE_DIAG:
            self._attr_native_value = self._module.diags[self._sensor_idx].value
        else:
            self._attr_native_value = self._module.sensors[self._sensor_idx].value
        self.async_write_ha_state()
