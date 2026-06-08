"""Module interfaces.

Contains interface descriptors for single entities (outputs, sensors, …)
shared across the Habitron bus / Home Assistant boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.util import slugify


class IfDescriptor:
    """Habitron interface descriptor.

    ``value`` carries a per-entity payload — usually a scalar number,
    but subclasses (notably :class:`CLedDescriptor`) override it with
    richer types. It is therefore typed as ``Any`` here so that
    re-assignment by subclasses does not violate the variance rules
    of :pep:`526`.
    """

    def __init__(
        self,
        iname: str,
        inmbr: int,
        itype: int,
        ivalue: float,
        iarea: int = 0,
    ) -> None:
        """Initialize interface."""
        self.name: str = iname
        self.nmbr: int = inmbr
        self.type: int = itype
        self.area: int = iarea  # area number, 0 = device area
        self.value: Any
        if not isinstance(ivalue, list):
            self.value = ivalue
        self._callbacks: set[Callable[..., Any]] = set()

    def register_callback(self, callback: Callable[..., None]) -> None:
        """Register callback, called when entity changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[..., None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    async def handle_upd_event(self, *args: Any) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            if len(args) == 0:
                callback()
            elif len(args) == 1:
                callback(args[0])
            elif len(args) == 2:
                callback(args[0], args[1])
            else:
                callback(args[0], args[1], args[2])

    def set_name(self, new_name: str) -> None:
        """Setter for name property."""
        self.name = new_name


class CLedDescriptor(IfDescriptor):
    """Habitron colour-LED descriptor (RGB value list)."""

    def __init__(self, iname: str, inmbr: int, itype: int, ivalue: list[int]) -> None:
        """Initialize interface."""
        super().__init__(iname, inmbr, itype, ivalue[0])
        self.value: list[int] = ivalue


class CovDescriptor(IfDescriptor):
    """Habitron cover (shutter / blind) interface descriptor."""

    def __init__(
        self,
        iname: str,
        inmbr: int,
        itype: int,
        ivalue: int,
        itilt: int,
        iarea: int = 0,
    ) -> None:
        """Initialize interface."""
        super().__init__(iname, inmbr, itype, ivalue, iarea)
        self.tilt: int = itilt


class CmdDescriptor(IfDescriptor):
    """Habitron command descriptor."""

    def __init__(self, cname: str, cnmbr: int) -> None:
        """Initialize interface."""
        super().__init__(cname, cnmbr, 0, 0)


class AreaDescriptor(IfDescriptor):
    """Habitron area descriptor."""

    def __init__(self, aname: str, anmbr: int) -> None:
        """Initialize interface."""
        super().__init__(aname, anmbr, 0, 0)

    def get_name(self) -> str:
        """Get area name."""
        return self.name

    def get_name_id(self) -> str:
        """Get area id."""
        return slugify(self.name)


class LgcDescriptor(IfDescriptor):
    """Habitron logic descriptor."""

    def __init__(
        self,
        lname: str,
        lidx: int,
        lnmbr: int,
        ltype: int,
        lvalue: float,
    ) -> None:
        """Initialize interface."""
        super().__init__(lname, lnmbr, ltype, lvalue)
        self.idx: int = lidx


class StateDescriptor(IfDescriptor):
    """Descriptor for modes and flags."""

    def __init__(
        self,
        sname: str,
        sidx: int,
        snmbr: int,
        stype: int,
        svalue: bool | int,
    ) -> None:
        """Initialize interface."""
        super().__init__(sname, snmbr, stype, int(svalue))
        self.idx: int = sidx


TYPE_DIAG = 10  # entity will not show up by default
