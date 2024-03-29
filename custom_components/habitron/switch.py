"""Platform for switch integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .interfaces import IfDescriptor, StateDescriptor
from .module import HbtnModule
from .router import HbtnRouter


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add switches for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = hass.data[DOMAIN][entry.entry_id].router
    hbtn_cord = hbtn_rt.coord

    new_devices = []
    for hbt_module in hbtn_rt.modules:
        for mod_led in hbt_module.leds:
            if mod_led.type == 0:
                if mod_led.nmbr == 0:
                    led_name = "LED white"
                    led_no = ""
                else:
                    led_name = "LED red"
                    led_no = mod_led.nmbr
                if mod_led.name.strip() == "":
                    mod_led.set_name(f"{led_name} {led_no}")
                else:
                    mod_led.set_name(f"{led_name} {led_no}: {mod_led.name}")
                new_devices.append(
                    SwitchedLed(mod_led, hbt_module, hbtn_cord, len(new_devices))
                )
        flg_idx = 0
        for mod_flg in hbt_module.flags:
            if hbt_module.comm.is_smhub:
                new_devices.append(
                    HbtnFlagPush(mod_flg, hbt_module, hbtn_cord, flg_idx)
                )
            else:
                new_devices.append(HbtnFlag(mod_flg, hbt_module, hbtn_cord, flg_idx))
            flg_idx += 1
    flg_idx = 0
    for rt_flg in hbtn_rt.flags:
        if hbtn_rt.comm.is_smhub:
            new_devices.append(HbtnFlagPush(rt_flg, hbtn_rt, hbtn_cord, flg_idx))
        else:
            new_devices.append(HbtnFlag(rt_flg, hbtn_rt, hbtn_cord, flg_idx))
        flg_idx += 1

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        hbtn_cord.data = new_devices
        async_add_entities(new_devices)


class SwitchedLed(CoordinatorEntity, SwitchEntity):
    """Module switch background LEDs."""

    _attr_should_poll = False  # for push updates
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_has_entity_name = True

    def __init__(
        self,
        led: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an HbtnLED, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._led: IfDescriptor = led
        self._module: HbtnModule = module
        self._attr_name: str = led.name
        self._nmbr: int = led.nmbr
        self._state: bool = False
        self._attr_unique_id: str = f"{self._module.uid}_led_{self.idx}"

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
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str | None:
        """Return the display name of this switch."""
        return self._attr_name

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._state

    @property
    def icon(self) -> str:
        """Icon of the led, based on number and state."""
        if (self._nmbr > 0) & self.is_on:
            return "mdi:circle-double"
        if (self._nmbr > 0) & (not self.is_on):
            return "mdi:circle-outline"
        if self.is_on:
            return "mdi:white-balance-sunny"
        return "mdi:circle-medium"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._state = self._led.value == 1
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the led to turn on."""
        await self._module.comm.async_set_led_outp(self._module.mod_addr, self._nmbr, 1)
        self._state = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the led to turn off."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._nmbr + len(self._module.outputs) + 1, 0
        )
        self._state = False


class HbtnFlag(CoordinatorEntity, SwitchEntity):
    """Module switch local flag."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_has_entity_name = True

    def __init__(
        self,
        flag: StateDescriptor,
        module: HbtnRouter | HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an HbtnFlag, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._flag: StateDescriptor = flag
        self._module: HbtnRouter | HbtnModule = module
        self._attr_name: str = flag.name
        self._nmbr: int = flag.nmbr
        self._state: bool = False
        self._attr_unique_id: str = f"{self._module.uid}_flag_{self._nmbr}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str | None:
        """Return the display name of this switch."""
        return self._attr_name

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._state

    @property
    def icon(self) -> str:
        """Icon of the led, based on number and state."""
        if self.is_on:
            return "mdi:bookmark-check"
        return "mdi:bookmark-outline"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._state = self._flag.value == 1
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the flag to turn on."""
        if isinstance(self._module, HbtnModule):
            mod_addr = self._module.mod_addr
        else:
            mod_addr = self._module.id
        await self._module.comm.async_set_flag(mod_addr, self._nmbr, 1)
        self._state = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the flag to turn off."""
        if isinstance(self._module, HbtnModule):
            mod_addr = self._module.mod_addr
        else:
            mod_addr = self._module.id
        await self._module.comm.async_set_flag(mod_addr, self._nmbr, 0)
        self._state = False


class HbtnFlagPush(HbtnFlag):
    """Representation of habitron flag entities for push update."""

    _attr_should_poll = False  # for push updates

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._flag.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._flag.remove_callback(self._handle_coordinator_update)
