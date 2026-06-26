"""Tests for the Habitron per-module health repairs issues (health.py)."""

from unittest.mock import MagicMock

from habitron_client import Module

from custom_components.habitron.const import DOMAIN
from custom_components.habitron.health import (
    _async_track_module_health,
    _issue_id,
    async_setup_module_health_issues,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir


def _module(uid: str = "MOD-1", name: str = "Mod") -> Module:
    """Build a v2 model module with a default (healthy) health member."""
    return Module(uid=uid, addr=105, typ=b"\x01\x02", name=name)


async def test_fault_raises_then_clears_issue(hass: HomeAssistant) -> None:
    """A non-zero mask raises a module issue; arg1 == 0 deletes it again."""
    module = _module()
    remove = _async_track_module_health(hass, "entry-1", module)
    reg = ir.async_get(hass)
    issue_id = _issue_id(module)

    # Healthy at setup: no standing issue.
    assert reg.async_get_issue(DOMAIN, issue_id) is None

    # Fault arrives (F1 + F5) -> issue created with both faults listed.
    module.health.value = 0x01 | 0x80
    module.health.notify()
    issue = reg.async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.severity == ir.IssueSeverity.ERROR
    assert issue.is_fixable is True
    assert issue.data == {"entry_id": "entry-1", "module_uid": "MOD-1"}
    assert issue.translation_key == "module_fault"
    assert issue.translation_placeholders["module"] == "Mod"
    faults = issue.translation_placeholders["faults"]
    assert "F1: Timeout Modulkommunikation" in faults
    assert "F5: Spiegelung gestört" in faults

    # Cleared (arg1 == 0) -> issue removed.
    module.health.value = 0
    module.health.notify()
    assert reg.async_get_issue(DOMAIN, issue_id) is None

    # Unsubscribe stops further updates.
    remove()
    assert len(module.health._listeners) == 0


async def test_fault_mask_change_refreshes_issue(hass: HomeAssistant) -> None:
    """An updated mask refreshes the same issue id with the new fault list."""
    module = _module()
    _async_track_module_health(hass, "entry-1", module)
    reg = ir.async_get(hass)
    issue_id = _issue_id(module)

    module.health.value = 0x01  # F1 only
    module.health.notify()
    assert "F16" not in reg.async_get_issue(DOMAIN, issue_id).translation_placeholders[
        "faults"
    ]

    module.health.value = 0x10  # now F16 only
    module.health.notify()
    faults = reg.async_get_issue(DOMAIN, issue_id).translation_placeholders["faults"]
    assert "F16: Fehler Leistungsteil" in faults
    assert "F1:" not in faults


async def test_setup_subscribes_each_module(hass: HomeAssistant) -> None:
    """async_setup_module_health_issues tracks every module and registers unloaders."""
    modules = [_module(uid="MOD-1"), _module(uid="MOD-2")]
    smhub = MagicMock()
    smhub.router.modules = modules
    entry = MagicMock()

    async_setup_module_health_issues(hass, entry, smhub)

    assert all(len(module.health._listeners) == 1 for module in modules)
    # One unloader registered per module.
    assert entry.async_on_unload.call_count == len(modules)
