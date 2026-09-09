"""Setup / unload / migration tests for the Habitron integration."""

from collections.abc import Awaitable, Callable
import logging
from unittest.mock import AsyncMock, MagicMock, patch

from habitron_client import Router, SmartController
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.habitron import (
    _async_migrate_unique_ids,
    _legacy_suffixed_sensor_uid,
    _uid_scheme_rule,
    async_remove_config_entry_device,
    async_unload_entry,
)
from custom_components.habitron.const import DOMAIN, KEY_TOKEN
from custom_components.habitron.services import SERVICE_HUB_RESTART
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import MOCK_HOST


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


async def test_migrate_v1_entry_renames_the_host_key(
    hass: HomeAssistant,
    setup_homeassistant: None,
    mock_habitron_client: MagicMock,
    mock_smart_hub_setup: None,
    mock_ws_provider: MagicMock,
    mock_coordinator_refresh: AsyncMock,
) -> None:
    """A v1 entry keeps working: the host key is renamed, the token stays.

    ``update_interval`` goes: the coordinator has used a fixed SCAN_INTERVAL
    since long before this, so the key is dead weight in the entry.

    Entries created before 3.2.0 store the host under the integration-specific
    ``habitron_host`` key; core expects ``CONF_HOST``. Nobody should have to set
    the hub up again for that. The websocket token is untouched -- it is still
    used for the SmartController Touch and Assist connection.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Habitron",
        unique_id="hub-1",
        version=1,
        data={"habitron_host": MOCK_HOST, KEY_TOKEN: "tok", "update_interval": 10},
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.version == 2
    assert entry.data == {CONF_HOST: MOCK_HOST, KEY_TOKEN: "tok"}
    assert entry.state is ConfigEntryState.LOADED


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
            options={**entry.options, "websock_token": "rotated-token"},
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

    entry = setup_integration
    smhub = entry.runtime_data
    dev_reg = dr.async_get(hass)
    hub_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, smhub.uid)},
        name="Hub",
    )
    # Hub device identifies the smhub itself → must NOT be removable.
    assert await async_remove_config_entry_device(hass, entry, hub_device) is False, (
        f"Expected False; smhub.uid={smhub.uid!r}, identifiers={hub_device.identifiers!r}"
    )

    other_device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "some-other-uid")},
        name="Sub module",
    )
    assert await async_remove_config_entry_device(hass, entry, other_device) is True


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


async def test_unload_entry_returns_false_when_platform_unload_fails(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """A failing platform-unload propagates as False without touching state."""

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        return_value=False,
    ):
        ok = await async_unload_entry(hass, setup_integration)
    assert ok is False


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


async def test_touch_module_creates_webrtc_platform_entities(
    hass: HomeAssistant,
    real_setup: Callable[..., Awaitable[tuple[MockConfigEntry, AsyncMock]]],
) -> None:
    """A Smart Controller Touch module wires up the HACS WebRTC platforms.

    Drives a full config-entry setup whose bus model holds one Touch module and
    asserts the camera, media_player and assist_satellite entities are created
    for it — the HACS-only feature platforms that depend on the ws provider.
    """
    module = SmartController(
        uid="MOD-T",
        addr=104,
        typ=b"\x01\x04",
        name="Touch",
        mod_type="Smart Controller Touch",
    )
    router = Router(uid="rt_1", id=100)
    router.modules = [module]

    entry, _client = await real_setup(router)

    ent_reg = er.async_get(hass)
    domains = {
        e.domain for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    }
    assert {"camera", "media_player", "assist_satellite"} <= domains


def _register(
    ent_reg: er.EntityRegistry,
    entry: MockConfigEntry,
    unique_id: str,
    domain: str = "sensor",
) -> er.RegistryEntry:
    """Put an entity into the registry under ``unique_id``."""
    return ent_reg.async_get_or_create(
        domain, DOMAIN, unique_id, config_entry=entry, suggested_object_id=unique_id
    )


async def test_migrate_unique_ids_renames_a_matching_entity(
    hass: HomeAssistant,
) -> None:
    """A rule's answer becomes the entity's unique_id, entity_id kept."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    existing = _register(ent_reg, entry, "Mod_MOD-1_snsr0_humidity")

    _async_migrate_unique_ids(hass, entry, (_legacy_suffixed_sensor_uid,))

    assert ent_reg.async_get(existing.entity_id).unique_id == "Mod_MOD-1_snsr0"


