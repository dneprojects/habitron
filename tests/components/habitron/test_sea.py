"""Tests for the Smart Energy Agent (SEA) add-on entry."""

import asyncio
from collections.abc import AsyncIterator, Callable, Generator
from typing import Any
from unittest.mock import patch

from habitron_client.sea import SeaCommandError, SeaError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.habitron import async_remove_config_entry_device
from custom_components.habitron.config_flow import ConfigFlow
from custom_components.habitron.const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_SEA
from custom_components.habitron.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from custom_components.habitron.sea import SEA_STRATEGIES
from homeassistant.config_entries import SOURCE_HASSIO, ConfigEntryState
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
HOST = "sea-addon"
PORT = 7790
PV = "sensor.sea_pv_forecast_today"
PLAN = "sensor.sea_battery_plan"
WINDOW = "sensor.sea_next_cheap_window"
COST = "sensor.sea_cost_today"
CHEAP = "binary_sensor.sea_cheap_now"
STRATEGY = "sensor.sea_strategy_pv_surplus"
SWITCH = "switch.sea_pv_surplus"
SELECT = "select.sea_control_mode"

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
    """Stand-in for the SEA add-on behind the habitron_client SeaClient."""

    def __init__(self) -> None:
        """Start with the full contract state."""
        self.info: dict[str, Any] = {
            "api_version": 1,
            "version": "0.16.0",
            "name": "Smart Energy Agent",
            "url": "homeassistant://app/sea",
        }
        self.state: dict[str, Any] = dict(STATE)
        self.token = TOKEN
        self.down = False
        self.commands: list[tuple[str, Any]] = []
        self.command_error: Exception | None = None
        self.connected = asyncio.Event()
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def client(self, _session: Any, host: str, port: int, token: str) -> FakeSea:
        """Act as the SeaClient constructor."""
        assert (host, port) == (HOST, PORT)
        self.used_token = token
        return self

    def _check(self) -> None:
        if self.down or self.used_token != self.token:
            raise SeaError("unreachable")

    async def get_info(self) -> dict[str, Any]:
        """Return the info."""
        self._check()
        return dict(self.info)

    async def get_state(self) -> dict[str, Any]:
        """Return the state."""
        self._check()
        return dict(self.state)

    async def command(self, key: str, value: Any) -> None:
        """Apply a command and push the new state."""
        self._check()
        self.commands.append((key, value))
        if self.command_error is not None:
            raise self.command_error
        self.state[key] = (
            ("ready" if value else "off") if key.startswith("strategie_") else value
        )
        await self.send({"type": "update", "values": {key: self.state[key]}})

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        """Yield a snapshot, then pushed messages until dropped."""
        self._check()
        self.connected.set()
        yield {"type": "snapshot", "values": dict(self.state)}
        while (message := await self._queue.get()) is not None:
            yield message
        raise SeaError("ws: connection closed")

    async def send(self, message: dict[str, Any]) -> None:
        """Push a message."""
        await self._queue.put(message)

    async def drop(self) -> None:
        """End the connection."""
        self.connected.clear()
        await self._queue.put(None)


@pytest.fixture
def sea(hass: HomeAssistant) -> Generator[FakeSea]:
    """Replace the SEA client and retry reconnects without waiting."""
    fake = FakeSea()
    with (
        patch("custom_components.habitron.sea.SeaClient", fake.client),
        patch("custom_components.habitron.config_flow.SeaClient", fake.client),
        patch("custom_components.habitron.sea._RETRY_MIN", 0),
    ):
        yield fake


def _sea_entry(token: str = TOKEN) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Smart Energy Agent",
        unique_id="sea",
        version=2,
        data={
            CONF_ENTRY_TYPE: ENTRY_TYPE_SEA,
            CONF_HOST: HOST,
            CONF_PORT: PORT,
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
    hass: HomeAssistant, setup_homeassistant: None, sea: FakeSea
) -> MockConfigEntry:
    """Set up the SEA entry."""
    entry = _sea_entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await asyncio.wait_for(sea.connected.wait(), 10)
    return entry


def _discovery(token: str = TOKEN) -> HassioServiceInfo:
    return HassioServiceInfo(
        config={"sea": {CONF_HOST: HOST, CONF_PORT: PORT, CONF_TOKEN: token}},
        name="Smart Energy Agent",
        slug="sea",
        uuid="1234",
    )


