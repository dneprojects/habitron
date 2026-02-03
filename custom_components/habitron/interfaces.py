"""Module interfaces."""

# Contains interface descriptors for single entities, e.g. outputs, sensors

from collections.abc import Callable

from homeassistant.util import slugify


class IfDescriptor:
    """Habitron interface descriptor."""

    def __init__(
        self, iname: str, inmbr: int, itype: int, ivalue: float, iarea: int = 0
    ) -> None:
        """Initialize interface."""
        self.name: str = iname
        self.nmbr: int = inmbr
        self.type: int = itype
        self.area: int = iarea  # area number, 0 = device area
        if isinstance(ivalue, list):
            pass
        else:
            self.value: int | float = ivalue
        self._callbacks = set()

    def register_callback(self, callback: Callable[[], None]) -> None:
        """Register callback, called when entity changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback: Callable[[], None]) -> None:
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    async def handle_upd_event(self, *args) -> None:
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

    def set_name(self, new_name: str):
        """Setter for name property."""
        self.name = new_name


class CLedDescriptor(IfDescriptor):
    """Habitron cover interface descriptor."""

    def __init__(self, iname: str, inmbr: int, itype: int, ivalue: list[int]) -> None:
        """Initialize interface."""
        super().__init__(iname, inmbr, itype, ivalue[0])
        self.value: list[int] = ivalue


class CovDescriptor(IfDescriptor):
    """Habitron cover interface descriptor."""

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

    def __init__(self, cname, cnmbr) -> None:
        """Initialize interface."""
        super().__init__(cname, cnmbr, 0, 0)


class AreaDescriptor(IfDescriptor):
    """Habitron area descriptor."""

    def __init__(self, aname, anmbr) -> None:
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

    def __init__(self, lname, lidx, lnmbr, ltype, lvalue) -> None:
        """Initialize interface."""
        super().__init__(lname, lnmbr, ltype, lvalue)
        self.idx: int = lidx


class StateDescriptor(IfDescriptor):
    """Descriptor for modes and flags."""

    def __init__(self, sname, sidx, snmbr, stype, svalue) -> None:
        """Initialize interface."""
        super().__init__(sname, snmbr, stype, svalue)
        self.idx: int = sidx


TYPE_DIAG = 10  # entity will not show up by default
