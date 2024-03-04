"""Module modules."""
from __future__ import annotations

import logging
import math

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, MODULE_CODES, ModuleDescriptor, MSetIdx, MStatIdx
from .interfaces import IfDescriptor, IfDescriptorC, LgcDescriptor


class HbtnModule:
    """Habitron Module class."""

    manufacturer = "Habitron GmbH"

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron module."""
        self._hass = hass
        self._config = config
        self.b_uid = b_uid
        self.name = mod_descriptor.name
        self.comm = comm
        self.logger = logging.getLogger(__name__)
        self.sw_version = ""
        self.hw_version = ""
        self.uid = f"Mod_{mod_descriptor.uid}_{self.b_uid}"
        self._addr = mod_descriptor.addr
        self.raddr = self._addr - int(self._addr / 100) * 100
        self._typ: bytes = mod_descriptor.mtype
        self._type: str = MODULE_CODES[self._typ]
        self.smc = ""
        self.status = ""
        self.mstatus = ""
        self.shutter_state = []
        self.climate_settings = 0
        self.id = f"Mod_{mod_descriptor.uid}_{self.b_uid}"
        self.group = mod_descriptor.group
        self.mode = 1

        self.inputs: list[IfDescriptor] = []
        self.outputs: list[IfDescriptor] = []
        self.dimmers: list[IfDescriptor] = []
        self.covers: list[IfDescriptor] = []
        self.sensors: list[IfDescriptor] = []
        self.leds: list[IfDescriptor] = []
        self.messages: list[IfDescriptor] = []
        self.dir_commands: list[IfDescriptor] = []
        self.vis_commands: list[IfDescriptor] = []
        self.setvalues: list[IfDescriptor] = []
        self.flags: list[IfDescriptor] = []
        self.logic: list[LgcDescriptor] = []
        self.diags = [IfDescriptor("", 0, 0, 0)]
        self.diags.append(IfDescriptor("Status", 0, 1, 0))

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
        """Initialize module instance."""
        await self.get_names()
        await self.get_settings()
        device_registry = dr.async_get(self._hass)
        self.status = self.extract_status(sys_status)
        device_registry.async_get_or_create(
            config_entry_id=self._config.entry_id,
            configuration_url=f"http://{self.comm.com_ip}:7780/module-{self.raddr}",
            identifiers={(DOMAIN, self.uid)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self.name,
            model=self._type,
            sw_version=self.sw_version,
            hw_version=self.hw_version,
            via_device=(DOMAIN, self.comm.router.uid),
        )
        self.update(self.status)

    def get_cover_index(self, out_no: int) -> int:
        """Return cover index based on output number."""
        if self.outputs[out_no - 1].type == -10:
            c_idx = math.ceil(out_no / 2) - 1
            # if self._type[:16] == "Smart Controller":
            #     c_idx -= 2
            #     if c_idx < 0:
            #         c_idx += 5
            return c_idx
        else:
            return -1

    async def get_names(self) -> bool:
        """Get summary of Habitron module."""
        resp = await self.comm.async_get_module_definitions(self._addr)
        if resp == "":
            return False

        if self._type == "Smart Controller":
            no_lines = int.from_bytes(resp[0:2], "little")
            resp = resp[4 : len(resp)]  # Strip 4 header bytes
        else:
            no_lines = int.from_bytes(resp[3:5], "little")
            resp = resp[7 : len(resp)]  # Strip 7 header bytes
        if len(resp) == 0:
            return False
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
                if int(line[0]) == 252:
                    # Finger ids
                    self.ids.append(IfDescriptor(text, arg_code, 0, 0))
                elif int(line[0]) == 253:
                    # Description of commands
                    self.dir_commands.append(IfDescriptor(text, arg_code, 0, 0))
                elif int(line[0]) == 254:
                    # Description of messages
                    self.messages.append(IfDescriptor(text, arg_code, 0, 0))
                elif int(line[0]) == 255:
                    try:
                        if arg_code in range(10, 18):
                            # Description of module buttons
                            self.inputs[arg_code - 10] = IfDescriptor(
                                text, arg_code - 10, 1, 0
                            )
                        elif arg_code in range(18, 26):
                            # Description of module LEDs
                            self.leds[arg_code - 17] = IfDescriptor(
                                text, arg_code - 17, 0, 0
                            )
                        elif arg_code in range(40, 50):
                            # Description of  Inputs
                            if self.mod_type == "Smart Controller Mini":
                                if arg_code in range(44, 48):
                                    self.inputs[arg_code - 42] = IfDescriptor(
                                        text, arg_code - 42, 1, 0
                                    )
                            else:
                                self.inputs[arg_code - 32] = IfDescriptor(
                                    text, arg_code - 32, 1, 0
                                )
                        elif self.mod_type[0:9] == "Smart Out":
                            # Description of outputs in Out modules
                            self.outputs[arg_code - 60] = IfDescriptor(
                                text, arg_code - 60, 1, 0
                            )
                        else:
                            # Description of outputs
                            self.outputs[arg_code - 60].name = text
                    except:  # noqa: E722
                        pass

            resp = resp[line_len : len(resp)]  # Strip processed line
        self.set_default_names(self.inputs, "Inp")
        self.set_default_names(self.outputs, "Out")
        if self.mod_type == "Smart Controller Mini":
            self.leds[4].name = "Ambient"
            for led in self.leds:
                led.value = [0, 0, 0, 0]
                led.type = 4
        elif self._typ[0] == 0:
            self.leds[0].name = "Light"
            return True
        if self.mod_type[:16] == "Smart Controller":
            self.dimmers[0] = IfDescriptor(self.outputs[10].name, 0, 2, 0)
            self.dimmers[1] = IfDescriptor(self.outputs[11].name, 1, 2, 0)
            self.outputs[10].type = 2
            self.outputs[11].type = 2
        return True

    async def get_settings(self) -> bool:
        """Get settings of Habitron module."""
        resp = await self.comm.async_get_module_settings(self._addr)
        if resp == "":
            return False

        self.hw_version = (
            resp[MSetIdx.HW_VERS : MSetIdx.HW_VERS_].decode("iso8859-1").strip()
        )
        self.sw_version = (
            resp[MSetIdx.SW_VERS : MSetIdx.SW_VERS_].decode("iso8859-1").strip()
        )
        self.climate_settings = int(resp[MSetIdx.CLIM_MODE])
        inp_state = int.from_bytes(
            resp[MSetIdx.INP_STATE : MSetIdx.INP_STATE + 3], "little"
        )
        for inp in self.inputs:
            if inp_state & (0x01 << inp.nmbr) > 0:
                inp.type *= 2  # switch

        # pylint: disable-next=consider-using-enumerate
        for c_idx in range(len(self.covers)):
            cm_idx = c_idx
            if self.mod_type[:16] == "Smart Controller":
                cm_idx -= 2
                if cm_idx < 0:
                    cm_idx += 5
            if (
                resp[MSetIdx.SHUTTER_STAT] & (0x01 << cm_idx) > 0
            ):  # binary flag for shutters
                polarity = (
                    int(resp[MSetIdx.SHUTTER_TIMES + 1 + 2 * cm_idx])
                    - int(resp[MSetIdx.SHUTTER_TIMES + 2 * cm_idx])
                    >= 0
                ) * 2 - 1
                tilt = 1 + (
                    abs(
                        int(resp[MSetIdx.TILT_TIMES + 1 + 2 * cm_idx])
                        - int(resp[MSetIdx.TILT_TIMES + 2 * cm_idx])
                    )
                    > 0
                )
                pol = polarity * tilt  # +-1 for shutters, +-2 for blinds
                cname = self.outputs[2 * c_idx].name.strip()
                cname = cname.replace("auf", "")
                cname = cname.replace("ab", "")
                cname = cname.replace("auf", "")
                cname = cname.replace("zu", "")
                self.covers[c_idx] = IfDescriptorC(cname.strip(), c_idx, pol, 0, 0)
                self.outputs[2 * c_idx].type = -10  # disable light output
                self.outputs[2 * c_idx + 1].type = -10
        return True

    def update(self, mod_status):
        """General update for Habitron modules."""
        self.status = mod_status
        self.mode = self.status[MStatIdx.MODE]
        self.comm.grp_modes[self.group] = self.mode

        # Andere Logikelemente in self.logic aufnehmen?
        if len(self.logic) == 0:
            cnt_cnt = 0
            for l_idx in range(10):
                if self.status[MStatIdx.COUNTER + 3 * l_idx] == 5:
                    self.logic.append(
                        LgcDescriptor(f"Counter {cnt_cnt+1}", cnt_cnt, l_idx, 5, 0)
                    )
                    cnt_cnt += 1
        if len(self.logic) == 0:
            # No counter found, set 1st element inactive
            self.logic.append(LgcDescriptor("NotAvailable", 0, 0, -5, 0))
        for lgc in self.logic:
            lgc.value = self.status[MStatIdx.COUNTER_VAL + 3 * lgc.nmbr]

    def extract_status(self, sys_status) -> bytes:
        """Extract status of Habitron module from system status."""
        stat_len = MStatIdx.END
        no_mods = int(len(sys_status) / stat_len)
        m_addr = self._addr - int(self._addr / 100) * 100
        for m_idx in range(no_mods):
            if int(sys_status[m_idx * stat_len + MStatIdx.ADDR]) == m_addr:
                self.logger.info(f"Found module {m_addr}, extracting status")  # noqa: G004
                break
        self.logger.info(
            f"Extract status could not find module {m_addr}: status length: {len(sys_status)}"  # noqa: G004
        )
        return sys_status[m_idx * stat_len : (m_idx + 1) * stat_len]

    def set_default_names(self, mod_entities, def_name: str) -> None:
        """Set default names for entities."""
        e_idx = 0
        # pylint: disable-next=consider-using-enumerate
        for e_idx in range(len(mod_entities)):
            if mod_entities[e_idx].name.strip() == "":
                # Type sign switched, can be used to disable entity
                e_type = mod_entities[e_idx].type
                mod_entities[e_idx] = IfDescriptor(
                    f"{self.id} {def_name}{e_idx+1}", e_idx, -1 * e_type, 0
                )

    async def async_reset(self) -> None:
        """Call reset command for self."""
        rt_nmbr = int(self._addr / 100)
        await self.comm.module_restart(rt_nmbr, self.raddr)


class SmartController(HbtnModule):
    """Habitron SmartController module class."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron SmartController module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)

        self.inputs = [IfDescriptor("", i, 1, 0) for i in range(18)]
        self.outputs = [IfDescriptor("", i, 1, 0) for i in range(15)]
        self.covers = [IfDescriptorC("", -1, 0, 0, 0) for i in range(5)]
        self.dimmers = [IfDescriptor("", i, -1, 0) for i in range(2)]
        self.leds = [IfDescriptor("", i, 0, 0) for i in range(9)]
        self.diags = [IfDescriptor("", i, 0, 0) for i in range(2)]
        self.setvalues = [IfDescriptor("Set temperature", 0, 2, 20.0)]
        self.setvalues.append(IfDescriptor("Set temperature 2", 1, 2, 20.0))
        self.auxheat_value = 0

        self.sensors.append(IfDescriptor("Movement", 0, 2, 0))
        self.sensors.append(IfDescriptor("Temperature", 1, 2, 0))
        self.sensors.append(IfDescriptor("Temperature ext.", 2, 2, 0))
        self.sensors.append(IfDescriptor("Humidity", 3, 2, 0))
        self.sensors.append(IfDescriptor("Illuminance", 4, 2, 0))
        self.sensors.append(IfDescriptor("Airquality", 5, 2, 0))
        self.diags.append(IfDescriptor("PowerTemp", 1, 1, 0))

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        super().update(mod_status)
        self.sensors[0].value = int(self.status[MStatIdx.MOV])  # movement?
        self.sensors[1].value = (
            int.from_bytes(
                self.status[MStatIdx.TEMP_ROOM : MStatIdx.TEMP_ROOM + 2],
                "little",
            )
            / 10
        )  # current room temperature
        self.sensors[2].value = (
            int.from_bytes(
                self.status[MStatIdx.TEMP_EXT : MStatIdx.TEMP_EXT + 2],
                "little",
            )
            / 10
        )  # external temperature
        self.sensors[3].value = int(self.status[MStatIdx.HUM])  # current humidity
        self.sensors[4].value = int(self.status[MStatIdx.LUM]) * 10  # illuminance
        self.sensors[5].value = int(self.status[MStatIdx.AQI])  # current aqi?
        self.setvalues[0].value = (
            int.from_bytes(
                self.status[MStatIdx.T_SETP_0 : MStatIdx.T_SETP_0 + 2],
                "little",
            )
            / 10
        )
        self.setvalues[1].value = (
            int.from_bytes(
                self.status[MStatIdx.T_SETP_1 : MStatIdx.T_SETP_1 + 2],
                "little",
            )
            / 10
        )

        out_state = int.from_bytes(
            self.status[MStatIdx.OUT_1_8 : MStatIdx.OUT_1_8 + 2],
            "little",
        )
        for outpt in self.outputs:
            outpt.value = int((out_state & (0x01 << outpt.nmbr)) > 0)

        self.dimmers[0].value = int(self.status[MStatIdx.DIM_1])
        self.dimmers[1].value = int(self.status[MStatIdx.DIM_2])

        led_state = out_state >> 15
        for led in self.leds:
            led.value = int((led_state & (0x01 << led.nmbr)) > 0)

        for cover in self.covers:
            if cover.nmbr >= 0:
                cm_idx = cover.nmbr - 2
                if cm_idx < 0:
                    cm_idx += 5
                self.covers[cover.nmbr].value = self.status[MStatIdx.ROLL_POS + cm_idx]
                self.covers[cover.nmbr].tilt = self.status[MStatIdx.BLAD_POS + cm_idx]

        inp_state = int.from_bytes(
            self.status[MStatIdx.INP_1_8 : MStatIdx.INP_1_8 + 3],
            "little",
        )
        for inpt in self.inputs:
            if inpt.nmbr >= 0:
                inpt.value = int((inp_state & (0x01 << inpt.nmbr)) > 0)

        flags_state = int.from_bytes(
            self.status[MStatIdx.FLAG_LOC : MStatIdx.FLAG_LOC + 2],
            "little",
        )
        for flg in self.flags:
            flg.value = int((flags_state & (0x01 << flg.nmbr - 1)) > 0)

        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]
        self.diags[1].value = (
            int.from_bytes(
                self.status[MStatIdx.TEMP_PWR : MStatIdx.TEMP_PWR + 2],
                "little",
            )
            / 10
        )


