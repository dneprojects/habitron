"""Tests for the Habitron diagnostics support."""

from __future__ import annotations

from unittest.mock import MagicMock

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)

from .const import MOCK_HWTYPE, MOCK_NAME, MOCK_UID, MOCK_VERSION


def _module(uid: str = "MOD-1", name: str = "Living room", typ: bytes = b"\x01\x04") -> MagicMock:
    """Build a stub module the diagnostics helper can iterate."""
    m = MagicMock()
    m.uid = uid
    m.name = name
    m.typ = typ
    m.mod_type = "Smart Controller Touch"
    m.mod_addr = 105
    m.sw_version = "1.2.3"
    m.inputs = [MagicMock(), MagicMock()]
    m.outputs = [MagicMock(), MagicMock(), MagicMock()]
    m.sensors = [MagicMock()]
    m.leds = []
    return m


async def test_config_entry_diagnostics(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Config-entry diagnostics dump hub, router, coordinator and modules."""
    entry = setup_integration
    smhub = entry.runtime_data
    smhub.router.modules = [_module()]
    smhub.router.coord.update_interval = timedelta(seconds=5)
    smhub.router.coord.last_update_success = True

    info = await async_get_config_entry_diagnostics(hass, entry)

    assert info["config_entry"]["unique_id"] == MOCK_UID
    assert info["config_entry"]["title"] == MOCK_NAME
    # token must be redacted
    assert info["config_entry"]["data"]["websock_token"] == "**REDACTED**"

    assert info["hub"]["uid"] == MOCK_UID
    assert info["hub"]["version"] == MOCK_VERSION
    assert info["hub"]["type"] == MOCK_HWTYPE

    assert info["router"]["module_count"] == 1
    assert info["coordinator"]["update_interval_seconds"] == 5
    assert info["coordinator"]["always_update"] is True

    assert len(info["modules"]) == 1
    assert info["modules"][0]["uid"] == "MOD-1"
    assert info["modules"][0]["type"] == "0104"  # bytes hex


async def test_device_diagnostics_for_module(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A device matching a module reports its module summary."""
    entry = setup_integration
    smhub = entry.runtime_data
    smhub.router.modules = [_module(uid="MOD-XYZ", name="Kitchen")]

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "MOD-XYZ")},
        name="Kitchen Touch",
        model="Smart Controller Touch",
    )

    info = await async_get_device_diagnostics(hass, entry, device)
    assert info["device_identifier"] == "MOD-XYZ"
    assert info["target"]["kind"] == "module"
    assert info["target"]["summary"]["name"] == "Kitchen"


async def test_device_diagnostics_for_hub(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A device matching the hub UID reports the hub summary."""
    entry = setup_integration
    smhub = entry.runtime_data

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, smhub.uid)},
        name="SmartHub",
    )

    info = await async_get_device_diagnostics(hass, entry, device)
    assert info["device_identifier"] == smhub.uid
    assert info["target"]["kind"] == "hub"


async def test_device_diagnostics_unknown_identifier(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A device whose UID is not in the router returns target=None."""
    entry = setup_integration
    smhub = entry.runtime_data
    smhub.router.modules = []

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "ghost-uid")},
        name="Unknown",
    )

    info = await async_get_device_diagnostics(hass, entry, device)
    assert info["device_identifier"] == "ghost-uid"
    assert info["target"] is None


async def test_device_diagnostics_for_router(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A device whose UID matches the router reports the router summary."""
    entry = setup_integration
    smhub = entry.runtime_data
    router_uid = smhub.router.uid

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, router_uid)},
        name="Router",
    )

    info = await async_get_device_diagnostics(hass, entry, device)
    assert info["device_identifier"] == router_uid
    assert info["target"]["kind"] == "router"
