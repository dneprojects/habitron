"""Config flow for Habitron integration."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.components import network
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

# pylint:disable=unused-import
from .communicate import test_connection
from .const import (
    CONF_DEFAULT_HOST,
    CONF_DEFAULT_INTERVAL,
    CONF_HOST,
    CONF_MAX_INTERVAL,
    CONF_MIN_INTERVAL,
    CONF_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PORT = 7777
DISCOVERY_TIMEOUT = 3.0
DISCOVERY_MESSAGE = b"habitron_discovery"


async def _get_local_ip(hass: HomeAssistant) -> str:
    """Get the local IP address using HA network utilities."""
    try:
        # Versucht, die IP zu finden, die für das Standard-Interface genutzt wird
        return await network.async_get_source_ip(hass, target_ip="8.8.8.8")
    except Exception:  # pylint: disable=broad-except  # noqa: BLE001
        # Fallback auf Loopback, falls nichts gefunden wird
        return "127.0.0.1"


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""

    # 1. Local IP Check
    own_ip = await _get_local_ip(hass)
    _LOGGER.info("Smart Center own IP: %s", own_ip)

    host_input = data[CONF_HOST]

    # If the entered IP matches our own IP, save as 'local' to be robust against IP changes
    if host_input == own_ip:
        host_input = "local"
        data[CONF_HOST] = "local"

    host_to_test = host_input
    if host_to_test == "local":
        host_to_test = own_ip

    # 2. Basic Validation
    if len(host_to_test) < 4:
        raise InvalidHost

    if not isinstance(data[CONF_SCAN_INTERVAL], int):
        raise InvalidInterval

    if data[CONF_SCAN_INTERVAL] < CONF_MIN_INTERVAL:
        raise IntervalTooShort

    if data[CONF_SCAN_INTERVAL] > CONF_MAX_INTERVAL:
        raise IntervalTooLong

    # 3. Connection Test
    try:
        # test_connection läuft im Executor (synchron)
        result, host_name = await hass.async_add_executor_job(
            test_connection, host_to_test
        )
    except socket.gaierror as exc:
        raise HostNotFound from exc
    except ConnectionRefusedError as exc:
        raise CannotConnect from exc
    except Exception as exc:
        _LOGGER.error("Connection error: %s", exc)
        raise CannotConnect from exc

    if not result:
        raise CannotConnect

    return {"title": host_name}


class UDPDiscoveryProtocol(asyncio.DatagramProtocol):
    """Protocol to discover Habitron devices via UDP."""

    def __init__(self) -> None:
        """Initialize the protocol."""
        self.found_devices: list[dict[str, Any]] = []
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        """Set up transport for broadcast."""
        self.transport = transport  # type: ignore
        sock = transport.get_extra_info("socket")
        if sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Send discovery packet
        if self.transport:
            self.transport.sendto(
                DISCOVERY_MESSAGE, ("255.255.255.255", DISCOVERY_PORT)
            )

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Handle incoming discovery response."""
        try:
            resp = json.loads(data.decode())
            if "host" in resp and "ip" in resp:
                if not any(d.get("ip") == resp["ip"] for d in self.found_devices):
                    self.found_devices.append(resp)
        except Exception:  # pylint: disable=broad-except  # noqa: BLE001
            pass

    def error_received(self, exc: Exception) -> None:
        """Handle errors."""
        _LOGGER.debug("UDP Discovery error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        """Handle connection lost."""


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for habitron."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_device: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return MyOptionsFlowHandler()

    def _is_device_already_configured(self, host: str, ip: str | None = None) -> bool:
        """Check if a device with this host or IP is already configured."""
        existing_entries = self.hass.config_entries.async_entries(DOMAIN)
        for entry in existing_entries:
            entry_host = entry.data.get(CONF_HOST)
            if entry_host == host or (ip and entry_host == ip):
                return True
        return False

    async def _discover_habitron(self) -> list[dict[str, Any]]:
        """Run a quick UDP scan to find devices."""
        loop = asyncio.get_running_loop()
        try:
            transport, protocol = await loop.create_datagram_endpoint(
                UDPDiscoveryProtocol,
                local_addr=("0.0.0.0", 0),
                family=socket.AF_INET,
            )
        except OSError as err:
            _LOGGER.error("Could not start UDP discovery: %s", err)
            return []

        try:
            await asyncio.sleep(DISCOVERY_TIMEOUT)
        finally:
            transport.close()

        # cast because protocol is typed as BaseProtocol in create_datagram_endpoint return
        return protocol.found_devices  # type: ignore

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle SSDP discovery."""
        # Extract host from SSDP location URL
        host = urlparse(discovery_info.ssdp_location).hostname
        if not host:
            return self.async_abort(reason="no_host_in_ssdp")

        host_str = str(host)

        # 1. Fast check: Is this IP already configured?
        # If so, abort immediately to prevent "new device" notification
        if self._is_device_already_configured(str(host)):
            return self.async_abort(reason="already_configured")

        # Verify via UDP to get full details (Serial, MAC)
        devices = await self._discover_habitron()
        target_device = next((d for d in devices if d.get("ip") == host_str), None)

        if target_device:
            # Use serial if available
            unique_id = target_device.get("serial", f"habitron_{host_str}")
            self._discovered_device = target_device
        else:
            # Fallback if UDP fails but SSDP worked
            _LOGGER.debug("SSDP found %s but UDP probe failed", host_str)
            unique_id = f"habitron_{host_str}"
            self._discovered_device = {"host": host_str, "ip": host_str}

        # 2. Check if Unique ID matches (standard check)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host_str})

        self.context["title_placeholders"] = {"name": host_str}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm discovery."""
        if user_input is not None:
            # Create entry with discovered data
            data = {
                CONF_HOST: self._discovered_device.get(
                    "host", self._discovered_device.get("ip")
                ),
                CONF_SCAN_INTERVAL: 10,
                "websock_token": "",
            }
            try:
                info = await validate_input(self.hass, data)
                return self.async_create_entry(title=info["title"], data=data)
            except Exception:  # pylint: disable=broad-except  # noqa: BLE001
                return self.async_abort(reason="unknown")

        self._set_confirm_only()
        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={
                "name": self._discovered_device.get("host", "Habitron Hub")
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        default_host = CONF_DEFAULT_HOST
        default_interval = CONF_DEFAULT_INTERVAL

        # Pre-fill with discovery if just opened
        if user_input is None:
            discovered = await self._discover_habitron()

            # Filter: Keep only devices that are NOT yet configured
            valid_devices = [
                d
                for d in discovered
                if not self._is_device_already_configured(
                    d.get("host", ""), d.get("ip")
                )
            ]
            if valid_devices:
                device = valid_devices[0]
                default_host = device.get("host", device.get("ip", CONF_DEFAULT_HOST))

        if user_input is not None:
            # Use host as unique ID for manual entry if serial unknown
            # Best practice: Try to fetch serial in validate_input if possible
            unique_id = f"habitron_{user_input[CONF_HOST]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except HostNotFound:
                errors["base"] = "host_not_found"
            except InvalidHost:
                errors["base"] = "invalid_host"  # specific key
            except InvalidInterval:
                errors["base"] = "invalid_interval"
            except IntervalTooShort:
                errors["base"] = "interval_too_short"
            except IntervalTooLong:
                errors["base"] = "interval_too_long"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

            # If we failed, keep the input
            default_host = user_input[CONF_HOST]
            default_interval = user_input[CONF_SCAN_INTERVAL]

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=default_host): str,
                    vol.Required(CONF_SCAN_INTERVAL, default=default_interval): int,
                    vol.Optional("websock_token", default=""): str,
                }
            ),
            errors=errors,
        )


class MyOptionsFlowHandler(config_entries.OptionsFlow):
    """Allow to change options of integration while running."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)

                # Update Config Entry Data (Host/IP)
                # Note: Host change in OptionsFlow needs reload normally
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=user_input,  # Entire data is replaced in OptionsFlow
                )

                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                return self.async_create_entry(title="", data={})
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Options flow error")
                errors["base"] = "unknown"

        # Load default values from existing config
        current_config = self.config_entry.data

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=current_config.get(CONF_HOST)): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=current_config.get(
                            CONF_SCAN_INTERVAL, CONF_DEFAULT_INTERVAL
                        ),
                    ): int,
                    vol.Optional(
                        "websock_token", default=current_config.get("websock_token", "")
                    ): str,
                }
            ),
            errors=errors,
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class HostNotFound(exceptions.HomeAssistantError):
    """Error to indicate DNS name is not found."""


class InvalidHost(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid hostname."""


class InvalidInterval(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid update interval."""


class IntervalTooShort(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid update interval."""


class IntervalTooLong(exceptions.HomeAssistantError):
    """Error to indicate there is an invalid update interval."""


class AlreadyConfigured(exceptions.HomeAssistantError):
    """Error to indicate device is already configured."""