class SmartControllerMini(HbtnModule):
    """Mini Controller module."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron SmartController Mini module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)

        self.inputs = [IfDescriptor("", i, 1, 0) for i in range(6)]
        self.outputs = [IfDescriptor("", i, 1, 0) for i in range(2)]
        self.covers = [IfDescriptorC("", -1, 0, 0, 0) for i in range(0)]
        self.dimmers = [IfDescriptor("", i, -1, 0) for i in range(0)]
        self.leds = [IfDescriptor("", i, 0, 0) for i in range(5)]
        self.diags = [IfDescriptor("", i, 0, 0) for i in range(1)]
        self.setvalues = [IfDescriptor("Set temperature", 0, 2, 20.0)]
        self.setvalues.append(IfDescriptor("Set temperature 2", 1, 2, 20.0))
        self.auxheat_value = 0

        self.sensors.append(IfDescriptor("Movement", 0, 2, 0))
        self.sensors.append(IfDescriptor("Temperature", 1, 2, 0))
        # self.sensors.append(IfDescriptor("Temperature ext.", 2, 2, 0))
        # self.sensors.append(IfDescriptor("Humidity", 2, 2, 0))
        self.sensors.append(IfDescriptor("Illuminance", 2, 2, 0))
        self.sensors.append(IfDescriptor("Airquality", 3, 2, 0))

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        super().update(mod_status)
        self.sensors[0].value = int(self.status[MStatIdx.MOV])  # movement?
        self.sensors[1].value = (
            int.from_bytes(
                self.status[MStatIdx.TEMP_ROOM : MStatIdx.TEMP_ROOM + 2],
                "little",
            )
            / 10
        )  # current room temperature
        self.sensors[2].value = int(self.status[MStatIdx.LUM]) * 10  # illuminance
        self.sensors[3].value = int(self.status[MStatIdx.AQI])  # current air quality
        self.setvalues[0].value = (
            int.from_bytes(
                self.status[MStatIdx.T_SETP_0 : MStatIdx.T_SETP_0 + 2],
                "little",
            )
            / 10
        )
        self.setvalues[1].value = (
            int.from_bytes(
                self.status[MStatIdx.T_SETP_1 : MStatIdx.T_SETP_1 + 2],
                "little",
            )
            / 10
        )

        out_state = int.from_bytes(
            self.status[MStatIdx.OUT_1_8 : MStatIdx.OUT_1_8 + 2],
            "little",
        )
        for outpt in self.outputs:
            outpt.value = int((out_state & (0x01 << outpt.nmbr)) > 0)

        # led_state = int(self.status[MStatIdx.OUT_17_24])
        led_state = out_state >> 2  # Led corner 1 = out 3
        for led in self.leds:
            led.value[0] = int((led_state & (0x01 << led.nmbr)) > 0)

        inp_state = int.from_bytes(
            self.status[MStatIdx.INP_1_8 : MStatIdx.INP_1_8 + 3],
            "little",
        )
        for inpt in self.inputs:
            if inpt.nmbr >= 0:
                inpt.value = int((inp_state & (0x01 << inpt.nmbr)) > 0)

        flags_state = int.from_bytes(
            self.status[MStatIdx.FLAG_LOC : MStatIdx.FLAG_LOC + 2],
            "little",
        )
        for flg in self.flags:
            flg.value = int((flags_state & (0x01 << flg.nmbr - 1)) > 0)

        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]


class SmartOutput(HbtnModule):
    """Habitron SmartOutput module class."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron SmartOutput module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)

        self.outputs = [IfDescriptor("", i, 1, 0) for i in range(8)]
        self.covers = [IfDescriptorC("", -1, 0, 0, 0) for i in range(4)]

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        super().update(mod_status)
        out_state = int(self.status[MStatIdx.OUT_1_8])
        for outpt in self.outputs:
            outpt.value = int((out_state & (0x01 << outpt.nmbr)) > 0)

        for cover in self.covers:
            c_idx = cover.nmbr
            if c_idx >= 0:
                cover.value = self.status[MStatIdx.ROLL_POS + cover.nmbr]
                cover.tilt = self.status[MStatIdx.BLAD_POS + cover.nmbr]

        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]


