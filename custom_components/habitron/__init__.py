"""The Habitron integration."""

from collections.abc import Callable, Iterable
import logging
import re
from typing import Any, Final

from habitron_client import HabitronError, HabitronTimeoutError

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN
from .coordinator import HabitronConfigEntry
from .health import async_setup_module_health_issues
from .services import async_remove_services, async_setup_services
from .smart_hub import SmartHub
from .system_health import system_health_info  # noqa: F401
from .ws_provider import HabitronWebRTCProvider

_LOGGER = logging.getLogger(__name__)

# Per-module described-sensor keys that Beta 3.1.0b1 wrongly appended to the
# unique_id; see _async_restore_legacy_sensor_ids.
_LEGACY_SUFFIXED_KEYS = ("humidity", "illuminance", "wind", "airquality")
_LEGACY_UID_RE = re.compile(
    r"^(Mod_.+_snsr\d+)_(?:" + "|".join(_LEGACY_SUFFIXED_KEYS) + r")$"
)

# A rule answers with the unique_id an existing entity should carry, or
# ``None`` when it does not apply. Keeping them in a list means a later rename
# is one rule plus its test, not another migration pass of its own.
type UniqueIdRule = Callable[[er.RegistryEntry], str | None]

PLATFORMS: list[Platform] = [
    Platform.ASSIST_SATELLITE,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.UPDATE,
]


