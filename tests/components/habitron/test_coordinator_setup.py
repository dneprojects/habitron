"""Tests for the coordinator's setup path: connect, build, register."""

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Area, HabitronClient, HabitronError, Module, Router
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.coordinator import HbtnCoordinator, LoggingLevels
from custom_components.habitron.system_health import async_register, system_health_info
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar, device_registry as dr

from .const import (
    MOCK_CONFIG_DATA,
    MOCK_CONFIG_OPTIONS,
    MOCK_HOST,
    MOCK_MAC,
    MOCK_SMHUB_INFO,
    MOCK_UID,
)


def test_logging_levels_enum_values() -> None:
    """LoggingLevels exposes the documented int values for each named level."""
    assert LoggingLevels.notset.value == 0
    assert LoggingLevels.debug.value == 1
    assert LoggingLevels.info.value == 2
    assert LoggingLevels.warning.value == 3
    assert LoggingLevels.error.value == 4
    assert LoggingLevels.critical.value == 5


@pytest.fixture
def coordinator_stub() -> HbtnCoordinator:
    """Build a HbtnCoordinator with its client stubbed out.

    The coordinator owns the connection now, so the stub goes in after
    construction. ``hass.data`` carries the manifest the constructor reads for
    the version it reports to the hub.
    """
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.data = {"integrations": {"habitron": MagicMock(manifest={"version": "3.4.3"})}}
    config = MagicMock()
    config.title = "Habitron"
    config.entry_id = "entry-id"
    config.data = {"host": MOCK_HOST, "websock_token": "tok"}

    coord = HbtnCoordinator(hass, config)
    coord._client = AsyncMock()
    coord.host = MOCK_HOST
    coord._mac = "AA:BB:CC:DD:EE:FF"
    coord.is_addon = False
    return coord


