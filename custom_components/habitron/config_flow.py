"""Config flow for Habitron integration."""

from __future__ import annotations

import logging
import socket
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

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

# Note the input displayed to the user will be translated. See the
# translations/<lang>.json file and strings.json. See here for further information:
# https://developers.home-assistant.io/docs/config_entries_config_flow_handler/#translations


async def validate_input(hass: HomeAssistant, data: dict) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
    """
    # Validate the data can be used to set up a connection.

    # This is a simple example to show an error in the UI for a short hostname
    # The exceptions are defined at the end of this file, and are used in the
    # `async_step_user` method below.
    if len(data["habitron_host"]) < 4:
        raise InvalidHost

    if not (isinstance(data["update_interval"], int)):
        raise InvalidInterval

    if data["update_interval"] < CONF_MIN_INTERVAL:
        raise IntervalTooShort

    if data["update_interval"] > CONF_MAX_INTERVAL:
        raise IntervalTooLong

    # The dummy smhub provides a `test_connection` method to ensure it's working
    # as expected
    try:
        result, host_name = await test_connection(data["habitron_host"])
    except socket.gaierror as exc:
        raise socket.gaierror from exc
    except ConnectionRefusedError as exc:
        raise InvalidHost from exc
    if not result:
        # If there is an error, raise an exception to notify HA that there was a
        # problem. The UI will also show there was a problem
        raise CannotConnect

    # Return info that you want to store in the config entry.
    # "Title" is what is displayed to the user for this smhub device
    # It is stored internally in HA as part of the device config.
    # See `async_step_user` below for how this is used
    return {"title": host_name}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for habitron."""

    VERSION = 1

    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod  # type: ignore
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        await self.async_set_unique_id("unique_habitron")

        # smartips = discover_smartips(True)

        self._abort_if_unique_id_configured()
        if user_input is None:
            # default_host = smartips[0]["ip"]
            default_host = CONF_DEFAULT_HOST
            default_interval = CONF_DEFAULT_INTERVAL
        else:
            default_host = user_input["habitron_host"]
            default_interval = user_input["update_interval"]
        user_schema = vol.Schema(
            {
                vol.Required(
                    "habitron_host",
                    default=default_host,  # type: ignore
                ): str,
                vol.Required(
                    "update_interval",
                    default=default_interval,  # type: ignore
                ): int,
                vol.Optional(
                    "websock_token",
                    default="",  # type: ignore
                ): str,
            }
        )
        # This goes through the steps to take the user through the setup process.
        # Using this it is possible to update the UI and prompt for additional
        # information. When that has some validated input, it calls `async_create_entry` to
        # actually create the HA config entry. Note the "title" value is returned by
        # `validate_input` above.
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                await self.async_set_unique_id(
                    f"habitron_{user_input['habitron_host']}"
                )
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

        # If there is no user input or there were errors, show the form again, including any errors that were found with the input.
        return self.async_show_form(
            step_id="user", data_schema=user_schema, errors=errors
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Allow to change options of integration while running."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is None:
            default_host = self.config_entry.data["habitron_host"]
            default_interval = self.config_entry.data["update_interval"]
            default_enablestate = True
        else:
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
                    default=default_enablestate,  # type: ignore
                ): bool,
                vol.Optional(
                    "websock_token",
                    default="",  # type: ignore
                ): str,
            }
        )
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=user_input,
                    options=self.config_entry.options,
                )
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
