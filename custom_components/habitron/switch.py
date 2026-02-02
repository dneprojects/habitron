"""Platform for switch integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .interfaces import AreaDescriptor, IfDescriptor, StateDescriptor
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

    new_devices: list[SwitchEntity] = []
    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            if abs(mod_output.type) == 1:  # standard
                new_devices.append(
                    SwitchedOutputPush(
                        mod_output, hbt_module, hbtn_cord, len(new_devices)
                    )
                )
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
            new_devices.append(HbtnFlagPush(mod_flg, hbt_module, hbtn_cord, flg_idx))
            flg_idx += 1  # noqa: SIM113

        if hbt_module.mod_type.startswith("Smart Controller"):
            new_devices.append(ClimateCtlSwitch(hbt_module))

        if hbt_module.mod_type == "Smart Controller Touch":
            new_devices.append(MicrophoneSwitch(hbt_module))
    flg_idx = 0
    for rt_flg in hbtn_rt.flags:
        new_devices.append(HbtnFlagPush(rt_flg, hbtn_rt, hbtn_cord, flg_idx))
        flg_idx += 1

    if new_devices:
        await hbtn_cord.async_config_entry_first_refresh()
        async_add_entities(new_devices)

    registry: er.EntityRegistry = er.async_get(hass)
    area_names: dict[int, AreaDescriptor] = hbtn_rt.areas

    for hbt_module in hbtn_rt.modules:
        for mod_output in hbt_module.outputs:
            if (
                abs(mod_output.type) == 1
                and mod_output.area > 0
                and mod_output.area != hbt_module.area_member
            ):  # standard
                entity_entry = registry.async_get_entity_id(
                    "switch", DOMAIN, f"Mod_{hbt_module.uid}_out{mod_output.nmbr}"
                )
                if entity_entry:
                    registry.async_update_entity(
                        entity_entry, area_id=area_names[mod_output.area].get_name_id()
                    )
                else:
                    logging.getLogger(__name__).warning(
                        "Set area for switch, entity not found for output: Mod_%s_out%s",
                        hbt_module.uid,
                        mod_output.nmbr,
                    )
            elif mod_output.area <= 0:
                logging.getLogger(__name__).warning(
                    "Set area 0 for switch, output area is 0: Mod_%s_out%s",
                    hbt_module.uid,
                    mod_output.nmbr,
                )
            elif mod_output.area == hbt_module.area_member:
                logging.getLogger(__name__).warning(
                    "Set area %s for switch, output area same as module area: Mod_%s_out%s",
                    area_names[mod_output.area].get_name_id(),
                    hbt_module.uid,
                    mod_output.nmbr,
                )
            else:
                logging.getLogger(__name__).warning(
                    "Set area %s for switch, output not in area: Mod_%s_out%s",
                    area_names[mod_output.area].get_name_id(),
                    hbt_module.uid,
                    mod_output.nmbr,
                )


class SwitchedOutput(CoordinatorEntity, SwitchEntity):
    """Representation of habitron outout as switch entities."""

    _attr_has_entity_name = True
    _attr_should_poll = True  # for push updates

    def __init__(
        self,
        output: IfDescriptor,
        module: HbtnModule,
        coord: DataUpdateCoordinator,
        idx: int,
    ) -> None:
        """Initialize an HbtnSwitch, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx: int = idx
        self._output: IfDescriptor = output
        self._area_member: int = output.area
        self._module: HbtnModule = module
        if output.name.strip() == "":
            self._attr_name = f"Out {output.nmbr + 1}"
        else:
            self._attr_name = output.name
        self._nmbr: int = output.nmbr
        self._out_offs = 0  # Dimm 1 = Out 1 + offs
        self._attr_unique_id: str | None = f"Mod_{self._module.uid}_out{output.nmbr}"
        if output.type < 0:
            # Entity will not show up
            self._attr_entity_registry_enabled_default = False
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self._output.value == 1
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._nmbr + 1, 1
        )
        self._attr_is_on = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self._module.comm.async_set_output(
            self._module.mod_addr, self._nmbr + 1, 0
        )
        self._attr_is_on = False