async def test_migrate_unique_ids_removes_the_stale_duplicate(
    hass: HomeAssistant,
) -> None:
    """When both ids exist, the one being migrated away from goes.

    Home Assistant refuses a duplicate unique_id, and the entity already
    carrying the target is the one the platform is about to claim -- so the
    stale entry has to be removed rather than renamed onto it.
    """
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    target = _register(ent_reg, entry, "Mod_MOD-1_snsr0")
    stale = _register(ent_reg, entry, "Mod_MOD-1_snsr0_humidity")

    _async_migrate_unique_ids(hass, entry, (_legacy_suffixed_sensor_uid,))

    assert ent_reg.async_get(stale.entity_id) is None
    assert ent_reg.async_get(target.entity_id).unique_id == "Mod_MOD-1_snsr0"


async def test_migrate_unique_ids_leaves_everything_else_alone(
    hass: HomeAssistant,
) -> None:
    """An id no rule answers for is untouched, and a second pass is a no-op."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    # A router stream: the key suffix is what keeps it distinct, so it stays.
    router = _register(ent_reg, entry, "Mod_RT-1_snsr0_current")
    other = _register(ent_reg, entry, "MOD-1_output_3", domain="switch")

    for _ in range(2):
        _async_migrate_unique_ids(hass, entry, (_legacy_suffixed_sensor_uid,))

    assert ent_reg.async_get(router.entity_id).unique_id == "Mod_RT-1_snsr0_current"
    assert ent_reg.async_get(other.entity_id).unique_id == "MOD-1_output_3"


async def test_migrate_unique_ids_takes_the_first_rule_that_answers(
    hass: HomeAssistant,
) -> None:
    """Rules are tried in order; the first answer wins and the rest are skipped."""
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    existing = _register(ent_reg, entry, "Mod_MOD-1_snsr0_humidity")

    _async_migrate_unique_ids(
        hass,
        entry,
        (
            lambda ent: None,
            lambda ent: "Mod_MOD-1_first",
            lambda ent: "Mod_MOD-1_second",
        ),
    )

    assert ent_reg.async_get(existing.entity_id).unique_id == "Mod_MOD-1_first"


def _model_for_migration() -> MagicMock:
    """A hub whose members carry the names the id mapping keys on."""

    def member(name: str, nmbr: int) -> MagicMock:
        m = MagicMock()
        m.name = name
        m.nmbr = nmbr
        return m

    module = MagicMock()
    module.uid = "MOD-1"
    module.sensors = [member("Temperature", 0), member("Humidity", 1)]
    router = MagicMock()
    router.uid = "RT-1"
    router.modules = [module]
    smhub = MagicMock()
    smhub.uid = "HUB-1"
    smhub.router = router
    smhub.sensors = [member("Memory free", 0), member("Disk free", 1)]
    smhub.diags = [member("CPU Frequency", 0)]
    return smhub


@pytest.mark.parametrize(
    ("old", "new", "domain"),
    [
        # the readings whose old id said nothing about what they were
        ("Mod_MOD-1_snsr0", "MOD-1_temperature", "sensor"),
        ("Mod_MOD-1_snsr1", "MOD-1_humidity", "sensor"),
        ("Mod_HUB-1_snsr0", "HUB-1_cpu_frequency", "sensor"),
        ("Mod_HUB-1_perc0", "HUB-1_memory_usage", "sensor"),
        ("Mod_HUB-1_perc1", "HUB-1_disk_usage", "sensor"),
        ("Mod_HUB-1_dperc0", "HUB-1_cpu_load", "sensor"),
        # abbreviations and display names
        ("Mod_MOD-1_adin0", "MOD-1_analog_in_0", "sensor"),
        ("Mod_MOD-1_ekey_ident", "MOD-1_ekey_identifier", "sensor"),
        ("Mod_MOD-1_ekey_ident_name", "MOD-1_ekey_user_name", "sensor"),
        ("Mod_MOD-1_ekey_fngr", "MOD-1_ekey_finger", "sensor"),
        ("Mod_MOD-1_ekey_fngr_ident", "MOD-1_ekey_finger_name", "sensor"),
        ("Mod_MOD-1_PowerTemp", "MOD-1_power_temperature", "sensor"),
        ("Mod_HUB-1_CPU Temperature", "HUB-1_cpu_temperature", "sensor"),
        ("Mod_MOD-1_snsr0_current", "MOD-1_current_0", "sensor"),
        ("Mod_MOD-1_logic0", "MOD-1_logic_0", "sensor"),
        # the prefixes that said "module" for the router and the hub
        ("Rt_RT-1_restart_all", "RT-1_restart_all_modules", "button"),
        ("Rt_RT-1_powcyc2", "RT-1_power_cycle_2", "button"),
        ("Hub_HUB-1_reboot", "HUB-1_reboot", "button"),
        ("Hub_HUB-1_Logginglevelconsole", "HUB-1_log_level_console", "select"),
        ("Rt_RT-1_group_0_alarm_mode", "RT-1_group_0_alarm_mode", "select"),
        ("mod_MOD-1_app_update", "MOD-1_app_update", "update"),
        ("Mod_MOD-1_update", "MOD-1_firmware_update", "update"),
        # display names with spaces
        ("Mod_MOD-1_Activate voice input", "MOD-1_activate_voice_input", "button"),
        ("Mod_MOD-1_Climate Controller 2", "MOD-1_climate_controller_2", "switch"),
        ("Mod_MOD-1_Microphone Mode", "MOD-1_microphone_mode", "switch"),
        # the ASCII-digit offset that was never applied as one
        ("Mod_MOD-1_number48", "MOD-1_set_temperature_1", "number"),
        ("Mod_MOD-1_number49", "MOD-1_set_temperature_2", "number"),
        # plain renames
        ("Mod_MOD-1_out3", "MOD-1_output_3", "switch"),
        ("Mod_MOD-1_rgbled1", "MOD-1_rgb_led_1", "light"),
        ("Mod_MOD-1_cover2", "MOD-1_cover_2", "cover"),
        ("Mod_MOD-1_in7", "MOD-1_input_7", "binary_sensor"),
        ("Mod_MOD-1_evnt4", "MOD-1_event_4", "event"),
        ("Mod_MOD-1_u12", "MOD-1_ekey_user_12", "event"),
        ("Mod_MOD-1_mediaplayer", "MOD-1_media_player", "media_player"),
        ("Mod_MOD-1_assist_sat", "MOD-1_assist_satellite", "assist_satellite"),
        ("Mod_MOD-1_message", "MOD-1_message", "text"),
    ],
)
async def test_uid_scheme_rule_maps_every_old_form(
    hass: HomeAssistant, old: str, new: str, domain: str
) -> None:
    """Each id this integration ever wrote lands on the current scheme.

    These are what the four known installations carry. A wrong mapping does not
    fail loudly -- it registers a second entity and leaves the first orphaned,
    taking its history and customisations with it.
    """
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    existing = _register(ent_reg, entry, old, domain=domain)

    _async_migrate_unique_ids(hass, entry, (_uid_scheme_rule(_model_for_migration()),))

    assert ent_reg.async_get(existing.entity_id).unique_id == new


async def test_uid_scheme_rule_is_a_no_op_on_the_second_run(
    hass: HomeAssistant,
) -> None:
    """Nothing is rewritten once the ids are already current.

    This is what the warning's count reports: non-zero on the update, zero on
    every start after it.
    """
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    current = _register(ent_reg, entry, "MOD-1_temperature")
    rule = _uid_scheme_rule(_model_for_migration())

    for _ in range(2):
        _async_migrate_unique_ids(hass, entry, (rule,))

    assert ent_reg.async_get(current.entity_id).unique_id == "MOD-1_temperature"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Mod_MOD-1_sms01701234", "MOD-1_sms_01701234"),
        ("Mod_MOD-1_sms+491701234", "MOD-1_sms_+491701234"),
        ("Mod_MOD-1_smsChef", "MOD-1_sms_Chef"),
    ],
)
async def test_sms_ids_migrate_whatever_the_number_is_called(
    hass: HomeAssistant, old: str, new: str
) -> None:
    """The SMS suffix is the number's name, not a counter.

    It is the GSM number's label with spaces and hyphens stripped, so it can be
    an international number with a "+" or a plain word. A rule expecting digits
    left those entities behind while the platform registered new ones beside
    them.
    """
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    existing = _register(ent_reg, entry, old, domain="notify")

    _async_migrate_unique_ids(hass, entry, (_uid_scheme_rule(_model_for_migration()),))

    assert ent_reg.async_get(existing.entity_id).unique_id == new


async def test_an_unmapped_old_id_is_reported(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """An id in the old shape that no rule claims must not pass silently.

    It would stay behind while the platform registers a new entity next to it --
    exactly the failure the SMS rule had, and one nothing else would reveal.
    """
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    _register(ent_reg, entry, "Mod_MOD-1_SomethingNobodyMapped", domain="sensor")

    with caplog.at_level(logging.WARNING):
        _async_migrate_unique_ids(
            hass, entry, (_uid_scheme_rule(_model_for_migration()),)
        )

    assert "no id migration for Mod_MOD-1_SomethingNobodyMapped" in caplog.text


@pytest.mark.parametrize(
    "old",
    [
        "Mod_MOD-1_Climate Contoller 2",
        "Mod_MOD-1_Climate Controller 2",
    ],
    ids=["as it shipped", "after the name was corrected"],
)
async def test_both_climate_controller_spellings_migrate(
    hass: HomeAssistant, old: str
) -> None:
    """The misspelt id has to be carried over too.

    ``Climate Contoller 2`` shipped until the display name was corrected. The
    id was built from that name, so the correction silently changed it and
    every installation from before still carries the misspelt one -- dead since
    then, and invisible until the migration started reporting what it could not
    map.
    """
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    existing = _register(ent_reg, entry, old, domain="switch")

    _async_migrate_unique_ids(hass, entry, (_uid_scheme_rule(_model_for_migration()),))

    assert (
        ent_reg.async_get(existing.entity_id).unique_id == "MOD-1_climate_controller_2"
    )


async def test_the_old_display_notify_is_revived(hass: HomeAssistant) -> None:
    """The "Messages" entity removed in v2.10.0 gets its entry back.

    Its notify target was dropped when the text entity arrived, so those
    registry entries have been orphaned since. Mapping the old id onto the new
    one hands the user back the entity they had, with its name and
    customisations, instead of putting a fresh one beside a dead one.

    The bare form is what is actually in the field: the v3.3.0 rename already
    stripped the ``Mod_`` prefix off these, and looking only for the prefixed
    spelling is what let the first attempt at this miss them entirely.
    """
    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    existing = _register(ent_reg, entry, "MOD-1_msg", domain="notify")

    _async_migrate_unique_ids(hass, entry, (_uid_scheme_rule(_model_for_migration()),))

    assert ent_reg.async_get(existing.entity_id).unique_id == "MOD-1_message"
