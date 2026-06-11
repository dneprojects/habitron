"""Shared helpers for the Habitron entity platforms.

* ``async_assign_entity_area`` pushes an entity's HA area derived from
  the bus-side ``area_index`` / module ``area_member`` / router-collected
  ``area_names`` into the registry. The mapping is identical across all
  Habitron platforms — only the entity-domain string and the unique_id
  pattern differ.
* ``hbtn_device_info`` builds the ``DeviceInfo`` dict that every Habitron
  entity uses to link itself to the matching module device.
"""

from __future__ import annotations

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .interfaces import AreaDescriptor


def hbtn_device_info(uid: str) -> DeviceInfo:
    """Return the ``DeviceInfo`` dict that links an entity to its Habitron device.

    All Habitron entities live underneath the module identified by
    ``(DOMAIN, uid)`` in the HA device registry.
    """
    return {"identifiers": {(DOMAIN, uid)}}


def async_assign_entity_area(
    registry: er.EntityRegistry,
    *,
    domain: str,
    unique_id: str,
    area_index: int,
    area_member: int,
    area_names: dict[int, AreaDescriptor],
    propagate_to_hidden_duplicates: bool = False,
) -> None:
    """Push the entity identified by (domain, unique_id) into the right HA area.

    ``area_index`` is the bus-side area number that came down from the
    module description. When it falls outside the known area-name map,
    or matches the module's own ``area_member``, the entity is reset to
    the "no area" default. Otherwise the entity is moved into the area
    whose slug ``area_names[area_index].get_name_id()`` returns.

    ``propagate_to_hidden_duplicates`` extends the same area to every
    *hidden* entity on the same device that shares the original name —
    needed by platforms (currently ``switch``) where bus updates create
    duplicate hidden entities that would otherwise drift out of sync.
    """
    entity_entry = registry.async_get_entity_id(domain, DOMAIN, unique_id)
    if not entity_entry:
        return
    if area_index not in area_names:
        area_index = 0
    target_area = (
        None if area_index in (0, area_member) else area_names[area_index].get_name_id()
    )
    registry.async_update_entity(entity_entry, area_id=target_area)
    if not propagate_to_hidden_duplicates:
        return
    entity = registry.async_get(entity_entry)
    if entity is None or not entity.hidden or entity.device_id is None:
        return
    for dev_entity in er.async_entries_for_device(registry, entity.device_id):
        if dev_entity.original_name == entity.original_name:
            registry.async_update_entity(dev_entity.entity_id, area_id=target_area)
