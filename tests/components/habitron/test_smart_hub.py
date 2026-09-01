"""Tests for the Habitron SmartHub class."""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import (
    Area,
    Diagnostic,
    HabitronError,
    HabitronProtocolError,
    HostDiagnostics,
    Module,
    Router,
    Sensor,
)
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.smart_hub import LoggingLevels, SmartHub
from custom_components.habitron.system_health import async_register, system_health_info
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr

from .const import MOCK_HOST, MOCK_SMHUB_INFO, MOCK_UID


def test_logging_levels_enum_values() -> None:
    """LoggingLevels exposes the documented int values for each named level."""
    assert LoggingLevels.notset.value == 0
    assert LoggingLevels.debug.value == 1
    assert LoggingLevels.info.value == 2
    assert LoggingLevels.warning.value == 3
    assert LoggingLevels.error.value == 4
    assert LoggingLevels.critical.value == 5


@pytest.fixture
def smart_hub_stub() -> SmartHub:
    """Build a SmartHub with the heavy dependencies stubbed out."""
    with (
        patch("custom_components.habitron.smart_hub.hbtn_com") as mock_com,
        patch("custom_components.habitron.smart_hub.HbtnCoordinator"),
    ):
        comm = MagicMock()
        comm.com_ip = MOCK_HOST
        comm.com_port = 7777
        comm.com_mac = "AA:BB:CC:DD:EE:FF"
        comm.com_version = "9.9.9"
        comm.com_hwtype = "Raspberry Pi 4"
        comm.is_addon = False
        comm.slugname = ""
        comm.async_setup = AsyncMock()
        comm.async_close = AsyncMock()
        comm.get_smhub_info = AsyncMock()
        comm.get_smhub_update = AsyncMock()
        comm.get_host_diagnostics = AsyncMock()
        comm.get_smhub_version = AsyncMock()
        comm.reinit_hub = AsyncMock()
        comm.send_network_info = AsyncMock()
        comm.send_devregid = AsyncMock()
        comm.set_router = MagicMock()
        comm.hub_restart = AsyncMock()
        comm.hub_reboot = AsyncMock()
        mock_com.return_value = comm

        hass = MagicMock()
        hass.async_add_executor_job = AsyncMock()
        hass.http.async_register_static_paths = AsyncMock()
        config = MagicMock()
        config.title = "Habitron"
        config.entry_id = "entry-id"
        config.data = {"websock_token": "tok"}
        hub = SmartHub(hass, config)
    return hub  # noqa: RET504


def test_smhub_init_sets_placeholder_uid_and_owns_router(
    smart_hub_stub: SmartHub,
) -> None:
    """__init__ leaves uid as ``pending`` until async_setup runs."""
    assert smart_hub_stub.uid == "pending"
    assert smart_hub_stub._mac == "00:00:00:00:00:00"
    assert smart_hub_stub.online is True
    assert smart_hub_stub.router is not None
    assert smart_hub_stub.addon_slug == ""
    assert smart_hub_stub.base_url == ""


def test_smhub_version_property(smart_hub_stub: SmartHub) -> None:
    """smhub_version returns the cached version field."""
    smart_hub_stub._version = "1.2.3"
    assert smart_hub_stub.smhub_version == "1.2.3"


@pytest.mark.parametrize(
    ("supervisor_token", "expected_conf_url"),
    [
        (None, f"http://{MOCK_HOST}:7780/hub"),
        (
            "token",
            f"http://{MOCK_HOST}:8123/habitron_smarthub/ingress?index=/hub",
        ),
    ],
)
async def test_setup_registers_hub_device(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
    supervisor_token: str | None,
    expected_conf_url: str,
) -> None:
    """Full config-entry setup registers the hub device in the registry.

    Drives the public path (config entry -> SmartHub.async_setup -> device
    registry); only the ``habitron_client`` boundary, the bus-model build and
    the frontend iconset JS are mocked, so the real wiring (addon vs standalone
    base URL included) runs.
    """
    router = Router(uid="rt_1")
    router.modules = []
    await real_setup(router, supervisor_token=supervisor_token)

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, MOCK_UID)})
    assert device is not None
    assert device.manufacturer == "Habitron GmbH"
    assert device.sw_version == MOCK_SMHUB_INFO["software"]["version"]
    assert device.configuration_url == expected_conf_url


async def test_update_survives_an_unreadable_reading(smart_hub_stub: SmartHub) -> None:
    """A reading that is not a number must not fail the coordinator tick.

    The unit stripping used to happen here, so a malformed value raised a bare
    ValueError out of update() and took the whole tick (and with it every
    entity) down. The library now reports it as a protocol error, which lands
    in the same handler as a dropped response.
    """
    smart_hub_stub.comm.get_host_diagnostics.side_effect = HabitronProtocolError(
        "SmartHub update: 'cpu.load' is not a number: 'n/a'"
    )
    smart_hub_stub.diags = [Diagnostic(name="Status", nmbr=0, type=1)]
    await smart_hub_stub.update()  # must not raise
    smart_hub_stub.comm.get_host_diagnostics.assert_awaited_once()
    assert smart_hub_stub.host_diags_valid is False


