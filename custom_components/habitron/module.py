"""Module class."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .communicate import HbtnComm as hbtn_com
from .const import DOMAIN, SMARTIP_COMMAND_STRINGS, MirrIdx, MMirrIdx

# In a real implementation, this would be in an external library that's on PyPI.
# The PyPI package needs to be included in the `requirements` section of manifest.json
# See https://developers.home-assistant.io/docs/creating_integration_manifest
# for more information.


class ModuleDescriptor:
    """Habitron modules descriptor."""

    def __init__(self, addr, mtype, name, group):
        self.addr: int = addr
        self.mtype: str = mtype
        self.name: str = name
        self.group: int = group


class IfDescriptor:
    """Habitron interface descriptor."""

    def __init__(self, iname, inmbr, itype, ivalue):
        self.name: str = iname
        self.nmbr: int = inmbr
        self.type: int = itype
        self.value: int = ivalue


class HbtnModule:
    """Habitron Module class."""

    manufacturer = "Habitron GmbH"

    has_inputs = False
    has_outputs = False
    has_sensors = False
    has_setvals = False

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
    ) -> None:
        """Init Habitron module."""
        self._hass = hass
        self._config = config
        self.name = mod_descriptor.name
        self.comm = hbtn_com(hass, config)
        self.sw_version = ""
        self.hw_version = ""
        self._addr = mod_descriptor.addr
        self._type = mod_descriptor.mtype
        self.smc = ""
        self.smg = ""
        self.status = ""
        self.mstatus = ""
        self.id = "Mod_" + f"{mod_descriptor.addr}"
        self.group = mod_descriptor.group
        self.mode = 1

        self.inputs: list[IfDescriptor] = []
        self.outputs: list[IfDescriptor] = []
        self.dimmers: list[IfDescriptor] = []
        self.covers: list[IfDescriptor] = []
        self.sensors: list[IfDescriptor] = []
        self.leds: list[IfDescriptor] = []
        self.messages: list[IfDescriptor] = []
        self.commands: list[IfDescriptor] = []
        self.flags: list[IfDescriptor] = []
        self.logic: list[IfDescriptor] = []

    @property
    def mod_id(self) -> str:
        """Id of module."""
        return self.id

    @property
    def mod_addr(self) -> str:
        """Address of module."""
        return self._addr

    @property
    def mod_type(self) -> str:
        """Type of module."""
        return self._type

    async def initialize(self, sys_status) -> None:
        """Initialize module instance"""
        await self.get_smg()
        self.hw_version = self.smg[83 : (83 + 17)].decode("iso8859-1").strip()
        self.sw_version = self.smg[100 : (100 + 22)].decode("iso8859-1").strip()
        device_registry = dr.async_get(self._hass)
        device_registry.async_get_or_create(
            config_entry_id=self._config.entry_id,
            identifiers={(DOMAIN, self.id)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self.name,
            model=self._type,
            sw_version=self.sw_version,
            hw_version=self.hw_version,
        )

    async def get_smc(self) -> bool:
        """Get summary of all Habitron module."""
        cmd_str = SMARTIP_COMMAND_STRINGS["GET_MODULE_SMC"]
        cmd_str = cmd_str[0:4] + chr(self._addr) + "\0\0"
        resp = await self.comm.async_send_command(cmd_str)
        mod_string = resp.decode("iso8859-1")
        if mod_string[0:5] == "Error":
            return False
        elif mod_string == "":
            return False
        self.smc = resp
        return True

    async def get_smg(self) -> bool:
        """Get settings of Habitron module."""
        cmd_str = SMARTIP_COMMAND_STRINGS["GET_MODULE_SMG"]
        cmd_str = cmd_str[0:4] + chr(self._addr) + "\0\0"
        resp = await self.comm.async_send_command(cmd_str)
        mod_string = resp.decode("iso8859-1")
        if mod_string[0:5] == "Error":
            return False
        elif mod_string == "":
            return False
        self.smg = resp
        return True

    def update(self, sys_status):
        """General update for Habitron modules."""
        self.status = self.extract_status(sys_status)
        self.mode = self.status[MirrIdx.STAT_IND_MODE]
        return

    def extract_status(self, sys_status) -> bytes:
        """Extract status of Habitron module from system status."""
        stat_len = MirrIdx.STAT_IND_END
        no_mods = int(len(sys_status) / stat_len)
        for m_idx in range(no_mods):
            if int(sys_status[m_idx * stat_len + MirrIdx.STAT_IND_ADDR]) == self._addr:
                break
        return sys_status[m_idx * stat_len : (m_idx + 1) * stat_len]


class SmartController(HbtnModule):
    """Habitron SmartController module class."""

    has_inputs = True
    has_outputs = True
    has_sensors = True
    has_setvals = True

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
    ) -> None:
        """Init Habitron SmartController module."""
        super().__init__(mod_descriptor, hass, config)
        self.messages: list[IfDescriptor] = []
        self.commands: list[IfDescriptor] = []
        self.setvalues = [IfDescriptor("Set temperature", 0, 2, 20.0)]

        self.sensors.append(IfDescriptor("Movement", 0, 2, 0))
        self.sensors.append(IfDescriptor("Temperature", 1, 2, 0))
        self.sensors.append(IfDescriptor("Humidity", 2, 2, 0))
        self.sensors.append(IfDescriptor("Illuminance", 3, 2, 0))
        self.sensors.append(IfDescriptor("Airquality", 4, 2, 0))

    async def initialize(self, sys_status) -> None:
        await super().initialize(sys_status)
        await self.get_smg()
        await self.get_smc()
        self.parse_smc()
        self.parse_smg()
        self.update(sys_status)

    def parse_smc(self) -> None:
        """Get names"""
        resp = self.smc
        empty = IfDescriptor("", -1, 0, 0)
        empty_inp = IfDescriptor("", 0, -1, 0)
        self.inputs = [empty_inp] * 18
        self.outputs = [empty] * 15
        self.dimmers = [empty] * 2
        self.leds = [empty] * 12
        self.covers = [empty] * 5
        no_lines = int.from_bytes(resp[0:2], "little")
        resp = resp[4 : len(resp)]  # Strip 4 header bytes
        for _ in range(no_lines):
            if resp == b"":
                break
            line_len = int(resp[5]) + 5
            line = resp[0:line_len]
            event_code = int(line[2])
            if event_code == 235:  # Beschriftung
                text = line[8:-1]
                text = text.decode("iso8859-1")
                text = text.strip()
                arg_code = int(line[3])
                if int(line[0]) == 253:
                    # Beschriftungen Direktbefehle
                    self.commands.append(IfDescriptor(text, arg_code, 0, 0))
                elif int(line[0]) == 254:
                    # Beschriftungen Meldungen
                    self.messages.append(IfDescriptor(text, arg_code, 0, 0))
                elif int(line[0]) == 255:
                    if arg_code in range(10, 18):
                        # Beschriftungen Modultaster
                        self.inputs[arg_code - 10] = IfDescriptor(
                            text, arg_code - 10, 0, 0
                        )
                    elif arg_code in range(18, 26):
                        # Beschriftungen LEDs
                        self.leds[arg_code - 18] = IfDescriptor(
                            text, arg_code - 18, 0, 0
                        )
                    elif arg_code in range(40, 50):
                        # Beschriftungen Inputs
                        self.inputs[arg_code - 32] = IfDescriptor(
                            text, arg_code - 32, 0, 0
                        )
                    else:
                        # Beschriftungen Outputs
                        self.outputs[arg_code - 60] = IfDescriptor(
                            text, arg_code - 60, 1, 0
                        )
            resp = resp[line_len : len(resp)]  # Strip processed line
        self.dimmers[0] = IfDescriptor(self.outputs[10].name, 0, 2, 0)
        self.dimmers[1] = IfDescriptor(self.outputs[1].name, 1, 2, 0)
        self.outputs[10].type = 2
        self.outputs[11].type = 2

    def parse_smg(self) -> None:
        """Get settings"""
        resp = self.smg
        roller_state = resp[132]
        input_state = int.from_bytes(resp[40:42], "little")
        for c_idx in range(len(self.inputs)):
            if input_state & (0x01 << c_idx) > 0:
                self.inputs[c_idx + 8].type = 1  # switch, skip 8 internal buttons
        for c_idx in range(2, len(self.covers)):
            if roller_state & (0x01 << (c_idx - 2)) > 0:
                cname = self.outputs[2 * c_idx].name.strip()
                cname = cname.replace("auf", "")
                cname = cname.replace("ab", "")
                cname = cname.replace("auf", "")
                cname = cname.replace("zu", "")
                self.covers[c_idx] = IfDescriptor(cname.strip(), c_idx, 1, 1)
                self.outputs[2 * c_idx].nmbr = -1  # disable light output
                self.outputs[2 * c_idx].type = 0
                self.outputs[2 * c_idx + 1].nmbr = -1
                self.outputs[2 * c_idx + 1].type = 0

    def update(self, sys_status) -> None:
        """Module specific update method reads and parses status"""
        super().update(sys_status)
        self.sensors[0].value = int(self.status[MirrIdx.STAT_IND_MOV])  # movement?
        self.sensors[1].value = (
            int.from_bytes(
                self.status[MirrIdx.STAT_IND_TEMP_EXT : MirrIdx.STAT_IND_TEMP_EXT + 2],
                "little",
            )
            / 10
        )  # external temperature
        self.sensors[1].value = (
            int.from_bytes(
                self.status[
                    MirrIdx.STAT_IND_TEMP_ROOM : MirrIdx.STAT_IND_TEMP_ROOM + 2
                ],
                "little",
            )
            / 10
        )  # current room temperature
        self.sensors[2].value = int(
            self.status[MirrIdx.STAT_IND_HUM]
        )  # current humidity
        self.sensors[3].value = (
            int(self.status[MirrIdx.STAT_IND_LUM]) * 10
        )  # illuminance
        self.sensors[4].value = int(self.status[MirrIdx.STAT_IND_AQI])  # current aqi?
        self.setvalues[0].value = (
            int.from_bytes(
                self.status[MirrIdx.STAT_IND_T_SETP_0 : MirrIdx.STAT_IND_T_SETP_0 + 2],
                "little",
            )
            / 10
        )

        out_state = int.from_bytes(
            self.status[MirrIdx.STAT_IND_OUT_1_8 : MirrIdx.STAT_IND_OUT_1_8 + 2],
            "little",
        )
        for o_idx in range(15):
            self.outputs[o_idx].value = int((out_state & (0x01 << o_idx)) > 0)
        self.dimmers[0].value = int(self.status[MirrIdx.STAT_IND_DIM_1])
        self.dimmers[1].value = int(self.status[MirrIdx.STAT_IND_DIM_2])

        for c_idx in range(2, len(self.covers)):
            shades_time = int(self.smg[17 + 2 * c_idx])
            if shades_time > 0:
                self.covers[c_idx].type = 2  # Roller with tiltable blades
            self.covers[c_idx].value = self.status[MMirrIdx.STAT_IND_ROLL_POS + c_idx]
            self.covers[c_idx].tilt = self.status[MMirrIdx.STAT_IND_BLAD_POS + c_idx]

        inp_state = int.from_bytes(
            self.status[MirrIdx.STAT_IND_INP_1_8 : MirrIdx.STAT_IND_INP_1_8 + 3],
            "little",
        )
        for inpt in self.inputs:
            inpt.value = int((inp_state & (0x01 << inpt.nmbr)) > 0)

        if (len(self.logic) == 0) & (self.status[MMirrIdx.STAT_IND_COUNTER] == 5):
            l_idx = 0
            while self.status[MMirrIdx.STAT_IND_COUNTER + 3 * l_idx] == 5:
                self.logic.append(IfDescriptor(f"Counter {l_idx + 1}", l_idx, 5, 0))
                l_idx += 1
        for lgc in self.logic:
            lgc.value = self.status[MMirrIdx.STAT_IND_COUNTER_VAL + 3 * lgc.nmbr]


class SmartOutput(HbtnModule):
    """Habitron SmartOutput module class."""

    has_inputs = False
    has_outputs = True
    has_sensors = False

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
    ) -> None:
        """Init Habitron SmartOutput module."""
        super().__init__(mod_descriptor, hass, config)

        self.messages: list[IfDescriptor] = []
        self.commands: list[IfDescriptor] = []

    async def initialize(self, sys_status) -> None:
        await super().initialize(sys_status)
        await self.get_smg()
        await self.get_smc()
        self.parse_smc()
        self.parse_smg()
        self.update(sys_status)

    def parse_smc(self) -> None:
        """Setting names"""
        resp = self.smc
        empty = IfDescriptor("", -1, 0, 0)
        self.outputs = [empty] * 8
        self.covers = [empty] * 4
        no_lines = resp[3] + 256 * resp[4]
        resp = resp[7 : len(resp)]  # Strip 4 header bytes
        for _ in range(no_lines):
            if resp == b"":
                break
            line_len = int(resp[5]) + 5
            line = resp[0:line_len]
            event_code = int(line[2])
            if event_code == 235:  # Beschriftung
                text = line[8:-1]
                text = text.decode("iso8859-1")
                text = text.strip()
                arg_code = int(line[3])
                if int(line[0]) == 253:
                    # Beschriftungen Direktbefehle
                    self.commands.append(IfDescriptor(text, arg_code, 0, 0))
                elif int(line[0]) == 254:
                    # Beschriftungen Meldungen
                    self.messages.append(IfDescriptor(text, arg_code, 0, 0))
                elif int(line[0]) == 255:
                    if arg_code in range(10, 18):
                        # Beschriftungen Modultaster
                        self.inputs.append(IfDescriptor(text, arg_code - 10, 0, 0))
                    elif arg_code in range(18, 26):
                        # Beschriftungen LEDs
                        self.leds.append(IfDescriptor(text, arg_code - 18, 0, 0))
                    elif arg_code in range(40, 50):
                        # Beschriftungen Inputs
                        self.inputs.append(IfDescriptor(text, arg_code - 40, 0, 0))
                    else:
                        # Beschriftungen Outputs
                        self.outputs[arg_code - 60] = IfDescriptor(
                            text, arg_code - 60, 1, 0
                        )
            resp = resp[line_len : len(resp)]  # Strip processed line

    def parse_smg(self) -> None:
        """Get settings"""
        resp = self.smg
        self.hw_version = resp[83 : (83 + 17)].decode("iso8859-1").strip()
        self.sw_version = resp[100 : (100 + 22)].decode("iso8859-1").strip()
        roller_state = resp[132]
        for c_idx in range(4):
            if (roller_state & (0x01 << c_idx)) > 0:
                cname = self.outputs[2 * c_idx].name.strip()
                cname = cname.replace("auf", "")
                cname = cname.replace("ab", "")
                cname = cname.replace("auf", "")
                cname = cname.replace("zu", "")
                self.covers[c_idx] = IfDescriptor(cname.strip(), c_idx, 1, 1)
                self.outputs[2 * c_idx].nmbr = -1  # disable light output
                self.outputs[2 * c_idx].type = 0
                self.outputs[2 * c_idx + 1].nmbr = -1
                self.outputs[2 * c_idx + 1].type = 0

    def update(self, sys_status) -> None:
        """Module specific update method reads and parses status"""
        super().update(sys_status)
        out_state = int(self.status[MirrIdx.STAT_IND_OUT_1_8])
        for o_idx in range(8):
            self.outputs[o_idx].value = int((out_state & (0x01 << o_idx)) > 0)

        for cover in self.covers:
            cover.value = self.status[MirrIdx.STAT_IND_ROLL_POS + cover.nmbr - 1]
            cover.tilt = self.status[MirrIdx.STAT_IND_BLAD_POS + cover.nmbr - 1]


class SmartInput(HbtnModule):
    """Habitron SmartInput module class."""

    has_inputs = True
    has_outputs = False
    has_sensors = False

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
    ) -> None:
        """Init Habitron SmartInput module."""
        super().__init__(mod_descriptor, hass, config)

        self.messages: list[IfDescriptor] = []
        self.commands: list[IfDescriptor] = []

    async def initialize(self, sys_status) -> None:
        await super().initialize(sys_status)
        await self.get_smg()
        # self.parse_smg()
        self.update(sys_status)

    def parse_smc(self) -> None:
        """Setting names"""
        resp = self.smc
        no_lines = resp[3] + 256 * resp[4]
        resp = resp[7 : len(resp)]  # Strip 7 header bytes
        count = 0
        for _ in range(no_lines):
            if resp == b"":
                break
            line_len = int(resp[5]) + 5
            line = resp[0:line_len]
            event_code = int(line[2])
            if event_code == 235:  # Beschriftung
                text = line[8:-1]
                text = text.decode("iso8859-1")
                text = text.strip()
                if int(line[0]) == 255:
                    # Beschriftungen Inputs
                    self.inputs.append(IfDescriptor(text, count, 0, 0))
                count = count + 1
            resp = resp[line_len : len(resp)]  # Strip processed line

    def update(self, sys_status) -> None:
        """Module specific update method reads and parses status"""
        super().update(sys_status)
        inp_state = int(self.status[MirrIdx.STAT_IND_INP_1_8])
        inp_type = int(self.status[MirrIdx.STAT_IND_SWMOD_1_8])
        for mod_inp in self.inputs:
            i_idx = mod_inp.nmbr
            mod_inp.value = int((inp_state & (0x01 << i_idx)) > 0)
            mod_inp.type = int((inp_type & (0x01 << i_idx)) > 0)


class SmartDetect(HbtnModule):
    """Habitron SmartDetect module class."""

    has_inputs = False
    has_outputs = False
    has_sensors = True

    async def initialize(self, sys_status) -> None:
        await super().initialize(sys_status)

        self.messages: list[IfDescriptor] = []
        self.commands: list[IfDescriptor] = []

        self.sensors.append(IfDescriptor("Movement", 0, 2, 0))
        self.sensors.append(IfDescriptor("Illuminance", 1, 2, 0))
        self.update(sys_status)

    def update(self, sys_status) -> None:
        """Module specific update method reads and parses status"""
        super().update(sys_status)
        self.sensors[0].value = int(self.status[MirrIdx.STAT_IND_MOV])  # movement
        self.sensors[1].value = (
            int(self.status[MirrIdx.STAT_IND_LUM]) * 10
        )  # illuminance


class SmartNature(HbtnModule):
    """Habitron SmartNature module class."""

    has_inputs = False
    has_outputs = False
    has_sensors = True

    async def initialize(self, sys_status) -> None:
        await super().initialize(sys_status)

        self.sensors.append(IfDescriptor("Temperature", 0, 2, 0))
        self.sensors.append(IfDescriptor("Humidity", 1, 2, 0))
        self.sensors.append(IfDescriptor("Illuminance", 2, 2, 0))
        self.sensors.append(IfDescriptor("Wind", 3, 2, 0))
        self.sensors.append(IfDescriptor("Rain", 4, 0, 0))
        self.sensors.append(IfDescriptor("Windpeak", 5, 2, 0))

        self.update(sys_status)

        self.messages: list[IfDescriptor] = []
        self.commands: list[IfDescriptor] = []

    def update(self, sys_status) -> None:
        """Module specific update method reads and parses status"""
        super().update(sys_status)
        self.sensors[0].value = (
            int.from_bytes(
                self.status[5 : 5 + 2],
                "little",
            )
            / 10
        )  # current temperature
        # self.sensors[2].value = int(
        #     self.status[22] * 256 + self.status[21]) / 10  # other temperature?
        self.sensors[1].value = int(
            self.status[MirrIdx.STAT_IND_HUM]
        )  # current humidity?
        self.sensors[2].value = int.from_bytes(
            self.status[MirrIdx.STAT_IND_LUM : MirrIdx.STAT_IND_LUM + 2],
            "little",
        )  # illuminance
        self.sensors[3].value = int(self.status[MirrIdx.STAT_IND_WINDP])  # wind??
        self.sensors[4].value = int(self.status[MirrIdx.STAT_IND_RAIN])  # rain??
        self.sensors[5].value = int(self.status[MirrIdx.STAT_IND_WINDP])  # wind peak??
