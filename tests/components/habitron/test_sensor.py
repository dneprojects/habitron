"""Tests for the Habitron sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.habitron.sensor import (
    AIRQUALITY_DESCRIPTION,
    CURRENT_DESCRIPTION,
    HUMIDITY_DESCRIPTION,
    ILLUMINANCE_DESCRIPTION,
    TIMEOUT_DESCRIPTION,
    VOLTAGE_DESCRIPTION,
    WIND_DESCRIPTION,
    HbtnDescribedSensor,
    HbtnSensorEntityDescription,
)
from custom_components.habitron.interfaces import TYPE_DIAG


def _make_module(uid: str = "MOD-1") -> MagicMock:
    """Build a stub module with the dataset attributes the sensor reads."""
    mod = MagicMock()
    mod.uid = uid
    mod.sensors = {}
    mod.chan_currents = {}
    mod.voltages = {}
    mod.chan_timeouts = {}
    mod.diags = {}
    mod.analogins = {}
    mod.logic = {}
    return mod


def _make_sensor_descriptor(name: str = "Humidity", type_: int = 1) -> MagicMock:
    """Build a stub IfDescriptor."""
    desc = MagicMock()
    desc.nmbr = 0
    desc.name = name
    desc.type = type_
    return desc


def _make_value(value: float) -> MagicMock:
    """Build a stub sensor value object."""
    s = MagicMock()
    s.value = value
    return s


def test_humidity_description_attributes() -> None:
    """Humidity description carries device class + unit + value_fn."""
    assert HUMIDITY_DESCRIPTION.device_class is SensorDeviceClass.HUMIDITY
    assert HUMIDITY_DESCRIPTION.native_unit_of_measurement == "%"
    assert HUMIDITY_DESCRIPTION.value_fn is not None
    assert HUMIDITY_DESCRIPTION.diag_check is False


def test_wind_description_carries_translation_key() -> None:
    """Wind description points at the icon-translation key."""
    assert WIND_DESCRIPTION.translation_key == "wind"
    assert WIND_DESCRIPTION.device_class is SensorDeviceClass.WIND_SPEED
    assert WIND_DESCRIPTION.suggested_display_precision == 1


@pytest.mark.parametrize(
    ("description", "expected_dc"),
    [
        (HUMIDITY_DESCRIPTION, SensorDeviceClass.HUMIDITY),
        (ILLUMINANCE_DESCRIPTION, SensorDeviceClass.ILLUMINANCE),
        (WIND_DESCRIPTION, SensorDeviceClass.WIND_SPEED),
        (AIRQUALITY_DESCRIPTION, SensorDeviceClass.AQI),
        (CURRENT_DESCRIPTION, SensorDeviceClass.CURRENT),
        (VOLTAGE_DESCRIPTION, SensorDeviceClass.VOLTAGE),
    ],
)
def test_descriptions_have_expected_device_class(
    description: HbtnSensorEntityDescription,
    expected_dc: SensorDeviceClass | None,
) -> None:
    """Every description targets the right device class."""
    assert description.device_class is expected_dc


def test_diag_check_flagged_descriptions() -> None:
    """Current/Voltage/Timeout opt into the DIAG fallback."""
    assert CURRENT_DESCRIPTION.diag_check is True
    assert VOLTAGE_DESCRIPTION.diag_check is True
    assert TIMEOUT_DESCRIPTION.diag_check is True
    # Wind/Humidity etc. do not.
    assert WIND_DESCRIPTION.diag_check is False


def test_described_sensor_marks_diagnostic_entity_when_flagged() -> None:
    """A sensor whose descriptor type is DIAG is hidden by default."""
    module = _make_module()
    sensor_desc = _make_sensor_descriptor(name="Iload", type_=TYPE_DIAG)
    coord = MagicMock(spec=DataUpdateCoordinator)
    entity = HbtnDescribedSensor(
        module, sensor_desc, coord, 0, CURRENT_DESCRIPTION
    )
    assert entity.entity_description is CURRENT_DESCRIPTION
    assert entity._attr_entity_registry_enabled_default is False


def test_described_sensor_not_diagnostic_for_normal_type() -> None:
    """A non-DIAG type stays user-visible."""
    module = _make_module()
    sensor_desc = _make_sensor_descriptor(type_=1)
    coord = MagicMock(spec=DataUpdateCoordinator)
    entity = HbtnDescribedSensor(
        module, sensor_desc, coord, 0, HUMIDITY_DESCRIPTION
    )
    # ``_attr_entity_registry_enabled_default`` is the SensorEntity
    # default (True / unset) for normal entities.
    assert getattr(entity, "_attr_entity_registry_enabled_default", True) is not False


def test_described_sensor_value_fn_humidity() -> None:
    """value_fn reads from ``module.sensors`` for Humidity."""
    module = _make_module()
    module.sensors[0] = _make_value(42.0)
    sensor_desc = _make_sensor_descriptor()
    coord = MagicMock(spec=DataUpdateCoordinator)
    entity = HbtnDescribedSensor(
        module, sensor_desc, coord, 0, HUMIDITY_DESCRIPTION
    )
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_native_value == 42.0


def test_described_sensor_value_fn_current_from_chan_currents() -> None:
    """value_fn for Current reads from ``module.chan_currents``."""
    module = _make_module()
    module.chan_currents[0] = _make_value(1.25)
    sensor_desc = _make_sensor_descriptor(type_=1)
    coord = MagicMock(spec=DataUpdateCoordinator)
    entity = HbtnDescribedSensor(
        module, sensor_desc, coord, 0, CURRENT_DESCRIPTION
    )
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_native_value == 1.25


def test_described_sensor_value_fn_voltage_from_voltages() -> None:
    """value_fn for Voltage reads from ``module.voltages``."""
    module = _make_module()
    module.voltages[0] = _make_value(231.5)
    sensor_desc = _make_sensor_descriptor(type_=1)
    coord = MagicMock(spec=DataUpdateCoordinator)
    entity = HbtnDescribedSensor(
        module, sensor_desc, coord, 0, VOLTAGE_DESCRIPTION
    )
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_native_value == 231.5


def test_described_sensor_value_fn_timeout_from_chan_timeouts() -> None:
    """value_fn for Timeout reads from ``module.chan_timeouts``."""
    module = _make_module()
    module.chan_timeouts[0] = _make_value(7)
    sensor_desc = _make_sensor_descriptor(type_=1)
    coord = MagicMock(spec=DataUpdateCoordinator)
    entity = HbtnDescribedSensor(
        module, sensor_desc, coord, 0, TIMEOUT_DESCRIPTION
    )
    entity.async_write_ha_state = MagicMock()
    entity._handle_coordinator_update()
    assert entity._attr_native_value == 7


def test_described_sensor_inherits_measurement_state_class() -> None:
    """All described sensors are MEASUREMENT state-class (inherited from base)."""
    module = _make_module()
    sensor_desc = _make_sensor_descriptor()
    coord = MagicMock(spec=DataUpdateCoordinator)
    entity = HbtnDescribedSensor(
        module, sensor_desc, coord, 0, HUMIDITY_DESCRIPTION
    )
    # State class comes from HbtnSensor base.
    assert entity._attr_state_class is SensorStateClass.MEASUREMENT


async def test_sensor_platform_setup(
    hass: HomeAssistant, setup_integration
) -> None:
    """The platform sets up without error against an empty router."""
    # ``setup_integration`` already exercises the entire setup chain.
    # The router fixture starts with no modules so no entities are
    # added — but the setup must still complete without exception.
    assert setup_integration.runtime_data is not None
