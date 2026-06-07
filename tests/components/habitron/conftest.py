"""Pytest fixtures for the Habitron integration."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN


def class_attr(cls: type, name: str) -> Any:
    """Read a HA ``_attr_<name>`` declared as a class attribute.

    HA's ``Entity`` base class re-exposes each ``_attr_*`` slot as a
    name-mangled property, so ``Cls._attr_x`` returns the property
    descriptor instead of the value. This helper resolves it by
    constructing an uninitialised instance and reading the attribute,
    which goes through the descriptor and returns the stored value.
    """
    instance = cls.__new__(cls)
    return getattr(instance, name)

from .const import (
    MOCK_CONFIG_DATA,
    MOCK_CONFIG_OPTIONS,
    MOCK_HOST,
    MOCK_HWTYPE,
    MOCK_MAC,
    MOCK_NAME,
    MOCK_UID,
    MOCK_VERSION,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable Habitron as a custom integration in every test."""
    return


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Build a ready-to-add Habitron config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_NAME,
        unique_id=MOCK_UID,
        data=MOCK_CONFIG_DATA,
        options=MOCK_CONFIG_OPTIONS,
    )


@pytest.fixture
def mock_habitron_client() -> Generator[MagicMock]:
    """Patch the ``habitron_client`` package surface used by the integration.

    ``test_connection`` is the connect-probe used by the config flow; the
    rest of the API surface (``HabitronClient``, IP helpers) is stubbed
    with no-op MagicMocks so the integration imports cleanly without a
    real hub.
    """
    with (
        patch(
            "custom_components.habitron.config_flow.test_connection",
            return_value=(True, MOCK_NAME),
        ) as mock_test,
        patch(
            "custom_components.habitron.config_flow._get_local_ip",
            return_value="192.168.1.10",
        ),
        patch(
            "custom_components.habitron.config_flow.ConfigFlow._discover_habitron",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "custom_components.habitron.communicate.get_own_ip",
            return_value="192.168.1.10",
        ),
        patch(
            "custom_components.habitron.communicate.get_host_ip",
            return_value=MOCK_HOST,
        ),
        patch(
            "custom_components.habitron.communicate.HabitronClient",
            autospec=True,
        ) as mock_client_cls,
    ):
        mock_client = mock_client_cls.return_value
        mock_client.host = MOCK_HOST
        mock_client.send_network_info = MagicMock()
        yield mock_test


@pytest.fixture
def mock_smart_hub_setup() -> Generator[MagicMock]:
    """Stub ``SmartHub.async_setup`` so config-entry tests don't touch the bus.

    Populates the SmartHub instance with the field set the rest of the
    integration expects after a real ``async_setup`` would have run.
    """

    async def _async_setup(self) -> None:
        self._mac = MOCK_MAC
        self.uid = MOCK_UID
        self._version = MOCK_VERSION
        self._type = MOCK_HWTYPE
        self.host = MOCK_HOST
        self.addon_slug = ""
        self.base_url = f"http://{MOCK_HOST}:7780"
        self.router.b_uid = MOCK_UID
        self.router.modules = []
        self.router.states = []

    with (
        patch(
            "custom_components.habitron.smart_hub.SmartHub.async_setup",
            new=_async_setup,
        ),
        patch(
            "homeassistant.components.frontend.add_extra_js_url",
        ),
    ):
        yield


@pytest.fixture
def mock_ws_provider() -> Generator[MagicMock]:
    """Patch the WebRTC provider so its constructor does not register globally.

    Also stubs ``async_register_websocket_handlers`` because it would
    install 15 WebSocket command handlers that hold references which can
    block the test event loop during teardown.
    """
    with (
        patch(
            "custom_components.habitron.ws_provider.async_register_webrtc_provider",
            return_value=MagicMock(),
        ) as mock_register,
        patch(
            "custom_components.habitron.ws_provider."
            "HabitronWebRTCProvider.async_register_websocket_handlers",
        ),
    ):
        yield mock_register


@pytest.fixture
def mock_coordinator_refresh() -> Generator[AsyncMock]:
    """Skip the first refresh so coordinator setup completes without a hub."""
    with patch(
        "homeassistant.helpers.update_coordinator."
        "DataUpdateCoordinator.async_config_entry_first_refresh",
        new=AsyncMock(),
    ) as mock:
        yield mock


@pytest.fixture
async def setup_homeassistant(hass: Any) -> None:
    """Load the ``homeassistant`` core component before every test.

    ``conversation`` (a transitive dependency via ``assist_pipeline``)
    expects ``hass.data['homeassistant.exposed_entities']`` to be
    populated by the core component's setup. Without it any test that
    causes habitron to attempt setup — even indirectly through
    listeners — fails on the dependency chain.
    """
    assert await async_setup_component(hass, "homeassistant", {})


@pytest.fixture
async def setup_integration(
    hass: Any,
    setup_homeassistant: None,
    mock_config_entry: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh: AsyncMock,
) -> MockConfigEntry:
    """Add and set up a Habitron config entry, returning the entry."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_config_entry
