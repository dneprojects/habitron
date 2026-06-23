"""Tests for the Habitron domain services (habitron_client v2 model)."""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Module, Router
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.services import (
    _async_dispatch_sc_command_for_device,
    _async_reboot_hub,
    _async_restart_hub,
    _async_restart_module,
    _async_restart_router,
    _async_save_module_smc,
    _async_sc_system_command,
    _async_update_entity,
)
from custom_components.habitron.ws_provider import HabitronWebRTCProvider
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

_TARGETED = "custom_components.habitron.services._targeted_hubs"


def _hub(host: str = "1.2.3.4") -> MagicMock:
    hub = MagicMock()
    hub.host = host
    hub.comm = MagicMock()
    for method in (
        "hub_restart",
        "hub_reboot",
        "module_restart",
        "save_smc_file",
        "update_entity",
    ):
        setattr(hub.comm, method, AsyncMock())
    hub.router = Router(uid="rt_1", id=100)
    hub.ws_provider = None
    return hub


def _hass(entries: list) -> MagicMock:
    hass = MagicMock()
    hass.config_entries.async_loaded_entries = MagicMock(return_value=entries)
    return hass


def _entry(hub: MagicMock) -> MagicMock:
    entry = MagicMock()
    entry.runtime_data = hub
    return entry


def _call(hass: MagicMock, data: dict) -> MagicMock:
    call = MagicMock()
    call.hass = hass
    call.data = data
    return call


# ---------------------------------------------------------------------------
# restart / save services (hub resolved via _targeted_hubs)
# ---------------------------------------------------------------------------


async def test_restart_and_reboot_hub() -> None:
    """Hub restart/reboot forward to the comm wrapper of the targeted hub."""
    hub = _hub()
    with patch(_TARGETED, AsyncMock(return_value=[hub])):
        await _async_restart_hub(_call(_hass([_entry(hub)]), {}))
        hub.comm.hub_restart.assert_awaited()
        await _async_reboot_hub(_call(_hass([_entry(hub)]), {}))
        hub.comm.hub_reboot.assert_awaited()


async def test_restart_module_and_router() -> None:
    """Module restart adds 100 to the address; router restart targets 0."""
    hub = _hub()
    with patch(_TARGETED, AsyncMock(return_value=[hub])):
        await _async_restart_module(_call(_hass([_entry(hub)]), {"mod_nmbr": 5}))
        hub.comm.module_restart.assert_awaited_with(105)
        await _async_restart_router(_call(_hass([_entry(hub)]), {}))
        hub.comm.module_restart.assert_awaited_with(0)


async def test_save_module_smc() -> None:
    """Saving a module .smc file forwards the (100 + nmbr) address."""
    hub = _hub()
    with patch(_TARGETED, AsyncMock(return_value=[hub])):
        await _async_save_module_smc(_call(_hass([_entry(hub)]), {"mod_nmbr": 3}))
    hub.comm.save_smc_file.assert_awaited_with(103)


# ---------------------------------------------------------------------------
# update_entity
# ---------------------------------------------------------------------------


async def test_update_entity_matches_host() -> None:
    """The event is forwarded to the hub whose host matches."""
    hub = _hub(host="10.0.0.5")
    hass = _hass([_entry(hub)])
    data = {
        "hub_uid": "10.0.0.5",
        "mod_nmbr": 2,
        "evnt_type": 1,
        "evnt_arg1": 3,
        "evnt_arg2": 1,
    }
    await _async_update_entity(_call(hass, data))
    hub.comm.update_entity.assert_awaited_with("10.0.0.5", 2, 1, 3, 1, 0, 0, 0)


async def test_update_entity_unknown_host_ignored() -> None:
    """An unknown host is ignored (no forwarding, no error)."""
    hub = _hub(host="10.0.0.5")
    hass = _hass([_entry(hub)])
    data = {
        "hub_uid": "9.9.9.9",
        "mod_nmbr": 2,
        "evnt_type": 1,
        "evnt_arg1": 3,
        "evnt_arg2": 1,
    }
    await _async_update_entity(_call(hass, data))
    hub.comm.update_entity.assert_not_awaited()


# ---------------------------------------------------------------------------
# sc_system_command dispatch
# ---------------------------------------------------------------------------


def _touch_hub() -> MagicMock:
    hub = _hub()
    module = Module(uid="MOD-T", addr=104, typ=b"\x01\x04", name="Touch")
    module.stream_name = "touch_1"
    hub.router.modules = [module]
    hub.ws_provider = MagicMock()
    hub.ws_provider.async_send_system_command = AsyncMock()
    return hub


def _device(identifiers: set) -> MagicMock:
    device = MagicMock()
    device.identifiers = identifiers
    return device


async def test_dispatch_sc_command_to_touch_module() -> None:
    """A Touch module device is dispatched the system command."""
    hub = _touch_hub()
    device = _device({(DOMAIN, "MOD-T")})
    ok = await _async_dispatch_sc_command_for_device(device, [hub], "restart", None)
    assert ok is True
    hub.ws_provider.async_send_system_command.assert_awaited_with(
        "touch_1", "restart", None
    )


async def test_dispatch_sc_command_no_match() -> None:
    """A device with no matching module returns False."""
    hub = _touch_hub()
    device = _device({(DOMAIN, "OTHER")})
    ok = await _async_dispatch_sc_command_for_device(device, [hub], "restart", None)
    assert ok is False


async def test_dispatch_sc_command_ws_provider_missing() -> None:
    """A matching module without a ws provider raises."""
    hub = _touch_hub()
    hub.ws_provider = None
    device = _device({(DOMAIN, "MOD-T")})
    with pytest.raises(ServiceValidationError):
        await _async_dispatch_sc_command_for_device(device, [hub], "restart", None)


async def test_sc_system_command_no_target_devices() -> None:
    """An empty target list raises a ServiceValidationError."""
    hass = _hass([_entry(_touch_hub())])
    with pytest.raises(ServiceValidationError):
        await _async_sc_system_command(_call(hass, {"target_device": []}))


# ---------------------------------------------------------------------------
# sc_system_command — public surface (full config-entry setup + service call)
# ---------------------------------------------------------------------------


async def test_sc_system_command_service_dispatches_to_touch_module(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
) -> None:
    """Calling the ``sc_system_command`` service reaches the Touch ws provider.

    Drives the public path: full config-entry setup builds a router with a
    Touch module (registered as a device), then a real ``hass.services.async_call``
    resolves that device and forwards the command to the module's ws provider.
    """
    module = Module(uid="MOD-T", addr=104, typ=b"\x01\x04", name="Touch")
    module.stream_name = "touch_1"
    router = Router(uid="rt_1", id=100)
    router.modules = [module]

    await real_setup(router)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "MOD-T")})
    assert device is not None

    with patch.object(
        HabitronWebRTCProvider, "async_send_system_command", new=AsyncMock()
    ) as mock_send:
        await hass.services.async_call(
            DOMAIN,
            "sc_system_command",
            {"target_device": device.id, "command": "restart"},
            blocking=True,
        )

    mock_send.assert_awaited_once_with("touch_1", "restart", None)
