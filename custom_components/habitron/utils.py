"""Utilities for Habitron integration."""

import logging
from pathlib import Path

import aiohttp
import yaml

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

GO2RTC_CONFIG = Path("/config/go2rtc.yaml")


def normalize_module_name(name: str) -> str:
    """Normalize module name for go2rtc stream key."""
    return name.lower().replace(" ", "_")


async def ensure_webrtc_streams(
    hass: HomeAssistant, modules: list[str], host: str
) -> bool:
    """Ensure that all given modules have a WebRTC stream entry in go2rtc.yaml."""
    config: dict

    def get_go2rtc_config_path(hass: HomeAssistant) -> Path:
        """Return the absolute path to go2rtc.yaml inside the HA config directory."""
        return Path(hass.config.path("go2rtc.yaml"))

    go2rtc_path = get_go2rtc_config_path(hass)

    def _load_config() -> dict:
        if not go2rtc_path.exists():
            return {}
        with go2rtc_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _save_config(config: dict) -> None:
        go2rtc_path.parent.mkdir(parents=True, exist_ok=True)  # ensure /config exists
        with go2rtc_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                config,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    if not GO2RTC_CONFIG.exists():
        _LOGGER.warning("File go2rtc.yaml not found, creating a new one")
        config = {
            "go2rtc": {
                "webrtc": {
                    "candidates": [
                        f"{host}:8555",
                        "stun:8555",
                    ]
                }
            },
            "streams": {},
            "log": {"level": "debug"},
        }
        changed = True
    else:
        try:
            config = await hass.async_add_executor_job(_load_config)
        except (OSError, yaml.YAMLError) as err:
            _LOGGER.error("Error loading go2rtc.yaml: %s", err)
            return False
        changed = False

    streams = config.setdefault("streams", {})

    for module_name in modules:
        stream_name = normalize_module_name(module_name)
        if stream_name not in streams:
            streams[stream_name] = ["webrtc://"]
            _LOGGER.info("Added stream '%s' to go2rtc.yaml", stream_name)
            changed = True

    if changed:
        try:
            await hass.async_add_executor_job(_save_config, config)
            _LOGGER.debug("go2rtc.yaml successfully updated")
        except OSError as err:
            _LOGGER.error("Could not write go2rtc.yaml: %s", err)
            return False
        else:
            return True

    return False


async def reload_go2rtc(hass: HomeAssistant, host: str) -> None:
    """Trigger go2rtc to reload its configuration via REST API."""
    url = f"http://{host}:1984/api/reload"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url) as resp:
                if resp.status == 200:
                    _LOGGER.info("Integration go2rtc successfully reloaded config")
                else:
                    _LOGGER.error(
                        "Integration go2rtc reload failed with status %s", resp.status
                    )
        except aiohttp.ClientError as err:
            _LOGGER.error("Error reloading go2rtc: %s", err)
