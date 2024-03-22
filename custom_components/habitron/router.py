"""Habitron router class."""
from __future__ import annotations

from enum import Enum
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

# for more information.
from .const import DOMAIN, FALSE_VAL, TRUE_VAL, ModuleDescriptor, MStatIdx, RoutIdx
from .coordinator import HbtnCoordinator
from .interfaces import TYPE_DIAG, CmdDescriptor, IfDescriptor, StateDescriptor
from .module import (
    HbtnModule,
    SmartController as hbtscm,
    SmartControllerMini as hbtscmm,
    SmartDetect as hbtsdm,
    SmartDimm as hbtdimm,
    SmartEKey as hbtkey,
    SmartInput as hbtinm,
    SmartNature as hbtsnm,
    SmartOutput as hbtoutm,
    SmartUpM as hbtupm,
)


class DaytimeMode(Enum):
    """Habitron daytime mode states."""

    day = 1
    night = 2
    undefined = 3


class AlarmMode(Enum):
    """Habitron alarm mode states."""

    off = 0
    on = 4


class GroupMode(Enum):
    """Habitron group mode states."""

    absent = 16
    present = 32
    sleeping = 48
    update = 63
    config = 64
    summer = 80
    user1 = 96
    user2 = 112


class HbtnRouter:
    """Habitron Router class."""

    manufacturer = "Habitron GmbH"

    def __init__(self, hass: HomeAssistant, config: ConfigEntry, smhub) -> None:
        """Init habitron router."""
        self.id = 100  # to be adapted for more routers
        self.b_uid = smhub.uid
        self.uid = f"rt_{self.b_uid}"
        self.hass: HomeAssistant = hass
        self.config: ConfigEntry = config
        self.smhub = smhub
        self.comm = smhub.comm
        self.logger = logging.getLogger(__name__)
        self.coord: HbtnCoordinator = HbtnCoordinator(hass, self.comm)
        self.name = f"Router {smhub.uid}"
        self.version = ""
        self.serial = ""
        self.status = ""
        self.smr = ""
        self.chan_list = []
        self.module_grp = []
        self.max_group = 0
        self.modules_desc = list
        self.modules: list[HbtnModule] = []
        self.coll_commands: list[CmdDescriptor] = []
        self.flags: list[StateDescriptor] = []
        self.chan_timeouts = [
            IfDescriptor(f"Timeouts channel {i+1}", i, TYPE_DIAG, 0) for i in range(4)
        ]
        self.chan_currents = [
            IfDescriptor(f"Current channel {i+1}", i, TYPE_DIAG, 0) for i in range(8)
        ]
        self.voltages = [IfDescriptor("", i, TYPE_DIAG, 0) for i in range(2)]
        self.voltages[0].name = "Voltage 5V"
        self.voltages[1].name = "Voltage 24V"
        self.states = [StateDescriptor("", i, TYPE_DIAG, True) for i in range(2)]
        self.states[0].name = "System OK"
        self.states[1].name = "Mirror started"
        self.user1_name = "user1"
        self.user2_name = "user2"
        self.sys_status = ""
        self.mode0 = 0x11
        self.mod_reg = {}
        self._sys_ok = True
        self._mirror_started = True

    async def initialize(self) -> bool:
        """Initialize router instance."""

        self.comm.set_router(self)
        await self.get_definitions()

        device_registry = dr.async_get(self.hass)
        device_registry.async_get_or_create(
            config_entry_id=self.config.entry_id,
            configuration_url=f"http://{self.comm.com_ip}:7780/router",
            identifiers={(DOMAIN, self.uid)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self.name,
            model="Smart Router",
            sw_version=self.version,
            hw_version=self.serial,
            via_device=(DOMAIN, self.smhub.uid),
        )
        # Further initialization of module instances
        if not self.comm.is_smhub:
            await self.comm.async_start_mirror(self.id)
        self.modules_desc = await self.get_modules(self.module_grp)
        await self.comm.async_system_update()  # Inital update

        for mod_desc in self.modules_desc:
            if (mod_desc.mtype[0] == 10) & (mod_desc.mtype[1] in [1, 2, 50, 51]):
                self.modules.append(
                    hbtoutm(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            elif (mod_desc.mtype[0] == 10) & (mod_desc.mtype[1] in [20, 21, 22]):
                self.modules.append(
                    hbtdimm(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            elif (mod_desc.mtype[0] == 10) & (mod_desc.mtype[1] in [30]):
                self.modules.append(
                    hbtupm(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            elif mod_desc.mtype[0] == 11:
                self.modules.append(
                    hbtinm(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            elif mod_desc.mtype[0] == 80:
                self.modules.append(
                    hbtsdm(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            elif mod_desc.mtype[0] == 20:
                self.modules.append(
                    hbtsnm(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            elif mod_desc.mtype[0] == 50:
                self.modules.append(
                    hbtscmm(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            elif mod_desc.mtype[0] == 1:
                self.modules.append(
                    hbtscm(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            elif (mod_desc.mtype[0] == 30) & (mod_desc.mtype[1] == 1):
                self.modules.append(
                    hbtkey(mod_desc, self.hass, self.config, self.b_uid, self.comm)
                )
            else:
                continue  # Prevent dealing with unknown modules
                # self.modules.append(hbtm(mod_desc, self.hass, self.config, self.comm))
            await self.modules[-1].initialize(self.sys_status)

        await self.get_descriptions()  # Some descriptions for modules, too
        return True

    async def get_definitions(self) -> None:
        """Parse router smr info and set values."""
        self.status = await self.comm.async_get_router_status(self.id)
        self.smr = await self.comm.get_smr(self.id)
        # self.group_list = []
        ptr = 1
        max_mod_no = 0
        for ch_i in range(4):
            count = self.smr[ptr]
            self.chan_list.append(sorted(self.smr[ptr + 1 : ptr + count + 1]))
            # pylint: disable-next=nested-min-max
            if count > 0:
                max_mod_no = max(max_mod_no, *self.chan_list[ch_i])
            ptr += 1 + count
        ptr += 2
        grp_cnt = self.smr[ptr - 1]
        self.max_group = max(list(self.smr[ptr : ptr + grp_cnt]))
        # self.group_list: list[int] = [[]] * (max_group + 1)
        for mod_i in range(max_mod_no):
            grp_no = int(self.smr[ptr + mod_i])
            self.module_grp.append(grp_no)
        ptr += 2 * grp_cnt + 1  # groups, group dependencies, timeout
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
        str_len = self.smr[ptr]
        self.serial = self.smr[ptr + 1 : ptr + 1 + str_len].decode("iso8859-1").strip()
        ptr += str_len + 71  # Korr von Hand, vorher 71 + 1
        str_len = self.smr[ptr]
        self.version = self.smr[-22:].decode("iso8859-1").strip()

    def get_module(self, mod_addr) -> HbtnModule | None:
        """Return module based on id."""
        for module in self.modules:
            if module.raddr == mod_addr:
                return module
        return None

    async def get_modules(self, mod_groups) -> list[ModuleDescriptor]:
        """Get summary of all Habitron modules."""
        desc: list[ModuleDescriptor] = []
        addr_dict = {}
        resp = await self.comm.async_get_router_modules(self.id)
        mod_string = resp.decode("iso8859-1")
        while len(resp) > 0:
            mod_uid = self.b_uid + f"{resp[0]}"
            mod_addr = resp[0] + self.id
            mod_typ = resp[1:3]
            name_len = int(resp[3])
            mod_name = mod_string[4 : 4 + name_len]
            mod_group = mod_groups[resp[0] - 1]
            desc.append(
                ModuleDescriptor(mod_uid, mod_addr, mod_typ, mod_name, mod_group)
            )
            addr_dict[mod_addr] = len(desc) - 1
            mod_string = mod_string[4 + name_len : len(resp)]
            resp = resp[4 + name_len :]
        self.mod_reg = addr_dict
        return desc

    async def get_descriptions(self) -> str | None:
        """Get descriptions of commands, etc."""
        resp = await self.comm.get_global_descriptions(self.id)

        no_lines = int.from_bytes(resp[:2], "little")
        resp = resp[4:]
        for _ in range(no_lines):
            if resp == b"":
                break
            line_len = int(resp[8]) + 9
            line = resp[:line_len]
            content_code = int.from_bytes(line[1:3], "little")
            entry_no = int(line[3])
            entry_name = line[9:line_len].decode("iso8859-1").strip()
            if content_code == 767:  # FF 02: global flg (Merker)
                self.flags.append(
                    StateDescriptor(entry_name, len(self.flags), entry_no, 0)
                )
            elif content_code == 1023:  # FF 03: collective commands (Sammelbefehle)
                self.coll_commands.append(CmdDescriptor(entry_name, entry_no))
            elif content_code == 2303:  # FF 08: alarm commands
                pass
            else:
                mod_addr = int(line[1]) + self.id
                # Skip disabled modules
                mod_found = False
                for mod in self.modules:
                    if mod.mod_addr == mod_addr:
                        mod_found = True
                        break
                if mod_found:
                    if int(line[2]) == 1:
                        # local flag (Merker)
                        if self.unit_not_exists(
                            self.modules[self.mod_reg[mod_addr]].flags, entry_name
                        ):
                            self.modules[self.mod_reg[mod_addr]].flags.append(
                                StateDescriptor(
                                    entry_name,
                                    len(self.modules[self.mod_reg[mod_addr]].flags),
                                    entry_no,
                                    0,
                                )
                            )
                    # elif int(line[2]) == 2:
                    # global flag (Merker)
                    elif int(line[2]) == 4:
                        # local visualization command
                        if self.unit_not_exists(
                            self.modules[self.mod_reg[mod_addr]].vis_commands,
                            entry_name,
                        ):
                            entry_no = int.from_bytes(resp[3:5], "little")
                            self.modules[self.mod_reg[mod_addr]].vis_commands.append(
                                CmdDescriptor(entry_name, entry_no)
                            )
                    elif int(line[2]) == 5:
                        # logic element, if needed to fix unexpected error
                        if self.unit_not_exists(
                            self.modules[self.mod_reg[mod_addr]].logic, entry_name
                        ):
                            l_nmbr = line[3] - 1
                            for lgc in self.modules[self.mod_reg[mod_addr]].logic:
                                if lgc.nmbr == l_nmbr:
                                    lgc.name = entry_name  # counter

                    # elif int(line[2]) == 7:
                    # Group name
            resp = resp[line_len:]

    async def get_comm_errors(self) -> bytes:
        """Get current communication errors."""
        resp = await self.comm.async_get_error_status(self.id)
        err_cnt = resp[0]
        ret_bytes = b""
        for e_idx in range(err_cnt):
            ret_bytes += resp[2 * e_idx + 1] + resp[2 * e_idx + 2]
        return ret_bytes

    async def update_system_status(self, sys_status) -> None:
        """Distribute module status to all modules and update self status."""
        self.sys_status = sys_status
        # update not always
        self.smhub.update()
        self.status = await self.comm.async_get_router_status(self.id)
        if not (len(self.status) >= RoutIdx.MIRROR_STARTED):
            self.logger.warning(f"Router status too short, length: {len(self.status)}")  # noqa: G004
            return
        self.mode0 = int(self.status[RoutIdx.MODE0])
        self.comm.grp_modes[0] = self.mode0
        flags_state = int.from_bytes(
            self.status[RoutIdx.FLAG_GLOB : RoutIdx.FLAG_GLOB + 2],
            "little",
        )
        for flg in self.flags:
            flg.value = int((flags_state & (0x01 << flg.nmbr - 1)) > 0)
        for time_out in self.chan_timeouts:
            time_out.value = self.status[RoutIdx.TIME_OUT + time_out.nmbr]
        for curr in self.chan_currents:
            i_0 = RoutIdx.CURRENTS + curr.nmbr * 2
            curr.value = (
                int.from_bytes(
                    self.status[i_0 : i_0 + 2],
                    "little",
                )
                / 1000
            )
        self.voltages[0].value = (
            int.from_bytes(
                self.status[RoutIdx.VOLTAGE_5 : RoutIdx.VOLTAGE_5 + 2], "little"
            )
            / 10
        )
        self.voltages[1].value = (
            int.from_bytes(
                self.status[RoutIdx.VOLTAGE_24 : RoutIdx.VOLTAGE_24 + 2], "little"
            )
            / 10
        )
        self._sys_ok = self.status[RoutIdx.ERR_SYSTEM] == FALSE_VAL
        self._mirror_started = self.status[RoutIdx.MIRROR_STARTED] == TRUE_VAL
        self.states[0].value = self._sys_ok
        self.states[1].value = self._mirror_started
        if not (self._mirror_started):
            await self.comm.async_start_mirror(self.id)

        for m_idx in range(len(self.modules)):
            mod_status = self.sys_status[
                m_idx * MStatIdx.END : (m_idx + 1) * MStatIdx.END
            ]
            if len(mod_status) > 0:
                # Disabled modules return empty status
                mod_addr = mod_status[MStatIdx.ADDR] + self.id
                self.modules[self.mod_reg[mod_addr]].update(mod_status)
        return

    async def async_reset(self) -> None:
        """Call reset command for self."""
        self.comm.module_restart(self.id, 0)

    async def async_reset_all_modules(self) -> None:
        """Call reset command for all modules."""
        self.comm.module_restart(self.id, 0xFF)

    def unit_not_exists(self, mod_units: list[IfDescriptor], entry_name: str) -> bool:
        """Check for existing unit based on name."""
        for exist_unit in mod_units:
            if exist_unit.name == entry_name:
                return False
        return True