def test_init_starts_with_empty_models(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """Empty models until ``async_setup`` builds them from the bus.

    Empty rather than ``None`` so nothing downstream has to guard against it,
    and an empty uid rather than a placeholder: a placeholder that reached the
    registry would be an identity two hubs could share.
    """
    assert coordinator_stub.uid == ""
    assert coordinator_stub.online is True
    assert coordinator_stub.router is not None
    assert coordinator_stub.router.modules == []
    assert coordinator_stub.addon_slug == ""
    assert coordinator_stub.base_url == ""
    assert coordinator_stub.host_diags_valid is False


def test_hub_properties_read_through_to_the_model(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """The hub facts come off the library model, not a second copy."""
    coordinator_stub.hub.version = "1.2.3"
    coordinator_stub.hub.platform = "Raspberry Pi 5"
    coordinator_stub.hub.slug = "habitron_smarthub"
    assert coordinator_stub.smhub_version == "1.2.3"
    assert coordinator_stub.smhub_type == "Raspberry Pi 5"
    assert coordinator_stub.addon_slug == "habitron_smarthub"


@pytest.mark.parametrize(
    ("is_addon", "expected_conf_url"),
    [
        (False, f"http://{MOCK_HOST}:7780/hub"),
        # Relative to whatever base the viewer is on: the frontend rewrites
        # ``homeassistant://`` to ``/``, so this one stored value resolves both
        # on the LAN and behind a remote (Nabu Casa) URL.
        (True, "homeassistant://habitron_smarthub/ingress?index=%2Fhub"),
    ],
)
async def test_setup_registers_hub_device(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
    is_addon: bool,
    expected_conf_url: str,
) -> None:
    """Full config-entry setup registers the hub device in the registry.

    Drives the public path (config entry -> HbtnCoordinator.async_setup -> device
    registry); only the ``habitron_client`` boundary, the bus-model build and
    the frontend iconset JS are mocked, so the real wiring (addon vs standalone
    base URL included) runs.
    """
    router = Router(uid="rt_1")
    router.modules = []
    entry, _client = await real_setup(router, is_addon=is_addon)

    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, MOCK_UID), entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "Habitron GmbH"
    assert device.sw_version == MOCK_SMHUB_INFO["software"]["version"]
    assert device.configuration_url == expected_conf_url


@pytest.mark.parametrize(
    ("build_error", "stop_error"),
    [
        (HabitronError("truncated inventory"), None),
        (None, HabitronError("no reply")),
    ],
    ids=["the build fails", "the stop itself fails"],
)
async def test_event_server_is_restored_when_setup_fails(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh: AsyncMock,
    build_error: Exception | None,
    stop_error: Exception | None,
) -> None:
    """``reinit_hub(1)`` has to run even when the build never got going.

    The stop takes seconds, so its answer can go missing long after the hub has
    already stopped the event server. Restoring only after a stop that answered
    would leave the hub stopped for good, across every setup retry.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=MOCK_UID,
        data=MOCK_CONFIG_DATA,
        options=MOCK_CONFIG_OPTIONS,
    )
    entry.add_to_hass(hass)

    client = AsyncMock(spec=HabitronClient)
    client.host = MOCK_HOST
    client.get_smhub_info = AsyncMock(return_value=MOCK_SMHUB_INFO)
    client.get_smhub_update = AsyncMock(return_value=None)

    def _reinit(mode: int) -> None:
        if mode == 0 and stop_error is not None:
            raise stop_error

    client.reinit_hub = AsyncMock(side_effect=_reinit)

    hass.data.setdefault("integrations", {})["habitron"] = MagicMock(
        manifest={"version": "3.4.3"}
    )

    build = AsyncMock(return_value=Router(uid="rt_1"))
    if build_error is not None:
        build = AsyncMock(side_effect=build_error)

    coord = HbtnCoordinator(hass, entry)
    with (
        patch(
            "custom_components.habitron.coordinator.HabitronClient",
            return_value=client,
        ),
        patch(
            "custom_components.habitron.coordinator.get_host_ip",
            new=AsyncMock(return_value=MOCK_HOST),
        ),
        patch("custom_components.habitron.coordinator.async_build_system", new=build),
        patch("custom_components.habitron.coordinator.add_extra_js_url"),
        patch.object(HbtnCoordinator, "_register_iconset", new=AsyncMock()),
        pytest.raises(HabitronError),
    ):
        await coord.async_setup()

    assert [call.args[0] for call in client.reinit_hub.await_args_list] == [0, 1]


@pytest.mark.parametrize(
    "raised",
    [HabitronError("boom"), OSError("socket gone"), TimeoutError("slow")],
)
async def test_update_swallows_a_failed_host_read(
    coordinator_stub: HbtnCoordinator, raised: Exception
) -> None:
    """A failed host read is non-fatal.

    The readings are decoupled from the bus status: a dropped or unreadable
    response must not fail the coordinator tick -- which would mark *every*
    entity unavailable -- or abort setup. The values written so far are kept
    and the next tick refreshes them.
    """
    with patch(
        "custom_components.habitron.coordinator.async_refresh_hub",
        new=AsyncMock(side_effect=raised),
    ):
        await coordinator_stub.update()  # must not raise

    assert coordinator_stub.host_diags_valid is False


async def test_update_hands_the_hub_to_the_library(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """Writing the readings is the library's job, driving the poll is ours.

    Which platform exposes which reading, and the notification on a change,
    live in ``habitron_client`` -- the coordinator only supplies the client,
    the model and the version the hub is told about.
    """
    with patch(
        "custom_components.habitron.coordinator.async_refresh_hub", new=AsyncMock()
    ) as refresh:
        await coordinator_stub.update()

    refresh.assert_awaited_once_with(
        coordinator_stub.client,
        coordinator_stub.hub,
        hbtn_version=coordinator_stub._hbtn_version,
    )


async def test_async_update_delegates_to_update(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """async_update is a thin awaiter around update() directly."""
    with patch(
        "custom_components.habitron.coordinator.async_refresh_hub", new=AsyncMock()
    ) as refresh:
        await coordinator_stub.async_update()

    refresh.assert_awaited_once()


async def test_async_close_releases_the_client(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """Unload drops the client so it can close any probe socket it holds."""
    client = coordinator_stub.client
    await coordinator_stub.async_close()
    client.close.assert_awaited()
    # Idempotent: a second unload must not explode on the dropped reference.
    await coordinator_stub.async_close()
    client.close.assert_awaited_once()


async def test_get_version_strips_smartip_prefix(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """``get_version`` strips the leading SmartIP marker from the reply."""
    # ``get_version`` returns ver_string[9:] when the SmartIP prefix is
    # present — so the version payload sits at byte index 9.
    coordinator_stub.client.get_smhub_version = AsyncMock(
        return_value=b"SmartIP\x00\x001.2.3.4"
    )
    ver = await coordinator_stub.get_version()
    assert ver == "1.2.3.4"


async def test_get_version_returns_zero_default_when_marker_missing(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """If the SmartIP marker is missing, ``get_version`` falls back to 0.0.0."""
    coordinator_stub.client.get_smhub_version = AsyncMock(return_value=b"garbled")
    ver = await coordinator_stub.get_version()
    assert ver == "0.0.0"


async def test_restart_forwards_to_comm(coordinator_stub: HbtnCoordinator) -> None:
    """``restart`` accepts a router id (forward-compat) but forwards a no-arg call."""
    await coordinator_stub.restart()
    coordinator_stub.client.hub_restart.assert_awaited_with()


async def test_reboot_forwards_to_comm(coordinator_stub: HbtnCoordinator) -> None:
    """reboot() forwards the call to ``client.hub_reboot``."""
    await coordinator_stub.reboot()
    coordinator_stub.client.hub_reboot.assert_awaited()


def test_async_register_forwards_system_health_info() -> None:
    """``async_register`` wires ``system_health_info`` into the registration helper."""

    hass = MagicMock()
    register = MagicMock()
    async_register(hass, register)
    register.async_register_info.assert_called_with(system_health_info)


async def test_setup_suggests_module_area_on_first_creation(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
) -> None:
    """A newly created module device lands in its bus area."""
    router = Router(uid="rt_1")
    router.areas = [Area(nmbr=1, name="Living Room")]
    router.modules = [
        Module(uid="MOD-1", addr=5, typ=b"\x01\x02", name="Mod 1", area=1)
    ]
    entry, _client = await real_setup(router)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device_by_identifier((DOMAIN, "MOD-1"), entry.entry_id)
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
        Module(uid="MOD-1", addr=5, typ=b"\x01\x02", name="Mod 1", area=1),
        Module(uid="MOD-2", addr=6, typ=b"\x01\x02", name="Mod 2", area=1),
    ]
    entry, _client = await real_setup(router)

    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)
    device = dev_reg.async_get_device_by_identifier((DOMAIN, "MOD-1"), entry.entry_id)
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
    device = dev_reg.async_get_device_by_identifier((DOMAIN, "MOD-1"), entry.entry_id)
    assert device is not None
    assert device.area_id == kitchen.id

    other = dev_reg.async_get_device_by_identifier((DOMAIN, "MOD-2"), entry.entry_id)
    assert other is not None
    assert other.area_id is not None
    assert area_reg.async_get_area(other.area_id).name == "Living Room"


async def test_setup_links_modules_via_router_to_hub(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
) -> None:
    """Modules hang under the router, which hangs under the hub.

    The link is registered through ``via_device_id`` (the registry id) rather
    than the deprecated ``via_device`` identifier tuple, so this pins that the
    hierarchy still comes out the same.
    """
    router = Router(uid="rt_1")
    router.modules = [
        Module(uid="MOD-1", addr=5, typ=b"\x01\x02", name="Mod 1", area=0)
    ]
    entry, _client = await real_setup(router)

    dev_reg = dr.async_get(hass)
    hub = dev_reg.async_get_device_by_identifier((DOMAIN, MOCK_UID), entry.entry_id)
    rt = dev_reg.async_get_device_by_identifier((DOMAIN, "rt_1"), entry.entry_id)
    mod = dev_reg.async_get_device_by_identifier((DOMAIN, "MOD-1"), entry.entry_id)
    assert hub is not None and rt is not None and mod is not None
    assert rt.via_device_id == hub.id
    assert mod.via_device_id == rt.id


@pytest.mark.parametrize(
    "stamp",
    ["10.0.0.7", "192.168.1.50", "smarthub.local"],
    ids=["reached at", "reported by the hub", "as configured"],
)
def test_a_pushed_event_is_matched_by_any_address_naming_this_hub(
    coordinator_stub: HbtnCoordinator, stamp: str
) -> None:
    """The hub picks the stamp itself, so all three spellings have to match.

    The service documents the field as "host name or IP", and an unmatched push
    is dropped with a debug line -- guessing which one the firmware uses would
    cost every button press and motion pulse silently.
    """
    coordinator_stub.host = "10.0.0.7"
    coordinator_stub.reported_ip = "192.168.1.50"
    coordinator_stub._host_conf = "smarthub.local"

    assert coordinator_stub.owns_event_from(stamp) is True


def test_a_pushed_event_from_another_hub_is_not_claimed(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """A second hub's events must not be applied to this one's model."""
    coordinator_stub.host = "10.0.0.7"
    coordinator_stub.reported_ip = "192.168.1.50"
    coordinator_stub._host_conf = "smarthub.local"

    assert coordinator_stub.owns_event_from("10.0.0.99") is False


async def test_the_reported_address_does_not_replace_the_one_we_reached(
    coordinator_stub: HbtnCoordinator,
) -> None:
    """Device links are built from ``host``, so the hub must not overwrite it.

    A hub whose interface is unnumbered from its own point of view answers
    ``0.0.0.0``; taking that as the address would put it into every device's
    configuration URL.
    """
    coordinator_stub.host = "10.0.0.7"
    coordinator_stub.client.get_smhub_info = AsyncMock(
        return_value={
            "hardware": {
                "platform": {"type": "Raspberry Pi 4"},
                "network": {"ip": "0.0.0.0", "host": "smarthub", "lan mac": MOCK_MAC},
            },
            "software": {"version": "9.9.9", "type": "Smart Hub"},
        }
    )

    await coordinator_stub._async_read_hub_info()

    assert coordinator_stub.host == "10.0.0.7"
    assert coordinator_stub.reported_ip == "0.0.0.0"
    # ...and the hub is still recognised when it stamps that very address.
    assert coordinator_stub.owns_event_from("0.0.0.0") is True
