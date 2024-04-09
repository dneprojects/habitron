"""Communicate class for Habitron system."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import struct
from typing import Final

import yaml

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
import homeassistant.exceptions as HAexceptions

from .const import DOMAIN, HaEvents
from .router import HbtnRouter

BASE_PATH_COMPONENT = "./homeassistant/components"
BASE_PATH_CUSTOM_COMPONENT = "./custom_components"
DATA_FILES_ADDON_DIR = "/addon_configs/"
DEF_TOKEN_FILE = "def_token.set"

SMHUB_COMMANDS: Final[dict[str, str]] = {
    "GET_MODULES": "\x0a\1\2<rtr>\0\0\0",
    "GET_MODULE_SMG": "\x0a\2\7<rtr><mod>\0\0",
    "GET_MODULE_SMC": "\x0a\3\7<rtr><mod>\0\0",
    "GET_ROUTER_SMR": "\x0a\4\3<rtr>\0\0\0",
    "GET_ROUTER_STATUS": "\x0a\4\4<rtr>\0\0\0",
    "GET_MODULE_STATUS": "\x0a\5\1<rtr><mod>\0\0",
    "GET_COMPACT_STATUS": "\x0a\5\2<rtr>\xff\0\0",  # compact status of all modules (0xFF)
    "GET_SMHUB_BOOT_STATUS": "\x0a\6\1\0\0\0\0",
    "GET_SMHUB_INFO": "\x0a\6\2\0\0\0\0",
    "GET_SMHUB_UPDATE": "\x0a\6\3\0\0\0\0",
    "GET_GLOBAL_DESCRIPTIONS": "\x0a\7\1<rtr>\0\0\0",  # Flags, Command collections
    "GET_SMHUB_STATUS": "\x14\0\0\0\0\0\0",
    "GET_SMHUB_FIRMWARE": "\x14\x1e\0\0\0\0\0",
    "GET_GROUP_MODE": "\x14\2\1<rtr><mod>\0\0",  # <Group 0..>
    "GET_GROUP_MODE0": "\x14\2\1<rtr>\0\0\0",
    "SET_GROUP_MODE": "\x14\2\2<rtr><mod>\3\0<rtr><mod><arg1>",  # <Group 0..><Mode>
    "GET_ROUTER_MODES": "\x14\2\3<rtr><mod>\3\0<rtr><mod>\0",
    "START_MIRROR": "\x14\x28\1<rtr>\0\0\0",
    "STOP_MIRROR": "\x14\x28\2<rtr>\0\0\0",
    "CHECK_COMM_STATUS": "\x14\x64\0\0\0\0\0",
    "SET_OUTPUT_ON": "\x1e\1\1<rtr><mod>\3\0<rtr><mod><arg1>",
    "SET_OUTPUT_OFF": "\x1e\1\2<rtr><mod>\3\0<rtr><mod><arg1>",
    "SET_DIMMER_VALUE": "\x1e\1\3<rtr><mod>\4\0<rtr><mod><arg1><arg2>",  # <Module><DimNo><DimVal>
    "SET_SHUTTER_POSITION": "\x1e\1\4<rtr>\0\5\0<rtr><mod>\1<arg1><arg2>",  # <Module><RollNo><RolVal>
    "SET_BLIND_TILT": "\x1e\1\4<rtr>\0\5\0<rtr><mod>\2<arg1><arg2>",
    "SET_SETPOINT_VALUE": "\x1e\2\1<rtr>\0\5\0<rtr><mod><arg1><arg2><arg3>",  # <Module><ValNo><ValL><ValH>
    "CALL_VIS_COMMAND": "\x1e\3\1\0\0\4\0<rtr><mod><visl><vish>",  # <Module><VisNoL><VisNoH> not tested
    "CALL_COLL_COMMAND": "\x1e\4\1<rtr><cno>\0\0",  # <CmdNo>
    "READ_MODULE_MIRR_STATUS": "\x64\1\5<rtr><mod>\0\0",  # <Module>
    "SET_FLAG_OFF": "\x1e\x0f\0<rtr><mod>\1\0<fno>",
    "SET_FLAG_ON": "\x1e\x0f\1<rtr><mod>\1\0<fno>",
    "COUNTR_UP": "\x1e\x10\2<rtr><mod>\1\0<cno>",
    "COUNTR_DOWN": "\x1e\x10\3<rtr><mod>\1\0<cno>",
    "COUNTR_VAL": "\x1e\x10\4<rtr><mod>\2\0<cno><val>",
    "SET_RGB_OFF": "\x1e\x0c\x00<rtr><mod>\1\0<lno>",
    "SET_RGB_ON": "\x1e\x0c\x01<rtr><mod>\1\0<lno>",
    "SET_RGB_COL": "\x1e\x0c\x04<rtr><mod>\4\0<lno><rd><gn><bl>",
    "GET_LAST_IR_CODE": "\x32\2\1<rtr><mod>\0\0",
    "REINIT_HUB": "\x3c\x00\x00<rtr><opr>\0\0",
    "RESTART_HUB": "\x3c\x00\x02<rtr>\0\0\0",
    "REBOOT_HUB": "\x3c\x00\x03\0\0\0\0",
    "SEND_NETWORK_INFO": "\x3c\x00\x04\0\0<len><iplen><ipv4><toklen><tok>",
    "SET_LOG_LEVEL": "\x3c\x00\x05<hdlr><lvl>\0\0",  # Set logging level of console/file handler
    "RESTART_FORWARD_TABLE": "\x3c\x01\x01<rtr>\0\0\0",  # Weiterleitungstabelle löschen und -automatik starten
    "GET_CURRENT_ERROR": "\x3c\x01\x02<rtr>\0\0\0",
    "GET_LAST_ERROR": "\x3c\x01\x03<rtr>\0\0\0",
    "REBOOT_ROUTER": "\x3c\x01\x04<rtr>\0\0\0",  #
    "REBOOT_MODULE": "\x3c\x03\x01<rtr><mod>\0\0",  # <Module> or 0xFF for all modules
}


class HbtnComm:
    """Habitron communication class."""

    def __init__(self, hass: HomeAssistant, config: ConfigEntry) -> None:
        """Init CommTest for connection test."""
        self._name: str = "HbtnComm"
        self._host_conf: str = config.data.__getitem__("habitron_host")
        self.logger = logging.getLogger(__name__)
        self._host: str = get_host_ip(self._host_conf)
        self.logger.info(f"Initializing hub, got own ip: {self._host}")  # noqa: G004
        self._port: int = 7777

        self._hass: HomeAssistant = hass
        self._config: ConfigEntry = config
        self._hostname: str = ""
        self._hostip: str = self._host
        self._mac: str = ""
        self._hwtype: str = ""
        self._version: str = ""
        self._network_ip: str = hass.data["network"].adapters[0]["ipv4"][0]["address"]
        self.logger.info(f"Got network ip: {self._network_ip}")  # noqa: G004
        # self._websck_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJjMWI1ZjgyNmUxMDg0MjFhYWFmNTZlYWQ0ZThkZGNiZSIsImlhdCI6MTY5NDUzNTczOCwiZXhwIjoyMDA5ODk1NzM4fQ.0YZWyuQn5DgbCAfEWZXbQZWaViNBsR4u__LjC4Zf2lY"
        # self._websck_token = ""
        self._loop = asyncio.get_event_loop()
        self.crc: int = 0
        self.router: HbtnRouter
        self.update_suspended: bool = False
        self.is_smhub: bool = False  # will be set in get_smhub_info()
        self.is_addon: bool = False  # will be set in get_smhub_info()
        self.info: dict[str, str] = self.get_smhub_info()
        self.grp_modes: dict = {}

    @property
    def com_ip(self) -> str:
        """IP of SmartHub."""
        return self._hostip

    @property
    def com_port(self) -> int:
        """Port for SmartHub."""
        return self._port

    @property
    def com_mac(self) -> str:
        """Mac address for SmartHub."""
        return self._mac

    @property
    def com_version(self) -> str:
        """Firmware version of SmartHub."""
        return self._version

    @property
    def com_hwtype(self) -> str:
        """Firmware version of SmartHub."""
        return self._hwtype

    async def set_host(self, host: str):
        """Update host information for integration re-configuration."""
        self._hass.config_entries.async_update_entry(
            self._config, data=self._config.options
        )
        if self._host_conf == host:
            return
        self._host_conf = host
        self._host = get_host_ip(self._host_conf)
        await self._hass.config_entries.async_reload(self._config.entry_id)

    async def send_network_info(self, tok: str):
        """Send home assistant ipv4."""
        if tok == "":
            return
        cmd_str = SMHUB_COMMANDS["SEND_NETWORK_INFO"]
        ipv4 = self._network_ip
        ip_len = len(ipv4)
        tk_len = len(tok)
        if not self.is_addon:
            nmbrs = self._mac.split(":")
            for i in range(len(nmbrs)):
                idx = int("0x" + nmbrs[len(nmbrs) - i - 1], 0) & 0x7F
                if idx < tk_len:
                    tok = tok[:idx] + tok[idx + 1 :] + tok[idx]
        args_len = ip_len + tk_len + 2
        len_l = args_len & 0xFF
        len_h = args_len >> 8
        cmd_str = (
            cmd_str.replace("<len>", chr(len_l) + chr(len_h))
            .replace("<iplen>", chr(ip_len))
            .replace("<ipv4>", ipv4)
            .replace("<toklen>", chr(tk_len))
            .replace("<tok>", tok)
        )
        await self.async_send_command(cmd_str)
        self.logger.warning(
            f"Sent network info to hub (ip and token) - ip: {ipv4} - token: {tok}"  # noqa: G004
        )

    async def reinit_hub(self, rtr_id, mode):
        """Restart event server on hub."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["REINIT_HUB"].replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<opr>", chr(mode))
        resp = await self.async_send_command(
            cmd_str, time_out_sec=12
        )  # extended time-out 12 s
        self.logger.info(f"Re-initialized hub with mode {mode}")  # noqa: G004
        return resp

    def set_router(self, rtr) -> None:
        """Register the router instance."""
        self.router = rtr

    async def get_smhub_version(self) -> bytes:
        """Query of SmartHub firmware."""
        return await self.async_send_command(SMHUB_COMMANDS["GET_SMHUB_FIRMWARE"])

    def get_smhub_info(self) -> dict[str, str]:
        """Get basic infos of SmartHub."""
        smhub_info = query_smarthub(self._host)  # get info from query port
        if not smhub_info:
            raise (TimeoutError)
        self.is_smhub = smhub_info["serial"] == "RBPI"
        if not self.is_smhub:
            # Smart Hub
            info = smhub_info
            self._version = info["version"]
            self._serial = info["serial"]
            self._hwtype = info["type"]
            self._hostip = info["ip"]
            self._mac = info["mac"]
            self._hostname = info["hostname"]
        else:
            # Smart Hub
            sck = socket.socket()  # Create a socket object
            try:
                sck.connect((self._host, self._port))
            except ConnectionRefusedError as exc:
                raise ConnectionRefusedError from exc
            sck.settimeout(8)  # 8 seconds
            cmd_str = SMHUB_COMMANDS["GET_SMHUB_INFO"]
            full_string = wrap_command(cmd_str)
            resp_bytes = send_receive(sck, full_string)
            sck.close()

            info = yaml.load(resp_bytes.decode("iso8859-1"), Loader=yaml.Loader)
            self._version = info["software"]["version"]
            self._hwtype = info["hardware"]["platform"]["type"]
            self._hostip = info["hardware"]["network"]["ip"]
            self._hostname = info["hardware"]["network"]["host"]
            self._mac = info["hardware"]["network"]["lan mac"]
            self.is_addon = self._hostname.split(".")[0].find("smart-hub") > 0
        self.logger.debug(f"SmartHub info - host name: {self._hostname}")  # noqa: G004
        self.logger.debug(f"SmartHub info - ip: {self._hostip}")  # noqa: G004
        self.logger.debug(f"SmartHub info - version: {self._version}")  # noqa: G004
        self.logger.debug(f"SmartHub info - hw type: {self._hwtype}")  # noqa: G004
        return info

    def get_smhub_update(self):
        """Get current sensor and status values."""
        sck = socket.socket()  # Create a socket object
        try:
            sck.connect((self._host, self._port))
        except ConnectionRefusedError as exc:
            raise ConnectionRefusedError from exc
        sck.settimeout(8)  # 8 seconds
        cmd_str = SMHUB_COMMANDS["GET_SMHUB_UPDATE"]
        full_string = wrap_command(cmd_str)
        resp_bytes = send_receive(sck, full_string)
        sck.close()
        info = yaml.load(resp_bytes.decode("iso8859-1"), Loader=yaml.Loader)
        return info

    async def get_smr(self, rtr_id) -> bytes:
        """Get router SMR information."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["GET_ROUTER_SMR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        resp = await self.async_send_command(cmd_str, time_out_sec=15)
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

    async def async_send_command(self, cmd_string: str, time_out_sec=10) -> bytes:
        """General function for communication via SmartHub."""
        try:
            sck = socket.socket()  # Create a socket object
            sck.connect((self._host, self._port))
            sck.settimeout(time_out_sec)  # 8 seconds
            full_string = wrap_command(cmd_string)
            res = await async_send_receive(sck, full_string)
            sck.close()
            resp_bytes = res[0]
            return resp_bytes
        except TimeoutError as err_msg:  # noqa: F841
            sck.close()
            self.logger.error(f"Error connecting to Smart Hub: {err_msg}")  # noqa: G004
            return b""

    async def async_send_command_crc(
        self, cmd_string: str, time_out_sec=10
    ) -> tuple[bytes, int]:
        """General function for communication via SmartHub, returns additional crc."""
        try:
            sck = socket.socket()  # Create a socket object
            sck.connect((self._host, self._port))
            sck.settimeout(time_out_sec)  # default: 10 seconds
            full_string = wrap_command(cmd_string)
            res = await async_send_receive(sck, full_string)
            sck.close()
            return res[0], res[1]
        except TimeoutError as err_msg:  # noqa: F841
            sck.close()
            self.logger.error(f"Error connecting to Smart Hub: {err_msg}")  # noqa: G004
            return b"", 0

    async def async_get_router_status(self, rtr_id) -> bytes:
        """Get router status."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["GET_ROUTER_STATUS"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        resp = await self.async_send_command(cmd_str)
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def async_get_router_modules(self, rtr_id) -> bytes:
        """Get summary of all Habitron modules of a router."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["GET_MODULES"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        resp = await self.async_send_command(cmd_str)
        if resp[0:5].decode("iso8859-1") == "Error":
            return b""
        return resp

    async def get_global_descriptions(self, rtr_id) -> bytes:
        """Get descriptions of commands, etc."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["GET_GLOBAL_DESCRIPTIONS"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        return await self.async_send_command(cmd_str)

    async def async_get_error_status(self, rtr_id) -> bytes:
        """Get error byte for each module."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["GET_CURRENT_ERROR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        return await self.async_send_command(cmd_str)

    async def async_start_mirror(self, rtr_id) -> None:
        """Start mirror on specified router."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["START_MIRROR"]
        if self.is_smhub:
            cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        else:
            cmd_str = cmd_str.replace("<rtr>", "\0")
        if self.router.version.split("/")[1] == "2024":
            # Quick fix for problems with router-fw
            self.send_only(cmd_str)
        else:
            await self.async_send_command(cmd_str)

    async def async_stop_mirror(self, rtr_id) -> None:
        """Start mirror on specified router."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["STOP_MIRROR"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        await self.async_send_command(cmd_str)

    async def async_system_update(self) -> None:
        """Trigger update of Habitron states, must poll all routers."""

        if self.update_suspended:
            # disable update to avoid conflict with SmartConfig or other communication
            return
        else:
            sys_status = await self.get_compact_status(self.router.id)
        if sys_status == b"":
            # self.logger.debug("No changes in compact system status, update skipped")
            return
        elif len(sys_status) < 10:
            self.logger.warning(
                f"Received compact system status too short, length: {len(sys_status)}"  # noqa: G004
            )
            return
        await self.router.update_system_status(sys_status)

    async def async_set_group_mode(self, rtr_id, grp_no, new_mode) -> None:
        """Set mode for given group."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["SET_GROUP_MODE"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(grp_no))
        cmd_str = cmd_str.replace("<arg1>", chr(new_mode))
        await self.async_send_command(cmd_str)

    async def async_set_daytime_mode(self, rtr_id, grp_no, new_mode) -> None:
        """Set mode for given group."""
        rtr_nmbr = int(rtr_id / 100)
        if new_mode == 1:
            mode = 0x42
        elif new_mode == 2:
            mode = 0x43
        else:
            return
        cmd_str = SMHUB_COMMANDS["SET_GROUP_MODE"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(grp_no))
        cmd_str = cmd_str.replace("<arg1>", chr(mode))
        await self.async_send_command(cmd_str)

    async def async_set_alarm_mode(self, rtr_id, grp_no, alarm_mode) -> None:
        """Set mode for given group."""
        rtr_nmbr = int(rtr_id / 100)
        if alarm_mode:
            mode = 0x40
        else:
            mode = 0x41
        cmd_str = SMHUB_COMMANDS["SET_GROUP_MODE"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(grp_no))
        cmd_str = cmd_str.replace("<arg1>", chr(mode))
        await self.async_send_command(cmd_str)

    async def async_set_log_level(self, hdlr, level) -> None:
        """Set new logging level."""
        cmd_str = SMHUB_COMMANDS["SET_LOG_LEVEL"]
        cmd_str = cmd_str.replace("<hdlr>", chr(hdlr))
        cmd_str = cmd_str.replace("<lvl>", chr(level))
        await self.async_send_command(cmd_str)

    def set_output(self, mod_id, nmbr, val) -> None:
        """Send turn_on/turn_off command."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        if val:
            cmd_str = SMHUB_COMMANDS["SET_OUTPUT_ON"]
        else:
            cmd_str = SMHUB_COMMANDS["SET_OUTPUT_OFF"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        self.send_only(cmd_str)

    async def async_set_output(self, mod_id, nmbr, val) -> None:
        """Send turn_on/turn_off command."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        if val:
            cmd_str = SMHUB_COMMANDS["SET_OUTPUT_ON"]
        else:
            cmd_str = SMHUB_COMMANDS["SET_OUTPUT_OFF"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        await self.async_send_command(cmd_str)

    async def async_set_led_outp(self, mod_id, nmbr, val) -> None:
        """Translate led nmbr to output nmbr and send on/off command."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        mod = self.router.get_module(mod_addr)
        await self.async_set_output(
            mod_id,
            nmbr + len(mod.outputs) + 1,  # type: ignore
            val,
        )

    async def async_set_dimmval(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMHUB_COMMANDS["SET_DIMMER_VALUE"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        await self.async_send_command(cmd_str)

    async def async_set_rgb_output(self, mod_id, nmbr, val) -> None:
        """Turn RGB light on/off."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        if val:
            cmd_str = SMHUB_COMMANDS["SET_RGB_ON"]
        else:
            cmd_str = SMHUB_COMMANDS["SET_RGB_OFF"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<lno>", chr(nmbr))
        await self.async_send_command(cmd_str)

    async def async_set_rgbval(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMHUB_COMMANDS["SET_RGB_COL"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<lno>", chr(nmbr))
        cmd_str = cmd_str.replace("<rd>", chr(val[0]))
        cmd_str = cmd_str.replace("<gn>", chr(val[1]))
        cmd_str = cmd_str.replace("<bl>", chr(val[2]))
        await self.async_send_command(cmd_str)

    async def async_set_shutterpos(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMHUB_COMMANDS["SET_SHUTTER_POSITION"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        await self.async_send_command(cmd_str)

    async def async_set_blindtilt(self, mod_id, nmbr, val) -> None:
        """Send value to dimm output."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMHUB_COMMANDS["SET_BLIND_TILT"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg2>", chr(val))
        await self.async_send_command(cmd_str)

    async def async_set_flag(self, mod_id, nmbr, val) -> None:
        """Send flag on/flag off command."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        # if zero, global flag
        if val:
            cmd_str = SMHUB_COMMANDS["SET_FLAG_ON"]
        else:
            cmd_str = SMHUB_COMMANDS["SET_FLAG_OFF"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<fno>", chr(nmbr))
        await self.async_send_command(cmd_str)

    async def async_inc_dec_counter(self, mod_id, nmbr, val) -> None:
        """Send flag on/flag off command."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        if val == 1:
            cmd_str = SMHUB_COMMANDS["COUNTR_UP"]
        else:
            cmd_str = SMHUB_COMMANDS["COUNTR_DOWN"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<cno>", chr(nmbr))
        await self.async_send_command(cmd_str)

    async def async_set_setpoint(self, mod_id, nmbr, val) -> None:
        """Send two byte value for setpoint definition."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMHUB_COMMANDS["SET_SETPOINT_VALUE"]
        hi_val = int(val / 256)
        lo_val = val - 256 * hi_val
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<arg1>", chr(nmbr))
        cmd_str = cmd_str.replace("<arg3>", chr(hi_val))
        cmd_str = cmd_str.replace("<arg2>", chr(lo_val))
        await self.async_send_command(cmd_str)

    async def async_call_vis_command(self, mod_id, nmbr) -> None:
        """Call of visualization command of nmbr."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMHUB_COMMANDS["CALL_VIS_COMMAND"]
        hi_no = int(nmbr / 256)
        lo_no = nmbr - 256 * hi_no
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_addr))
        cmd_str = cmd_str.replace("<vish>", chr(hi_no))
        cmd_str = cmd_str.replace("<visl>", chr(lo_no))
        await self.async_send_command(cmd_str)

    async def async_call_coll_command(self, rtr_id, nmbr) -> None:
        """Call collective command of nmbr."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["CALL_COLL_COMMAND"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<cno>", chr(nmbr))
        await self.async_send_command(cmd_str)

    async def get_compact_status(self, rtr_id) -> bytes:
        """Get compact status for all modules, if changed crc."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["GET_COMPACT_STATUS"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        [resp_bytes, crc] = await self.async_send_command_crc(cmd_str, time_out_sec=15)
        if crc == self.crc:
            return b""
        else:
            self.crc = crc
            return resp_bytes

    async def get_module_status(self, mod_id) -> bytes:
        """Get compact status for all modules, if changed crc."""
        rtr_nmbr = int(mod_id / 100)
        mod_nmbr = mod_id - rtr_nmbr * 100
        cmd_str = SMHUB_COMMANDS["GET_MODULE_STATUS"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        cmd_str = cmd_str.replace("<mod>", chr(mod_nmbr))
        [resp_bytes, crc] = await self.async_send_command_crc(cmd_str, time_out_sec=15)
        if crc == self.crc:
            return b""
        else:
            self.crc = crc
            return resp_bytes

    async def async_get_module_definitions(self, mod_id) -> bytes:
        """Get summary of Habitron module: names, commands, etc."""
        rtr_nmbr = int(mod_id / 100)
        mod_addr = int(mod_id - 100 * rtr_nmbr)
        cmd_str = SMHUB_COMMANDS["GET_MODULE_SMC"]
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
        cmd_str = SMHUB_COMMANDS["GET_MODULE_SMG"]
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
        """Get router settings (smr) and saves them to file."""
        data = await self.get_smr(rtr_id)
        file_name = f"Router_{rtr_id}.smr"
        str_data = ""
        for byt in data:
            str_data += f"{byt};"
        await self.save_config_data(file_name, str_data)

    async def save_config_data(self, file_name: str, str_data: str) -> None:
        """Save config info to text file."""
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

    async def hub_restart(self, rtr_id: int) -> None:
        """Restart hub."""
        rtr_nmbr = int(rtr_id / 100)
        cmd_str = SMHUB_COMMANDS["RESTART_HUB"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        await self.async_send_command(cmd_str)

    async def hub_reboot(self) -> None:
        """Reboot hub."""
        cmd_str = SMHUB_COMMANDS["REBOOT_HUB"]
        await self.async_send_command(cmd_str)

    async def module_restart(self, rtr_nmbr: int, mod_nmbr: int) -> None:
        """Restart a single module or all with arg 0xFF or router if arg 0."""
        if mod_nmbr > 0:
            # module restart
            cmd_str = SMHUB_COMMANDS["REBOOT_MODULE"]
            cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
            cmd_str = cmd_str.replace("<mod>", chr(mod_nmbr))

        else:
            # router restart
            cmd_str = SMHUB_COMMANDS["REBOOT_ROUTER"]
        cmd_str = cmd_str.replace("<rtr>", chr(rtr_nmbr))
        await self.async_send_command(cmd_str)

    async def update_entity(self, hub_id, rtr_id, mod_id, evnt, arg1, arg2):
        """Event server handler to receive entity updates."""
        inp_event_types = ["inactive", "single_press", "long_press", "long_press_end"]
        if self._hostip != hub_id:
            return
        module = self.router.get_module(mod_id)
        if module is None:
            self.logger.error(
                f"Error in update_entity: No module found for mod_id {mod_id}"  # noqa: G004
            )
        else:
            try:
                if evnt == HaEvents.BUTTON:
                    # Button pressed or released
                    await module.inputs[arg1 - 1].handle_upd_event(
                        inp_event_types[arg2]
                    )
                    if arg2 in [1, 3]:
                        await module.inputs[arg1 - 1].handle_upd_event(
                            inp_event_types[0]
                        )
                elif evnt == HaEvents.SWITCH:
                    # Switch input changed
                    module.inputs[arg1 - 1].value = arg2
                    await module.inputs[arg1 - 1].handle_upd_event()
                elif evnt == HaEvents.OUTPUT:
                    # Output changed
                    if arg1 > 15:
                        # LED
                        module.leds[arg1 - 16].value = arg2
                        await module.leds[arg1 - 16].handle_upd_event()
                    elif (module.typ[0] == 50) & (arg1 > 2):
                        await module.leds[arg1 - 2 - 1].handle_upd_event()
                    else:
                        module.outputs[arg1 - 1].value = arg2
                        await module.outputs[arg1 - 1].handle_upd_event()
                        if (c_idx := module.get_cover_index(arg1)) >= 0:
                            # module.covers[c_idx].value = module.status[
                            #     MStatIdx.ROLL_POS + c_idx
                            # ]
                            # module.covers[c_idx].tilt = module.status[
                            #     MStatIdx.BLAD_POS + c_idx
                            # ]
                            await module.covers[c_idx].handle_upd_event()
                elif evnt == HaEvents.FINGER:
                    # Ekey input detected
                    module.sensors[0].value = arg1
                    await module.sensors[0].handle_upd_event()
                    await module.fingers[0].handle_upd_event("finger", arg1)
                    await asyncio.sleep(0.2)
                    await module.fingers[0].handle_upd_event(
                        "inactive", 0
                    )  # set back to 'None'
                elif evnt == HaEvents.DIM_VAL:
                    module.dimmers[arg1].value = arg2
                    await module.dimmers[arg1].handle_upd_event()
                elif evnt == HaEvents.COV_VAL:
                    module.covers[arg1].value = arg2
                    await module.covers[arg1].handle_upd_event()
                elif evnt == HaEvents.BLD_VAL:
                    module.covers[arg1].tilt = arg2
                    await module.covers[arg1].handle_upd_event()
                elif evnt == HaEvents.MOVE:
                    module.sensors[arg1].value = int(arg2 > 0)
                    await module.sensors[arg1].handle_upd_event()
                elif evnt == HaEvents.FLAG:
                    for flg in module.flags:
                        if flg.nmbr == arg1 + 1:
                            flg.value = int(arg2 > 0)
                            await flg.handle_upd_event()
                elif evnt == HaEvents.CNT_VAL:
                    module.logic[arg1].value = arg2
                    await module.logic[arg1].handle_upd_event()
                elif evnt == HaEvents.MODE:
                    module.mode.value = arg2
                    await module.mode.handle_upd_event()
            except Exception as err_msg:  # pylint: disable=broad-exception-caught
                self.logger.warning(
                    f"Error handling habitron event {evnt} with arg1 {arg1} of module {mod_id}: {err_msg}"  # noqa: G004
                )


async def test_connection(host_name) -> tuple[bool, str]:
    """Test connectivity to SmartHub is OK."""
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
    cmd_str = SMHUB_COMMANDS["CHECK_COMM_STATUS"]
    full_string = wrap_command(cmd_str)
    resp_bytes = send_receive(sck, full_string)
    sck.close()
    resp_string = resp_bytes.decode("iso8859-1")
    conn_ok = resp_string[0:2] == "OK"
    smhub_info = query_smarthub(host)
    if conn_ok:
        host_name = smhub_info["name"]
    else:
        host_name = ""
    return conn_ok, host_name


def get_host_ip(host_name: str) -> str:
    """Get IP from DNS host name, error handling."""
    host = socket.gethostbyname(host_name)
    return host


def send_receive(sck, cmd_str: str) -> bytes:
    """Send string to SmartHub and wait for response with timeout."""
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


async def async_send_receive(sck, cmd_str: str) -> tuple[bytes, int]:
    """Send string to SmartHub and wait for response with timeout."""
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


def init_crc16_tbl() -> list[int]:
    """Prepare the crc16 table."""
    res: list[int] = []
    for byte in range(256):
        crc = 0x0000
        for _ in range(8):
            if (byte ^ crc) & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
            byte >>= 1
        res.append(crc)
    return res


__crc16_tbl: list[int] = init_crc16_tbl()


def calc_crc(data: bytes) -> int:
    """Calculate a crc16 for the given byte string."""
    crc = 0xFFFF
    for byt in data:
        idx = __crc16_tbl[(crc ^ int(byt)) & 0xFF]
        crc = ((crc >> 8) & 0xFF) ^ idx
    crc_res = ((crc << 8) & 0xFF00) | ((crc >> 8) & 0x00FF)
    return crc_res


def check_crc(msg) -> bool:
    """Check crc of message."""
    msg_crc = int.from_bytes(msg[-3:-1], "little")
    return calc_crc(msg[:-3]) == msg_crc


def wrap_command(cmd_string: str) -> str:
    """Take command and add prefix, crc, postfix."""
    cmd_prefix = "¨\0\0\x0bSmartConfig\x05michlS\x05"
    cmd_postfix = "\x3f"
    full_string = cmd_prefix + cmd_string
    cmd_len = len(full_string) + 3
    full_string = full_string[0] + chr(cmd_len) + full_string[2 : cmd_len - 3]
    cmd_crc = calc_crc(full_string.encode("iso8859-1"))
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


def get_own_ip():
    """Return string of own ip."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    own_ip = s.getsockname()[0]
    s.close()
    return own_ip


def discover_smarthubs():
    """Discover SmartHub and SmartServer hardware on the network."""
    smhub_port = 30718
    own_ip = get_own_ip()
    timeout = 2
    logger = logging.getLogger(__name__)

    req_header_data = [0x00, 0x00, 0x00, 0xF6]
    req_header = struct.pack("B" * len(req_header_data), *req_header_data)
    resp_header_data = [0x00, 0x00, 0x00, 0xF7]
    resp_header = struct.pack("B" * len(resp_header_data), *resp_header_data)

    network_socket = socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
    )
    network_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
    network_socket.settimeout(timeout)
    network_socket.bind((own_ip, 0))

    network_socket.sendto(req_header, ("<broadcast>", smhub_port))

    smarthubs = []

    try:
        while True:
            response, address_info = network_socket.recvfrom(1024)

            smhub_ip = address_info[0]
            logger.info(f"SmartHub found at address {smhub_ip}")  # noqa: G004

            if response[0:4] == resp_header and smhub_ip != "0.0.0.0":
                smhub_version = f"{response[7]}.{response[6]}.{response[5]}"
                smhub_mac = f"{response[24]:02X}:{response[25]:02X}:{response[26]:02X}:{response[27]:02X}:{response[28]:02X}:{response[29]:02X}"
                smhub_serial = (
                    f"{response[20]:c}{response[21]:c}{response[22]:c}{response[23]:c}"
                )
                smhub_type = f"{response[8]:c}-{response[9]:c}"
                smarthub_info = {
                    "type": smhub_type,
                    "version": smhub_version,
                    "serial": smhub_serial,
                    "mac": smhub_mac,
                    "ip": smhub_ip,
                }

                smarthubs.append(smarthub_info)

            else:
                pass

    except TimeoutError:
        pass

    network_socket.close()
    return smarthubs


def query_smarthub(smhub_ip) -> dict[str, str]:
    """Read properties of identified SmartIP or SmartHub.

    :param smhub_ip: ip address of a single smartip
    """

    smhub_port = 30718
    timeout = 1

    req_header_data = [0x00, 0x00, 0x00, 0xF6]
    req_header = struct.pack("B" * len(req_header_data), *req_header_data)
    resp_header_data = [0x00, 0x00, 0x00, 0xF7]
    resp_header = struct.pack("B" * len(resp_header_data), *resp_header_data)

    network_socket = socket.socket(
        socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP
    )
    network_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
    network_socket.settimeout(timeout)

    try:
        network_socket.sendto(req_header, (smhub_ip, smhub_port))
        response, address_info = network_socket.recvfrom(1024)

        smhub_ip = address_info[0]

        if response[0:4] == resp_header and smhub_ip != "0.0.0.0":
            smhub_version = f"{response[7]}.{response[6]}.{response[5]}"
            smhub_mac = f"{response[24]:02X}:{response[25]:02X}:{response[26]:02X}:{response[27]:02X}:{response[28]:02X}:{response[29]:02X}"
            smhub_serial = (
                f"{response[20]:c}{response[21]:c}{response[22]:c}{response[23]:c}"
            )
            smhub_type = f"{response[8]:c}-{response[9]:c}"
            if smhub_type == "E-5":
                # Classic SmartIP
                smhub_name = f"SmartIP_{smhub_mac.replace(':','')}"
            else:
                # Smart Hub
                smhub_name = f"SmartHub_{smhub_mac.replace(':','')}"

            smartip_info = {
                "name": smhub_name,
                "hostname": "",
                "type": smhub_type,
                "version": smhub_version,
                "serial": smhub_serial,
                "mac": smhub_mac,
                "ip": smhub_ip,
            }
    except TimeoutError:
        network_socket.close()
        return {}

    network_socket.close()
    try:  # noqa: SIM105
        smartip_info["hostname"] = socket.gethostbyaddr(smhub_ip)[0].split(".")[0]
    except:  # noqa: E722
        smartip_info["hostname"] = ""
    return smartip_info


class TimeoutException(HAexceptions.HomeAssistantError):
    """Error to indicate timeout."""
