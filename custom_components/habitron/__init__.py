"""The Habitron integration."""

from habitron_client import HabitronTimeoutError

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntry

from .const import DOMAIN
from .coordinator import HabitronConfigEntry
from .services import async_remove_services, async_setup_services
from .smart_hub import SmartHub
from .system_health import system_health_info  # noqa: F401
from .ws_provider import HabitronWebRTCProvider

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
    except (OSError, ConnectionError) as ex:
        # Network-level failures (DNS, socket errors, ...) are transient
        # and should let HA retry the entry. Programming errors such as
        # AttributeError/KeyError must propagate so they show up in the
        # logs instead of being masked as a retry loop.
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
    # ``set_host`` triggered a reload itself, which left the rest of this
    # listener acting on a hub instance that was being torn down. Doing
    # the reload here unconditionally keeps host, interval and token in
    # sync via the normal setup path.
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
