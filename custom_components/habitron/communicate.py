"""Communicate class for Habitron system."""
from __future__ import annotations

import os
import socket
import struct
from typing import Final

from pymodbus.utilities import computeCRC
import requests

from homeassistant import exceptions
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, MirrIdx, ModuleDescriptor

BASE_PATH_COMPONENT = "./homeassistant/components"
BASE_PATH_CUSTOM_COMPONENT = "./custom_components"

SMIP_COMMANDS: Final[dict[str, str]] = {
    "GET_MODULES": "\x0a\1\2<rtr>\0\0\0",
    "GET_MODULE_SMG": "\x0a\2\7<rtr><mod>\0\0",
    "GET_MODULE_SMC": "\x0a\3\7<rtr><mod>\0\0",
    "GET_ROUTER_SMR": "\x0a\4\3<rtr>\0\0\0",
    "GET_ROUTER_STATUS": "\x0a\4\4<rtr>\0\0\0",
    "GET_MODULE_STATUS": "\x0a\5\1<rtr><mod>\0\0",
    "GET_COMPACT_STATUS": "\x0a\5\2<rtr>\xff\0\0",  # compact status of all modules (0xFF)
    "GET_SMIP_BOOT_STATUS": "\x0a\6\1\0\0\0\0",
    "GET_GLOBAL_DESCRIPTIONS": "\x0a\7\1<rtr>\0\0\0",  # Flags, Command collections
    "GET_SMIP_STATUS": "\x14\0\0\0\0\0\0",
    "GET_SMIP_FIRMWARE": "\x14\x1e\0\0\0\0\0",
    "GET_GROUP_MODE": "\x14\2\1<rtr><mod>\0\0",  # <Group 0..>
    "GET_GROUP_MODE0": "\x14\2\1<rtr>\0\0\0",
    "SET_GROUP_MODE": "\x14\2\2<rtr><mod>\3\0<rtr><mod><arg1>",  # <Group 0..><Mode>
    "GET_ROUTER_MODES": "\x14\2\3<rtr><mod>\3\0<rtr><mod>\0",
    "START_MIRROR": "\x14\x28\1\0\0\0\0",
    "STOP_MIRROR": "\x14\x28\2\0\0\0\0",
    "CHECK_COMM_STATUS": "\x14\x64\0\0\0\0\0",
    "SET_OUTPUT_ON": "\x1e\1\1<rtr><mod>\3\0<rtr><mod><arg1>",
    "SET_OUTPUT_OFF": "\x1e\1\2<rtr><mod>\3\0<rtr><mod><arg1>",
    "SET_DIMMER_VALUE": "\x1e\1\3<rtr><mod>\4\0<rtr><mod><arg1><arg2>",  # <Module><DimNo><DimVal>
    "SET_SHUTTER_POSITION": "\x1e\1\4<rtr>\0\5\0<rtr><mod>\1<arg1><arg2>",  # <Module><RollNo><RolVal>
    "SET_BLIND_TILT": "\x1e\1\4<rtr>\0\5\0<rtr><mod>\2<arg1><arg2>",
    "SET_SETPOINT_VALUE": "\x1e\2\1<rtr>\0\5\0<rtr><mod><arg1><arg2><arg3>",  # <Module><ValNo><ValL><ValH>
    "CALL_VIS_COMMAND": "\x1e\3\1\0\0\4\0<rtr><mod><arg2><arg3>",  # <Module><VisNoL><VisNoH> not tested
    "CALL_COLL_COMMAND": "\x1e\4\1<rtr><arg2>\0\0",  # <CmdNo>
    "GET_LAST_IR_CODE": "\x32\2\1<rtr><mod>\0\0",
    "RESTART_FORWARD_TABLE": "\x3c\1\1<rtr>\0\0\0",  # Weiterleitungstabelle löschen und -automatik starten
    "GET_CURRENT_ERROR": "\x3c\1\2<rtr>\0\0\0",
    "GET_LAST_ERROR": "\x3c\1\3<rtr>\0\0\0",
    "REBOOT_ROUTER": "\x3c\1\4<rtr>\0\0\0",  #
    "REBOOT_MODULE": "\x3c\3\1<rtr><mod>\0\0",  # <Module> or 0xFF for all modules
    "READ_MODULE_MIRR_STATUS": "\x64\1\5<rtr><mod>\0\0",  # <Module>
}


