"""Setup / unload / migration tests for the Habitron integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.services import SERVICE_HUB_RESTART


async def test_setup_entry(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A successful setup loads the entry and registers services."""
    entry = setup_integration
    assert entry.state is ConfigEntryState.LOADED
    # runtime_data is populated with the SmartHub instance
    assert entry.runtime_data is not None
    # Services are registered globally on the domain
    assert hass.services.has_service(DOMAIN, SERVICE_HUB_RESTART)


async def test_unload_entry(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Unloading the last entry tears down state and removes services."""
    entry = setup_integration
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    # Services are domain-global and removed only when the last entry is gone.
    assert not hass.services.has_service(DOMAIN, SERVICE_HUB_RESTART)


async def test_services_kept_while_other_entry_loaded(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh: AsyncMock,
) -> None:
    """A second loaded entry keeps services alive when the first unloads."""
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

    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    # Other entry still here → services must still be registered.
    assert hass.services.has_service(DOMAIN, SERVICE_HUB_RESTART)


async def test_update_listener_triggers_reload(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Updating entry options triggers an entry reload."""
    entry = setup_integration
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ) as mock_reload:
        hass.config_entries.async_update_entry(
            entry,
            options={**entry.options, "update_interval": 8},
        )
        await hass.async_block_till_done()
        mock_reload.assert_called_with(entry.entry_id)


async def test_setup_entry_timeout_marks_retry(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_config_entry: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_ws_provider: MagicMock,
) -> None:
    """A timeout during setup surfaces as SETUP_RETRY, not SETUP_ERROR."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.habitron.smart_hub.SmartHub.async_setup",
        side_effect=TimeoutError("hub silent"),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_async_remove_config_entry_device(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A device matching the hub UID cannot be removed standalone."""
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

    from custom_components.habitron import (  # noqa: PLC0415
        async_remove_config_entry_device,
    )

    entry = setup_integration
    smhub = entry.runtime_data
    dev_reg = dr.async_get(hass)
    hub_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, smhub.uid)},
        name="Hub",
    )
    # Hub device identifies the smhub itself → must NOT be removable.
    assert (
        await async_remove_config_entry_device(hass, entry, hub_device) is False
    ), f"Expected False; smhub.uid={smhub.uid!r}, identifiers={hub_device.identifiers!r}"

    other_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "some-other-uid")},
        name="Sub module",
    )
    assert (
        await async_remove_config_entry_device(hass, entry, other_device) is True
    )


async def test_setup_entry_connection_refused_marks_retry(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_config_entry: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_ws_provider: MagicMock,
) -> None:
    """A ``ConnectionRefusedError`` during setup surfaces as SETUP_RETRY."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.habitron.smart_hub.SmartHub.async_setup",
        side_effect=ConnectionRefusedError("hub refused"),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_oserror_marks_retry(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_config_entry: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_ws_provider: MagicMock,
) -> None:
    """A network-level ``OSError`` during setup surfaces as SETUP_RETRY."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "custom_components.habitron.smart_hub.SmartHub.async_setup",
        side_effect=OSError("network down"),
    ):
        assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_removes_stale_device(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_config_entry: MockConfigEntry,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh: AsyncMock,
) -> None:
    """``_async_cleanup_stale_devices`` removes registry entries for gone modules."""
    from homeassistant.helpers import device_registry as dr  # noqa: PLC0415

    mock_config_entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    stale = dev_reg.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, "stale-uid")},
        name="Gone module",
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert dev_reg.async_get(stale.id) is None
