"""Shared helpers for the Habitron entity platforms.

* :class:`HabitronEntity` is the common base for every coordinator-driven
  Habitron entity: it links to the module device and binds a model member's
  change listener to ``async_write_ha_state`` (the v2 ``habitron_client`` model
  fires per-member listeners instead of the old descriptor callbacks).
* ``async_assign_entity_area`` pushes an entity's HA area (derived from the
  bus-side area index / module area / router area names) into the registry.
* ``hbtn_device_info`` builds the ``DeviceInfo`` dict linking an entity to its
  module device.
"""

from typing import TYPE_CHECKING

from habitron_client import BusMember, Module

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import HbtnCoordinator


def hbtn_device_info(uid: str) -> DeviceInfo:
    """Return the ``DeviceInfo`` dict that links an entity to its Habitron device.

    All Habitron entities live underneath the module identified by
    ``(DOMAIN, uid)`` in the HA device registry.
    """
    return {"identifiers": {(DOMAIN, uid)}}


class HabitronEntity(CoordinatorEntity["HbtnCoordinator"]):
    """Base for Habitron entities bound to a single model member.

    Holds the parsed :class:`~habitron_client.Module` and one of its members,
    links to the module device and—on add—subscribes the member's change
    listener so the SmartHub's pushed updates write HA state immediately. The
    transport is reached through ``self.comm`` (the coordinator owns it); the
    model itself carries no back-reference.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HbtnCoordinator,
        module: Module,
        member: BusMember,
        idx: int,
    ) -> None:
        """Initialize and link the entity to its module device."""
        super().__init__(coordinator, context=idx)
        self.idx = idx
        self._module = module
        self._member = member
        self._attr_device_info = hbtn_device_info(module.uid)

    @property
    def comm(self) -> object:
        """Return the transport wrapper held by the coordinator."""
        return self.coordinator.comm

    async def async_added_to_hass(self) -> None:
        """Subscribe to the member's change notifications (push updates)."""
        await super().async_added_to_hass()
        self._member.add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe the member listener."""
        self._member.remove_listener(self.async_write_ha_state)
        await super().async_will_remove_from_hass()


def async_assign_entity_area(
    registry: er.EntityRegistry,
    *,
    domain: str,
    unique_id: str,
    area_index: int,
    area_member: int,
    area_names: dict[int, str],
    propagate_to_hidden_duplicates: bool = False,
) -> None:
    """Push the entity identified by (domain, unique_id) into the right HA area.

    ``area_index`` is the bus-side area number from the module description.
    ``area_names`` maps a bus area number to its slugified HA area id (the
    consumer slugifies ``Area.name`` — the library carries only number + name).
    When ``area_index`` is unknown or equals the module's own ``area_member``,
    the entity is reset to the "no area" default; otherwise it is moved into the
    matching area.

    ``propagate_to_hidden_duplicates`` extends the same area to every *hidden*
    entity on the same device that shares the original name — needed by platforms
    (currently ``switch``) where bus updates create duplicate hidden entities.
    """
    entity_entry = registry.async_get_entity_id(domain, DOMAIN, unique_id)
    if not entity_entry:
        return
    if area_index not in area_names:
        area_index = 0
    target_area = None if area_index in (0, area_member) else area_names[area_index]
    registry.async_update_entity(entity_entry, area_id=target_area)
    if not propagate_to_hidden_duplicates:
        return
    entity = registry.async_get(entity_entry)
    if entity is None or not entity.hidden or entity.device_id is None:
        return
    for dev_entity in er.async_entries_for_device(registry, entity.device_id):
        if dev_entity.original_name == entity.original_name:
            registry.async_update_entity(dev_entity.entity_id, area_id=target_area)