class HbtnComm:
    """Habitron communication class."""

    def __init__(self, hass: HomeAssistant, config: ConfigEntry) -> None:
        """Init CommTest for connection test."""
        self._name = "HbtnComm"
        self._host_conf = config.data.__getitem__("habitron_host")
        self._host = get_host_ip(self._host_conf)
        self._port = 7777
        self._hass = hass
        self._config = config
        self.crc = 0
        self.router = []
        self.update_suspended = False
        self.smart_ip_properties = query_smartip(self._host)
        self._mac = self._mac = self.smart_ip_properties["mac"]
        self._version = self.smart_ip_properties["version"]
        self._hwtype = (
            f"{self.smart_ip_properties['type']} {self.smart_ip_properties['serial']}"
        )

    @property
    def com_ip(self) -> str:
        """IP of SmartIP."""
        return self._host

    @property
    def com_port(self) -> str:
        """Port for SmartIP."""
        return self._port

    @property
    def com_mac(self) -> str:
        """Mac address for SmartIP."""
        return self._mac

    @property
    def com_version(self) -> str:
        """Firmware version of SmartIP."""
        return self._version

    @property
    def com_hwtype(self) -> str:
        """Firmware version of SmartIP."""
        return self._hwtype

    async def set_host(self, host: str):
        """Updating host information for integration re-configuration."""
        self._config.data = self._config.options
        if self._host_conf == host:
            return
        self._host_conf = host
        self._host = get_host_ip(self._host_conf)
        await self._hass.config_entries.async_reload(self._config.entry_id)

    def set_router(self, rtr) -> None:
        """Registers the router instance."""
        self.router = rtr

    async def get_smip_version(self) -> bytes:
        """Query of SmartIP firmware."""
        return await self.async_send_command(SMIP_COMMANDS["GET_SMIP_FIRMWARE"])

    async def get_smr(self, rtr_id) -> bytes:
        """Get router SMR information."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["GET_ROUTER_SMR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        resp = await self.async_send_command(cmd_str)
        router_string = resp.decode("iso8859-1")
        if router_string[0:5] == "Error":
            return b""
        return resp

    def send_only(self, cmd_string: str) -> None:
        """Send string and return."""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        full_string = wrap_command(cmd_string)
        sck.send(full_string.encode("iso8859-1"))  # Send command
        sck.close()

    async def async_send_command(self, cmd_string: str) -> bytes:
        """General function for communication via SmartIP."""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        sck.settimeout(30)  # 30 seconds
        full_string = wrap_command(cmd_string)
        res = await async_send_receive(sck, full_string)
        sck.close()
        resp_bytes = res[0]
        return resp_bytes

    async def async_send_command_crc(self, cmd_string: str):
        """General function for communication via SmartIP, returns additional crc."""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        sck.settimeout(30)  # 30 seconds
        full_string = wrap_command(cmd_string)
        res = await async_send_receive(sck, full_string)
        sck.close()
        return res[0], res[1]

    async def async_get_router_status(self, rtr_id) -> bytes:
        """Get router status."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["GET_ROUTER_STATUS"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        resp = await self.async_send_command(cmd_str)
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def async_get_router_modules(self, rtr_id) -> bytes:
        """Get summary of all Habitron modules of a router."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["GET_MODULES"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        resp = await self.async_send_command(cmd_str)
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def get_global_descriptions(self, rtr_id) -> bytes:
        """Get descriptions of commands, etc."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["GET_GLOBAL_DESCRIPTIONS"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        return await self.async_send_command(cmd_str)

    async def async_get_error_status(self, rtr_id) -> bytes:
        """Get error byte for each module."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["GET_CURRENT_ERROR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        return await self.async_send_command(cmd_str)

    async def async_start_mirror(self, rtr_id) -> None:
        """Starts mirror on specified router."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["START_MIRROR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        await self.async_send_command(cmd_str)

    async def async_system_update(self) -> None:
        """Trigger update of Habitron states, must poll all routers."""

        if self.update_suspended:
            # disable update to avoid conflict with SmartConfig or other communication
            return
        else:
            sys_status = await self.get_compact_status(self.router.id)
        await self.router.update_system_status(sys_status)

    async def async_set_group_mode(self, rtr_id, grp_no, mode) -> None:
        """Set mode for given group."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["SET_GROUP_MODE"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(grp_no))
        cmd_str = cmd_str.replace("<arg1>", chr(mode))
        self.send_only(cmd_str)

    def set_output(self, mod_id, nmbr, val) -> None:
        """Send turn_on/turn_off command."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        if val:
            cmd_str = SMIP_COMMANDS["SET_OUTPUT_ON"]
        else:
            cmd_str = SMIP_COMMANDS["SET_OUTPUT_OFF"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        self.send_only(cmd_str)

    async def async_set_output(self, mod_id, nmbr, val) -> None:
        """Send turn_on/turn_off command."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        if val:
            cmd_str = SMIP_COMMANDS["SET_OUTPUT_ON"]
        else:
            cmd_str = SMIP_COMMANDS["SET_OUTPUT_OFF"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        self.send_only(cmd_str)

    async def async_set_dimmval(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["SET_DIMMER_VALUE"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        self.send_only(cmd_str)

    async def async_set_shutterpos(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["SET_SHUTTER_POSITION"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        self.send_only(cmd_str)

    async def async_set_blindtilt(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["SET_BLIND_TILT"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        self.send_only(cmd_str)

    async def async_set_setpoint(self, mod_id, nmbr, val) -> None:
        """Send two byte value for setpoint definition."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["SET_SETPOINT_VALUE"]
        hi_val = int(val / 256)
        lo_val = val - 256 * hi_val
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg3>", chr(hi_val))
        cmd_str = cmd_str.replace("<arg2>", chr(lo_val))
        self.send_only(cmd_str)

    async def async_call_vis_command(self, mod_id, nmbr) -> None:
        """Call of visualization command of nmbr."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["CALL_VIS_COMMAND"]
        hi_no = int(nmbr / 256)
        lo_no = nmbr - 256 * hi_no
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg2>", chr(hi_no))
        cmd_str = cmd_str.replace("<arg3>", chr(lo_no))
        self.send_only(cmd_str)

    async def async_call_coll_command(self, rtr_id, nmbr) -> None:
        """Call collective command of nmbr."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["CALL_COLL_COMMAND"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        self.send_only(cmd_str)

    async def get_mirror_status(self, mod_desc) -> bytes:
        """Get common sys_status by separate calls to mirror."""
        if isinstance(mod_desc, ModuleDescriptor):
            rtr_nmbr = int(mod_desc[0].uid / 100)
        else:
            mod_uid = mod_desc
            rtr_nmbr = int(mod_uid / 100)
            mod_desc: list[ModuleDescriptor] = []
            mod_desc.append(ModuleDescriptor(mod_uid, "", "", 1))
        sys_status = b""
        sys_crc = 0
        for desc in mod_desc:
            cmd_str = SMIP_COMMANDS["READ_MODULE_MIRR_STATUS"]
            cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
            cmd_str = cmd_str.replace("<mod>", chr(desc.uid - 100 * rtr_nmbr))
            [resp, crc] = await self.async_send_command_crc(cmd_str)
            status = (
                (chr(91) + chr(1)).encode("iso8859-1")
                + resp[0 : MirrIdx.LED_I]
                + resp[MirrIdx.IR_H : MirrIdx.ROLL_T]
                + resp[MirrIdx.ROLL_POS : MirrIdx.BLAD_T]
                + resp[MirrIdx.BLAD_POS : MirrIdx.T_SHORT]
                + resp[MirrIdx.T_SETP_1 : MirrIdx.T_LIM]
                + resp[MirrIdx.RAIN : MirrIdx.RAIN + 2]
                + resp[MirrIdx.USER_CNT : MirrIdx.FINGER_CNT + 1]
                + resp[MirrIdx.MODULE_STAT : MirrIdx.MODULE_STAT + 1]
                + resp[MirrIdx.COUNTER : MirrIdx.END - 3]
            )
            sys_status = sys_status + status
            sys_crc += crc
        if sys_crc == self.crc:
            return b""
        else:
            self.crc = sys_crc
            return sys_status

    async def get_compact_status(self, rtr_id) -> bytes:
        """Get compact status for all modules, if changed crc."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["GET_COMPACT_STATUS"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        [resp_bytes, crc] = await self.async_send_command_crc(cmd_str)
        if crc == self.crc:
            return b""
        else:
            self.crc = crc
            return resp_bytes

    async def get_module_status(self, mod_id) -> bytes:
        """Get compact status for all modules, if changed crc."""
        rtr_nmbr = int(mod_id / 100)
        mod_nmbr = mod_id - rtr_nmbr * 100
        cmd_str = SMIP_COMMANDS["GET_MODULE_STATUS"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_nmbr))
        [resp_bytes, crc] = await self.async_send_command_crc(cmd_str)
        if crc == self.crc:
            return b""
        else:
            self.crc = crc
            return resp_bytes

    async def async_get_module_definitions(self, mod_id) -> bytes:
        """Get summary of Habitron module: names, commands, etc."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["GET_MODULE_SMC"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        resp = await self.async_send_command(cmd_str)
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def async_get_module_settings(self, mod_id) -> bytes:
        """Get settings of Habitron module."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["GET_MODULE_SMG"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        resp = await self.async_send_command(cmd_str)
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def save_module_status(self, mod_id) -> None:
        """Get module module status and saves it to file."""
        data = await self.get_module_status(mod_id)
        file_name = f"Module_{mod_id}.mstat"
        await self.save_config_data(file_name, format_block_output(data))

    async def save_router_status(self, rtr_id) -> None:
        """Get module mirror status and saves it to file."""
        data = await self.async_get_router_status(rtr_id)
        file_name = f"Router_{rtr_id}.rstat"
        await self.save_config_data(file_name, format_block_output(data))

    async def save_smc_file(self, mod_id) -> None:
        """Get module definitions (smc) and saves them to file."""
        data = await self.async_get_module_definitions(mod_id)
        file_name = f"Module_{mod_id}.smc"
        str_data = ""
        for b_idx in range(7):
            str_data += f"{data[b_idx]};"  # header
        str_data += chr(13)
        data = data[b_idx + 1 : len(data)]
        while len(data) > 6:
            line_len = data[5] + 5
            for b_idx in range(line_len):
                str_data += f"{data[b_idx]};"
            str_data += chr(13)
            data = data[b_idx + 1 : len(data)]
        await self.save_config_data(file_name, str_data)

    async def save_smg_file(self, mod_id) -> None:
        """Get module settings (smg) and saves them to file."""
        data = await self.async_get_module_settings(mod_id)
        file_name = f"Module_{mod_id}.smg"
        str_data = ""
        for byt in data:
            str_data += f"{byt};"
        await self.save_config_data(file_name, str_data)

    async def save_smr_file(self, rtr_id) -> None:
        """Get module settings (smg) and saves them to file."""
        data = await self.get_smr(rtr_id)
        file_name = f"Router_{rtr_id}.smr"
        str_data = ""
        for byt in data:
            str_data += f"{byt};"
        await self.save_config_data(file_name, str_data)

    async def save_config_data(self, file_name: str, str_data: str) -> None:
        """Saving config info to text file."""
        if os.path.isdir(BASE_PATH_COMPONENT):
            data_path = f"{BASE_PATH_COMPONENT}/{DOMAIN}/data/"
        else:
            data_path = f"{BASE_PATH_CUSTOM_COMPONENT}/{DOMAIN}/data/"
        if not (os.path.isdir(data_path)):
            os.mkdir(data_path)
        file_path = data_path + file_name
        hbtn_file = open(file_path, "w", encoding="ascii", errors="surrogateescape")
        hbtn_file.write(str_data)
        hbtn_file.close()

    async def module_restart(self, rtr_id, mod_nmbr: int) -> None:
        """Restarts a single module or all with arg 0xFF or router if arg 0."""
        rtr_nmbr = int(rtr_id / 100)
        if mod_nmbr > 0:
            # module restart
            cmd_str = SMIP_COMMANDS["REBOOT_MODULE"]
            cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
            cmd_str = cmd_str.replace("<mod>", chr(mod_nmbr))

        else:
            # router restart
            cmd_str = SMIP_COMMANDS["REBOOT_ROUTER"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        self.send_only(cmd_str)


async def test_connection(host_name) -> bool:
    """Test connectivity to SmartIP is OK."""
    port = 7777
    try:
        host = get_host_ip(host_name)
    except socket.gaierror as exc:
        raise socket.gaierror from exc
    sck = socket.socket()  # Create a socket object
    try:
        sck.connect((host, port))
    except ConnectionRefusedError as exc:
        raise ConnectionRefusedError from exc
    sck.settimeout(15)  # 15 seconds
    # router restart
    cmd_str = SMIP_COMMANDS["CHECK_COMM_STATUS"]
    full_string = wrap_command(cmd_str)
    resp_bytes = send_receive(sck, full_string)
    sck.close()
    resp_string = resp_bytes.decode("iso8859-1")
    return bool(resp_string[0:2] == "OK")


def get_host_ip(host_name: str) -> str:
    """Get IP from DNS host name, error handling."""
    host = socket.gethostbyname(host_name)
    return host


def send_receive(sck, cmd_str: str) -> bytes:
    """Send string to SmartIP and wait for response with timeout."""
    try:
        sck.send(cmd_str.encode("iso8859-1"))  # Send command

        resp_bytes = sck.recv(30)
        if len(resp_bytes) < 30:
            return b"OK"
        resp_len = resp_bytes[29] * 256 + resp_bytes[28]
        resp_bytes = b""
        while len(resp_bytes) < resp_len + 3:
            buffer = sck.recv(resp_len + 3)
            resp_bytes = resp_bytes + buffer
        resp_bytes = resp_bytes[0:resp_len]
    except TimeoutError as exc:
        raise TimeoutException from exc
    return resp_bytes


async def async_send_receive(sck, cmd_str: str) -> bytes:
    """Send string to SmartIP and wait for response with timeout."""
    try:
        sck.send(cmd_str.encode("iso8859-1"))  # Send command

        resp_bytes = sck.recv(30)
        if len(resp_bytes) < 30:
            return b"OK", 0
        resp_len = resp_bytes[29] * 256 + resp_bytes[28]
        resp_bytes = b""
        while len(resp_bytes) < resp_len + 3:
            buffer = sck.recv(resp_len + 3)
            resp_bytes = resp_bytes + buffer
        crc = resp_bytes[-2] * 256 + resp_bytes[-3]
        resp_bytes = resp_bytes[0:resp_len]
    except TimeoutError as exc:
        raise TimeoutException from exc
    return resp_bytes, crc


def wrap_command(cmd_string: str) -> str:
    """Take command and add prefix, crc, postfix."""
    cmd_prefix = "¨\0\0\x0bSmartConfig\x05michlS\x05"
    cmd_postfix = "\x3f"
    full_string = cmd_prefix + cmd_string
    cmd_len = len(full_string) + 3
    full_string = full_string[0] + chr(cmd_len) + full_string[2 : cmd_len - 3]
    cmd_crc = computeCRC(full_string.encode("iso8859-1"))
    crc_low = cmd_crc & 0xFF
    crc_high = (cmd_crc - crc_low) >> 8
    cmd_postfix = chr(crc_high) + chr(crc_low) + cmd_postfix
    return full_string + cmd_postfix


def format_block_output(byte_str: bytes) -> str:
    """Format block hex output with lines."""
    lbs = len(byte_str)
    res_str = ""
    ptr = 0
    while ptr < lbs:
        line = ""
        end_l = min([ptr + 10, lbs])
        for i in range(end_l - ptr):
            line = line + f"{f'{byte_str[ptr+i]:02X}'} "
        res_str += f"{f'{ptr:03d}'}  {line}{chr(13)}"
        ptr += 10
    return res_str


def get_udp_broadcast_socket(timeout):
    """Get a UDP broadcast socket with a specific timeout."""

    network_socket = socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
    )

    network_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
    network_socket.settimeout(timeout)

    return network_socket


def discover_smartips(flg_one):
    """Discover SmartIP and SmartServer hardware on the network.

    :param address: string - The broadcast address to use.
    :param port: int - The port to use for the broadcast.
    :param timeout: int - The timeout to wait for answers.
    :param bind_to: string - The network interface to bind to
    :param try_info_api:  bool - Whether to try the HTTP info interface on
                                 discovered SmartIPs.
    :return:
    """
    smip_port = 30718
    base_ip = "192.168.178.0"
    lower_ip = 2
    upper_ip = 255
    timeout = 0.1
    try_info_api = False

    req_header_data = [0x00, 0x00, 0x00, 0xF6]
    req_header = struct.pack("B" * len(req_header_data), *req_header_data)
    network_socket = get_udp_broadcast_socket(timeout)

    resp_header_data = [0x00, 0x00, 0x00, 0xF7]
    resp_header = struct.pack("B" * len(resp_header_data), *resp_header_data)

    smartips = []

    for ip in range(lower_ip, upper_ip):
        try:
            tst_address = base_ip.replace(".0", f".{ip}")
            network_socket.sendto(req_header, (tst_address, smip_port))
            response, address_info = network_socket.recvfrom(1024)

            print(f"SmartIP found at address {tst_address}")
            smip_ip = address_info[0]

            if response[0:4] == resp_header and smip_ip != "0.0.0.0":
                smip_version = f"{response[7]}.{response[6]}.{response[5]}"
                smip_mac = f"{response[24]:02X}:{response[25]:02X}:{response[26]:02X}:{response[27]:02X}:{response[28]:02X}:{response[29]:02X}"
                smip_serial = (
                    f"{response[20]:c}{response[21]:c}{response[22]:c}{response[23]:c}"
                )
                smip_type = f"{response[8]:c}-{response[9]:c}"
                smartip_info = {
                    "type": smip_type,
                    "version": smip_version,
                    "serial": smip_serial,
                    "mac": smip_mac,
                    "ip": smip_ip,
                }

                smartips.append(smartip_info)
                if flg_one:
                    break

            else:
                print(("Response: %s (%d)" % ([response], len(response)), address_info))

        except socket.timeout:
            pass

    network_socket.close()

    if try_info_api:
        # starting with newer firmwares, we do have a JSON endpoint
        # reporting some additional information
        # @ /api/info (it's behind HTTP Digest Auth with admin/PASS

        add_http_info(smartips)

    return smartips


def query_smartip(smip_ip):
    """Read properties of identified SmartIP.

    :param smip_ip: ip address of a single smartip
    """
    smip_port = 30718
    timeout = 0.1
    try_info_api = False

    req_header_data = [0x00, 0x00, 0x00, 0xF6]
    req_header = struct.pack("B" * len(req_header_data), *req_header_data)
    network_socket = get_udp_broadcast_socket(timeout)

    resp_header_data = [0x00, 0x00, 0x00, 0xF7]
    resp_header = struct.pack("B" * len(resp_header_data), *resp_header_data)

    try:
        network_socket.sendto(req_header, (smip_ip, smip_port))
        response, address_info = network_socket.recvfrom(1024)

        smip_ip = address_info[0]

        if response[0:4] == resp_header and smip_ip != "0.0.0.0":
            smip_version = f"{response[7]}.{response[6]}.{response[5]}"
            smip_mac = f"{response[24]:02X}:{response[25]:02X}:{response[26]:02X}:{response[27]:02X}:{response[28]:02X}:{response[29]:02X}"
            smip_serial = (
                f"{response[20]:c}{response[21]:c}{response[22]:c}{response[23]:c}"
            )
            smip_type = f"{response[8]:c}-{response[9]:c}"
            smartip_info = {
                "type": smip_type,
                "version": smip_version,
                "serial": smip_serial,
                "mac": smip_mac,
                "ip": smip_ip,
            }

        else:
            print(("Response: %s (%d)" % ([response], len(response)), address_info))

    except socket.timeout:
        pass

    network_socket.close()

    if try_info_api:
        # starting with newer firmwares, we do have a JSON endpoint
        # reporting some additional information
        # @ /api/info (it's behind HTTP Digest Auth with admin/PASS

        add_http_info(smartip_info)

    return smartip_info


def add_http_info(smartip_info):
    """Request and annotate HTTP info for discovered SmartIPs."""

    smartip_info_template = "http://{ip}/api/info"
    auth_user = "admin"
    auth_passwd = "PASS"

    auth = requests.auth.HTTPDigestAuth(auth_user, auth_passwd)
    url = smartip_info_template.format(**smartip_info)
    response = requests.get(url, auth=auth, timeout=1)

    if response.status_code == 200:
        data = response.json()

        if data.get("status", None) == "OK":
            smartip_info.update(
                {
                    "firmware": data.get("version", None),
                    "free_ram": data.get("free_ram", None),
                }
            )
        else:
            print("Info API call succeeded, but did not return status ok")

    else:
        print(f"Info API call failed with status code {response.status_code}")


class TimeoutException(exceptions.HomeAssistantError):
    """Error to indicate timeout."""