class SmartDimm(HbtnModule):
    """Habitron SmartOutput module class."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron SmartDimm module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)

        self.outputs = [IfDescriptor("", i, 2, 0) for i in range(4)]
        for outp in self.outputs:
            outp.name = f"DOut{outp.nmbr}"
        self.dimmers = [IfDescriptor("", i, 1, 0) for i in range(4)]
        # self.inputs = [IfDescriptor("", i, 1, 0) for i in range(4)]
        for mod_inp in self.inputs:
            mod_inp.name = f"DOut{mod_inp.nmbr}"
        self.diags.append(IfDescriptor("PowerTemp", 1, 1, 0))

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        super().update(mod_status)

        # inp_state = int(self.status[MStatIdx.INP_1_8])
        # for mod_inp in self.inputs:
        #     i_idx = mod_inp.nmbr
        #     if i_idx >= 0:
        #         mod_inp.value = int((inp_state & (0x01 << i_idx)) > 0)

        out_state = int(self.status[MStatIdx.OUT_1_8])
        for outpt in self.outputs:
            outpt.value = int((out_state & (0x01 << outpt.nmbr)) > 0)
        self.dimmers[0].value = int(self.status[MStatIdx.DIM_1])
        self.dimmers[1].value = int(self.status[MStatIdx.DIM_2])
        self.dimmers[2].value = int(self.status[MStatIdx.DIM_3])
        self.dimmers[3].value = int(self.status[MStatIdx.DIM_4])

        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]
        self.diags[1].value = (
            int.from_bytes(
                self.status[MStatIdx.TEMP_PWR : MStatIdx.TEMP_PWR + 2],
                "little",
            )
            / 10,
        )


class SmartUpM(HbtnModule):
    """Habitron SmartOutput module class."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron SmartOutput module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)

        self.outputs = [IfDescriptor("", i, 1, 0) for i in range(2)]
        self.inputs = [IfDescriptor("", i, 1, 0) for i in range(2)]
        self.diags = [IfDescriptor("", i, 0, 0) for i in range(1)]
        self.covers = [IfDescriptorC("", -1, 0, 0, 0)]

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        super().update(mod_status)

        inp_state = int(self.status[MStatIdx.INP_1_8])
        for mod_inp in self.inputs:
            i_idx = mod_inp.nmbr
            if i_idx >= 0:
                mod_inp.value = int((inp_state & (0x01 << i_idx)) > 0)

        out_state = int(self.status[MStatIdx.OUT_1_8])
        for outpt in self.outputs:
            outpt.value = int((out_state & (0x01 << outpt.nmbr)) > 0)

        c_idx = self.covers[0].nmbr
        if c_idx >= 0:
            self.covers[0].value = self.status[MStatIdx.ROLL_POS - 1]
            self.covers[0].tilt = self.status[MStatIdx.BLAD_POS - 1]
        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]


