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
from .const import DOMAIN, SMARTIP_COMMAND_STRINGS, MirrIdx


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

    async def async_send_command(self, cmd_string: str) -> bytes:
        """General function for communication via SmartIP"""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        sck.settimeout(30)  # 30 seconds
        full_string = wrap_command(cmd_string)
        resp_bytes = await async_send_receive(sck, full_string)
        sck.close()
        return resp_bytes

    def send_command(self, cmd_string: str) -> bytes:
        """General function for communication via SmartIP"""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        sck.settimeout(15)  # 15 seconds
        full_string = wrap_command(cmd_string)
        resp_bytes = send_receive(sck, full_string)
        sck.close()
        return resp_bytes

    async def async_system_update(self) -> bytes:
        """Trigger update of Habitron states"""
        resp_bytes = self._hass.data[DOMAIN][
            self._config.entry_id
        ].router.update_system_status()
        return resp_bytes

    async def send_command_update(self, cmd_string: str) -> bytes:
        """Send command and trigger update of Habitron states"""
        resp_bytes = await self.async_send_command(cmd_string)
        resp_bytes = await self.async_system_update()
        return resp_bytes

    def get_mirror_status(self, mod_desc):
        """Get common sys_status by separate calls to mirror"""
        sys_status = b""
        for desc in mod_desc:
            cmd_str = SMARTIP_COMMAND_STRINGS["READ_MODULE_MIRR_STATUS"]
            cmd_str = cmd_str.replace("\xff", chr(desc.addr))
            resp = self.send_command(cmd_str)
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
        return sys_status

    def get_mac(self) -> str:
        """Get mac address of SmartIP."""
        sck = socket.socket()  # Create a socket object
        sck.connect((self._host, self._port))
        mac_res = sck.getsockname()[2]
        self.com_mac = hexlify(mac_res)
        sck.close()
        return self.com_mac


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
