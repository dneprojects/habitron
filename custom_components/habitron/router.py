"""Habitron router class."""
from __future__ import annotations
from enum import Enum

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import RoutIdx
from .communicate import HbtnComm as hbtn_com

# In a real implementation, this would be in an external library that's on PyPI.
# The PyPI package needs to be included in the `requirements` section of manifest.json
# See https://developers.home-assistant.io/docs/creating_integration_manifest
# for more information.
from .const import DOMAIN, SMARTIP_COMMAND_STRINGS, MODULE_CODES
from .module import ModuleDescriptor
from .module import (
    HbtnModule as hbtm,
    SmartController as hbtscm,
    SmartDetect as hbtsdm,
    SmartInput as hbtinm,
    SmartNature as hbtsnm,
    SmartOutput as hbtoutm,
    SmartDimm as hbtdimm,
    SmartUpM as hbtupm,
)
from .coordinator import HbtnCoordinator


class CmdDescriptor:
    """Habitron interface descriptor."""

    def __init__(self, cname, cnmbr):
        self.name: str = cname
        self.nmbr: int = cnmbr


class StateDescriptor:
    """Descriptor for modes and flags"""

    def __init__(self, sname, sidx, snmbr, svalue):
        self.name: str = sname
        self.idx: int = sidx
        self.nmbr: int = snmbr
        self.value: bool = svalue


class DaytimeMode(Enum):
    """Habitron daytime mode states"""

    Day = 1
    Night = 2


class AlarmMode(Enum):
    """Habitron alarm mode states"""

    Off = 0
    On = 4


class GroupMode(Enum):
    """Habitron group mode states"""

    Absent = 16
    Present = 32
    Sleeping = 48
    Summer = 80
    User1 = 96
    User2 = 112


