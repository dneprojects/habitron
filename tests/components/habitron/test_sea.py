"""Tests for the Smart Energy Agent (SEA) device."""

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.sea import DATA_SEA, SEA_TIMEOUT
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import MOCK_CONFIG_DATA, MOCK_CONFIG_OPTIONS, MOCK_NAME

PV = "sensor.sea_pv_prognose_heute"
CHEAP = "binary_sensor.sea_guenstig"
WINDOW = "sensor.sea_naechstes_guenstiges_fenster"

PAYLOAD: dict[str, Any] = {
    "version": "0.15.0-beta.97",
    "url": "homeassistant://hassio/ingress/sea",
    "full": True,
    "entities": [
        {
            "key": "pv_prognose_heute",
            "platform": "sensor",
            "name": "PV-Prognose heute",
            "state": "12.4",
            "unit": "kWh",
            "device_class": None,
            "icon": "mdi:solar-power",
            "attributes": {"rest_kwh": 5.1},
        },
        {
            "key": "guenstig",
            "platform": "binary_sensor",
            "name": "günstig jetzt",
            "state": "on",
            "unit": None,
            "device_class": None,
            "icon": "mdi:cash-check",
            "attributes": {"grund": "Preis 18,2 ct"},
        },
        {
            "key": "naechstes_guenstiges_fenster",
            "platform": "sensor",
            "name": "nächstes günstiges Fenster",
            "state": "2026-11-15T01:00:00+00:00",
            "unit": None,
            "device_class": "timestamp",
            "icon": "mdi:clock-start",
            "attributes": {"ende": "2026-11-15T05:00:00+00:00"},
        },
    ],
}


async def _sea_update(hass: HomeAssistant, payload: dict[str, Any]) -> None:
    await hass.services.async_call(DOMAIN, "sea_update", payload, blocking=True)
    await hass.async_block_till_done()


def _entity(key: str, state: Any, **extra: Any) -> dict[str, Any]:
    return {"key": key, "platform": "sensor", "name": key, "state": state, **extra}


async def _second_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=f"{MOCK_NAME} 2",
        unique_id="112233445566",
        data=MOCK_CONFIG_DATA,
        options=MOCK_CONFIG_OPTIONS,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.mark.usefixtures("setup_integration")
async def test_service_registered(hass: HomeAssistant) -> None:
    """The service exists once a hub is loaded."""
    assert hass.services.has_service(DOMAIN, "sea_update")


