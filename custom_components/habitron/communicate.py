"""Communicate class for Habitron system."""
from __future__ import annotations

from binascii import hexlify

# In a real implementation, this would be in an external library that's on PyPI.
# The PyPI package needs to be included in the `requirements` section of manifest.json
# See https://developers.home-assistant.io/docs/creating_integration_manifest
# for more information.
# This dummy smip always returns 3 rollers.
import socket
from typing import Final

from pymodbus.utilities import computeCRC

from homeassistant import exceptions
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import MirrIdx

SMIP_COMMANDS: Final[dict[str, str]] = {
    "GET_MODULES": "\x0a\1\2\1\0\0\0",
    "GET_MODULE_SMG": "\x0a\2\7\1\xff\0\0",
    "GET_MODULE_SMC": "\x0a\3\7\1\xff\0\0",
    "GET_ROUTER_SMR": "\x0a\4\3\1\0\0\0",
    "GET_ROUTER_STATUS": "\x0a\4\4\1\0\0\0",
    "GET_MODULE_STATUS": "\x0a\5\1\x01\xff\0\0",
    "GET_COMPACT_STATUS": "\x0a\5\2\1\xff\0\0",  # compact status of all modules (0xFF)
    "GET_SMIP_BOOT_STATUS": "\x0a\6\1\0\0\0\0",
    "GET_GLOBAL_DESCRIPTIONS": "\x0a\7\1\1\0\0\0",  # Flags, Command collections
    "GET_SMIP_STATUS": "\x14\0\0\0\0\0\0",
    "GET_SMIP_FIRMWARE": "\x14\x1e\0\0\0\0\0",
    "GET_GROUP_MODE": "\x14\2\1\x01\xff\0\0",  # <Group 0..>
    "GET_GROUP_MODE0": "\x14\2\1\x01\0\0\0",
    "SET_GROUP_MODE": "\x14\2\2\x01\xff\3\0\1\xff\xfe",  # <Group 0..><Mode>
    "GET_ROUTER_MODES": "\x14\2\3\x01\xff\3\0\1\xff\0",
    "START_MIRROR": "\x14\x28\1\0\0\0\0",
    "STOP_MIRROR": "\x14\x28\2\0\0\0\0",
    "CHECK_COMM_STATUS": "\x14\x64\0\0\0\0\0",
    "SET_OUTPUT_ON": "\x1e\1\1\x01\xff\3\0\1\xff\xfe",
    "SET_OUTPUT_OFF": "\x1e\1\2\x01\xff\3\0\1\xff\xfe",
    "SET_DIMMER_VALUE": "\x1e\1\3\x01\xff\4\0\1\xff\xfe\xfd",  # <Module><DimNo><DimVal>
    "SET_SHUTTER_POSITION": "\x1e\1\4\x01\0\5\0\1\xff\1\xfe\xfd",  # <Module><RollNo><RolVal>
    "SET_BLIND_TILT": "\x1e\1\4\x01\0\5\0\1\xff\2\xfe\xfd",
    "SET_SETPOINT_VALUE": "\x1e\2\1\x01\0\5\0\1\xff\xfe\xfd\xfc",  # <Module><ValNo><ValL><ValH>
    "CALL_VIS_COMMAND": "\x1e\3\1\0\0\4\0\1\xff\xfd\xfc",  # <Module><VisNoL><VisNoH> not tested
    "CALL_COLL_COMMAND": "\x1e\4\1\1\xfd\0\0",  # <CmdNo>
    "GET_LAST_IR_CODE": "\x32\2\1\x01\xff\0\0",
    "RESTART_FORWARD_TABLE": "\x3c\1\1\x01\0\0\0",  # Weiterleitungstabelle löschen und -automatik starten
    "GET_CURRENT_ERROR": "\x3c\1\2\x01\0\0\0",
    "GET_LAST_ERROR": "\x3c\1\3\x01\0\0\0",
    "REBOOT_ROUTER": "\x3c\1\4\x01\0\0\0",  #
    "REBOOT_MODULE": "\x3c\3\1\x01\xff\0\0",  # <Module> or 0xFF for all modules
    "READ_MODULE_MIRR_STATUS": "\x64\1\5\1\xff\0\0",  # <Module>
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
        """Get router smr."""
        resp = await self.async_send_command(SMIP_COMMANDS["GET_ROUTER_SMR"])
        router_string = resp.decode("iso8859-1")
        if router_string[0:5] == "Error":
            return b""
        return resp

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
        resp = await self.async_send_command(SMIP_COMMANDS["GET_ROUTER_STATUS"])
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def async_get_router_modules(self, rtr_id) -> bytes:
        """Get summary of all Habitron modules of a router."""

        resp = await self.async_send_command(SMIP_COMMANDS["GET_MODULES"])
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def get_global_descriptions(self, rtr_id) -> bytes:
        """Get descriptions of commands, etc."""
        return await self.async_send_command(SMIP_COMMANDS["GET_GLOBAL_DESCRIPTIONS"])

    async def async_get_error_status(self, rtr_id) -> bytes:
        """Get error byte for each module"""
        return await self.async_send_command(SMIP_COMMANDS["GET_CURRENT_ERROR"])

    async def async_start_mirror(self, rtr_id) -> None:
        """Starts mirror on specified router"""
        await self.async_send_command(SMIP_COMMANDS["START_MIRROR"])

    async def async_system_update(self) -> None:
        """Trigger update of Habitron states, must poll all routers"""

        if self.router.coord.update_interval.seconds == 6:
            sys_status = await self.get_mirror_status(self.router.modules_desc)
        else:
            sys_status = await self.get_compact_status()
        if sys_status == b"":
            return
        else:
            await self.router.update_system_status(sys_status)

    async def async_set_group_mode(self, rtr_id, grp_no, mode) -> None:
        """Set mode for given group"""
        rtr_id = int(rtr_id / 100)
        cmd_str = SMIP_COMMANDS["SET_GROUP_MODE"]
        cmd_str = cmd_str.replace("\xff", chr(grp_no))
        cmd_str = cmd_str.replace("\xfe", chr(mode))
        await self.async_send_command(cmd_str)

    async def async_set_output(self, mod_id, nmbr, val) -> None:
        """Send turn_on/turn_off command"""
        rtr_id = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_id)
        if val:
            cmd_str = SMIP_COMMANDS["SET_OUTPUT_ON"]
        else:
            cmd_str = SMIP_COMMANDS["SET_OUTPUT_OFF"]
        cmd_str = cmd_str.replace("\xff", chr(mod_addr))
        cmd_str = cmd_str.replace("\xfe", chr(nmbr))
        await self.async_send_command(cmd_str)

    async def async_set_dimmval(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output"""
        rtr_id = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_id)
        cmd_str = SMIP_COMMANDS["SET_DIMMER_VALUE"]
        cmd_str = cmd_str.replace("\xff", chr(mod_addr))
        cmd_str = cmd_str.replace("\xfe", chr(nmbr))
        cmd_str = cmd_str.replace("\xfd", chr(val))
        await self.async_send_command(cmd_str)

    async def async_set_shutterpos(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output"""
        rtr_id = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_id)
        cmd_str = SMIP_COMMANDS["SET_SHUTTER_POSITION"]
        cmd_str = cmd_str.replace("\xff", chr(mod_addr))
        cmd_str = cmd_str.replace("\xfe", chr(nmbr))
        cmd_str = cmd_str.replace("\xfd", chr(val))
        await self.async_send_command(cmd_str)

    async def async_set_blindtilt(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output"""
        rtr_id = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_id)
        cmd_str = SMIP_COMMANDS["SET_BLIND_TILT"]
        cmd_str = cmd_str.replace("\xff", chr(mod_addr))
        cmd_str = cmd_str.replace("\xfe", chr(nmbr))
        cmd_str = cmd_str.replace("\xfd", chr(val))
        await self.async_send_command(cmd_str)

    async def async_set_setpoint(self, mod_id, nmbr, val) -> None:
        """Send two byte value for setpoint definition"""
        rtr_id = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_id)
        cmd_str = SMIP_COMMANDS["SET_SETPOINT_VALUE"]
        hi_val = max(val - 255, 0)
        lo_val = val - 256 * hi_val
        cmd_str = cmd_str.replace("\xff", chr(mod_addr))
        cmd_str = cmd_str.replace("\xfe", chr(nmbr))
        cmd_str = cmd_str.replace("\xfc", chr(hi_val))
        cmd_str = cmd_str.replace("\xfd", chr(lo_val))
        await self.async_send_command(cmd_str)

    async def async_call_vis_command(self, mod_id, nmbr) -> None:
        """Call of visualization command of nmbr"""
        rtr_id = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_id)
        cmd_str = SMIP_COMMANDS["CALL_VIS_COMMAND"]
        hi_no = max(nmbr - 255, 0)
        lo_no = nmbr - 256 * hi_no
        cmd_str = cmd_str.replace("\xff", chr(mod_addr))
        cmd_str = cmd_str.replace("\xfc", chr(hi_no))
        cmd_str = cmd_str.replace("\xfd", chr(lo_no))
        await self.async_send_command(cmd_str)

    async def async_call_coll_command(self, rtr_id, nmbr) -> None:
        """Call collective command of nmbr"""
        rtr_id = rtr_id / 100
        cmd_str = SMIP_COMMANDS["CALL_COLL_COMMAND"]
        cmd_str = cmd_str.replace("\xfe", chr(nmbr))
        await self.async_send_command(cmd_str)

    async def get_mirror_status(self, mod_desc) -> bytes:
        """Get common sys_status by separate calls to mirror"""
        sys_status = b""
        sys_crc = 0
        for desc in mod_desc:
            cmd_str = SMIP_COMMANDS["READ_MODULE_MIRR_STATUS"]
            cmd_str = cmd_str.replace("\xff", chr(desc.addr))
            [resp, crc] = await self.async_send_command_crc(cmd_str)
            status = (
                resp[0 : MirrIdx.LED_I]
                + resp[MirrIdx.IR_H : MirrIdx.ROLL_T]
                + resp[MirrIdx.ROLL_POS : MirrIdx.BLAD_T]
                + resp[MirrIdx.BLAD_POS : MirrIdx.T_SHORT]
                + resp[MirrIdx.T_SETP_1 : MirrIdx.T_LIM]
                + resp[MirrIdx.RAIN : MirrIdx.RAIN + 2]
                + resp[MirrIdx.USER_CNT : MirrIdx.FINGER_CNT + 1]
                + resp[MirrIdx.MODULE_STAT : MirrIdx.MODULE_STAT + 1]
                + resp[MirrIdx.COUNTER : MirrIdx.END]
            )
            sys_status = sys_status + status
            sys_crc += crc
        if sys_crc == self.crc:
            return b""
        else:
            self.crc = sys_crc
            return sys_status

    async def get_compact_status(self) -> bytes:
        """Get compact status for all modules, if changed crc"""
        cmd_string = SMIP_COMMANDS["GET_COMPACT_STATUS"]
        [resp_bytes, crc] = await self.async_send_command_crc(cmd_string)
        if crc == self.crc:
            return b""
        else:
            self.crc = crc
            return resp_bytes

    async def async_get_module_definitions(self, mod_id) -> bytes:
        """Get summary of Habitron module: names, commands, etc."""
        rtr_id = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_id)
        cmd_str = SMIP_COMMANDS["GET_MODULE_SMC"]
        cmd_str = cmd_str[0:4] + chr(mod_addr) + "\0\0"
        resp = await self.async_send_command(cmd_str)
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def async_get_module_settings(self, mod_id) -> bytes:
        """Get settings of Habitron module."""
        rtr_id = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_id)
        cmd_str = SMIP_COMMANDS["GET_MODULE_SMG"]
        cmd_str = cmd_str[0:4] + chr(mod_addr) + "\0\0"
        resp = await self.async_send_command(cmd_str)
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def module_restart(self, mod_nmbr: int) -> None:
        """Restarts a single module or all with arg 0xFF or router if arg 0"""
        if mod_nmbr > 0:
            # module restart
            cmd_str = SMIP_COMMANDS["REBOOT_MODULE"]
            if mod_nmbr < 65:
                cmd_str = cmd_str.replace("\xff", chr(mod_nmbr))
        else:
            # router restart
            cmd_str = SMIP_COMMANDS["REBOOT_ROUTER"]
        await self.async_send_command(cmd_str)


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


class TimeoutException(exceptions.HomeAssistantError):
    """Error to indicate timeout."""
