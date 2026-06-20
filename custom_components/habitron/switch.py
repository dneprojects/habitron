"""Platform for switch integration."""

from typing import TYPE_CHECKING, Any

from habitron_client import Flag, Led, Module, Output

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from ._helpers import HabitronEntity, async_assign_entity_area, hbtn_device_info
from .coordinator import HabitronConfigEntry, HbtnCoordinator

if TYPE_CHECKING:
    from .ws_provider import HabitronWebRTCProvider

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add switches for passed config_entry in HA."""
    smhub = entry.runtime_data
    router = smhub.router
    coord = smhub.coordinator

    new_devices: list[SwitchEntity] = []
    for module in router.modules:
        for output in module.outputs:
            if abs(output.type) == 1:  # standard relay output
                new_devices.append(
                    SwitchedOutput(coord, module, output, len(new_devices))
                )
        for led in module.leds:
            if led.type != 0:
                continue
            if module.typ == b"\x01\x04" and led.nmbr == 0:
                # CLED 0 is the ambient light on the Touch, not a switchable LED.
                continue
            new_devices.append(SwitchedLed(coord, module, led, len(new_devices)))
        for flag in module.flags:
            new_devices.append(
                HbtnFlag(
                    coord,
                    flag,
                    device_uid=module.uid,
                    mod_addr=module.addr,
                    idx=len(new_devices),
                )
            )
        if module.mod_type.startswith("Smart Controller"):
            new_devices.append(ClimateCtlSwitch(coord, module, len(new_devices)))
        if (
            module.mod_type == "Smart Controller Touch"
            and smhub.ws_provider is not None
        ):
            new_devices.append(MicrophoneSwitch(module, smhub.ws_provider))

    for flag in router.flags:
        new_devices.append(
            HbtnFlag(
                coord,
                flag,
                device_uid=router.uid,
                mod_addr=router.id,
                idx=len(new_devices),
            )
        )

    if new_devices:
        async_add_entities(new_devices)

    registry = er.async_get(hass)
    area_names = {area.nmbr: slugify(area.name) for area in router.areas}
    for module in router.modules:
        for output in module.outputs:
            if abs(output.type) == 1:
                async_assign_entity_area(
                    registry,
                    domain="switch",
                    unique_id=f"Mod_{module.uid}_out{output.nmbr}",
                    area_index=output.area,
                    area_member=module.area,
                    area_names=area_names,
                    propagate_to_hidden_duplicates=True,
                )


class SwitchedOutput(HabitronEntity, SwitchEntity):
    """Representation of a Habitron relay output as a switch."""

    def __init__(
        self, coordinator: HbtnCoordinator, module: Module, output: Output, idx: int
    ) -> None:
        """Initialize the output switch."""
        super().__init__(coordinator, module, output, idx)
        self._output = output
        self._nmbr = output.nmbr
        self._attr_name = (
            output.name if output.name.strip() else f"Out {output.nmbr + 1}"
        )
        self._attr_unique_id = f"Mod_{module.uid}_out{output.nmbr}"
        if output.type < 0:
            self._attr_entity_registry_enabled_default = False

    @property
    def is_on(self) -> bool:
        """Return whether the output is on."""
        return self._output.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the output on."""
        await self.comm.async_set_output(self._module.addr, self._nmbr + 1, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the output off."""
        await self.comm.async_set_output(self._module.addr, self._nmbr + 1, 0)


class SwitchedLed(HabitronEntity, SwitchEntity):
    """Representation of a Habitron module background LED as a switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self, coordinator: HbtnCoordinator, module: Module, led: Led, idx: int
    ) -> None:
        """Initialize the LED switch."""
        super().__init__(coordinator, module, led, idx)
        self._led = led
        self._nmbr = led.nmbr
        if led.nmbr == 0:
            led_name, led_no = "LED white", ""
        else:
            led_name, led_no = "LED red", str(led.nmbr)
        if led.name.strip() == "":
            self._attr_name = f"{led_name} {led_no}"
        else:
            self._attr_name = f"{led_name} {led_no}: {led.name}"
        self._attr_unique_id = f"Mod_{module.uid}_led{led.nmbr}"

    @property
    def is_on(self) -> bool:
        """Return whether the LED is on."""
        return self._led.is_on

    @property
    def icon(self) -> str:
        """Icon of the LED, based on number and state."""
        if (self._nmbr > 0) & self.is_on:
            return "mdi:circle-double"
        if (self._nmbr > 0) & (not self.is_on):
            return "mdi:circle-outline"
        if self.is_on:
            return "mdi:white-balance-sunny"
        return "mdi:circle-medium"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the LED on."""
        await self.comm.async_set_led_outp(self._module.addr, self._nmbr, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the LED off."""
        await self.comm.async_set_led_outp(self._module.addr, self._nmbr, 0)


