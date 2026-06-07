"""Tests for the Habitron config flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from habitron_client import TimeoutException
import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.ssdp import (
    ATTR_UPNP_SERIAL,
    ATTR_UPNP_UDN,
    SsdpServiceInfo,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN

from .const import (
    MOCK_CONFIG_DATA,
    MOCK_HOST,
    MOCK_NAME,
    MOCK_SERIAL,
    MOCK_UDN,
    MOCK_UID,
)


async def test_user_flow_success(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh,
) -> None:
    """The manual user flow creates an entry when the hub responds."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG_DATA,
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_NAME
    assert result["data"] == MOCK_CONFIG_DATA


async def test_user_flow_cannot_connect(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
) -> None:
    """A failing connect probe surfaces ``cannot_connect``."""
    mock_habitron_client.return_value = (False, "")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG_DATA,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_invalid_interval(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
) -> None:
    """An interval below the allowed minimum is rejected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={**MOCK_CONFIG_DATA, "update_interval": 1},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "interval_too_short"}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
) -> None:
    """An identical config aborts with ``already_configured``.

    The user step falls back to ``habitron_{host}`` for the unique id
    when no UDP probe response arrives, so we register an existing
    entry with that same id to trigger the abort path.
    """
    MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_NAME,
        unique_id=f"habitron_{MOCK_HOST}",
        data=MOCK_CONFIG_DATA,
    ).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG_DATA,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_ssdp_discovery_with_udn(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh,
) -> None:
    """SSDP discovery prefers the UDN as unique id."""
    discovery = SsdpServiceInfo(
        ssdp_usn=f"{MOCK_UDN}::urn:habitron-com:device:SmartHub:1",
        ssdp_st="urn:habitron-com:device:SmartHub:1",
        ssdp_location=f"http://{MOCK_HOST}:80/desc.xml",
        upnp={ATTR_UPNP_UDN: MOCK_UDN},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_SSDP},
        data=discovery,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    # Confirm step
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == MOCK_UDN


async def test_ssdp_discovery_serial_fallback(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh,
) -> None:
    """When no UDN, the UPnP serialNumber is used."""
    discovery = SsdpServiceInfo(
        ssdp_usn="dummy::urn:habitron-com:device:SmartHub:1",
        ssdp_st="urn:habitron-com:device:SmartHub:1",
        ssdp_location=f"http://{MOCK_HOST}:80/desc.xml",
        upnp={ATTR_UPNP_SERIAL: MOCK_SERIAL},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_SSDP},
        data=discovery,
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    await hass.async_block_till_done()
    entry = result["result"]
    assert entry.unique_id == MOCK_SERIAL


async def test_ssdp_legacy_unique_id_migrated(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
) -> None:
    """A pre-existing host-based entry gets migrated on rediscovery."""
    legacy_entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_NAME,
        unique_id=f"habitron_{MOCK_HOST}",
        data=MOCK_CONFIG_DATA,
    )
    legacy_entry.add_to_hass(hass)

    discovery = SsdpServiceInfo(
        ssdp_usn=f"{MOCK_UDN}::urn:habitron-com:device:SmartHub:1",
        ssdp_st="urn:habitron-com:device:SmartHub:1",
        ssdp_location=f"http://{MOCK_HOST}:80/desc.xml",
        upnp={ATTR_UPNP_UDN: MOCK_UDN},
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_SSDP},
        data=discovery,
    )
    # Old host-based entry should already have been rewritten and the
    # flow aborted as "already configured" against the new id.
    await hass.async_block_till_done()
    assert legacy_entry.unique_id == MOCK_UDN
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_ssdp_no_host(
    hass: HomeAssistant,
    setup_homeassistant: None,
) -> None:
    """SSDP without a hostname is aborted."""
    discovery = SsdpServiceInfo(
        ssdp_usn="dummy",
        ssdp_st="urn:habitron-com:device:SmartHub:1",
        ssdp_location=None,
        upnp={},
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_SSDP},
        data=discovery,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_host_in_ssdp"


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (TimeoutException("timeout"), "cannot_connect"),
        (ConnectionRefusedError("refused"), "cannot_connect"),
    ],
)
async def test_user_flow_exception_mapping(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
    exception: Exception,
    expected: str,
) -> None:
    """Connection errors map to expected form errors."""
    mock_habitron_client.side_effect = exception

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input=MOCK_CONFIG_DATA,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_options_flow(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_config_entry: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh,
) -> None:
    """The options flow updates the entry's options."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    new_input = {
        "habitron_host": MOCK_HOST,
        "update_interval": 10,
        "websock_token": "test-token-not-real",  # noqa: S106
    }
    with patch.object(
        hass.config_entries, "async_reload", return_value=True
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=new_input
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
