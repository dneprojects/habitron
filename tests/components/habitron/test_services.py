"""Tests for the Habitron domain services."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.services import (
    SERVICE_HUB_REBOOT,
    SERVICE_HUB_RESTART,
    SERVICE_MOD_RESTART,
    SERVICE_RTR_RESTART,
    SERVICE_SAVE_MODULE_SMC,
    SERVICE_SAVE_MODULE_SMG,
    SERVICE_SAVE_MODULE_STATUS,
    SERVICE_SAVE_ROUTER_SMR,
    SERVICE_SAVE_ROUTER_STATUS,
    SERVICE_SC_SYSTEM_COMMAND,
    SERVICE_UPDATE_ENTITY,
    _primary_hub,
)

ALL_SERVICE_NAMES = (
    SERVICE_HUB_RESTART,
    SERVICE_HUB_REBOOT,
    SERVICE_MOD_RESTART,
    SERVICE_RTR_RESTART,
    SERVICE_SAVE_MODULE_SMC,
    SERVICE_SAVE_MODULE_SMG,
    SERVICE_SAVE_ROUTER_SMR,
    SERVICE_SAVE_MODULE_STATUS,
    SERVICE_SAVE_ROUTER_STATUS,
    SERVICE_UPDATE_ENTITY,
    SERVICE_SC_SYSTEM_COMMAND,
)


@pytest.mark.parametrize("service_name", ALL_SERVICE_NAMES)
async def test_all_services_registered(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    service_name: str,
) -> None:
    """All 11 Habitron services are registered after setup."""
    assert hass.services.has_service(DOMAIN, service_name)


async def test_hub_restart_calls_comm(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``hub_restart`` is forwarded to ``hub.comm.hub_restart``."""
    hub = setup_integration.runtime_data
    hub.comm.hub_restart = AsyncMock()
    await hass.services.async_call(DOMAIN, SERVICE_HUB_RESTART, {}, blocking=True)
    hub.comm.hub_restart.assert_awaited_once()


