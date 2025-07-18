"""Provide info to system health."""

from typing import Any

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


@callback
def async_register(
    hass: HomeAssistant, register: system_health.SystemHealthRegistration
) -> None:
    """Register system health callbacks."""
    register.async_register_info(system_health_info)


def get_router_status(hass: HomeAssistant) -> str:
    """Get the router status."""
    hbtn = hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]]
    if hbtn.comm.router._sys_ok:  # noqa: SLF001
        return "ok"
    return "errors"


async def system_health_info(hass: HomeAssistant) -> dict[str, Any]:
    """Get info for the info page."""

    hbtn_health: dict[str, Any] = {}
    hbtn_health["hbtn_version"] = hass.data["integrations"]["habitron"].manifest[
        "version"
    ]
    hbtn = hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]]
    hbtn_health["router_status"] = get_router_status(hass)
    hbtn_health["module_count"] = len(hbtn.router.modules)
    return hbtn_health