class HbtnFlag(CoordinatorEntity[HbtnCoordinator], SwitchEntity):
    """Representation of a Habitron flag (module or router) as a switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_has_entity_name = True
    _attr_translation_key = "habitron_flag"

    def __init__(
        self,
        coordinator: HbtnCoordinator,
        flag: Flag,
        *,
        device_uid: str,
        mod_addr: int,
        idx: int,
    ) -> None:
        """Initialize the flag switch (router flags use the router address)."""
        super().__init__(coordinator, context=idx)
        self.idx = idx
        self._flag = flag
        self._mod_addr = mod_addr
        self._nmbr = flag.nmbr
        self._attr_name = flag.name
        self._attr_unique_id = f"Mod_{device_uid}_flag{flag.nmbr}"
        self._attr_device_info = hbtn_device_info(device_uid)

    async def async_added_to_hass(self) -> None:
        """Subscribe to the flag's change notifications."""
        await super().async_added_to_hass()
        self._flag.add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe the flag listener."""
        self._flag.remove_listener(self.async_write_ha_state)
        await super().async_will_remove_from_hass()

    @property
    def is_on(self) -> bool:
        """Return whether the flag is set."""
        return self._flag.value == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the flag."""
        await self.coordinator.comm.async_set_flag(self._mod_addr, self._nmbr, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Clear the flag."""
        await self.coordinator.comm.async_set_flag(self._mod_addr, self._nmbr, 0)


class ClimateCtlSwitch(CoordinatorEntity[HbtnCoordinator], SwitchEntity):
    """Switch to select the second climate controller of a Smart Controller."""

    _attr_has_entity_name = True
    _attr_translation_key = "climate_ctl"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: HbtnCoordinator, module: Module, idx: int = 0
    ) -> None:
        """Initialize the climate-control switch."""
        super().__init__(coordinator, context=idx)
        self.idx = idx
        self._module = module
        self._attr_unique_id = f"Mod_{module.uid}_Climate Controller 2"
        self._attr_name = "Climate Controller 2"
        self._attr_entity_registry_enabled_default = False
        self._attr_device_info = hbtn_device_info(module.uid)

    @property
    def is_on(self) -> bool:
        """Return whether the second climate controller is active."""
        return self._module.climate_ctl12 == 2

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Activate the second climate controller."""
        self._module.climate_ctl12 = 2
        await self.coordinator.comm.async_set_climate_mode(
            self._module.addr, self._module.climate_settings, self._module.climate_ctl12
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Activate the first climate controller."""
        self._module.climate_ctl12 = 1
        await self.coordinator.comm.async_set_climate_mode(
            self._module.addr, self._module.climate_settings, self._module.climate_ctl12
        )


class MicrophoneSwitch(SwitchEntity):
    """Switch to toggle the WebRTC microphone of a Smart Controller Touch."""

    _attr_has_entity_name = True
    _attr_translation_key = "microphone"

    def __init__(self, module: Module, provider: HabitronWebRTCProvider) -> None:
        """Initialize the microphone switch."""
        self._module = module
        self._name = "Microphone Mode"
        self._stream_name = module.name.lower().replace(" ", "_")
        self._provider = provider
        self._attr_unique_id = f"Mod_{module.uid}_{self._name}"
        self._attr_name = "Microphone Mode"
        self._state = False

    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return hbtn_device_info(self._module.uid)

    @property
    def is_on(self) -> bool:
        """Return the microphone mode state."""
        return self._state

    def _send_audio_mode(self, *, enabled: bool) -> None:
        """Send the audio-mode command over the module's websocket, if open."""
        ws_connection = self._provider.active_ws_connections.get(self._stream_name)
        if ws_connection:
            ws_connection.send_message(
                {"type": "habitron/set_webrtc_audio_mode", "audio_enabled": enabled}
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the microphone."""
        self._send_audio_mode(enabled=True)
        self._state = True

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the microphone."""
        self._send_audio_mode(enabled=False)
        self._state = False
