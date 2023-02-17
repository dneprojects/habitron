"""Communicate class for Habitron system."""
from __future__ import annotations

from binascii import hexlify

# In a real implementation, this would be in an external library that's on PyPI.
# The PyPI package needs to be included in the `requirements` section of manifest.json
# See https://developers.home-assistant.io/docs/creating_integration_manifest
# for more information.
# This dummy smip always returns 3 rollers.
import socket

from pymodbus.utilities import computeCRC

from homeassistant import exceptions
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import SMARTIP_COMMAND_STRINGS, MirrIdx


class HbtnComm:
    """Habitron communication class."""

    def __init__(self, hass: HomeAssistant, config: ConfigEntry) -> None:
        """Init CommTest for connection test."""
        self._name = config.data["habitron_host"]
        self._host = get_host_ip(self._name)
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

    def set_host(self):
        """Updating host information for integration re-configuration"""
        self._config.data = self._config.options
        self._name = self._config.data["habitron_host"]
        self._host = get_host_ip(self._name)

    def set_router(self, rtr) -> None:
        """Registers the router instance"""
        self.router = rtr

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

    def send_command(self, cmd_string: str) -> bytes:
        """General function for communication via SmartIP"""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        sck.settimeout(15)  # 15 seconds
        full_string = wrap_command(cmd_string)
        resp_bytes = send_receive(sck, full_string)
        sck.close()
        return resp_bytes

    async def async_system_update(self) -> None:
        """Trigger update of Habitron states"""

        if self.router.coord.update_interval.seconds == 6:
            sys_status = await self.get_mirror_status(self.router.modules_desc)
        else:
            sys_status = await self.get_compact_status()
        if sys_status == b"":
            return
        else:
            await self.router.update_system_status(sys_status)

    async def get_mirror_status(self, mod_desc) -> bytes:
        """Get common sys_status by separate calls to mirror"""
        sys_status = b""
        sys_crc = 0
        for desc in mod_desc:
            cmd_str = SMARTIP_COMMAND_STRINGS["READ_MODULE_MIRR_STATUS"]
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
        cmd_string = SMARTIP_COMMAND_STRINGS["GET_COMPACT_STATUS"]
        [resp_bytes, crc] = await self.async_send_command_crc(cmd_string)
        if crc == self.crc:
            return b""
        else:
            self.crc = crc
            return resp_bytes

    def get_mac(self) -> str:
        """Get mac address of SmartIP."""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        mac_res = sck.getsockname()[2]
        self.com_mac = hexlify(mac_res)
        sck.close()
        return self.com_mac

    def module_restart(self, mod_nmbr: int) -> None:
        """Restarts a single module or all with arg 0xFF or router if arg 0"""
        if mod_nmbr > 0:
            # module restart
            cmd_str = SMARTIP_COMMAND_STRINGS["REBOOT_MODULE"]
            if mod_nmbr < 65:
                cmd_str = cmd_str.replace("\xff", chr(mod_nmbr))
        else:
            # router restart
            cmd_str = SMARTIP_COMMAND_STRINGS["REBOOT_ROUTER"]
        self.send_command(cmd_str)


async def test_connection(host_name) -> bool:
    """Test connectivity to SmartIP is OK."""
    port = 7777
    host = get_host_ip(host_name)
    sck = socket.socket()  # Create a socket object
    sck.connect((host, port))
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
    except TimeoutError:
        resp_bytes = b"Timeout"
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
    except TimeoutError:
        return b"Timeout", 0
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


class HostNotFound(exceptions.HomeAssistantError):
    """Error to indicate DNS name is not found."""