async def test_update_short_circuits_when_no_diags(smart_hub_stub: SmartHub) -> None:
    """update() skips the query entirely when self.diags is empty.

    Non-Raspberry-Pi hubs have no host diagnostics, so it must not fetch and
    discard a SmartHub update on every tick.
    """
    smart_hub_stub.diags = []
    await smart_hub_stub.update()
    smart_hub_stub.comm.get_host_diagnostics.assert_not_awaited()


async def test_update_writes_diag_sensor_and_log_levels(
    smart_hub_stub: SmartHub,
) -> None:
    """A fully-populated info dict is parsed into the descriptor lists."""
    smart_hub_stub.comm.get_host_diagnostics.return_value = HostDiagnostics(
        cpu_frequency=1500.0,
        cpu_load=12.0,
        cpu_temperature=55.5,
        memory_usage=60.0,
        disk_usage=30.0,
        log_level_console=3,
        log_level_file=4,
    )
    smart_hub_stub.diags = [MagicMock(), MagicMock(), MagicMock()]
    smart_hub_stub.sensors = [MagicMock(), MagicMock()]
    smart_hub_stub.loglvl = [MagicMock(), MagicMock()]

    await smart_hub_stub.update()

    assert smart_hub_stub.diags[0].value == 1500.0
    assert smart_hub_stub.diags[1].value == 12.0
    assert smart_hub_stub.diags[2].value == 55.5
    assert smart_hub_stub.sensors[0].value == 60.0
    assert smart_hub_stub.sensors[1].value == 30.0
    assert smart_hub_stub.loglvl[0].value == 3
    assert smart_hub_stub.loglvl[1].value == 4
    assert smart_hub_stub.host_diags_valid is True


async def test_update_notifies_all_members_on_first_success(
    smart_hub_stub: SmartHub,
) -> None:
    """The first successful read notifies every member, even unchanged ones.

    When the setup-time reads failed, the entities report ``unknown``. A later
    successful read must publish *all* host readings, including members whose
    value happens to equal the placeholder they were seeded with -- those do
    not notify on their own, and with an otherwise idle bus their entities
    would stay ``unknown`` indefinitely.
    """
    smart_hub_stub.comm.get_host_diagnostics.return_value = HostDiagnostics(
        cpu_frequency=1500.0,
        cpu_load=12.0,
        cpu_temperature=55.5,
        memory_usage=60.0,
        disk_usage=30.0,
        log_level_console=0,
        log_level_file=0,
    )
    # Seed every member with the value the read will return, so no _set() call
    # sees a change and none of them notifies by itself.
    smart_hub_stub.diags = [
        Diagnostic(name="CPU Frequency", nmbr=0, type=10, value=1500.0),
        Diagnostic(name="CPU load", nmbr=1, type=10, value=12.0),
        Diagnostic(name="CPU Temperature", nmbr=2, type=10, value=55.5),
    ]
    smart_hub_stub.sensors = [
        Sensor(name="Memory usage", nmbr=0, type=2, value=60.0),
        Sensor(name="Disk usage", nmbr=1, type=2, value=30.0),
    ]
    smart_hub_stub.loglvl = [
        Sensor(name="Logging level console", nmbr=0, type=2, value=0),
        Sensor(name="Logging level file", nmbr=1, type=2, value=0),
    ]
    members = [
        *smart_hub_stub.diags,
        *smart_hub_stub.sensors,
        *smart_hub_stub.loglvl,
    ]
    for member in members:
        member.notify = MagicMock()
    smart_hub_stub.host_diags_valid = False

    await smart_hub_stub.update()

    assert smart_hub_stub.host_diags_valid is True
    for member in members:
        assert member.notify.call_count == 1

    # A subsequent unchanged read must not re-notify: the entities are already
    # showing these values.
    for member in members:
        member.notify.reset_mock()

    await smart_hub_stub.update()

    for member in members:
        member.notify.assert_not_called()


async def test_async_update_delegates_to_update(
    smart_hub_stub: SmartHub,
) -> None:
    """async_update is now a thin awaiter around update() directly."""
    smart_hub_stub.comm.get_host_diagnostics.side_effect = HabitronError("boom")
    smart_hub_stub.diags = [Diagnostic(name="Status", nmbr=0, type=1)]
    await smart_hub_stub.async_update()
    smart_hub_stub.comm.get_host_diagnostics.assert_awaited()


async def test_async_close_delegates_to_comm(
    smart_hub_stub: SmartHub,
) -> None:
    """async_close hands off to comm.async_close to tear down the persistent client."""
    await smart_hub_stub.async_close()
    smart_hub_stub.comm.async_close.assert_awaited()