@pytest.mark.usefixtures("setup_homeassistant", "sea")
async def test_discovery_creates_the_entry(hass: HomeAssistant) -> None:
    """The add-on discovery leads to a confirmed SEA entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery()
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Smart Energy Agent"
    assert result["data"] == {
        CONF_ENTRY_TYPE: ENTRY_TYPE_SEA,
        CONF_HOST: HOST,
        CONF_PORT: PORT,
        CONF_TOKEN: TOKEN,
    }
    assert result["result"].unique_id == "sea"


@pytest.mark.usefixtures("setup_homeassistant", "sea")
async def test_discovery_with_a_wrong_token_cannot_connect(
    hass: HomeAssistant,
) -> None:
    """A rejected token shows an error instead of creating the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery(token="wrong")
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_rediscovery_updates_the_entry(
    hass: HomeAssistant, sea_entry: MockConfigEntry
) -> None:
    """A new discovery updates host, port and token of the existing entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=_discovery(token="b" * 64)
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert sea_entry.data[CONF_TOKEN] == "b" * 64


async def test_entities(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """The entry creates the device SEA with the entities of the contract."""
    device = device_registry.async_get_device({(DOMAIN, "sea")})
    assert device == snapshot(name="device")
    entities = er.async_entries_for_config_entry(entity_registry, sea_entry.entry_id)
    assert len(entities) == 37
    for entity in sorted(entities, key=lambda entity: entity.entity_id):
        assert entity == snapshot(name=f"{entity.entity_id}-entry")
        assert hass.states.get(entity.entity_id) == snapshot(
            name=f"{entity.entity_id}-state"
        )


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
    """Messages without values or of another type change nothing."""
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
    """After a lost connection the reconnect brings fresh values and info."""
    sea.info["version"] = "0.17.0"
    sea.state["pv_prognose_heute"] = 13.0
    await sea.drop()

    await asyncio.wait_for(sea.connected.wait(), 10)
    await _until(lambda: _state(hass, PV) == "13.0")
    device = device_registry.async_get_device({(DOMAIN, "sea")})
    assert device.sw_version == "0.17.0"


async def test_entities_unavailable_while_the_add_on_is_down(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """While SEA is down the entities are unavailable, then come back."""
    sea.down = True
    await sea.drop()
    await _until(lambda: _state(hass, PV) == STATE_UNAVAILABLE)

    sea.down = False
    await asyncio.wait_for(sea.connected.wait(), 10)
    await _until(lambda: _state(hass, PV) == "12.4")


@pytest.mark.usefixtures("setup_homeassistant", "sea")
async def test_unreachable_add_on_retries_the_setup(hass: HomeAssistant) -> None:
    """A rejected token or a missing add-on lets HA retry the setup."""
    entry = _sea_entry(token="wrong")
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload(hass: HomeAssistant, sea_entry: MockConfigEntry) -> None:
    """Unloading stops the listener and the entities."""
    assert await hass.config_entries.async_unload(sea_entry.entry_id)
    await hass.async_block_till_done()

    assert sea_entry.state is ConfigEntryState.NOT_LOADED
    assert _state(hass, PV) == STATE_UNAVAILABLE


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


async def test_strategy_states(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """Each strategy is an enum sensor that follows the pushed state."""
    await sea.send(
        {"type": "update", "values": {"strategie_self_consumption": "acting"}}
    )
    await _until(lambda: _state(hass, STRATEGY) == "acting")
    assert _state(hass, "sensor.sea_strategy_optimizer") == "ready"


async def test_strategy_switches(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """A switch sends the command; the state follows the push update."""
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
    )
    assert sea.commands[-1] == ("strategie_self_consumption", False)
    await _until(lambda: _state(hass, SWITCH) == STATE_OFF)
    assert _state(hass, STRATEGY) == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": SWITCH}, blocking=True
    )
    assert sea.commands[-1] == ("strategie_self_consumption", True)
    await _until(lambda: _state(hass, SWITCH) == STATE_ON)


async def test_missing_prerequisite_is_still_on(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """A strategy waiting for a prerequisite is on; unknown is unknown."""
    await sea.send(
        {"type": "update", "values": {"strategie_self_consumption": "missing"}}
    )
    await _until(lambda: _state(hass, STRATEGY) == "missing")
    assert _state(hass, SWITCH) == STATE_ON

    await sea.send({"type": "update", "values": {"strategie_self_consumption": None}})
    await _until(lambda: _state(hass, SWITCH) == STATE_UNKNOWN)


async def test_control_level_select(
    hass: HomeAssistant, sea_entry: MockConfigEntry, sea: FakeSea
) -> None:
    """The control level can be selected."""
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "manual"},
        blocking=True,
    )
    assert sea.commands[-1] == ("regelung", "manual")
    await _until(lambda: _state(hass, SELECT) == "manual")

    await sea.send({"type": "update", "values": {"regelung": "boost"}})
    await _until(lambda: _state(hass, SELECT) == STATE_UNKNOWN)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        pytest.param(SeaCommandError("nope"), "refused the command", id="refused"),
        pytest.param(SeaError("down"), "cannot be reached", id="unreachable"),
    ],
)
async def test_command_errors(
    hass: HomeAssistant,
    sea_entry: MockConfigEntry,
    sea: FakeSea,
    error: Exception,
    message: str,
) -> None:
    """A refused or failed command raises an error and changes nothing."""
    sea.command_error = error

    with pytest.raises(HomeAssistantError, match=message):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": SWITCH}, blocking=True
        )
    assert _state(hass, SWITCH) == STATE_ON
