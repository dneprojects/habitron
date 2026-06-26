"""Repair flows for Habitron per-module operate-mode faults.

A ``module_fault`` issue (see ``health.py``) is fixable: this flow offers a
remote recovery action based on the module's *current* fault mask.

* Communication timeout (**F1**, bit ``0x01``): the module is unreachable on the
  bus, so a restart command would never arrive. The only remaining remote action
  is a **power cycle of the module's router channel** — a coarse measure that
  also resets every other module on that channel (pair). The confirm step warns
  about this and lists the co-located modules.
* Any other fault: a plain **module restart**, which may clear a transient fault.

The flow always re-reads the live model, so a fault that cleared (or changed)
between raising the issue and opening the flow is handled correctly.
"""

from habitron_client import Module, Router, decode_module_faults
import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .coordinator import HabitronConfigEntry
from .smart_hub import SmartHub

# Communication-timeout bit (F1): the module cannot be reached on the bus.
_FAULT_COMM_TIMEOUT = 0x01


def _resolve_module(
    hass: HomeAssistant, data: dict[str, str] | None
) -> tuple[SmartHub, Module] | None:
    """Return the (hub, module) referenced by an issue's ``data``, or None.

    None means the entry is gone/unloaded or the module no longer exists — the
    caller then clears the now-stale issue.
    """
    if not data:
        return None
    entry: HabitronConfigEntry | None = hass.config_entries.async_get_entry(
        data.get("entry_id", "")
    )
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        return None
    smhub: SmartHub = entry.runtime_data
    module = next(
        (mod for mod in smhub.router.modules if mod.uid == data.get("module_uid")),
        None,
    )
    if module is None:
        return None
    return smhub, module


def _channel_and_peers(router: Router, module: Module) -> tuple[int | None, list[str]]:
    """Return the module's router channel (1..4) and the other modules on it."""
    mod_id = module.addr - router.id
    for channel, mod_ids in enumerate(router.chan_list, start=1):
        if mod_id in mod_ids:
            peers = [
                peer.name
                for peer in router.modules
                if peer.uid != module.uid and (peer.addr - router.id) in mod_ids
            ]
            return channel, peers
    return None, []


def _format_faults(mask: int) -> str:
    """Render the active faults of ``mask`` as a bullet list."""
    return "\n".join(
        f"- {fault.code}: {fault.label}" for fault in decode_module_faults(mask)
    )


class ModuleFaultRepairFlow(RepairsFlow):
    """Confirm-and-recover flow for a module's operate-mode fault."""

    def __init__(self, issue_id: str, data: dict[str, str] | None) -> None:
        """Store the issue id and its data payload."""
        self._issue_id = issue_id
        self._data = data

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Pick the recovery step from the module's current fault mask."""
        resolved = _resolve_module(self.hass, self._data)
        if resolved is None:
            # Hub unloaded or module gone — nothing left to repair.
            return self.async_abort(reason="module_unavailable")
        _, module = resolved
        mask = module.health.value
        if mask == 0:
            # The fault already cleared; complete the flow so HA drops the issue.
            return self.async_create_entry(title="", data={})
        if mask & _FAULT_COMM_TIMEOUT:
            return await self.async_step_confirm_power_cycle()
        return await self.async_step_confirm_restart()

    async def async_step_confirm_restart(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Offer a plain module restart for a reachable, faulty module."""
        resolved = _resolve_module(self.hass, self._data)
        if resolved is None:
            return self.async_abort(reason="module_unavailable")
        smhub, module = resolved
        if user_input is not None:
            await smhub.comm.module_restart(module.addr)
            return self.async_create_entry(title="", data={})
        return self.async_show_form(
            step_id="confirm_restart",
            data_schema=vol.Schema({}),
            description_placeholders={
                "module": module.name,
                "faults": _format_faults(module.health.value),
            },
        )

    async def async_step_confirm_power_cycle(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Offer a channel power cycle for an unreachable module (F1)."""
        resolved = _resolve_module(self.hass, self._data)
        if resolved is None:
            return self.async_abort(reason="module_unavailable")
        smhub, module = resolved
        channel, peers = _channel_and_peers(smhub.router, module)
        if channel is None:
            # Module not mapped to a channel — cannot power cycle.
            return self.async_abort(reason="channel_unknown")
        if user_input is not None:
            await smhub.comm.async_power_cycle_channel(channel)
            return self.async_create_entry(title="", data={})
        others = (
            "\n".join(f"- {name}" for name in peers)
            if peers
            else "- (keine weiteren / none)"
        )
        return self.async_show_form(
            step_id="confirm_power_cycle",
            data_schema=vol.Schema({}),
            description_placeholders={
                "module": module.name,
                "channel": str(channel),
                "others": others,
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str] | None,
) -> RepairsFlow:
    """Create the repair flow for a ``module_fault`` issue."""
    return ModuleFaultRepairFlow(issue_id, data)
