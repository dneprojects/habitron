"""Module interfaces"""

# Contains interface descriptors for single entities, e.g. outputs, sensors


class IfDescriptor:
    """Habitron interface descriptor."""

    def __init__(self, iname, inmbr, itype, ivalue) -> None:
        self.name: str = iname
        self.nmbr: int = inmbr
        self.type: int = itype
        self.value: int = ivalue


class IfDescriptorC:
    """Habitron cover interface descriptor."""

    def __init__(self, iname, inmbr, itype, ivalue, itilt) -> None:
        self.name: str = iname
        self.nmbr: int = inmbr
        self.type: int = itype
        self.value: int = ivalue
        self.tilt: int = itilt


class CmdDescriptor:
    """Habitron command descriptor."""

    def __init__(self, cname, cnmbr) -> None:
        self.name: str = cname
        self.nmbr: int = cnmbr


class StateDescriptor:
    """Descriptor for modes and flags"""

    def __init__(self, sname, sidx, snmbr, svalue) -> None:
        self.name: str = sname
        self.idx: int = sidx
        self.nmbr: int = snmbr
        self.value: bool = svalue


TYPE_DIAG = 10  # entity will not show up by default