async def test_get_version_strips_smartip_prefix(
    smart_hub_stub: SmartHub,
) -> None:
    """``get_version`` strips the leading SmartIP marker from the reply."""
    # ``get_version`` returns ver_string[9:] when the SmartIP prefix is
    # present — so the version payload sits at byte index 9.
    smart_hub_stub.comm.get_smhub_version = AsyncMock(
        return_value=b"SmartIP\x00\x001.2.3.4"
    )
    ver = await smart_hub_stub.get_version()
    assert ver == "1.2.3.4"


async def test_get_version_returns_zero_default_when_marker_missing(
    smart_hub_stub: SmartHub,
) -> None:
    """If the SmartIP marker is missing, ``get_version`` falls back to 0.0.0."""
    smart_hub_stub.comm.get_smhub_version = AsyncMock(return_value=b"garbled")
    ver = await smart_hub_stub.get_version()
    assert ver == "0.0.0"


async def test_restart_forwards_to_comm(smart_hub_stub: SmartHub) -> None:
    """``restart`` accepts a router id (forward-compat) but forwards a no-arg call."""
    await smart_hub_stub.restart(7)
    smart_hub_stub.comm.hub_restart.assert_awaited_with()


async def test_reboot_forwards_to_comm(smart_hub_stub: SmartHub) -> None:
    """reboot() forwards the call to ``comm.hub_reboot``."""
    await smart_hub_stub.reboot()
    smart_hub_stub.comm.hub_reboot.assert_awaited()


def test_async_register_forwards_system_health_info() -> None:
    """``async_register`` wires ``system_health_info`` into the registration helper."""

    hass = MagicMock()
    register = MagicMock()
    async_register(hass, register)
    register.async_register_info.assert_called_with(system_health_info)


async def test_update_swallows_habitron_error(smart_hub_stub: SmartHub) -> None:
    """A library error during the diagnostics read is non-fatal (swallowed).

    Host diagnostics are decoupled from the bus status: a dropped/bad response
    must not fail the coordinator tick or abort setup, so update() catches the
    library error and keeps the last values.
    """
    smart_hub_stub.comm.get_host_diagnostics.side_effect = HabitronError("boom")
    smart_hub_stub.diags = [Diagnostic(name="Status", nmbr=0, type=1)]
    await smart_hub_stub.update()  # must not raise
    smart_hub_stub.comm.get_host_diagnostics.assert_awaited_once()
    # Nothing was read, so the host readings must stay unknown rather than
    # publishing the zero defaults as if they were measurements.
    assert smart_hub_stub.host_diags_valid is False


async def test_setup_suggests_module_area_on_first_creation(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
) -> None:
    """A newly created module device lands in its bus area."""
    router = Router(uid="rt_1")
    router.areas = [Area(nmbr=1, name="Living Room")]
    router.modules = [
        Module(uid="MOD-1", addr=105, typ=b"\x01\x02", name="Mod 1", area=1)
    ]
    await real_setup(router)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, "MOD-1")})
    assert device is not None
    area_reg = ar.async_get(hass)
    assert device.area_id is not None
    assert area_reg.async_get_area(device.area_id).name == "Living Room"


async def test_reload_keeps_user_area_when_router_area_list_is_lost(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
) -> None:
    """A user's own area assignment survives re-registration.

    Regression test: the bus area used to be re-applied with
    ``async_update_device`` on every setup. When the router lost its area list,
    ``_area_name`` fell back to "House" for every module, so a reload moved all
    devices into a fresh "House" area and discarded the user's assignment.
    """
    router = Router(uid="rt_1")
    router.areas = [Area(nmbr=1, name="Living Room")]
    router.modules = [
        Module(uid="MOD-1", addr=105, typ=b"\x01\x02", name="Mod 1", area=1),
        Module(uid="MOD-2", addr=106, typ=b"\x01\x02", name="Mod 2", area=1),
    ]
    entry, _client = await real_setup(router)

    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, "MOD-1")})
    assert device is not None

    # The user moves the module into an area of their own.
    kitchen = area_reg.async_get_or_create("Kitchen")
    dev_reg.async_update_device(device.id, area_id=kitchen.id)

    # The router comes back without its area list -- every module now resolves
    # to the "House" fallback.
    router.areas = []
    await entry.runtime_data._register_bus_devices()
    await hass.async_block_till_done()

    # The moved module keeps the user's area, the untouched one keeps the area
    # it was created in -- neither is dragged into the "House" fallback.
    device = dev_reg.async_get_device(identifiers={(DOMAIN, "MOD-1")})
    assert device is not None
    assert device.area_id == kitchen.id

    other = dev_reg.async_get_device(identifiers={(DOMAIN, "MOD-2")})
    assert other is not None
    assert other.area_id is not None
    assert area_reg.async_get_area(other.area_id).name == "Living Room"