@pytest.mark.usefixtures("setup_integration")
async def test_first_call_creates_device_and_entities(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """The first call creates the device and its entities."""
    await _sea_update(hass, PAYLOAD)

    device = device_registry.async_get_device({(DOMAIN, "sea")})
    assert device is not None
    assert device.name == "Smart Energy Agent"
    assert device.manufacturer == "Habitron"
    assert device.model == "SEA"
    assert device.sw_version == "0.15.0-beta.97"
    assert device.configuration_url == "homeassistant://hassio/ingress/sea"

    pv = hass.states.get(PV)
    assert pv is not None
    assert pv.state == "12.4"
    assert pv.attributes["unit_of_measurement"] == "kWh"
    assert pv.attributes["rest_kwh"] == 5.1
    assert pv.attributes["icon"] == "mdi:solar-power"
    assert pv.attributes["friendly_name"] == "Smart Energy Agent PV-Prognose heute"
    entry = entity_registry.async_get(PV)
    assert entry is not None
    assert entry.unique_id == "sea_pv_prognose_heute"
    assert entry.device_id == device.id

    cheap = hass.states.get(CHEAP)
    assert cheap is not None
    assert cheap.state == STATE_ON
    assert cheap.attributes["grund"] == "Preis 18,2 ct"

    window = hass.states.get(WINDOW)
    assert window is not None
    assert window.state == "2026-11-15T01:00:00+00:00"
    assert window.attributes["device_class"] == "timestamp"


@pytest.mark.parametrize(
    ("entity", "expected"),
    [
        pytest.param(_entity("zahl", "7", unit="ct/kWh"), "7.0", id="number"),
        pytest.param(_entity("text", "Akku laden"), "Akku laden", id="text"),
        pytest.param(_entity("leer", None), STATE_UNKNOWN, id="null"),
        pytest.param(
            _entity("kaputt", "n/a", unit="kWh"), STATE_UNKNOWN, id="bad-number"
        ),
        pytest.param(
            _entity("zeit", "morgen", device_class="timestamp"),
            STATE_UNKNOWN,
            id="bad-timestamp",
        ),
        pytest.param(
            _entity("naiv", "2026-11-15T01:00:00", device_class="timestamp"),
            STATE_UNKNOWN,
            id="timestamp-without-zone",
        ),
        pytest.param(
            {"key": "aus", "platform": "binary_sensor", "state": "off"},
            STATE_OFF,
            id="binary-off",
        ),
        pytest.param(
            {"key": "offen", "platform": "binary_sensor", "state": None},
            STATE_UNKNOWN,
            id="binary-null",
        ),
    ],
)
@pytest.mark.usefixtures("setup_integration")
async def test_state_conversion(
    hass: HomeAssistant, entity: dict[str, Any], expected: str
) -> None:
    """Numbers, times, flags and missing values are converted."""
    await _sea_update(hass, {"full": True, "entities": [entity]})

    state = hass.states.get(f"{entity['platform']}.sea_{entity['key']}")
    assert state is not None
    assert state.state == expected


@pytest.mark.usefixtures("setup_integration")
async def test_partial_update_changes_only_the_named(hass: HomeAssistant) -> None:
    """A partial update leaves the other entities as they are."""
    await _sea_update(hass, PAYLOAD)
    await _sea_update(
        hass,
        {
            "full": False,
            "entities": [
                {"key": "guenstig", "platform": "binary_sensor", "state": "off"}
            ],
        },
    )

    assert hass.states.get(CHEAP).state == STATE_OFF
    assert hass.states.get(PV).state == "12.4"
    assert hass.states.get(WINDOW).state == "2026-11-15T01:00:00+00:00"


@pytest.mark.usefixtures("setup_integration")
async def test_unknown_key_adds_an_entity(hass: HomeAssistant) -> None:
    """A key seen for the first time adds a new entity at runtime."""
    await _sea_update(hass, PAYLOAD)
    await _sea_update(
        hass, {"full": False, "entities": [_entity("kosten_heute", "1.5", unit="EUR")]}
    )

    state = hass.states.get("sensor.sea_kosten_heute")
    assert state is not None
    assert state.state == "1.5"


@pytest.mark.usefixtures("setup_integration")
async def test_full_update_without_a_key_makes_it_unavailable(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """A key missing from a full update becomes unavailable, not removed."""
    await _sea_update(hass, PAYLOAD)
    await _sea_update(hass, {**PAYLOAD, "entities": PAYLOAD["entities"][:2]})

    assert hass.states.get(WINDOW).state == STATE_UNAVAILABLE
    assert entity_registry.async_get(WINDOW) is not None
    assert hass.states.get(PV).state == "12.4"


@pytest.mark.usefixtures("setup_integration")
async def test_silence_makes_everything_unavailable(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Without a call for 30 minutes all SEA entities become unavailable."""
    await _sea_update(hass, PAYLOAD)

    freezer.tick(SEA_TIMEOUT - timedelta(seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(PV).state == "12.4"

    freezer.tick(timedelta(seconds=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(PV).state == STATE_UNAVAILABLE
    assert hass.states.get(CHEAP).state == STATE_UNAVAILABLE

    await _sea_update(hass, PAYLOAD)
    assert hass.states.get(PV).state == "12.4"


async def test_restart_restores_the_entities(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_homeassistant: None,
    mock_config_entry: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_coordinator_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh: AsyncMock,
) -> None:
    """After a restart the stored entities exist, unavailable until SEA calls."""
    hass_storage["habitron.sea"] = {
        "version": 1,
        "key": "habitron.sea",
        "data": {
            "version": "0.15.0",
            "url": None,
            "entities": [
                {
                    "key": "pv_prognose_heute",
                    "platform": "sensor",
                    "name": "PV-Prognose heute",
                    "unit": "kWh",
                    "device_class": None,
                    "icon": "mdi:solar-power",
                }
            ],
        },
    }
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(PV).state == STATE_UNAVAILABLE

    await _sea_update(hass, PAYLOAD)
    assert hass.states.get(PV).state == "12.4"


@pytest.mark.usefixtures("setup_integration")
async def test_full_list_is_stored(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A full update stores the entity list for the next start."""
    await _sea_update(hass, PAYLOAD)
    await hass.async_block_till_done()

    stored = hass_storage["habitron.sea"]["data"]
    assert stored["version"] == "0.15.0-beta.97"
    assert [item["key"] for item in stored["entities"]] == [
        "pv_prognose_heute",
        "guenstig",
        "naechstes_guenstiges_fenster",
    ]


async def test_two_hubs_make_one_device(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    setup_integration: MockConfigEntry,
) -> None:
    """A second hub does not create a second SEA device."""
    await _second_entry(hass)
    await _sea_update(hass, PAYLOAD)

    devices = [
        device
        for device in device_registry.devices.values()
        if (DOMAIN, "sea") in device.identifiers
    ]
    assert len(devices) == 1
    assert devices[0].config_entries == {setup_integration.entry_id}
    assert hass.states.get(PV).state == "12.4"


async def test_device_moves_when_its_hub_unloads(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    setup_integration: MockConfigEntry,
) -> None:
    """Unloading the hub SEA hangs on moves its entities to the other hub."""
    second = await _second_entry(hass)
    await _sea_update(hass, PAYLOAD)

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(PV).state == "12.4"
    assert entity_registry.async_get(PV).config_entry_id == second.entry_id


async def test_unload_removes_service_and_manager(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Unloading the last hub removes the service, the timer and the manager."""
    await _sea_update(hass, PAYLOAD)

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    assert not hass.services.has_service(DOMAIN, "sea_update")
    assert DATA_SEA not in hass.data
    assert hass.states.get(PV).state == STATE_UNAVAILABLE


@pytest.mark.usefixtures("setup_integration")
async def test_rest_state_keeps_its_entity_id(hass: HomeAssistant) -> None:
    """A state the old REST way left does not push the entity id to a suffix."""
    hass.states.async_set(PV, "11.0")

    await _sea_update(hass, PAYLOAD)

    assert hass.states.get(PV).state == "12.4"
    assert hass.states.get(f"{PV}_2") is None


@pytest.mark.usefixtures("setup_integration")
async def test_version_url_and_platform_changes(
    hass: HomeAssistant, device_registry: dr.DeviceRegistry
) -> None:
    """A new version updates the device; a bad url or platform change is ignored."""
    await _sea_update(hass, PAYLOAD)
    await _sea_update(
        hass,
        {
            "version": "0.16.0",
            "url": "/hassio/ingress/sea",
            "full": False,
            "entities": [{"key": "guenstig", "platform": "sensor", "state": "x"}],
        },
    )

    device = device_registry.async_get_device({(DOMAIN, "sea")})
    assert device.sw_version == "0.16.0"
    assert device.configuration_url is None
    assert hass.states.get(CHEAP).state == STATE_ON
    assert hass.states.get("sensor.sea_guenstig") is None