class SwitchedOutputPush(SwitchedOutput):
    """Version for push update."""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._output.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._output.remove_callback(self.async_write_ha_state)


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
        self._attr_name: str | None = led.name
        self._nmbr: int = led.nmbr
        self._state: bool = False
        self._attr_unique_id: str | None = f"Mod_{self._module.uid}_led{led.nmbr}"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        await super().async_added_to_hass()
        self._led.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._led.remove_callback(self._handle_coordinator_update)

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
        await self._module.comm.async_set_led_outp(self._module.mod_addr, self._nmbr, 0)
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
        self._attr_name: str | None = flag.name
        self._nmbr: int = flag.nmbr
        self._state: bool = False
        self._attr_unique_id: str | None = f"Mod_{self._module.uid}_flag{self._nmbr}"
        self._attr_device_info = {"identifiers": {(DOMAIN, self._module.uid)}}

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


class MicrophoneSwitch(SwitchEntity):
    """Representation of a button to trigger a speech command."""

    _attr_has_entity_name = True

    def __init__(self, module) -> None:
        """Initialize a switch for the microphone."""
        self._name = "Microphone Mode"
        self._module = module
        self._stream_name = module.name.lower().replace(" ", "_")
        self._provider = module.comm.router.smhub.ws_provider
        self._active_ws_connections = self._provider.active_ws_connections
        self._attr_unique_id = f"Mod_{self._module.uid}_{self._name}"
        self._attr_name = "Microphone Mode"
        self._attr_icon = "mdi:microphone"
        self._state = False

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        return self._state

    @property
    def icon(self) -> str:
        """Icon of the switch, based on state."""
        if self.is_on:
            return "mdi:webcam"
        return "mdi:microphone-message"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the flag to turn on."""
        ws_connection = self._active_ws_connections.get(self._stream_name)
        if ws_connection:
            ws_connection.send_message(
                {"type": "habitron/set_webrtc_audio_mode", "audio_enabled": True}
            )
        self._state = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the flag to turn off."""
        ws_connection = self._active_ws_connections.get(self._stream_name)
        if ws_connection:
            ws_connection.send_message(
                {"type": "habitron/set_webrtc_audio_mode", "audio_enabled": False}
            )
        self._state = False


class ClimateCtlSwitch(SwitchEntity):
    """Representation of a button to trigger a speech command."""

    _attr_has_entity_name = True
    _attr_should_poll = True

    def __init__(self, module) -> None:
        """Initialize a switch for the microphone."""
        self._name = "Climate Contoller 2"
        self._module = module
        self._attr_unique_id = f"Mod_{self._module.uid}_{self._name}"
        self._attr_name = self._name
        self._attr_icon = "mdi:heat-pump-outline"  # "mdi:home-climate-outline"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_entity_registry_enabled_default = (
            False  # Entity will initally be disabled
        )
        self._state = self._module.climate_ctl12 == 2

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._state = self._module.climate_ctl12 == 2
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def is_on(self) -> bool:
        """Return status of output."""
        self._state = self._module.climate_ctl12 == 2
        return self._state

    @property
    def icon(self) -> str:
        """Icon of the switch, based on state."""
        if self.is_on:
            return "mdi:heat-pump"  # "mdi:home-climate"
        return "mdi:heat-pump-outline"  # "mdi:home-climate-outline"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the flag to turn on."""
        self._module.climate_ctl12 = 2
        await self._module.comm.async_set_climate_mode(
            self._module.mod_addr,
            self._module.climate_settings,
            self._module.climate_ctl12,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the flag to turn off."""
        self._module.climate_ctl12 = 1
        await self._module.comm.async_set_climate_mode(
            self._module.mod_addr,
            self._module.climate_settings,
            self._module.climate_ctl12,
        )
