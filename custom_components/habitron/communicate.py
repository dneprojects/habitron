"""Communicate class for Habitron system."""
from __future__ import annotations

import os
import socket
from binascii import hexlify
from typing import Final

from pymodbus.utilities import computeCRC

from homeassistant import exceptions
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

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
        self._mac = "00:80:a3:d4:d1:4f"
        self._hass = hass
        self._config = config
        self.crc = 0
        self.router = []

    @property
    def com_ip(self) -> str:
        """IP of SmartIP."""
        return self._host

    @property
    def com_port(self) -> str:
        """Version for SmartIP."""
        return self._port

    @property
    def com_mac(self) -> str:
        """Mac address for SmartIP."""
        return self._mac

    async def set_host(self, host: str):
        """Updating host information for integration re-configuration"""
        self._config.data = self._config.options
        self._name = host
        self._host = get_host_ip(self._name)
        await self._hass.config_entries.async_reload(self._config.entry_id)

    def get_mac(self) -> str:
        """Get mac address of SmartIP."""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        mac_res = sck.getsockname()[2]
        self.com_mac = hexlify(mac_res)
        sck.close()
        return self.com_mac

    def set_router(self, rtr) -> None:
        """Registers the router instance"""
        self.router = rtr

    async def get_smip_version(self) -> bytes:
        """Query of SmartIP firmware"""
        return await self.async_send_command(SMIP_COMMANDS["GET_SMIP_FIRMWARE"])

    async def get_smr(self, rtr_id) -> bytes:
        """Get router SMR information"""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["GET_ROUTER_SMR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        resp = await self.async_send_command(cmd_str)
        router_string = resp.decode("iso8859-1")
        if router_string[0:5] == "Error":
            return b""
        return resp

    async def async_send_only(self, cmd_string: str) -> None:
        """Send string and return"""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        full_string = wrap_command(cmd_string)
        sck.send(full_string.encode("iso8859-1"))  # Send command
        sck.close()

    async def async_send_command(self, cmd_string: str) -> bytes:
        """General function for communication via SmartIP"""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        sck.settimeout(30)  # 30 seconds
        full_string = wrap_command(cmd_string)
        res = await async_send_receive(sck, full_string)
        sck.close()
        resp_bytes = res[0]
        return resp_bytes

    async def async_send_command_crc(self, cmd_string: str):
        """General function for communication via SmartIP, returns additional crc"""
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
        """Get error byte for each module"""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["GET_CURRENT_ERROR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        return await self.async_send_command(cmd_str)

    async def async_start_mirror(self, rtr_id) -> None:
        """Starts mirror on specified router"""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["START_MIRROR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        await self.async_send_command(cmd_str)

    async def async_system_update(self) -> None:
        """Trigger update of Habitron states, must poll all routers"""

        if self.router.coord.update_interval.seconds == 6:
            sys_status = await self.get_mirror_status(self.router.modules_desc)
        else:
            sys_status = await self.get_compact_status(self.router.id)
        await self.router.update_system_status(sys_status)

    async def async_set_group_mode(self, rtr_id, grp_no, mode) -> None:
        """Set mode for given group"""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["SET_GROUP_MODE"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(grp_no))
        cmd_str = cmd_str.replace("<arg1>", chr(mode))
        await self.async_send_only(cmd_str)

    async def async_set_output(self, mod_id, nmbr, val) -> None:
        """Send turn_on/turn_off command"""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        if val:
            cmd_str = SMIP_COMMANDS["SET_OUTPUT_ON"]
        else:
            cmd_str = SMIP_COMMANDS["SET_OUTPUT_OFF"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        await self.async_send_only(cmd_str)

    async def async_set_dimmval(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output"""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["SET_DIMMER_VALUE"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        await self.async_send_only(cmd_str)

    async def async_set_shutterpos(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output"""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["SET_SHUTTER_POSITION"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        await self.async_send_only(cmd_str)

    async def async_set_blindtilt(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output"""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["SET_BLIND_TILT"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        await self.async_send_only(cmd_str)

    async def async_set_setpoint(self, mod_id, nmbr, val) -> None:
        """Send two byte value for setpoint definition"""
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
        await self.async_send_only(cmd_str)

    async def async_call_vis_command(self, mod_id, nmbr) -> None:
        """Call of visualization command of nmbr"""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMIP_COMMANDS["CALL_VIS_COMMAND"]
        hi_no = int(nmbr / 256)
        lo_no = nmbr - 256 * hi_no
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg2>", chr(hi_no))
        cmd_str = cmd_str.replace("<arg3>", chr(lo_no))
        await self.async_send_only(cmd_str)

    async def async_call_coll_command(self, rtr_id, nmbr) -> None:
        """Call collective command of nmbr"""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["CALL_COLL_COMMAND"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        await self.async_send_only(cmd_str)

    async def get_mirror_status(self, mod_desc) -> bytes:
        """Get common sys_status by separate calls to mirror"""
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
        """Get compact status for all modules, if changed crc"""
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
        """Get compact status for all modules, if changed crc"""
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
        """Get module module status and saves it to file"""
        data = await self.get_module_status(mod_id)
        file_name = f"Module_{mod_id}.mstat"
        await self.save_config_data(file_name, format_block_output(data))

    async def save_router_status(self, rtr_id) -> None:
        """Get module mirror status and saves it to file"""
        data = await self.async_get_router_status(rtr_id)
        file_name = f"Router_{rtr_id}.rstat"
        await self.save_config_data(file_name, format_block_output(data))

    async def save_smc_file(self, mod_id) -> None:
        """Get module definitions (smc) and saves them to file"""
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
        """Get module settings (smg) and saves them to file"""
        data = await self.async_get_module_settings(mod_id)
        file_name = f"Module_{mod_id}.smg"
        str_data = ""
        for byt in data:
            str_data += f"{byt};"
        await self.save_config_data(file_name, str_data)

    async def save_smr_file(self, rtr_id) -> None:
        """Get module settings (smg) and saves them to file"""
        data = await self.get_smr(rtr_id)
        file_name = f"Router_{rtr_id}.smr"
        str_data = ""
        for byt in data:
            str_data += f"{byt};"
        await self.save_config_data(file_name, str_data)

    async def save_config_data(self, file_name: str, str_data: str) -> None:
        """Saving config info to text file"""
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
        """Restarts a single module or all with arg 0xFF or router if arg 0"""
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
        await self.async_send_only(cmd_str)


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
    full_string = "¨!\0\x0bSmartConfig\x05michlS\x05\n\x04\x04\x01\0\0\0\x5f\xbe?"
    resp_bytes = send_receive(sck, full_string)
    sck.close()
    ver_string = resp_bytes.decode("iso8859-1")
    return bool(ver_string[0:2] == "\x01\x18")


def get_host_ip(host_name: str) -> str:
    """Get IP from DNS host name, error handling"""
    host = socket.gethostbyname(host_name)
    return host


def send_receive(sck, cmd_str: str) -> bytes:
    """Send string to SmartIP and wait for response with timeout"""
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
    """Send string to SmartIP and wait for response with timeout"""
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
    """Take command and add prefix, crc, postfix"""
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
    """Format block hex output with lines"""
    lbs = len(byte_str)
    res_str = ""
    ptr = 0
    while ptr < lbs:
        line = ""
        end_l = min([ptr + 10, lbs])
        for i in range(end_l - ptr):
            line = line + f"{'{:02X}'.format(byte_str[ptr+i])} "
        res_str += f"{'{:03d}'.format(ptr)}  {line}{chr(13)}"
        ptr += 10
    return res_str


class TimeoutException(exceptions.HomeAssistantError):
    """Error to indicate timeout."""