class HbtnRouter:
    """Habitron Router class."""

    manufacturer = "Habitron GmbH"

    def __init__(self, hass: HomeAssistant, config: ConfigEntry) -> None:
        """Init habitron router."""
        self.id = 1
        self.hass = hass
        self.config = config
        self.comm = hbtn_com(hass, config)
        self.coord = HbtnCoordinator(hass, self.comm)
        self.name = "Router"
        self.version = "0.0.0"
        self.status = ""
        self.smr = ""
        self.chan_list = []
        self.module_grp = []
        self.max_group = 0
        self.modules_desc = []
        self.modules = []
        self.coll_commands: list[CmdDescriptor] = []
        self.vis_commands: list[CmdDescriptor] = []
        self.flags: list[CmdDescriptor] = []
        self.user1_name = "user1"
        self.user2_name = "user2"
        self.sys_status = ""
        self.mode0 = 0x11
        self.mod_reg = dict()

    async def initialize(self) -> bool:
        """Initialize router instance"""

        self.status = self.get_status()
        self.smr = await self.get_smr()
        self.version = self.smr[-22 : len(self.smr)].decode("iso8859-1")
        self.parse_smr()

        device_registry = dr.async_get(self.hass)
        device_registry.async_get_or_create(
            config_entry_id=self.config.entry_id,
            identifiers={(DOMAIN, self.name)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self.name,
            model="Smart Router",
            sw_version=self.version,
            hw_version=self.version,
        )
        self.comm.set_router(self)
        # Further initialization of module instances
        self.comm.send_command(SMARTIP_COMMAND_STRINGS["START_MIRROR"])
        self.modules_desc = await self.get_modules(self.module_grp)
        await self.comm.async_system_update()

        for mod_desc in self.modules_desc:
            if mod_desc.mtype == "Smart Controller":
                self.modules.append(hbtscm(mod_desc, self.hass, self.config))
            elif mod_desc.mtype[0:9] == "Smart Out":
                self.modules.append(hbtoutm(mod_desc, self.hass, self.config))
            elif mod_desc.mtype[0:9] == "Smart Dimm":
                self.modules.append(hbtdimm(mod_desc, self.hass, self.config))
            elif mod_desc.mtype[0:9] == "Smart UpM":
                self.modules.append(hbtupm(mod_desc, self.hass, self.config))
            elif mod_desc.mtype[0:8] == "Smart In":
                self.modules.append(hbtinm(mod_desc, self.hass, self.config))
            elif mod_desc.mtype[0:12] == "Smart Detect":
                self.modules.append(hbtsdm(mod_desc, self.hass, self.config))
            elif mod_desc.mtype == "Smart Nature":
                self.modules.append(hbtsnm(mod_desc, self.hass, self.config))
            else:
                self.modules.append(hbtm(mod_desc, self.hass, self.config))
            await self.modules[-1].initialize(self.sys_status)

        await self.get_descriptions()
        return True

    def get_status(self) -> bool:
        """Get router status."""
        resp = self.comm.send_command(SMARTIP_COMMAND_STRINGS["GET_ROUTER_STATUS"])
        router_string = resp.decode("iso8859-1")
        if router_string[0:5] == "Error":
            return "Error"
        return resp

    async def get_smr(self) -> bool:
        """Get router smr."""
        resp = await self.comm.async_send_command(
            SMARTIP_COMMAND_STRINGS["GET_ROUTER_SMR"]
        )
        router_string = resp.decode("iso8859-1")
        if router_string[0:5] == "Error":
            return "Error"
        return resp

    def parse_smr(self) -> None:
        """Parse router smr info and set values"""
        # self.group_list = []
        ptr = 1
        max_mod_no = 0
        for ch_i in range(4):
            count = self.smr[ptr]
            self.chan_list.append(sorted(list(self.smr[ptr + 1 : ptr + count + 1])))
            max_mod_no = max(max_mod_no, max(self.chan_list[ch_i]))
            ptr += 1 + count
        ptr += 2
        self.max_group = max(list(self.smr[ptr : ptr + 64]))
        # self.group_list: list[int] = [[]] * (max_group + 1)
        for mod_i in range(max_mod_no):
            grp_no = int(self.smr[ptr + mod_i])
            self.module_grp.append(grp_no)
        ptr += 129
        str_len = self.smr[ptr]
        self.name = self.smr[ptr + 1 : ptr + 1 + str_len].decode("iso8859-1").strip()
        ptr += str_len + 1
        str_len = self.smr[ptr]
        self.user1_name = (
            self.smr[ptr + 1 : ptr + 1 + str_len].decode("iso8859-1").strip()
        )
        ptr += str_len + 1
        str_len = self.smr[ptr]
        self.user2_name = (
            self.smr[ptr + 1 : ptr + 1 + str_len].decode("iso8859-1").strip()
        )
        ptr += str_len + 1

    async def get_descriptions(self) -> str | None:
        """Get descriptions of commands etc"""
        cmd_str = SMARTIP_COMMAND_STRINGS["GET_GLOBAL_DESCRIPTIONS"]
        resp = await self.comm.async_send_command(cmd_str)

        no_lines = int.from_bytes(resp[0:2], "little")
        resp = resp[4 : len(resp)]  # Strip 4 header bytes
        for _ in range(no_lines):
            if resp == b"":
                break
            line_len = int(resp[8]) + 9
            line = resp[0:line_len]
            content_code = int.from_bytes(line[1:3], "little")
            entry_no = int(line[3])
            entry_name = line[9:line_len].decode("iso8859-1").strip()
            if content_code == 767:  # FF 02: global flg (Merker)
                self.flags.append(
                    StateDescriptor(entry_name, len(self.flags), entry_no, 0)
                )
            elif content_code == 1023:  # FF 03: collective commands (Sammelbefehle)
                self.coll_commands.append(CmdDescriptor(entry_name, entry_no))
            else:
                mod_addr = int(line[1])
                if int(line[2]) == 1:
                    # local flag (Merker)
                    self.modules[self.mod_reg[mod_addr]].flags.append(
                        StateDescriptor(
                            entry_name,
                            len(self.modules[self.mod_reg[mod_addr]].flags),
                            entry_no,
                            0,
                        )
                    )  # vis command
                elif int(line[2]) == 4:
                    # local visualization event
                    entry_no = int.from_bytes(resp[3:5], "little")
                    self.modules[self.mod_reg[mod_addr]].commands.append(
                        CmdDescriptor(entry_name, entry_no)
                    )  # vis command
                elif int(line[2]) == 5:
                    # logic element
                    self.modules[self.mod_reg[mod_addr]].logic[
                        entry_no - 1
                    ].name = entry_name  # counter
            resp = resp[line_len : len(resp)]

    async def update_system_status(self, sys_status) -> None:
        """Distribute module status to all modules and update self status"""
        self.sys_status = sys_status
        self.status = self.get_status()
        self.mode0 = int(self.status[RoutIdx.MODE0])
        flags_state = int.from_bytes(
            self.status[RoutIdx.FLAG_GLOB : RoutIdx.FLAG_GLOB + 2],
            "little",
        )
        for flg in self.flags:
            flg.value = int((flags_state & (0x01 << flg.nmbr - 1)) > 0)
        for module in self.modules:
            module.update(self.sys_status)
        return

    async def get_modules(self, mod_groups) -> list[ModuleDescriptor]:
        """Get summary of all Habitron modules."""

        desc: list[ModuleDescriptor] = []
        addr_dict = dict()
        resp = await self.comm.async_send_command(
            SMARTIP_COMMAND_STRINGS["GET_MODULES"]
        )
        mod_string = resp.decode("iso8859-1")
        if mod_string[0:5] == "Error":
            return False
        while len(resp) > 0:
            mod_addr = int(resp[0])
            mod_type = MODULE_CODES.get(mod_string[1:3], "Unknown Controller")
            name_len = int(resp[3])
            mod_name = mod_string[4 : 4 + name_len]
            mod_group = mod_groups[mod_addr - 1]
            desc.append(ModuleDescriptor(mod_addr, mod_type, mod_name, mod_group))
            addr_dict[mod_addr] = len(desc) - 1
            mod_string = mod_string[4 + name_len : len(resp)]
            resp = resp[4 + name_len : len(resp)]
        self.mod_reg = addr_dict
        return desc

    def get_comm_errors(self) -> bytes:
        """Get current communication errors"""
        resp = self.comm.send_command(SMARTIP_COMMAND_STRINGS["GET_CURRENT_ERROR"])
        error_list = list()
        err_cnt = resp[0]
        for e_idx in range(err_cnt):
            error_list.append({resp[2 * e_idx + 1], resp[2 * e_idx + 2]})
        return error_list
