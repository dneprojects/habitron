"""Tests for the Smart Energy Agent (SEA) add-on connection."""

import asyncio
from collections.abc import AsyncGenerator, Callable
from typing import Any
from unittest.mock import patch

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestServer
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron import async_remove_config_entry_device
from custom_components.habitron.config_flow import ConfigFlow
from custom_components.habitron.const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_SEA
from custom_components.habitron.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from custom_components.habitron.sea import SEA_STRATEGIES
from homeassistant.config_entries import (
    SOURCE_HASSIO,
    ConfigEntryDisabler,
    ConfigEntryState,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_TOKEN,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

# Raised inside HA's own async_get_clientsession with the pinned versions.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Setting custom ClientSession.close attribute is discouraged:DeprecationWarning"
)

TOKEN = "a" * 64
# Keys the b1 service did not have.
B1_MISSING = {
    "pv_prognose_heute_rest",
    "naechstes_guenstiges_fenster_ende",
    "akku_plan_bis",
    "tarif",
}
PV = "sensor.sea_pv_forecast_today"
PLAN = "sensor.sea_battery_plan"
WINDOW = "sensor.sea_next_cheap_window"
COST = "sensor.sea_cost_today"
CHEAP = "binary_sensor.sea_cheap_now"

STATE: dict[str, Any] = {
    "pv_prognose_heute": 12.4,
    "pv_prognose_heute_rest": 5.1,
    "pv_prognose_morgen": 20.0,
    "strompreis": 18.2,
    "guenstig": True,
    "tarif": "dynamic",
    "naechstes_guenstiges_fenster": "2026-11-15T01:00:00+00:00",
    "naechstes_guenstiges_fenster_ende": "2026-11-15T05:00:00+00:00",
    "akku_plan": "charge_pv",
    "akku_plan_bis": "2026-11-14T16:00:00+00:00",
    "einspeisung_gesperrt": False,
    "14a_gedimmt": False,
    "kosten_heute": None,
    "einsparung_heute": None,
    "hinweise": 2,
    "regelung": "auto",
    **{f"strategie_{strategy}": "ready" for strategy in SEA_STRATEGIES},
}


