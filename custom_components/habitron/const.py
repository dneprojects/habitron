"""Constants for the Habitron integration."""


from typing import Final


DOMAIN = "habitron"  # This is the internal name of the integration, it should also match the directory
CONF_DEFAULT_HOST = "SmartIP"  # default DNS name of SmartIP
CONF_DEFAULT_INTERVAL = 10  # default update interval
CONF_MIN_INTERVAL = 3  # min update interval
CONF_MAX_INTERVAL = 20  # max update interval
RESTART_ALL = 0xFF
RESTART_KEY_NMBR = "mod_nmbr"

SMARTIP_COMMAND_STRINGS: Final[dict[str, str]] = {
    "GET_MODULES": "\x0a\1\2\1\0\0\0",
    "GET_MODULE_SMG": "\x0a\2\7\1\xff\0\0",
    "GET_MODULE_SMC": "\x0a\3\7\1\xff\0\0",
    "GET_ROUTER_SMR": "\x0a\4\3\1\0\0\0",
    "GET_ROUTER_STATUS": "\x0a\4\4\1\0\0\0",
    "GET_MODULE_STATUS": "\x0a\5\1\x01\xff\0\0",
    "GET_COMPACT_STATUS": "\x0a\5\2\1\xff\0\0",  # compact status of all modules (0xFF)
    "GET_SMIP_BOOT_STATUS": "\x0a\6\1\0\0\0\0",
    "GET_GLOBAL_DESCRIPTIONS": "\x0a\7\1\1\0\0\0",  # Flags, Command collections
    "GET_SMARTIP_STATUS": "\x14\0\0\0\0\0\0",
    "GET_SMARTIP_FIRMWARE": "\x14\x1e\0\0\0\0\0",
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
    "SET_ROLLER_POSITION": "\x1e\1\4\x01\0\5\0\1\xff\1\xfe\xfd",  # <Module><RollNo><RolVal>
    "SET_ROLLER_TILT_POSITION": "\x1e\1\4\x01\0\5\0\1\xff\2\xfe\xfd",
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

MODULE_CODES: Final[dict[str, str]] = {
    "\x01\x02": "Smart Controller",
    "\x0a\x01": "Smart Out 8/R",
    "\x0a\x02": "Smart Out 8/T",
    "\x0a\x14": "Smart Dimm",
    "\x0a\x1e": "Smart UPM",  # Unterputzmodul
    "\x0b\x1e": "Smart In 8/24V",
    "\x0b\x01": "Smart In 8/230V",
    "\x14\x01": "Smart Nature",
    "\x50\x64": "Smart Detect 180",
    "\x50\x65": "Smart Detect 360",
    "\x1e\x01": "Fanekey",
    "\x1e\x03": "FanGSM",
    "\x1e\x04": "FanM-Bus",
}


class RoutIdx:
    """Definition of router status index values"""

    MODE0 = 2
    FLAG_GLOB = 38  # 1..8


class MStatIdx:
    """Definition of module status index values"""

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
    IR_H = 31  # General field 1
    IR_L = 32  # General field 2
    WIND = 31
    WINDP = 32
    ROLL_POS = 33  # 1..8: 33..40 bei SC: Roll 3..5
    BLAD_POS = 41  # 1..8: 41..48
    T_SETP_0 = 49  # low/high
    T_SETP_1 = 51  # low/high
    RAIN = 53  # General field 3
    Gen_4 = 54
    USER_CNT = 55
    FINGER_CNT = 56
    MODULE_STAT = 57  # Errors, etc
    COUNTER = 58  # type, max_cnt, val
    COUNTER_TYP = 58  # type, 10 for counter
    COUNTER_MAX = 59  # max_cnt
    COUNTER_VAL = 60  # cnt val
    LOGIC_OUT = 88  # 1..8, 89 9..16
    FLAG_LOC = 90  # 1..8, 91 9..16 Logic-Ausgänge
    END = 92


class MirrIdx:
    """Definition of full mirror index values"""

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
    COUNTER_VAL = 189  # cnt val
    LOGIC_OUT = 217  # 1..8, 218 9..16
    FLAG_LOC = 219  # 1..8, 220 9..16
    STAT_AD24_ACTIVE = 221  # in24 used as AD input
    END = 222


class SMirrIdx:
    """Definition of small mirror index values"""

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
