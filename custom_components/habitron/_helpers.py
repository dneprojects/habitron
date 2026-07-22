"""Shared helpers for the Habitron entity platforms.

* :class:`HabitronEntity` is the common base for every coordinator-driven
  Habitron entity: it links to the module device and binds a model member's
  change listener to ``async_write_ha_state`` (the v2 ``habitron_client`` model
  fires per-member listeners instead of the old descriptor callbacks).
* ``HbtnAreaMixin`` / ``deviating_area_id`` stamp an entity's deviating HA area
  (derived from the bus-side area index / module / router area names) once, at
  first creation, from ``async_added_to_hass``.
* ``hbtn_device_info`` builds the ``DeviceInfo`` dict linking an entity to its
  module device.
"""

from typing import TYPE_CHECKING

from habitron_client import BusMember, Module

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


def deviating_area_id(
    area_index: int, area_member: int, area_ids: dict[int, str]
) -> str | None:
    """Return the HA area id an entity deviates into, or ``None``.

    ``area_index`` is the bus-side area number. It is a real deviation only when
    it is known and differs from the module's own ``area_member``; otherwise the
    entity inherits the device area (``None``).
    """
    if area_index in (0, area_member) or area_index not in area_ids:
        return None
    return area_ids[area_index]


class HbtnAreaMixin(Entity):
    """Stamp a deviating area onto the entity, once, at first creation.

    The platform sets ``_initial_area_id`` only for a newly-created entity (it
    snapshots the already-registered ids before adding). Applying it here in
    ``async_added_to_hass`` -- which runs *after* the entity is registered,
    unlike a pass right after ``async_add_entities`` -- means the area lands
    reliably on first creation and is never re-stamped on a reload, so a later
    user area move (or clearing it to the device area) survives.

    ``_initial_area_propagate`` extends the area to every *hidden* entity on the
    same device that shares the original name (bus updates create such duplicate
    hidden entities on the ``switch`` platform).
    """

    _initial_area_id: str | None = None
    _initial_area_propagate: bool = False

    async def async_added_to_hass(self) -> None:
        """Apply the first-creation area after the base registration."""
        await super().async_added_to_hass()
        entry = self.registry_entry
        if self._initial_area_id is None or entry is None:
            return
        registry = er.async_get(self.hass)
        registry.async_update_entity(entry.entity_id, area_id=self._initial_area_id)
        if (
            not self._initial_area_propagate
            or not entry.hidden
            or entry.device_id is None
        ):
            return
        for dev_entity in er.async_entries_for_device(registry, entry.device_id):
            if dev_entity.original_name == entry.original_name:
                registry.async_update_entity(
                    dev_entity.entity_id, area_id=self._initial_area_id
                )


if TYPE_CHECKING:
    from .communicate import HbtnComm
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
    def comm(self) -> HbtnComm:
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