async def test_hub_reboot_calls_comm(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``hub_reboot`` is forwarded to ``hub.comm.hub_reboot``."""
    hub = setup_integration.runtime_data
    hub.comm.hub_reboot = AsyncMock()
    await hass.services.async_call(DOMAIN, SERVICE_HUB_REBOOT, {}, blocking=True)
    hub.comm.hub_reboot.assert_awaited_once()


async def test_mod_restart_passes_module_number(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``mod_restart`` forwards 100 + mod_nmbr as the bus address."""
    hub = setup_integration.runtime_data
    hub.comm.module_restart = AsyncMock()
    await hass.services.async_call(
        DOMAIN, SERVICE_MOD_RESTART, {"mod_nmbr": 5}, blocking=True
    )
    hub.comm.module_restart.assert_awaited_once_with(105)


async def test_rtr_restart_uses_zero(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``rtr_restart`` calls ``module_restart(0)``."""
    hub = setup_integration.runtime_data
    hub.comm.module_restart = AsyncMock()
    await hass.services.async_call(DOMAIN, SERVICE_RTR_RESTART, {}, blocking=True)
    hub.comm.module_restart.assert_awaited_once_with(0)


async def test_save_module_smc(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``save_module_smc`` forwards to ``save_smc_file`` with bus offset."""
    hub = setup_integration.runtime_data
    hub.comm.save_smc_file = AsyncMock()
    await hass.services.async_call(
        DOMAIN, SERVICE_SAVE_MODULE_SMC, {"mod_nmbr": 3}, blocking=True
    )
    hub.comm.save_smc_file.assert_awaited_once_with(103)


async def test_save_module_smg(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``save_module_smg`` forwards to ``save_smg_file`` with bus offset."""
    hub = setup_integration.runtime_data
    hub.comm.save_smg_file = AsyncMock()
    await hass.services.async_call(
        DOMAIN, SERVICE_SAVE_MODULE_SMG, {"mod_nmbr": 7}, blocking=True
    )
    hub.comm.save_smg_file.assert_awaited_once_with(107)


async def test_save_router_smr(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``save_router_smr`` is a no-arg call."""
    hub = setup_integration.runtime_data
    hub.comm.save_smr_file = AsyncMock()
    await hass.services.async_call(DOMAIN, SERVICE_SAVE_ROUTER_SMR, {}, blocking=True)
    hub.comm.save_smr_file.assert_awaited_once()


async def test_save_module_status(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``save_module_status`` forwards module number with bus offset."""
    hub = setup_integration.runtime_data
    hub.comm.save_module_status = AsyncMock()
    await hass.services.async_call(
        DOMAIN, SERVICE_SAVE_MODULE_STATUS, {"mod_nmbr": 2}, blocking=True
    )
    hub.comm.save_module_status.assert_awaited_once_with(102)


async def test_save_router_status(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``save_router_status`` is a no-arg call."""
    hub = setup_integration.runtime_data
    hub.comm.save_router_status = AsyncMock()
    await hass.services.async_call(
        DOMAIN, SERVICE_SAVE_ROUTER_STATUS, {}, blocking=True
    )
    hub.comm.save_router_status.assert_awaited_once()


async def test_update_entity_finds_matching_hub(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``update_entity`` looks up the hub by host string."""
    hub = setup_integration.runtime_data
    hub.host = "192.168.1.50"
    hub.comm.update_entity = AsyncMock()
    await hass.services.async_call(
        DOMAIN,
        SERVICE_UPDATE_ENTITY,
        {
            "hub_uid": "192.168.1.50",
            "rtr_nmbr": 1,
            "mod_nmbr": 10,
            "evnt_type": 1,
            "evnt_arg1": 0,
            "evnt_arg2": 0,
        },
        blocking=True,
    )
    hub.comm.update_entity.assert_awaited_once()


async def test_primary_hub_raises_when_no_entries(
    hass: HomeAssistant,
) -> None:
    """``_primary_hub`` raises ServiceValidationError when no entry is loaded."""
    with pytest.raises(ServiceValidationError) as err:
        _primary_hub(hass)
    assert err.value.translation_key == "no_hub_loaded"


async def test_sc_system_command_no_device(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """An empty target list raises ServiceValidationError."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SC_SYSTEM_COMMAND,
            {"target_device": [], "command": "restart"},
            blocking=True,
        )
    assert err.value.translation_key == "no_target_devices"


async def test_sc_system_command_dispatches(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A valid SC Touch device receives the system command."""
    hub = setup_integration.runtime_data
    module = MagicMock()
    module.typ = b"\x01\x04"
    module.name = "SC Touch 1"
    module.stream_name = "sc_touch_1"
    hub.router.get_module_by_uid = MagicMock(return_value=module)
    hub.ws_provider = MagicMock()
    hub.ws_provider.async_send_system_command = AsyncMock()

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=setup_integration.entry_id,
        identifiers={(DOMAIN, "module-uid-42")},
        name="SC Touch Device",
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SC_SYSTEM_COMMAND,
        {"target_device": [device.id], "command": "restart"},
        blocking=True,
    )
    hub.ws_provider.async_send_system_command.assert_awaited_once_with(
        "sc_touch_1", "restart", None
    )


async def test_primary_hub_logs_warning_on_multiple_hubs(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh: AsyncMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With more than one loaded hub, ``_primary_hub`` warns + returns the first."""
    other = MockConfigEntry(
        domain=DOMAIN,
        title="Habitron #2",
        unique_id="hub-2",
        data=setup_integration.data,
        options=setup_integration.options,
    )
    other.add_to_hass(hass)
    assert await hass.config_entries.async_setup(other.entry_id)
    await hass.async_block_till_done()

    with caplog.at_level("WARNING"):
        hub = _primary_hub(hass)
    assert hub is not None
    assert any("singleton service" in rec.message for rec in caplog.records)


async def test_update_entity_raises_when_hub_not_found(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """``update_entity`` raises ``hub_not_found`` when no host matches."""
    hub = setup_integration.runtime_data
    hub.host = "192.168.1.50"
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_UPDATE_ENTITY,
            {
                "hub_uid": "no-such-host",
                "rtr_nmbr": 1,
                "mod_nmbr": 10,
                "evnt_type": 1,
                "evnt_arg1": 0,
                "evnt_arg2": 0,
            },
            blocking=True,
        )
    assert err.value.translation_key == "hub_not_found"


async def test_sc_system_command_accepts_string_device(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A string ``target_device`` is wrapped into a single-element list."""
    hub = setup_integration.runtime_data
    module = MagicMock()
    module.typ = b"\x01\x04"
    module.name = "SC Touch 1"
    module.stream_name = "sc_touch_1"
    hub.router.get_module_by_uid = MagicMock(return_value=module)
    hub.ws_provider = MagicMock()
    hub.ws_provider.async_send_system_command = AsyncMock()

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=setup_integration.entry_id,
        identifiers={(DOMAIN, "module-uid-42")},
        name="SC Touch Device",
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SC_SYSTEM_COMMAND,
        {"target_device": device.id, "command": "restart"},
        blocking=True,
    )
    hub.ws_provider.async_send_system_command.assert_awaited()


async def test_sc_system_command_raises_when_no_matching_module(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A device whose identifier doesn't match any module raises ``no_matching_module``."""
    hub = setup_integration.runtime_data
    hub.router.get_module_by_uid = MagicMock(return_value=None)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=setup_integration.entry_id,
        identifiers={(DOMAIN, "phantom-uid")},
        name="Mystery Device",
    )

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SC_SYSTEM_COMMAND,
            {"target_device": [device.id], "command": "restart"},
            blocking=True,
        )
    assert err.value.translation_key == "no_matching_module"


async def test_sc_system_command_raises_when_ws_provider_missing(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A matching module without a ws_provider raises ``websocket_provider_missing``."""
    hub = setup_integration.runtime_data
    module = MagicMock()
    module.typ = b"\x01\x04"
    module.name = "SC Touch"
    module.stream_name = "sc_touch_1"
    hub.router.get_module_by_uid = MagicMock(return_value=module)
    hub.ws_provider = None

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=setup_integration.entry_id,
        identifiers={(DOMAIN, "module-uid-42")},
        name="SC Touch Device",
    )

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SC_SYSTEM_COMMAND,
            {"target_device": [device.id], "command": "restart"},
            blocking=True,
        )
    assert err.value.translation_key == "websocket_provider_missing"


async def test_sc_system_command_skips_module_without_stream_name(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A module without ``stream_name`` is skipped and the dispatch reports failure."""
    hub = setup_integration.runtime_data
    module = MagicMock(spec=["typ", "name"])
    module.typ = b"\x01\x04"
    module.name = "Stale"
    hub.router.get_module_by_uid = MagicMock(return_value=module)
    hub.ws_provider = MagicMock()

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=setup_integration.entry_id,
        identifiers={(DOMAIN, "module-uid-stale")},
        name="Stale Device",
    )

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SC_SYSTEM_COMMAND,
            {"target_device": [device.id], "command": "restart"},
            blocking=True,
        )
    assert err.value.translation_key == "no_matching_module"


async def test_sc_system_command_skips_unknown_device_id(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A device id that's not in the registry is silently skipped."""
    hub = setup_integration.runtime_data
    hub.router.get_module_by_uid = MagicMock(return_value=None)

    # No device created with this id — registry lookup returns None.
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SC_SYSTEM_COMMAND,
        {"target_device": ["does-not-exist"], "command": "restart"},
        blocking=True,
    )


async def test_sc_system_command_skips_foreign_identifiers(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A device with non-habitron identifiers ignores them but still dispatches."""
    hub = setup_integration.runtime_data
    module = MagicMock()
    module.typ = b"\x01\x04"
    module.name = "SC Touch"
    module.stream_name = "sc_touch_1"
    hub.router.get_module_by_uid = MagicMock(return_value=module)
    hub.ws_provider = MagicMock()
    hub.ws_provider.async_send_system_command = AsyncMock()

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=setup_integration.entry_id,
        # First identifier is from a foreign integration → trigger the
        # ``continue`` skip; second one is ours and drives the dispatch.
        identifiers={("zigbee2mqtt", "0xabc"), (DOMAIN, "module-uid")},
        name="Mixed Device",
    )

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SC_SYSTEM_COMMAND,
        {"target_device": [device.id], "command": "restart"},
        blocking=True,
    )
    hub.ws_provider.async_send_system_command.assert_awaited()


async def test_sc_system_command_raises_when_no_hubs_loaded(
    hass: HomeAssistant,
    setup_homeassistant: None,
) -> None:
    """Calling sc_system_command with no loaded entries surfaces ``no_hub_loaded``.

    We register the services manually since there is no SmartHub entry to
    drive ``async_setup_entry``.
    """
    from custom_components.habitron.services import (
        async_setup_services,  # noqa: PLC0415
    )

    async_setup_services(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SC_SYSTEM_COMMAND,
            {"target_device": "any-device", "command": "restart"},
            blocking=True,
        )
    assert err.value.translation_key == "no_hub_loaded"
