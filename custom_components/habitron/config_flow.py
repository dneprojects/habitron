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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.service_info.ssdp import SsdpServiceInfo

# pylint:disable=unused-import
from .communicate import test_connection
from .const import (
    CONF_DEFAULT_HOST,
    CONF_DEFAULT_INTERVAL,
    CONF_MAX_INTERVAL,
    CONF_MIN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
DISCOVERY_PORT = 7777
DISCOVERY_TIMEOUT = 3.0
DISCOVERY_MESSAGE = b"habitron_discovery"


def _get_local_ip() -> str:
    """Get local IP address via synchronous socket call."""
    try:
        # Create a dummy socket to detect own IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:  # pylint: disable=broad-except  # noqa: BLE001
        return "127.0.0.1"
    else:
        return ip


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    # Run synchronous network I/O in the executor
    own_ip = await hass.async_add_executor_job(_get_local_ip)

    # Log own IP without trailing period
    _LOGGER.info(f"Smart Center own IP: {own_ip}")  # noqa: G004

    # If the entered IP matches our own IP, save as 'local' to be robust against IP changes
    if data["habitron_host"] == own_ip:
        data["habitron_host"] = "local"

    host_to_test = data["habitron_host"]
    if host_to_test == "local":
        host_to_test = own_ip

    # Basic length check
    if len(host_to_test) < 4:
        raise InvalidHost

    # Validate interval type and range
    if not (isinstance(data["update_interval"], int)):
        raise InvalidInterval

    if data["update_interval"] < CONF_MIN_INTERVAL:
        raise IntervalTooShort

    if data["update_interval"] > CONF_MAX_INTERVAL:
        raise IntervalTooLong

    try:
        # Test actual connection via executor because test_connection is sync
        result, host_name = await hass.async_add_executor_job(
            test_connection, host_to_test
        )
    except socket.gaierror as exc:
        raise socket.gaierror from exc
    except ConnectionRefusedError as exc:
        raise InvalidHost from exc
    if not result:
        raise CannotConnect

    return {"title": host_name}


class UDPDiscoveryProtocol(asyncio.DatagramProtocol):
    """Protocol to discover Habitron devices via UDP."""

    def __init__(self) -> None:
        """Initialize the protocol."""
        self.found_devices = []
        self.transport = None

    def connection_made(self, transport):
        """Set up transport for broadcast."""
        self.transport = transport
        sock = transport.get_extra_info("socket")
        if sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # Send discovery packet
        self.transport.sendto(DISCOVERY_MESSAGE, ("255.255.255.255", DISCOVERY_PORT))

    def datagram_received(self, data, addr):
        """Handle incoming discovery response."""
        try:
            resp = json.loads(data.decode())
            if "host" in resp and "ip" in resp:
                self.found_devices.append(resp)
        except Exception:  # pylint: disable=broad-except  # noqa: BLE001
            pass

    def error_received(self, exc):
        """Handle errors."""

    def connection_lost(self, exc):
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
            entry_host = entry.data.get("habitron_host")
            # Check match against stored host OR ip if provided
            if entry_host == host or (ip and entry_host == ip):
                return True
        return False

    async def _discover_habitron(self) -> list[dict[str, Any]]:
        """Run a quick UDP scan to find devices."""
        loop = asyncio.get_running_loop()
        # Create datagram endpoint for discovery
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UDPDiscoveryProtocol(),
            local_addr=("0.0.0.0", 0),
            family=socket.AF_INET,
        )

        try:
            await asyncio.sleep(DISCOVERY_TIMEOUT)
        finally:
            transport.close()

        return protocol.found_devices

    async def async_step_ssdp(
        self, discovery_info: SsdpServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Handle SSDP discovery."""
        # Extract host from SSDP location URL
        host = urlparse(discovery_info.ssdp_location).hostname

        # 1. Fast check: Is this IP already configured?
        # If so, abort immediately to prevent "new device" notification
        if self._is_device_already_configured(str(host)):
            return self.async_abort(reason="already_configured")

        # Verify via UDP to get full details (Serial, MAC)
        devices = await self._discover_habitron()
        target_device = next((d for d in devices if d.get("ip") == host), None)

        if not target_device:
            # Fallback if UDP fails but SSDP worked
            _LOGGER.debug("SSDP found %s but UDP probe failed", host)
            unique_id = f"habitron_{host}"
            self._discovered_device = {"host": host, "ip": host}
        else:
            # Use serial if available
            unique_id = target_device.get("serial", f"habitron_{host}")
            self._discovered_device = target_device

        # 2. Check if Unique ID matches (standard check)
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={"habitron_host": str(host)})

        self.context["title_placeholders"] = {"name": str(host)}

        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Confirm discovery."""
        if user_input is not None:
            # Create entry with discovered data
            data = {
                "habitron_host": self._discovered_device.get(
                    "host", self._discovered_device.get("ip")
                ),
                "update_interval": 10,
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

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        errors = {}

        default_host = CONF_DEFAULT_HOST
        default_interval = CONF_DEFAULT_INTERVAL

        # Try UDP discovery if opening fresh form
        if user_input is None:
            discovered = await self._discover_habitron()

            # Filter: Keep only devices that are NOT yet configured
            valid_devices = [
                d
                for d in discovered
                if not self._is_device_already_configured(d.get("host"), d.get("ip"))  # type: ignore  # noqa: PGH003
            ]

            if valid_devices:
                # Prefer 'host' over 'ip'
                device = valid_devices[0]
                default_host = device.get("host", device.get("ip", CONF_DEFAULT_HOST))
                _LOGGER.debug(
                    "Discovered new Habitron device via active scan: %s", default_host
                )

        if user_input is not None:
            # Note: For manual entry, we construct ID from input.
            # Ideally this would also probe for serial to match SSDP behavior.
            unique_id = f"habitron_{user_input['habitron_host']}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            try:
                info = await validate_input(self.hass, user_input)
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except socket.gaierror:
                errors["base"] = "host_not_found"
            except InvalidHost:
                errors["base"] = "cannot_connect"
            except InvalidInterval:
                errors["base"] = "invalid_interval"
            except IntervalTooShort:
                errors["base"] = "interval_too_short"
            except IntervalTooLong:
                errors["base"] = "interval_too_long"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        user_schema = vol.Schema(
            {
                vol.Required(
                    "habitron_host",
                    default=default_host,
                ): str,
                vol.Required(
                    "update_interval",
                    default=default_interval,
                ): int,
                vol.Optional(
                    "websock_token",
                    default="",
                ): str,
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=user_schema, errors=errors
        )


class MyOptionsFlowHandler(config_entries.OptionsFlow):
    """Allow to change options of integration while running."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is None:
            # Load current settings from config entry
            default_host = self.config_entry.data["habitron_host"]
            default_interval = self.config_entry.data["update_interval"]
            default_enablestate = True
        else:
            # Use user provided input
            default_host = user_input["habitron_host"]
            default_interval = user_input["update_interval"]
            default_enablestate = user_input["updates_enabled"]

        opt_schema = vol.Schema(
            {
                vol.Required(
                    "habitron_host",
                    default=default_host,
                ): str,
                vol.Required(
                    "update_interval",
                    default=default_interval,
                ): int,
                vol.Required(
                    "updates_enabled",
                    default=default_enablestate,
                ): bool,
                vol.Optional(
                    "websock_token",
                    default="",
                ): str,
            }
        )
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                # Update main config entry data
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=user_input,
                    options=self.config_entry.options,
                )
                return self.async_create_entry(title=info["title"], data=user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="init", data_schema=opt_schema, errors=errors
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
