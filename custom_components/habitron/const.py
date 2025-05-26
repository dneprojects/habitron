"""Constants for the Habitron integration."""

from typing import Final

DOMAIN = "habitron"  # This is the internal name of the integration, it should also match the directory
CONF_DEFAULT_HOST = "local"  # default host string of SmartCenter, uses own ip
CONF_DEFAULT_INTERVAL = 10  # default update interval
CONF_MIN_INTERVAL = 4  # min update interval
CONF_MAX_INTERVAL = 60  # max update interval
RESTART_RTR = 0
RESTART_ALL = 0xFF
HUB_UID = "hub_uid"
ROUTER_NMBR = "rtr_nmbr"
MOD_NMBR = "mod_nmbr"
EVNT_TYPE = "evnt_type"
EVNT_ARG1 = "evnt_arg1"
EVNT_ARG2 = "evnt_arg2"
RESTART_KEY_NMBR = "mod_nmbr"
FILE_MOD_NMBR = "mod_nmbr"
LOC_FLAG_OFFS = 100
GLOB_FLAG_OFFS = 132
LOGIC_INP_OFFS = 164
HBTINT_VERSION = "2.1.3"

MODULE_CODES: Final[dict[bytes, str]] = {
    b"\x01\x01": "Smart Controller XL-1",
    b"\x01\x02": "Smart Controller XL-2",
    b"\x01\x03": "Smart Controller XL-2 (LE2)",
    b"\x01\x04": "Smart Controller Touch",
    # b"\x01\x0a": "Smart Controller X",
    b"\x0a\x01": "Smart Out 8/R",
    b"\x0a\x02": "Smart Out 8/T",
    b"\x0a\x14": "Smart Dimm",
    b"\x0a\x15": "Smart Dimm-1",
    b"\x0a\x16": "Smart Dimm-2",
    b"\x0a\x1e": "Smart IO 2",  # Unterputzmodul
    b"\x0a\x32": "Smart Out 8/R-1",
    b"\x0a\x33": "Smart Out 8/R-2",
    b"\x0b\x1e": "Smart In 8/24V",
    b"\x0b\x1f": "Smart In 8/24V-1",
    b"\x0b\x01": "Smart In 8/230V",
    b"\x14\x01": "Smart Nature",
    b"\x1e\x01": "Fanekey",
    b"\x1e\x03": "Smart GSM",
    b"\x1e\x04": "FanM-Bus",
    b"\x32\x01": "Smart Controller Mini",
    b"\x32\x28": "Smart Sensor",
    b"\x50\x64": "Smart Detect 180",
    b"\x50\x65": "Smart Detect 360",
    b"\x50\x66": "Smart Detect 180-2",
}


class RoutIdx:
    """Definition of router status index values."""

    ADDR = 0
    DEVICE_CNT = 1
    MODE0 = 2
    MEM_ERR_1 = 3  # 2 bytes
    MEM_ERR_2 = 5
    MEM_TEST_STRT = 7
    TIME_OUT = 8  # Channels 1..4: 8..11
    ERR_MSTR_RING = 12
    REBOOTED = 13
    MEM_TEST = 14
    BOOT_CNT = 15  # 2 bytes
    VOLTAGE_24 = 17  # 2 bytes
    VOLTAGE_5 = 19  # 2 bytes
    CURRENTS = 21  # Channels 1..8, 2 bytes: 21..36
    ERR_SYSTEM = 37
    FLAG_GLOB = 38  # 1..16: 38..39
    BOOTING = 40
    MOD_RESPONSE = 41
    MIRROR_STARTED = 42


TRUE_VAL = 0x4A  # Status values returned by router
FALSE_VAL = 0x4E


class MSetIdx:
    """Definition of module settings index values."""

    SHUTTER_TIMES = 4
    TILT_TIMES = 20
    INP_STATE = 39  # 3 bytes
    CLIM_MODE = 48
    HW_VERS = 83
    HW_VERS_ = 100
    SW_VERS = 100
    SW_VERS_ = 122
    SHUTTER_STAT = 132
    AD_STATE = 153


class MStatIdx:
    """Definition of module status index values."""

    BYTE_COUNT = 0  # in compact status included
    ADDR = 1
    MODE = 4
    INP_1_8 = 5
    INP_9_16 = 6
    INP_17_24 = 7
    AD_1 = 8
    AD_2 = 9
    OUT_1_8 = 10
    OUT_9_16 = 11
    OUT_17_24 = 12
    USE_230V = 13
    DIM_1 = 14
    DIM_2 = 15
    DIM_3 = 16
    DIM_4 = 17
    AOUT_1 = 18
    AOUT_2 = 19
    TEMP_ROOM = 20
    TEMP_PWR = 22
    TEMP_EXT = 24
    HUM = 26
    AQI = 27
    LUM = 28
    MOV = 30
    GEN_1 = 31  # General field 1
    GEN_2 = 32  # General field 2
    IR_H = 31
    IR_L = 32
    KEY_ID = 31
    WIND = 31
    WINDP = 32
    ROLL_POS = 33  # 1..8: 33..40 bei SC: Roll 3..5
    BLAD_POS = 41  # 1..8: 41..48
    T_SETP_0 = 49  # low/high
    T_SETP_1 = 51  # low/high
    GEN_3 = 53  # General field 3
    GEN_4 = 54  # General field 4
    RAIN = 53
    USER_CNT = 55
    FINGER_CNT = 56
    MODULE_STAT = 57  # Errors, etc
    COUNTER = 58  # type, max_cnt, val
    COUNTER_TYP = 58  # type, 10 for counter
    COUNTER_MAX = 59  # max_cnt
    COUNTER_VAL = 60  # cnt val
    LOGIC_OUT = 88  # 1..8, 89 9..16
    FLAG_LOC = 90  # 1..8, 91 9..16 Logic-Ausgänge
    END = 92  # incl. byte_count


