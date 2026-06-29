"""The Habitron integration."""

import logging
import re

from habitron_client import HabitronError, HabitronTimeoutError

from homeassistant.const import Platform
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

        # Undo the 3.1.0b1 per-module sensor unique_id churn before the sensor
        # platform registers entities, so the original entity_ids are restored.
        _async_restore_legacy_sensor_ids(hass, entry)

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


def _async_restore_legacy_sensor_ids(
    hass: HomeAssistant, entry: HabitronConfigEntry
) -> None:
    """Undo the Beta 3.1.0b1 per-module sensor unique_id churn.

    3.1.0b1 appended the description ``key`` to every described sensor's
    unique_id, including per-module humidity/illuminance/wind/airquality whose
    ``nmbr`` was already unique. That changed their unique_id, so Home Assistant
    registered fresh entities and (under 2026.6) rewrote the entity_ids
    (``sensor.<area>_<device>_<name>``). The suffix is now restricted to the
    colliding router streams (current/voltage/timeout); this one-time, idempotent
    migration realigns the per-module sensors with the original
    ``Mod_{uid}_snsr{nmbr}`` id:

    - if the original bare-id entry still exists (upgrade case) the suffixed
      duplicate is removed so the original — and its entity_id — takes over;
    - otherwise (fresh 3.1.0b1 install) the suffixed entry's unique_id is
      rewritten in place, keeping the entity and its entity_id.
    """
    ent_reg = er.async_get(hass)
    for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if ent.domain != "sensor":
            continue
        match = _LEGACY_UID_RE.match(ent.unique_id or "")
        if not match:
            continue
        base_uid = match.group(1)
        if ent_reg.async_get_entity_id("sensor", DOMAIN, base_uid):
            _LOGGER.info(
                "Habitron: removing duplicate sensor %s (unique_id %s); "
                "restoring original %s",
                ent.entity_id,
                ent.unique_id,
                base_uid,
            )
            ent_reg.async_remove(ent.entity_id)
        else:
            _LOGGER.info(
                "Habitron: migrating sensor unique_id %s -> %s",
                ent.unique_id,
                base_uid,
            )
            ent_reg.async_update_entity(ent.entity_id, new_unique_id=base_uid)
