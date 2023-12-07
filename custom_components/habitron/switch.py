"""Platform for switch integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .module import IfDescriptor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add switches for passed config_entry in HA."""
    hbtn_rt = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_led in hbt_module.leds:
            led_name = "LED red"
            led_no = mod_led.nmbr + 1
            if mod_led.name.strip() == "":
                mod_led.set_name(f"{led_name} {led_no}")
            else:
                mod_led.set_name(f"{led_name} {led_no}: {mod_led.name}")
            new_devices.append(
                SwitchedLed(mod_led, hbt_module, hbtn_cord, len(new_devices))
            )

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)


class SwitchedLed(CoordinatorEntity, SwitchEntity):
    """Module switch background LEDs."""

    should_poll = False  # for push updates
    device_class = "switch"
    _attr_has_entity_name = True

    def __init__(self, led, module, coord, idx) -> None:
        """Initialize an HbtnLED, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._led = led
        self._module = module
        self._attr_name = led.name
        self._nmbr = led.nmbr
        self._state = None
        self._brightness = None
        self._attr_unique_id = f"{self._module.uid}_led_{self.idx}"
        self._attr_icon = "mdi:circle-outline"

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._module.leds[self._nmbr].register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._module.leds[self._nmbr].remove_callback(self.async_write_ha_state)

    @property
    def device_info(self) -> None:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str:
        """Return the display name of this switch."""
        return self._attr_name

    @property
    def is_on(self) -> bool:
        """Return status of output"""
        self._attr_state = self._module.leds[self._nmbr].value == 1
        if self._attr_state:
            self._attr_icon = "mdi:circle-double"
        else:
            self._attr_icon = "mdi:circle-outline"
        return self._attr_state

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._module.leds[self._nmbr].value == 1
        self._attr_state = self._attr_is_on
        if self._attr_is_on:
            self._attr_icon = "mdi:circle-double"
        else:
            self._attr_icon = "mdi:circle-outline"
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the led to turn on."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._nmbr + len(self._module.outputs) + 2, 1
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the led to turn off."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._nmbr + len(self._module.outputs) + 2, 0
        )