class MirrIdx:
    """Definition of full mirror index values."""

    ADDR = 1
    MODE = 4
    INP_1_8 = 5
    INP_9_16 = 6
    INP_17_24 = 7
    AD_1 = 8
    AD_2 = 9
    OUT_1_8 = 10
    OUT_9_16 = 11
    OUT_17_24 = 12
    USE_230V = 13
    DIM_1 = 14
    DIM_2 = 15
    DIM_3 = 16
    DIM_4 = 17
    AOUT_1 = 18
    AOUT_2 = 19
    TEMP_ROOM = 20
    TEMP_OUTSIDE = 20
    TEMP_PWR = 22
    TEMP_EXT = 24
    HUM = 26
    AQI = 27
    LUM = 28
    MOV = 30
    LED_I = 31  # not included in status
    IR_H = 32
    IR_L = 33
    WIND = 32
    WINDP = 33
    ROLL_T = 34  # 1..8
    ROLL_POS = 42  # 1..8
    T_SETP_0 = 49  # low/high, alter Stand?
    BLAD_T = 50  # 1..8
    BLAD_POS = 58  # 1..8
    T_SHORT = 66
    T_LONG = 67
    T_DIM = 68
    SWMOD_1_8 = 69
    SWMOD_9_16 = 70
    SWMOD_17_24 = 71
    T_SETP_1 = 72
    T_SETP_2 = 74
    CLIM_MODE = 76
    T_LIM = 76
    RAIN = 79
    USER_CNT = 89
    FINGER_CNT = 90
    MOV_LVL = 91
    MOV_TIME = 92
    MODULE_STAT = 163
    ROLL_SETTINGS = 176
    ROLL_POL = 177  # 1..4, 178 5..8 val 1 = down dez.42 bei 175? Mod0: 42/0/2/2/2, RC2,3: 42/0/1/1/1 RC4: 42 0 1 2 1 RC8: 0 0 1 1 1
    COUNTER = 187  # type, max_cnt, val;    logic 1..10
    COUNTER_TYP = 187  # type, 5 for counter
    COUNTER_MAX = 188  # max_cnt
    COUNTER_VAL = 189  # cnt val; input state if gate
    LOGIC_OUT = 217  # 1..8, 218 9..10 for logic gates
    FLAG_LOC = 219  # 1..8, 220 9..16
    STAT_AD24_ACTIVE = 221  # in24 used as AD input
    END = 222


class SMirrIdx:
    """Definition of small mirror index values."""

    ADDR = 1
    MODE = 4
    INP_1_8 = 5
    INP_9_16 = 6
    INP_17_24 = 7
    AD_1 = 8
    OUT_1_8 = 9
    OUT_9_16 = 10
    OUT_17_24 = 11
    USE_230V = 12
    DIM_1 = 13
    DIM_2 = 14
    AOUT_1 = 15
    TEMP_ROOM = 16
    TEMP_PWR = 18
    TEMP_EXT = 20
    HUM = 22
    AQI = 23
    LUM = 24
    MOV = 25
    IR_H = 26
    IR_L = 27
    ROLL_POS = 28  # 1..8
    BLAD_POS = 33  # 1..8
    T_SETP_1 = 38
    T_SETP_2 = 40
    END = 42


class ModuleDescriptor:
    """Habitron modules descriptor."""

    def __init__(self, uid, addr, mtype, name, group) -> None:
        """Initialize descriptor.

        uid: unique id string, derived from hub's mac + rt uid
        addr: rt id * 100 + mod raw addr
        mtype: two bytes code for module type
        name: module name
        group: int of group
        """
        self.uid: str = uid
        self.addr: int = addr
        self.mtype: bytes = mtype
        self.name: str = name
        self.group: int = group


class HaEvents:
    """Identifier for home assistant events, e.g. input changes."""

    BUTTON = 1
    SWITCH = 2
    OUTPUT = 3
    COV_VAL = 4
    BLD_VAL = 5
    DIM_VAL = 6
    FINGER = 7
    IR_CMD = 8
    FLAG = 9
    CNT_VAL = 10
    PERCNT = 11
    DIR_CMD = 12
    MOVE = 13
    ANLG_VAL = 14
    MODE = 15
    SYS_ERR = 16