class SmartInput(HbtnModule):
    """Habitron SmartInput module class."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron SmartInput module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)

        self.inputs = [IfDescriptor("", i, 1, 0) for i in range(8)]

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        super().update(mod_status)
        inp_state = int(self.status[MStatIdx.INP_1_8])
        for mod_inp in self.inputs:
            i_idx = mod_inp.nmbr
            if i_idx >= 0:
                mod_inp.value = int((inp_state & (0x01 << i_idx)) > 0)
        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]


class SmartDetect(HbtnModule):
    """Habitron SmartDetect module class."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron SmartDetect module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)

        self.sensors.append(IfDescriptor("Movement", 0, 2, 0))
        self.sensors.append(IfDescriptor("Illuminance", 1, 2, 0))

    async def initialize(self, sys_status) -> None:
        """Initialize SmartDetect."""
        # No name and settings initialization needed
        device_registry = dr.async_get(self._hass)
        self.status = self.extract_status(sys_status)
        device_registry.async_get_or_create(
            config_entry_id=self._config.entry_id,
            identifiers={(DOMAIN, self.uid)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self.name,
            model=self._type,
            sw_version=self.sw_version,
            hw_version=self.hw_version,
            via_device=(DOMAIN, self.comm.router.uid),
        )
        self.update(self.status)

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        super().update(mod_status)
        self.sensors[0].value = int(self.status[MStatIdx.MOV])  # movement
        self.sensors[1].value = int(self.status[MStatIdx.LUM]) * 10  # illuminance
        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]