class FakeSea:
    """A SEA add-on serving the v1 API."""

    def __init__(self) -> None:
        """Start with the full contract state."""
        self.info: dict[str, Any] = {
            "api_version": 1,
            "version": "0.16.0",
            "name": "Smart Energy Agent",
            "url": "homeassistant://app/sea",
        }
        self.state: dict[str, Any] = dict(STATE)
        self.sockets: list[web.WebSocketResponse] = []
        self.connected = asyncio.Event()
        self.down = False
        self.commands: list[dict[str, Any]] = []
        self.command_status = 200

    def _authorized(self, request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {TOKEN}"

    async def _info(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        if self.down:
            return web.Response(status=503)
        return web.json_response(self.info)

    async def _state(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(self.state)

    async def _ws(self, request: web.Request) -> web.StreamResponse:
        if not self._authorized(request):
            return web.Response(status=401)
        if self.down:
            return web.Response(status=503)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.append(ws)
        await ws.send_json({"type": "snapshot", "values": self.state})
        self.connected.set()
        async for msg in ws:
            if msg.type is WSMsgType.CLOSE:
                break
        self.sockets.remove(ws)
        return ws

    async def _command(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.Response(status=401)
        body = await request.json()
        self.commands.append(body)
        if self.command_status != 200:
            return web.json_response({"error": "nope"}, status=self.command_status)
        key, value = body["key"], body["value"]
        self.state[key] = (
            ("ready" if value else "off") if key.startswith("strategie_") else value
        )
        await self.send({"type": "update", "values": {key: self.state[key]}})
        return web.json_response({"ok": True, "values": {}})

    def app(self) -> web.Application:
        """Return the web app."""
        app = web.Application()
        app.router.add_get("/api/v1/info", self._info)
        app.router.add_get("/api/v1/state", self._state)
        app.router.add_get("/api/v1/ws", self._ws)
        app.router.add_post("/api/v1/command", self._command)
        return app

    async def send(self, message: Any) -> None:
        """Push a raw message to every client."""
        for ws in list(self.sockets):
            if isinstance(message, str):
                await ws.send_str(message)
            else:
                await ws.send_json(message)

    async def drop(self) -> None:
        """Close every client connection."""
        self.connected.clear()
        for ws in list(self.sockets):
            await ws.close()


@pytest.fixture
def sea() -> FakeSea:
    """Return the fake add-on."""
    return FakeSea()


@pytest.fixture
async def sea_server(
    hass: HomeAssistant,
    sea: FakeSea,
    aiohttp_server: Callable[..., Any],
    socket_enabled: None,
) -> AsyncGenerator[TestServer]:
    """Serve the fake add-on and retry reconnects without waiting."""
    server: TestServer = await aiohttp_server(sea.app())
    with patch("custom_components.habitron.sea._RETRY_MIN", 0):
        yield server
        # The server waits for open sockets, and the listener would reconnect.
        for entry in hass.config_entries.async_loaded_entries(DOMAIN):
            await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


def _sea_entry(server: TestServer, token: str = TOKEN) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Smart Energy Agent",
        unique_id="sea",
        version=2,
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_SEA,
            CONF_HOST: server.host,
            CONF_PORT: server.port,
            CONF_TOKEN: token,
        },
    )


async def _until(check: Callable[[], bool]) -> None:
    """Wait for the listener task, which block_till_done does not track."""
    for _ in range(1000):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


def _state(hass: HomeAssistant, entity_id: str) -> str | None:
    state = hass.states.get(entity_id)
    return state.state if state else None


@pytest.fixture
async def sea_entry(
    hass: HomeAssistant, setup_homeassistant: None, sea: FakeSea, sea_server: TestServer
) -> MockConfigEntry:
    """Set up the SEA entry against the fake add-on."""
    entry = _sea_entry(sea_server)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.wait_for(sea.connected.wait(), 10)
    return entry


def _discovery(server: TestServer, token: str = TOKEN) -> HassioServiceInfo:
    return HassioServiceInfo(
        config={
            "sea": {CONF_HOST: server.host, CONF_PORT: server.port, CONF_TOKEN: token}
        },
        name="Smart Energy Agent",
        slug="sea",
        uuid="1234",
    )


@pytest.mark.usefixtures("setup_homeassistant")
async def test_discovery_creates_the_entry(
    hass: HomeAssistant, sea_server: TestServer
) -> None:
    """The add-on discovery leads to a confirmed SEA entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery(sea_server)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Smart Energy Agent"
    assert result["data"] == {
        CONF_ENTRY_TYPE: ENTRY_TYPE_SEA,
        CONF_HOST: sea_server.host,
        CONF_PORT: sea_server.port,
        CONF_TOKEN: TOKEN,
    }
    assert result["result"].unique_id == "sea"


@pytest.mark.usefixtures("setup_homeassistant")
async def test_discovery_with_a_wrong_token_cannot_connect(
    hass: HomeAssistant, sea_server: TestServer
) -> None:
    """A rejected token shows an error instead of creating the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_HASSIO},
        data=_discovery(sea_server, token="wrong"),
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_rediscovery_updates_the_entry(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea_server: TestServer
) -> None:
    """A new discovery updates host, port and token of the existing entry."""
    info = _discovery(sea_server, token="b" * 64)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=info
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert sea_entry.data[CONF_TOKEN] == "b" * 64


async def test_device_and_entities(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """The entry creates the device SEA with the entities of the contract."""
    device = device_registry.async_get_device({(DOMAIN, "sea")})
    assert device is not None
    assert device.name == "SEA"
    assert device.manufacturer == "Habitron"
    assert device.model == "Smart Energy Agent"
    assert device.sw_version == "0.16.0"
    assert device.configuration_url == "homeassistant://app/sea"
    assert len(er.async_entries_for_device(entity_registry, device.id)) == 38

    assert entity_registry.async_get(PV).unique_id == "sea_pv_prognose_heute"
    assert _state(hass, PV) == "12.4"
    assert hass.states.get(PV).attributes["unit_of_measurement"] == "kWh"
    assert _state(hass, PLAN) == "charge_pv"
    assert hass.states.get(PLAN).attributes["options"] == [
        "charge_pv",
        "charge_grid",
        "discharge",
        "hold",
        "spare",
        "idle",
    ]
    assert _state(hass, WINDOW) == "2026-11-15T01:00:00+00:00"
    assert _state(hass, COST) == STATE_UNKNOWN
    assert _state(hass, CHEAP) == STATE_ON


async def test_push_updates_the_values(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """An update message changes only the keys it carries."""
    await sea.send(
        {"type": "update", "values": {"guenstig": False, "kosten_heute": 1.5}}
    )
    await _until(lambda: _state(hass, CHEAP) == STATE_OFF)

    assert _state(hass, COST) == "1.5"
    assert _state(hass, PV) == "12.4"


@pytest.mark.parametrize(
    ("key", "value", "entity_id"),
    [
        pytest.param("pv_prognose_heute", "12.4", PV, id="number-as-text"),
        pytest.param("akku_plan", "boost", PLAN, id="unknown-option"),
        pytest.param(
            "naechstes_guenstiges_fenster", "2026-11-15T01:00:00", WINDOW, id="no-zone"
        ),
        pytest.param("guenstig", "on", CHEAP, id="flag-as-text"),
    ],
)
async def test_values_of_the_wrong_type_are_unknown(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    sea: FakeSea,
    key: str,
    value: Any,
    entity_id: str,
) -> None:
    """A value that does not match the contract type is unknown."""
    await sea.send({"type": "update", "values": {key: value}})
    await _until(lambda: _state(hass, entity_id) == STATE_UNKNOWN)


async def test_unusable_messages_are_ignored(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """Unreadable text and messages without values change nothing."""
    await sea.send("not json")
    await sea.send({"type": "update", "values": "nope"})
    await sea.send({"type": "entities", "entities": []})
    await sea.send({"type": "update", "values": {"strompreis": 20.0}})
    await _until(lambda: _state(hass, "sensor.sea_electricity_price") == "20.0")

    assert _state(hass, PV) == "12.4"


async def test_snapshot_without_a_key_makes_it_unavailable(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """A key missing from a snapshot makes its entity unavailable."""
    values = {key: value for key, value in STATE.items() if key != "akku_plan"}
    await sea.send({"type": "snapshot", "values": values})
    await _until(lambda: _state(hass, PLAN) == STATE_UNAVAILABLE)

    assert _state(hass, PV) == "12.4"


async def test_lost_connection_and_reconnect(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    sea: FakeSea,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Without a connection all entities are unavailable until the reconnect."""
    sea.info["version"] = "0.17.0"
    sea.state["pv_prognose_heute"] = 13.0
    await sea.drop()
    await _until(lambda: _state(hass, PV) in (STATE_UNAVAILABLE, "13.0"))

    await asyncio.wait_for(sea.connected.wait(), 10)
    await _until(lambda: _state(hass, PV) == "13.0")
    device = device_registry.async_get_device({(DOMAIN, "sea")})
    assert device.sw_version == "0.17.0"


async def test_reconnect_waits_while_the_add_on_is_down(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """While info cannot be read the listener keeps retrying."""
    sea.down = True
    await sea.drop()
    await _until(lambda: _state(hass, PV) == STATE_UNAVAILABLE)

    sea.down = False
    await asyncio.wait_for(sea.connected.wait(), 10)
    await _until(lambda: _state(hass, PV) == "12.4")


@pytest.mark.usefixtures("setup_homeassistant")
async def test_unreachable_add_on_retries_the_setup(
    hass: HomeAssistant, sea_server: TestServer
) -> None:
    """A rejected token or a missing add-on lets HA retry the setup."""
    entry = _sea_entry(sea_server, token="wrong")
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """Unloading stops the listener and the entities."""
    assert await hass.config_entries.async_unload(sea_entry.entry_id)
    await hass.async_block_till_done()

    assert sea_entry.state is ConfigEntryState.NOT_LOADED
    assert _state(hass, PV) == STATE_UNAVAILABLE
    await _until(lambda: not sea.sockets)


async def test_hubs_ignore_the_sea_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry, sea_entry: MockConfigEntry
) -> None:
    """Hub services skip the SEA entry; they end with the last hub."""
    await hass.services.async_call(
        DOMAIN,
        "update_entity",
        {
            "hub_uid": "10.9.9.9",
            "rtr_nmbr": 1,
            "mod_nmbr": 1,
            "evnt_type": 1,
            "evnt_arg1": 1,
            "evnt_arg2": 1,
        },
        blocking=True,
    )

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "update_entity")
    assert sea_entry.state is ConfigEntryState.LOADED


async def test_no_options_or_reconfigure(
    hass: HomeAssistant, sea_entry: MockConfigEntry, setup_integration: MockConfigEntry
) -> None:
    """The SEA entry has no options and cannot be reconfigured by hand."""
    assert not ConfigFlow.async_supports_options_flow(sea_entry)
    assert ConfigFlow.async_supports_options_flow(setup_integration)

    result = await sea_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "sea_not_supported"


async def test_diagnostics_hide_the_token(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Diagnostics show the SEA state without the token."""
    entry_diag = await async_get_config_entry_diagnostics(hass, sea_entry)
    device = device_registry.async_get_device({(DOMAIN, "sea")})
    device_diag = await async_get_device_diagnostics(hass, sea_entry, device)

    assert entry_diag == device_diag
    assert entry_diag["config_entry"][CONF_TOKEN] == "**REDACTED**"
    assert entry_diag["connected"] is True
    assert entry_diag["info"]["version"] == "0.16.0"
    assert entry_diag["values"]["akku_plan"] == "charge_pv"


async def test_the_sea_device_cannot_be_removed(
    hass: HomeAssistant, sea_entry: MockConfigEntry, device_registry: dr.DeviceRegistry
) -> None:
    """The SEA entry keeps its device."""
    device = device_registry.async_get_device({(DOMAIN, "sea")})
    assert not await async_remove_config_entry_device(hass, sea_entry, device)


async def test_service_storage_of_b1_is_removed(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    setup_homeassistant: None,
    sea: FakeSea,
    sea_server: TestServer,
) -> None:
    """The entity list the b1 service stored is deleted."""
    hass_storage["habitron.sea"] = {"version": 1, "key": "habitron.sea", "data": {}}
    entry = _sea_entry(sea_server)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert "habitron.sea" not in hass_storage


async def test_b1_entities_move_to_the_sea_entry(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    setup_homeassistant: None,
    sea: FakeSea,
    sea_server: TestServer,
) -> None:
    """Entities of the b1 service move to the SEA entry with their ids."""
    # Disabled, so loading the integration does not set up a real hub.
    hub = MockConfigEntry(
        domain=DOMAIN, unique_id="aabbccddeeff", disabled_by=ConfigEntryDisabler.USER
    )
    hub.add_to_hass(hass)
    old_device = device_registry.async_get_or_create(
        config_entry_id=hub.entry_id,
        identifiers={(DOMAIN, "sea")},
        name="Smart Energy Agent",
        manufacturer="Habitron",
        model="SEA",
    )
    binary = {"guenstig", "einspeisung_gesperrt", "14a_gedimmt"}
    b1_keys = [
        key
        for key in STATE
        if key not in B1_MISSING and not key.startswith("strategie_")
    ] + ["veraltet"]
    for key in b1_keys:
        platform = "binary_sensor" if key in binary else "sensor"
        entity_registry.async_get_or_create(
            platform,
            DOMAIN,
            f"sea_{key}",
            config_entry=hub,
            device_id=old_device.id,
            suggested_object_id=f"sea_{key}",
        )

    # The REST fallback of SEA posts plain states under the b1 ids.
    hass.states.async_set("sensor.sea_pv_prognose_heute", "11.0")
    hass.states.async_set("binary_sensor.sea_guenstig", "off")

    entry = _sea_entry(sea_server)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    assert len(entities) == 38
    assert _state(hass, "sensor.sea_pv_prognose_heute") == "12.4"
    assert _state(hass, "binary_sensor.sea_guenstig") == STATE_ON
    assert _state(hass, "sensor.sea_akku_plan") == "charge_pv"
    assert _state(hass, "sensor.sea_hinweise") == "2"
    assert entity_registry.async_get("sensor.sea_veraltet") is None

    device = device_registry.async_get_device({(DOMAIN, "sea")})
    assert device.id == old_device.id
    assert device.config_entries == {entry.entry_id}
    assert device.name == "SEA"
    assert device.model == "Smart Energy Agent"
    assert all(entity.device_id == device.id for entity in entities)


async def test_info_that_is_not_an_object_counts_as_unreachable(
    hass: HomeAssistant, setup_homeassistant: None, sea: FakeSea, sea_server: TestServer
) -> None:
    """An answer that is not a JSON object lets HA retry the setup."""
    sea.info = None  # type: ignore[assignment]
    entry = _sea_entry(sea_server)
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


WINDOWS = (WINDOW, "sensor.sea_next_cheap_window_end")


def _hidden_by(
    entity_registry: er.EntityRegistry, entity_id: str
) -> er.RegistryEntryHider | None:
    entry = entity_registry.async_get(entity_id)
    assert entry is not None
    return entry.hidden_by


async def test_fixed_tariff_hides_the_windows(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    sea: FakeSea,
    entity_registry: er.EntityRegistry,
) -> None:
    """A fixed price hides the window entities, another tariff shows them again."""
    assert _state(hass, "sensor.sea_tariff") == "dynamic"
    assert all(_hidden_by(entity_registry, entity_id) is None for entity_id in WINDOWS)

    await sea.send({"type": "update", "values": {"tarif": "fixed"}})
    await _until(lambda: _state(hass, "sensor.sea_tariff") == "fixed")
    assert all(
        _hidden_by(entity_registry, entity_id) is er.RegistryEntryHider.INTEGRATION
        for entity_id in WINDOWS
    )

    await sea.send({"type": "update", "values": {"tarif": None}})
    await _until(lambda: _state(hass, "sensor.sea_tariff") == STATE_UNKNOWN)
    assert all(
        _hidden_by(entity_registry, entity_id) is er.RegistryEntryHider.INTEGRATION
        for entity_id in WINDOWS
    )

    await sea.send({"type": "update", "values": {"tarif": "ht_nt"}})
    await _until(lambda: _state(hass, "sensor.sea_tariff") == "ht_nt")
    assert all(_hidden_by(entity_registry, entity_id) is None for entity_id in WINDOWS)


async def test_a_user_hidden_window_stays_hidden(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    sea: FakeSea,
    entity_registry: er.EntityRegistry,
) -> None:
    """The tariff never changes what the user hid or showed."""
    entity_registry.async_update_entity(WINDOW, hidden_by=er.RegistryEntryHider.USER)

    await sea.send({"type": "update", "values": {"tarif": "fixed"}})
    await _until(lambda: _state(hass, "sensor.sea_tariff") == "fixed")
    await sea.send({"type": "update", "values": {"tarif": "dynamic"}})
    await _until(lambda: _state(hass, "sensor.sea_tariff") == "dynamic")

    assert _hidden_by(entity_registry, WINDOW) is er.RegistryEntryHider.USER


async def test_fixed_tariff_at_start_hides_the_windows(
    hass: HomeAssistant,
    setup_homeassistant: None,
    sea: FakeSea,
    sea_server: TestServer,
    entity_registry: er.EntityRegistry,
) -> None:
    """A fixed price reported at setup hides the windows right away."""
    sea.state["tarif"] = "fixed"
    entry = _sea_entry(sea_server)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert all(
        _hidden_by(entity_registry, entity_id) is er.RegistryEntryHider.INTEGRATION
        for entity_id in WINDOWS
    )


async def test_strategy_states(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """Each strategy is an enum sensor that follows the pushed state."""
    entity_id = "sensor.sea_strategy_pv_surplus"
    assert _state(hass, entity_id) == "ready"
    assert hass.states.get(entity_id).attributes["options"] == [
        "off",
        "missing",
        "ready",
        "acting",
    ]

    await sea.send(
        {"type": "update", "values": {"strategie_self_consumption": "acting"}}
    )
    await _until(lambda: _state(hass, entity_id) == "acting")
    assert _state(hass, "sensor.sea_strategy_optimizer") == "ready"


SWITCH = "switch.sea_pv_surplus"
SELECT = "select.sea_control_mode"


async def test_strategy_switches(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    sea: FakeSea,
    entity_registry: er.EntityRegistry,
) -> None:
    """Eight strategies can be switched; the state follows the push update."""
    switches = [
        entry
        for entry in er.async_entries_for_config_entry(
            entity_registry, sea_entry.entry_id
        )
        if entry.domain == "switch"
    ]
    assert len(switches) == 8
    assert entity_registry.async_get(SWITCH).unique_id == (
        "sea_strategie_self_consumption_switch"
    )
    assert _state(hass, SWITCH) == STATE_ON

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
    )
    assert sea.commands[-1] == {"key": "strategie_self_consumption", "value": False}
    await _until(lambda: _state(hass, SWITCH) == STATE_OFF)
    assert _state(hass, "sensor.sea_strategy_pv_surplus") == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": SWITCH}, blocking=True
    )
    assert sea.commands[-1] == {"key": "strategie_self_consumption", "value": True}
    await _until(lambda: _state(hass, SWITCH) == STATE_ON)


async def test_missing_prerequisite_is_still_on(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """A strategy waiting for a prerequisite is on; unknown is unknown."""
    await sea.send(
        {"type": "update", "values": {"strategie_self_consumption": "missing"}}
    )
    await _until(lambda: _state(hass, "sensor.sea_strategy_pv_surplus") == "missing")
    assert _state(hass, SWITCH) == STATE_ON

    await sea.send({"type": "update", "values": {"strategie_self_consumption": None}})
    await _until(lambda: _state(hass, SWITCH) == STATE_UNKNOWN)


async def test_control_level_select(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """The control level can be selected."""
    assert _state(hass, SELECT) == "auto"

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "manual"},
        blocking=True,
    )
    assert sea.commands[-1] == {"key": "regelung", "value": "manual"}
    await _until(lambda: _state(hass, SELECT) == "manual")
    assert _state(hass, "sensor.sea_control_mode") == "manual"

    await sea.send({"type": "update", "values": {"regelung": "boost"}})
    await _until(lambda: _state(hass, SELECT) == STATE_UNKNOWN)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        pytest.param(400, "refused the command", id="refused"),
        pytest.param(500, "cannot be reached", id="unreachable"),
    ],
)
async def test_command_errors(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    sea: FakeSea,
    status: int,
    message: str,
) -> None:
    """A refused or failed command raises an error and changes nothing."""
    sea.command_status = status

    with pytest.raises(HomeAssistantError, match=message):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
        )
    assert _state(hass, SWITCH) == STATE_ON
