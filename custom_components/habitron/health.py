"""Operate-mode health repairs issues for Habitron modules.

The SmartHub reports per-module operate-mode faults via ``SYS_ERR`` events,
which the library applies to ``module.health``. For every module we subscribe to
that member and mirror its state into a repairs issue: an active fault bitmask
raises (or refreshes) a per-module issue, a cleared mask deletes it. The
diagnostic ``binary_sensor`` is the live state; this issue is the user-facing
"needs attention" surface.

The issue is *fixable* — its repair flow (``repairs.py``) offers a recovery
action: a module restart for most faults, or a coarser channel power cycle when
the module is unreachable (F1 communication timeout). The issue carries the
config-entry id and module uid in its ``data`` so the flow can find the live
module and act on the current fault state.

This lives apart from the entity on purpose — the issue must track faults even
when the diagnostic entity is disabled.
"""

from collections.abc import Callable

from habitron_client import Module, decode_module_faults

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .coordinator import HabitronConfigEntry
from .smart_hub import SmartHub


def _issue_id(module: Module) -> str:
    """Return the stable repairs issue id for a module's fault state."""
    return f"module_fault_{module.uid}"


def async_setup_module_health_issues(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    smhub: SmartHub,
) -> None:
    """Mirror each module's health member into a repairs issue.

    Registers one listener per module and an unloader so the subscriptions go
    away with the config entry.
    """
    for module in smhub.router.modules:
        remove = _async_track_module_health(hass, entry.entry_id, module)
        entry.async_on_unload(remove)


def _async_track_module_health(
    hass: HomeAssistant, entry_id: str, module: Module
) -> Callable[[], None]:
    """Mirror one module's health into a repairs issue; return an unsubscriber."""

    @callback
    def _sync_issue() -> None:
        faults = decode_module_faults(module.health.value)
        if not faults:
            # arg1 == 0 (or never faulted): clear any standing issue. A delete
            # for a non-existent issue is a no-op.
            ir.async_delete_issue(hass, DOMAIN, _issue_id(module))
            return
        ir.async_create_issue(
            hass,
            DOMAIN,
            _issue_id(module),
            is_fixable=True,
            severity=ir.IssueSeverity.ERROR,
            translation_key="module_fault",
            translation_placeholders={
                "module": module.name,
                "faults": "\n".join(
                    f"- {fault.code}: {fault.label}" for fault in faults
                ),
            },
            data={"entry_id": entry_id, "module_uid": module.uid},
        )

    module.health.add_listener(_sync_issue)
    # Reconcile once now, in case a fault arrived before setup completed.
    _sync_issue()
    return lambda: module.health.remove_listener(_sync_issue)