async def async_migrate_entry(hass: HomeAssistant, entry: HabitronConfigEntry) -> bool:
    """Migrate an old config entry.

    Version 1 stored the host under the integration-specific ``habitron_host``
    key; version 2 uses Home Assistant's shared ``CONF_HOST``, matching what the
    core integration expects. Rename it in place so nobody has to set the hub
    up again -- the websocket token stays, it is still used for the
    SmartController Touch and Assist connection.
    """
    if entry.version == 1:
        data = {**entry.data}
        if "habitron_host" in data:
            data[CONF_HOST] = data.pop("habitron_host")
        # ``update_interval`` was dropped when the coordinator moved to a fixed
        # SCAN_INTERVAL; nothing has read it since, so it does not need to be
        # carried along.
        data.pop("update_interval", None)
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HabitronConfigEntry) -> bool:
    """Set up Habitron from a config entry."""
    try:
        smhub = SmartHub(hass, entry)
        await smhub.async_setup()
        # Central first refresh — done once here instead of per platform.
        await smhub.coordinator.async_config_entry_first_refresh()

        provider = HabitronWebRTCProvider(hass, smhub.router)
        smhub.ws_provider = provider
        provider.async_register_websocket_handlers()

        entry.runtime_data = smhub
        entry.async_on_unload(entry.add_update_listener(update_listener))

        _async_cleanup_stale_devices(hass, entry, smhub)

        # Before the platforms register anything, so an entity comes up
        # under its final id and no duplicate is ever created.
        _async_migrate_unique_ids(
            hass, entry, (*_UNIQUE_ID_RULES, _uid_scheme_rule(smhub))
        )

        # Mirror per-module operate-mode faults (SYS_ERR) into repairs issues.
        async_setup_module_health_issues(hass, entry, smhub)

        # Services live on the domain, not on the entry. The helper is
        # idempotent so subsequent entries are a no-op.
        async_setup_services(hass)

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    except (TimeoutError, HabitronTimeoutError) as ex:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connect_timeout",
        ) from ex
    except ConnectionRefusedError as ex:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connect_refused",
            translation_placeholders={"error": str(ex)},
        ) from ex
    except (OSError, ConnectionError, HabitronError) as ex:
        # Any transient SmartHub problem at setup — a dropped connection or
        # incomplete data while the hub is (re)booting (HabitronConnectionError
        # / HabitronProtocolError), DNS/socket errors — must let HA retry the
        # entry. Otherwise a brief hub outage at setup leaves the integration
        # permanently down until a manual reload. Programming errors such as
        # AttributeError/KeyError still propagate (they are not HabitronError)
        # so they surface in the logs instead of being masked as a retry loop.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="connect_error",
            translation_placeholders={"error": str(ex)},
        ) from ex
    else:
        return True


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: HabitronConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Remove a config entry from a device."""
    smhub = config_entry.runtime_data
    return not any(
        identifier
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN and identifier[1] == smhub.uid
    )


async def async_unload_entry(hass: HomeAssistant, entry: HabitronConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    smhub = entry.runtime_data
    if smhub.ws_provider is not None:
        smhub.ws_provider.async_close()
    await smhub.async_close()

    # Services are registered globally on DOMAIN, not per entry. Only
    # tear them down once the last loaded hub is gone, otherwise a
    # remaining hub would lose its services. ``async_loaded_entries``
    # excludes the entry currently being unloaded.
    if not hass.config_entries.async_loaded_entries(DOMAIN):
        async_remove_services(hass)

    return True


async def update_listener(hass: HomeAssistant, entry: HabitronConfigEntry) -> None:
    """Handle options update by reloading the config entry."""
    # Reload unconditionally so host, interval and token changes are picked up
    # via the normal setup path.
    await hass.config_entries.async_reload(entry.entry_id)


def _async_cleanup_stale_devices(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    smhub: SmartHub,
) -> None:
    """Remove device-registry entries whose Habitron module is gone.

    Run after ``smhub.async_setup`` populates ``router.modules``. The
    hub device and the router device are kept; everything else identified
    by ``(DOMAIN, <some uid>)`` is removed if that uid is no longer in
    the router's current module list.
    """
    keep_uids: set[str] = {smhub.uid, smhub.router.uid}
    keep_uids.update(getattr(module, "uid", "") for module in smhub.router.modules)
    keep_uids.discard("")

    dev_reg = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN and identifier[1] not in keep_uids:
                dev_reg.async_remove_device(device.id)
                break


def _legacy_suffixed_sensor_uid(ent: er.RegistryEntry) -> str | None:
    """Undo the Beta 3.1.0b1 per-module sensor unique_id churn.

    3.1.0b1 appended the description ``key`` to every described sensor's
    unique_id, including per-module humidity/illuminance/wind/airquality whose
    ``nmbr`` was already unique. That changed their unique_id, so Home Assistant
    registered fresh entities and (under 2026.6) rewrote the entity_ids
    (``sensor.<area>_<device>_<name>``). The suffix is now restricted to the
    colliding router streams (current/voltage/timeout), so realign the
    per-module sensors with the original ``Mod_{uid}_snsr{nmbr}`` id.
    """
    if ent.domain != "sensor":
        return None
    match = _LEGACY_UID_RE.match(ent.unique_id or "")
    return match.group(1) if match else None


_UNIQUE_ID_RULES: tuple[UniqueIdRule, ...] = (_legacy_suffixed_sensor_uid,)


# Every entity id this integration ever wrote, mapped onto the scheme the core
# integration uses: ``{device uid}_{key}``, lower case, no prefix. The old ids
# grew a ``Mod_``/``Rt_``/``Hub_`` prefix that said module even for the router
# and the hub, and keys that were abbreviations or display names with spaces.
_UID_REWRITES: Final = [
    (re.compile(r"^Mod_(?P<u>.+)_ekey_ident_name$"), "{u}_ekey_user_name"),
    (re.compile(r"^Mod_(?P<u>.+)_ekey_fngr_ident$"), "{u}_ekey_finger_name"),
    (re.compile(r"^Mod_(?P<u>.+)_ekey_ident$"), "{u}_ekey_identifier"),
    (re.compile(r"^Mod_(?P<u>.+)_ekey_fngr$"), "{u}_ekey_finger"),
    (re.compile(r"^Mod_(?P<u>.+)_adin(?P<n>\d+)$"), "{u}_analog_in_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_logic(?P<n>\d+)$"), "{u}_logic_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_module_status$"), "{u}_module_status"),
    (re.compile(r"^Mod_(?P<u>.+)_dperc\d+$"), "{u}_cpu_load"),
    (re.compile(r"^Mod_(?P<u>.+)_CPU Temperature$"), "{u}_cpu_temperature"),
    (re.compile(r"^Mod_(?P<u>.+)_PowerTemp$"), "{u}_power_temperature"),
    (
        re.compile(r"^Mod_(?P<u>.+)_snsr\d+_(?P<k>current|voltage|timeout)$"),
        "{u}_{k}_0",
    ),
    (re.compile(r"^Mod_(?P<u>.+)_client_(?P<k>.+)$"), "{u}_client_{k}"),
    # buttons
    (re.compile(r"^Mod_(?P<u>.+)_ccmd(?P<n>\d+)$"), "{u}_collective_command_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_dcmd(?P<n>\d+)$"), "{u}_direct_command_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_vcmd(?P<n>\d+)$"), "{u}_vis_command_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_cntup(?P<n>\d+)$"), "{u}_counter_up_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_cntdown(?P<n>\d+)$"), "{u}_counter_down_{n}"),
    (re.compile(r"^Rt_(?P<u>.+)_powcyc(?P<n>\d+)$"), "{u}_power_cycle_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_restartfwdtable$"), "{u}_restart_forward_table"),
    (re.compile(r"^Rt_(?P<u>.+)_restart_all$"), "{u}_restart_all_modules"),
    (re.compile(r"^Mod_(?P<u>.+)_Activate voice input$"), "{u}_activate_voice_input"),
    # switch / light / cover / number / binary_sensor
    # "Contoller" is not a typo in this pattern: that spelling shipped until the
    # display name was corrected, and the id was built from that name at the
    # time -- so the correction silently changed the id and every installation
    # from before it still carries the misspelt one, dead ever since.
    (
        re.compile(r"^Mod_(?P<u>.+)_Climate Cont(?:r)?oller 2$"),
        "{u}_climate_controller_2",
    ),
    (re.compile(r"^Mod_(?P<u>.+)_Microphone Mode$"), "{u}_microphone_mode"),
    (re.compile(r"^Mod_(?P<u>.+)_out(?P<n>\d+)$"), "{u}_output_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_rgbled(?P<n>\d+)$"), "{u}_rgb_led_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_led(?P<n>\d+)$"), "{u}_led_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_flag(?P<n>\d+)$"), "{u}_flag_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_cover(?P<n>\d+)$"), "{u}_cover_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_state(?P<n>\d+)$"), "{u}_state_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_in(?P<n>\d+)$"), "{u}_input_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_evnt(?P<n>\d+)$"), "{u}_event_{n}"),
    (re.compile(r"^Mod_(?P<u>.+)_u(?P<n>\d+)$"), "{u}_ekey_user_{n}"),
    # Not ``\d+``: the suffix is the GSM number's name with spaces and hyphens
    # stripped, so it can carry a "+" or be a plain label like "Chef".
    (re.compile(r"^Mod_(?P<u>.+)_sms(?P<n>.+)$"), "{u}_sms_{n}"),
    # select / update / misc
    (re.compile(r"^Rt_(?P<u>.+)_group_0_(?P<k>.+)$"), "{u}_group_0_{k}"),
    (
        re.compile(r"^Hub_(?P<u>.+)_Logginglevel(?P<k>console|file)$"),
        "{u}_log_level_{k}",
    ),
    (re.compile(r"^Hub_(?P<u>.+)_(?P<k>restart|reboot)$"), "{u}_{k}"),
    (re.compile(r"^mod_(?P<u>.+)_app_update$"), "{u}_app_update"),
    (re.compile(r"^Mod_(?P<u>.+)_update$"), "{u}_firmware_update"),
    # The display notify was removed in v2.10.0 and is back; its entries have
    # been orphaned ever since, so this revives them with whatever the user had
    # named and customised rather than leaving a dead one beside a new one.
    (re.compile(r"^Mod_(?P<u>.+)_msg$"), "{u}_message"),
    (re.compile(r"^Mod_(?P<u>.+)_mediaplayer$"), "{u}_media_player"),
    (re.compile(r"^Mod_(?P<u>.+)_assist_sat$"), "{u}_assist_satellite"),
    # anything else that only carried the prefix
    (re.compile(r"^Mod_(?P<u>.+)_(?P<k>[a-z0-9_]+)$"), "{u}_{k}"),
]

# The set-value number used ``48 + nmbr`` -- an ASCII digit offset that was
# never applied as one -- while the bus and the hub's own screen count from 1.
_SET_VALUE_RE: Final = re.compile(r"^Mod_(?P<u>.+)_number(?P<n>\d+)$")

# ``snsr<n>`` and ``perc<n>`` do not say which reading they are; only the bus
# model does. It is built by the time this runs.
_MEMBER_KEYS: Final = {
    "Temperature": "temperature",
    "Temperature ext.": "temperature_external",
    "Humidity": "humidity",
    "Illuminance": "illuminance",
    "Wind": "wind",
    "Windpeak": "wind_peak",
    "Airquality": "airquality",
    "Memory free": "memory_usage",
    "Disk free": "disk_usage",
    "CPU Frequency": "cpu_frequency",
    "CPU load": "cpu_load",
    "CPU Temperature": "cpu_temperature",
}


def _uid_scheme_rule(smhub: SmartHub) -> UniqueIdRule:
    """Return a rule mapping the grown ids onto the current scheme."""
    by_uid: dict[str, Any] = {smhub.uid: smhub, smhub.router.uid: smhub.router}
    for module in smhub.router.modules:
        by_uid[module.uid] = module

    def _member_key(uid: str, nmbr: int, *, diag: bool) -> str | None:
        device = by_uid.get(uid)
        members = getattr(device, "diags" if diag else "sensors", None)
        if not members or nmbr >= len(members):
            return None
        return _MEMBER_KEYS.get(members[nmbr].name)

    def rule(ent: er.RegistryEntry) -> str | None:
        uid = ent.unique_id or ""
        if (m := _SET_VALUE_RE.match(uid)) is not None:
            return f"{m['u']}_set_temperature_{int(m['n']) - 47}"
        if (m := re.match(r"^Mod_(?P<u>.+)_snsr(?P<n>\d+)$", uid)) is not None:
            # On the hub this form was only ever the CPU frequency, a diag.
            key = _member_key(m["u"], int(m["n"]), diag=m["u"] == smhub.uid)
            return f"{m['u']}_{key}" if key else None
        if (m := re.match(r"^Mod_(?P<u>.+)_perc(?P<n>\d+)$", uid)) is not None:
            key = _member_key(m["u"], int(m["n"]), diag=False)
            return f"{m['u']}_{key}" if key else None
        for pattern, template in _UID_REWRITES:
            if (m := pattern.match(uid)) is not None:
                return template.format(**m.groupdict())
        if uid.startswith(("Mod_", "Rt_", "Hub_", "mod_")):
            # An id in the old shape that no rule claims. It would be left
            # behind while the platform registers a new entity beside it, so
            # say so rather than let it pass silently.
            _LOGGER.warning(
                "Habitron: no id migration for %s (%s); it will be left as it is",
                uid,
                ent.entity_id,
            )
        return None

    return rule


def _async_migrate_unique_ids(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    rules: Iterable[UniqueIdRule],
) -> None:
    """Rewrite this entry's entity unique_ids, once and idempotently.

    Each rule is handed a registry entry and returns the id that entry should
    carry, or ``None`` to leave it alone; the first rule to answer wins. Runs
    before the platforms are forwarded, so an entity comes up under its final
    id and no duplicate is ever created.

    Where the target id already exists -- an installation that ran under both
    schemes and so has both entities -- the stale entry is removed rather than
    renamed: Home Assistant refuses a duplicate unique_id, and the entity
    already carrying the target is the one the platform is about to claim.
    """
    ent_reg = er.async_get(hass)
    migrated = 0
    for ent in list(er.async_entries_for_config_entry(ent_reg, entry.entry_id)):
        for rule in rules:
            new_uid = rule(ent)
            if new_uid is None or new_uid == ent.unique_id:
                continue
            if ent_reg.async_get_entity_id(ent.domain, DOMAIN, new_uid):
                _LOGGER.info(
                    "Habitron: removing %s (unique_id %s); %s already exists",
                    ent.entity_id,
                    ent.unique_id,
                    new_uid,
                )
                ent_reg.async_remove(ent.entity_id)
            else:
                _LOGGER.info(
                    "Habitron: migrating unique_id %s -> %s",
                    ent.unique_id,
                    new_uid,
                )
                ent_reg.async_update_entity(ent.entity_id, new_unique_id=new_uid)
            migrated += 1
            break
    # Confirmed by the 3.3.0b1 beta: non-zero once, zero on every start after.
    # Kept as a debug line so a support log still shows whether a migration ran.
    _LOGGER.debug("Habitron: migrated %d entity unique_ids", migrated)
