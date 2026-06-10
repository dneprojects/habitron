"""Platform for select integration."""

from enum import Enum

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import DOMAIN
from .coordinator import HabitronConfigEntry
from .interfaces import IfDescriptor
from .module import HbtnModule
from .router import AlarmMode, DaytimeMode, HbtnRouter
from .smart_hub import LoggingLevels, SmartHub

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HabitronConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add input_select for passed config_entry in HA."""
    hbtn_rt: HbtnRouter = entry.runtime_data.router
    hbtn_cord: DataUpdateCoordinator[None] = hbtn_rt.coord
    smhub = entry.runtime_data

    new_devices: list[SelectEntity] = []
    for hbt_module in hbtn_rt.modules:
        if hbt_module.mod_type[:16] == "Smart Controller":
            # Mode setting is per group, entities linked to smart controllers only
            new_devices.append(
                HbtnSelectDaytimeModePush(
                    hbt_module, hbtn_rt, hbtn_cord, len(new_devices)
                )
            )
            new_devices.append(
                HbtnSelectAlarmModePush(
                    hbt_module, hbtn_rt, hbtn_cord, len(new_devices)
                )
            )
            new_devices.append(
                HbtnSelectGroupModePush(
                    hbt_module, hbtn_rt, hbtn_cord, len(new_devices)
                )
            )
    new_devices.append(
        HbtnSelectDaytimeModePush(0, hbtn_rt, hbtn_cord, len(new_devices))
    )
    new_devices.append(HbtnSelectAlarmModePush(0, hbtn_rt, hbtn_cord, len(new_devices)))
    new_devices.append(HbtnSelectGroupModePush(0, hbtn_rt, hbtn_cord, len(new_devices)))
    for log_level in smhub.loglvl:
        new_devices.append(
            HbtnSelectLoggingLevel(smhub, log_level, hbtn_cord, len(new_devices))
        )

    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    if new_devices:
        async_add_entities(new_devices)


class HbtnMode(CoordinatorEntity[DataUpdateCoordinator[None]], SelectEntity):
    """Representation of a input select for Habitron modes."""

    _attr_has_entity_name = True

    def __init__(
        self,
        module: int | HbtnModule,
        hbtnr: HbtnRouter,
        coord: DataUpdateCoordinator[None],
        idx: int,
    ) -> None:
        """Initialize a Habitron mode, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._module: HbtnModule | HbtnRouter = (
            hbtnr if isinstance(module, int) else module
        )
        self._mode = (
            int(hbtnr.mode.value) if isinstance(module, int) else int(module.mode.value)
        )
        self._current_option = ""
        self.hbtnr = hbtnr
        self._attr_translation_key = "habitron_mode"
        self._value = 0
        self._enum: type[Enum] = DaytimeMode
        self._mask: int = 0

    @property
    def available(self) -> bool:
        """Set true to let HA know that this entity is online."""
        return True

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        if isinstance(self._module, HbtnRouter):
            return {"identifiers": {(DOMAIN, self.hbtnr.uid)}}
        return {"identifiers": {(DOMAIN, self._module.uid)}}

    @property
    def name(self) -> str | None:
        """Return the display name of this selector."""
        return self._attr_name

    @property
    def options(self) -> list[str]:
        """Return all mode names of enumeration type."""
        return [mode.name for mode in self._enum]

    @property
    def current_option(self) -> str:
        """Return the current mode name."""
        return self._current_option

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator, get current module mode."""
        self._mode = int(self._module.mode.value)
        if self._mode == 0:
            # should not be the case
            return
        self._value = self._mode & self._mask
        if self._value not in [c.value for c in self._enum]:
            self.hbtnr.logger.warning(f"Could not find {self._value} in mode enum")
            return
        self._current_option = self._enum(self._value).name
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        mode_val = self._enum[option].value
        self._mode = (int(self._module.mode.value) & (0xFF - self._mask)) + mode_val
        if isinstance(self._module, HbtnRouter):
            # Router-level mode change targets group 0.
            await self.hbtnr.comm.async_set_group_mode(0, self._mode)
        else:
            await self._module.comm.async_set_group_mode(self._module.group, self._mode)


class HbtnSelectDaytimeMode(HbtnMode):
    """Daytime mode object."""

    def __init__(
        self,
        module: int | HbtnModule,
        hbtnr: HbtnRouter,
        coord: DataUpdateCoordinator[None],
        idx: int,
    ) -> None:
        """Initialize daytime mode selector."""
        super().__init__(module, hbtnr, coord, idx)
        self._mask = 0x03
        self._enum = DaytimeMode
        self._value = self._mode & self._mask
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if isinstance(self._module, HbtnRouter):
            self._attr_name = "Group 0 daytime"
            self._attr_unique_id = f"Rt_{self.hbtnr.uid}_group_0_daytime_mode"
            if self._value == 0:
                # hot fix: why is mode 0?
                hbtnr.logger.info("Enum value 0 for router")
                self._value = 1
            self._current_option = self._enum(self._value).name
        else:
            self._attr_name = f"Group {self._module.group} daytime"
            self._attr_unique_id = f"Mod_{self._module.uid}_daytime_mode"
            self._attr_entity_registry_enabled_default = (
                False  # Entity will initially be disabled
            )
            if self._value == 0:
                # Not clear, inherit mode of group 0?
                hbtnr.logger.info("Enum value 0 for router daytime mode")
                self._value = 1
            self._current_option = self._enum(self._value).name

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        mode_val = self._enum[option].value
        if isinstance(self._module, HbtnRouter):
            await self.hbtnr.comm.async_set_daytime_mode(0, mode_val)
        else:
            await self._module.comm.async_set_daytime_mode(self._module.group, mode_val)


class HbtnSelectAlarmMode(HbtnMode):
    """Alarm mode object."""

    def __init__(
        self,
        module: int | HbtnModule,
        hbtnr: HbtnRouter,
        coord: DataUpdateCoordinator[None],
        idx: int,
    ) -> None:
        """Initialize alarm mode selector."""
        super().__init__(module, hbtnr, coord, idx)
        self._mask = 0x04
        self._enum = AlarmMode
        self._value = self._mode & self._mask
        self._current_option = self._enum(self._value).name
        if isinstance(self._module, HbtnRouter):
            self._attr_name = "Group 0 alarm"
            self._attr_unique_id = f"Rt_{self.hbtnr.uid}_group_0_alarm_mode"
        else:
            self._attr_name = f"Group {self._module.group} alarm"
            self._attr_unique_id = f"Mod_{self._module.uid}_alarm_mode"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        set_val = bool(self._enum[option].value > 0)
        if isinstance(self._module, HbtnRouter):
            await self.hbtnr.comm.async_set_alarm_mode(0, set_val)
        else:
            await self._module.comm.async_set_alarm_mode(self._module.group, set_val)


class HbtnSelectGroupMode(HbtnMode):
    """Group mode object."""

    def __init__(
        self,
        module: int | HbtnModule,
        hbtnr: HbtnRouter,
        coord: DataUpdateCoordinator[None],
        idx: int,
    ) -> None:
        """Initialize group mode selector."""
        super().__init__(module, hbtnr, coord, idx)
        self._mask = 0xF0
        self.hbtnr = hbtnr
        user1_name = hbtnr.user1_name
        user2_name = hbtnr.user2_name
        if not user1_name.isprintable():
            user1_name = "Unbekannt"
        if not user2_name.isprintable():
            user2_name = "Unbekannt"
        if user1_name == user2_name:
            # e.g. both "UNBEKANNT"
            user2_name += "2"
        group_enum = Enum(  # type: ignore[misc]
            value="group_enum",
            names=[
                ("absent", 16),
                ("present", 32),
                ("sleeping", 48),
                ("update", 63),
                ("config", 64),
                (user1_name, 80),
                (user2_name, 96),
                ("vacation", 112),
            ],
        )
        self._enum = group_enum
        self._value = self._mode & self._mask
        if self._value == 0:
            self._value = 32
        self._current_option = self._enum(self._value).name
        if isinstance(self._module, HbtnRouter):
            self._attr_name = "Group 0 mode"
            self._attr_unique_id = f"Rt_{self.hbtnr.uid}_group_0_mode"
        else:
            self._attr_name = f"Group {self._module.group} mode"
            self._attr_unique_id = f"Mod_{self._module.uid}_group_mode"

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        set_val = self._enum[option].value
        if isinstance(self._module, HbtnRouter):
            await self.hbtnr.comm.async_set_group_mode(0, set_val)
        else:
            await self._module.comm.async_set_group_mode(self._module.group, set_val)


class HbtnSelectDaytimeModePush(HbtnSelectDaytimeMode):
    """Push version of group mode object."""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        await super().async_added_to_hass()
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        if isinstance(self._module, HbtnModule):
            self._module.mode.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        if isinstance(self._module, HbtnModule):
            self._module.mode.remove_callback(self._handle_coordinator_update)


class HbtnSelectAlarmModePush(HbtnSelectAlarmMode):
    """Push version of group mode object."""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        await super().async_added_to_hass()
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        if isinstance(self._module, HbtnModule):
            self._module.mode.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        if isinstance(self._module, HbtnModule):
            self._module.mode.remove_callback(self._handle_coordinator_update)


class HbtnSelectGroupModePush(HbtnSelectGroupMode):
    """Push version of group mode object."""

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        await super().async_added_to_hass()
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        if isinstance(self._module, HbtnModule):
            self._module.mode.register_callback(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        if isinstance(self._module, HbtnModule):
            self._module.mode.remove_callback(self._handle_coordinator_update)


class HbtnSelectLoggingLevel(
    CoordinatorEntity[DataUpdateCoordinator[None]], SelectEntity
):
    """Logging level object."""

    _attr_has_entity_name = True

    def __init__(
        self,
        smhub: SmartHub,
        level: IfDescriptor,
        coord: DataUpdateCoordinator[None],
        idx: int,
    ) -> None:
        """Initialize a Habitron mode, pass coordinator to CoordinatorEntity."""
        super().__init__(coord, context=idx)
        self.idx = idx
        self._level = level
        self._nmbr = level.nmbr
        self._value = level.value
        self._smhub = smhub
        self._current_option = ""
        self._enum = LoggingLevels
        self._attr_name = level.name
        self._attr_unique_id = f"Hub_{self._smhub.uid}_{level.name.replace(' ', '')}"
        self._attr_translation_key = "habitron_loglevel"

    @property
    def available(self) -> bool:
        """Set true to let HA know that this entity is online."""
        return True

    # To link this entity to its device, this property must return an
    # identifiers value matching that used in the module
    @property
    def device_info(self) -> DeviceInfo:
        """Return information to link this entity with the correct device."""
        return {"identifiers": {(DOMAIN, self._smhub.uid)}}

    @property
    def name(self) -> str | None:
        """Return the display name of this selector."""
        return self._attr_name

    @property
    def options(self) -> list[str]:
        """Return all mode names of enumeration type."""
        return [level.name for level in self._enum]

    @property
    def current_option(self) -> str:
        """Return the current mode name."""
        return self._current_option

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator, get current module mode."""
        self._value = int(self._level.value / 10)
        self._current_option = self._enum(int(self._level.value / 10)).name
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        self._value = self._enum[option].value
        # nmbr used to select console/file handler
        await self._smhub.comm.async_set_log_level(self._nmbr, self._value * 10)