class SmartEKey(HbtnModule):
    """Habitron eKey module class."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron eKey module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)
        self.ids: list[IfDescriptor] = []
        self.sensors.append(IfDescriptor("Identifier", 0, 2, 0))
        self.fingers: list[IfDescriptor] = []
        self.fingers.append(IfDescriptor("Finger", 0, 2, 0))

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        super().update(mod_status)
        self.sensors[0].value = int(self.status[MStatIdx.KEY_ID])  # last id
        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]


class SmartNature(HbtnModule):
    """Habitron SmartNature module class."""

    def __init__(
        self,
        mod_descriptor: ModuleDescriptor,
        hass: HomeAssistant,
        config: ConfigEntry,
        b_uid: str,
        comm,
    ) -> None:
        """Init Habitron SmartNature module."""
        super().__init__(mod_descriptor, hass, config, b_uid, comm)

        self.sensors.append(IfDescriptor("Temperature", 0, 2, 0))
        self.sensors.append(IfDescriptor("Humidity", 1, 2, 0))
        self.sensors.append(IfDescriptor("Illuminance", 2, 2, 0))
        self.sensors.append(IfDescriptor("Wind", 3, 2, 0))
        self.sensors.append(IfDescriptor("Rain", 4, 0, 0))
        self.sensors.append(IfDescriptor("Windpeak", 5, 2, 0))

    async def initialize(self, sys_status) -> None:
        """Initialize SmartNature."""
        # No name and settings initialization needed
        device_registry = dr.async_get(self._hass)
        self.status = self.extract_status(sys_status)
        device_registry.async_get_or_create(
            config_entry_id=self._config.entry_id,
            identifiers={(DOMAIN, self.uid)},
            manufacturer="Habitron GmbH",
            suggested_area="House",
            name=self.name,
            model=self._type,
            sw_version=self.sw_version,
            hw_version=self.hw_version,
            via_device=(DOMAIN, self.comm.router.uid),
        )
        self.update(self.status)

    def update(self, mod_status) -> None:
        """Update with module specific method. Reads and parses status."""
        self.sensors[0].value = (
            int.from_bytes(
                self.status[MStatIdx.TEMP_ROOM : MStatIdx.TEMP_ROOM + 2],
                "little",
            )
            / 10
        )  # current temperature
        self.sensors[1].value = int(self.status[MStatIdx.HUM])  # current humidity
        self.sensors[2].value = int.from_bytes(
            self.status[MStatIdx.LUM : MStatIdx.LUM + 2],
            "little",
        )  # illuminance
        self.sensors[3].value = int(self.status[MStatIdx.WINDP])  # wind
        self.sensors[4].value = int(self.status[MStatIdx.RAIN])  # rain
        self.sensors[5].value = int(self.status[MStatIdx.WINDP])  # wind peak
        self.diags[0].value = self.status[MStatIdx.MODULE_STAT]
