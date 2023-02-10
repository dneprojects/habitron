"""Constants for the Detailed Hello World Push integration."""

# This is the internal name of the integration, it should also match the directory
# name for the integration.

from typing import Final

DOMAIN = "habitron"
CONF_DEFAULT_HOST = "SmartIP"  # default DNS name of SmartIP
CONF_DEFAULT_INTERVAL = 10  # default update rate

SMARTIP_COMMAND_STRINGS: Final[dict[str, str]] = {
    "GET_ROUTER_IDS": "\x0a\6\1\0\0\0\0",
    "GET_MODULES": "\x0a\1\2\1\0\0\0",
    "GET_MODULE_SMG": "\x0a\2\7\1\xff\0\0",
    "GET_MODULE_SMC": "\x0a\3\7\1\xff\0\0",
    "GET_ROUTER_SMR": "\x0a\4\3\1\0\0\0",
    "GET_ROUTER_STATUS": "\x0a\4\4\1\0\0\0",
    "GET_MODULE_STATUS": "\x0a\5\1\x01\xff\0\0",
    "GET_MIRROR_STATUS": "\x0a\5\2\1\xff\0\0",
    "GET_GLOBAL_DESCRIPTIONS": "\x0a\7\1\1\0\0\0",  # Flags, Command collections
    "GET_SMARTIP_STATUS": "\x14\0\0\0\0\0\0",
    "GET_SMARTIP_FIRMWARE": "\x14\x1e\0\0\0\0\0",
    "GET_GROUP_MODE": "\x14\2\1\x01\xff\0\0",  # <Group 0..>
    "GET_GROUP_MODE0": "\x14\2\1\x01\0\0\0",
    "SET_GROUP_MODE": "\x14\2\2\x01\xff\3\0\1\xff\xfe",  # <Group 0..><Mode>
    "GET_ROUTER_MODES": "\x14\2\3\x01\xff\3\0\1\xff\0",
    "START_MIRROR": "\x14\x28\1\0\0\0\0",
    "STOP_MIRROR": "\x14\x28\2\0\0\0\0",
    "SET_CHANGE_MIRROR": "\x14\x28\3\0\0\0\0",
    "SET_OUTPUT_ON": "\x1e\1\1\x01\xff\3\0\1\xff\xfe",
    "SET_OUTPUT_OFF": "\x1e\1\2\x01\xff\3\0\1\xff\xfe",
    "SET_DIMMER_VALUE": "\x1e\1\3\x01\xff\4\0\1\xff\xfe\xfd",  # <Module><DimNo><DimVal>
    "SET_ROLLER_POSITION": "\x1e\1\4\x01\0\5\0\1\xff\1\xfe\xfd",  # <Module><RollNo><RolVal>
    "SET_ROLLER_TILT_POSITION": "\x1e\1\4\x01\0\5\0\1\xff\2\xfe\xfd",
    "SET_SETPOINT_VALUE": "\x1e\2\1\x01\0\5\0\1\xff\xfe\xfd\xfc",  # <Module><ValNo><ValL><ValH>
    "CALL_VIS_COMMAND": "\x1e\3\1\0\0\4\0\1\xff\xfd\xfc",  # <Module><VisNoL><VisNoH> not tested
    "CALL_COLL_COMMAND": "\x1e\4\1\1\xfd\0\0",  # <CmdNo> not tested
    "GET_LAST_IR_CODE": "\x32\2\1\x01\xff\0\0",
    "READ_MODULE_MIRR_STATUS": "\x64\1\5\1\xff\0\0",
}

MODULE_CODES: Final[dict[str, str]] = {
    "\x01\x02": "Smart Controller",
    "\n\x01": "Smart Out 8/R",
    "\n\x02": "Smart Out 8/T",
    "\x0b\x02": "Smart In 8/24V",
    "\x0b\x01": "Smart In 8/230V",
    "Pe": "Smart Detect 360",
    "\x14\x01": "Smart Nature",
}


class MirrIdx:
    """Definition of full mirror index values"""

    STAT_IND_ADDR = 1
    STAT_IND_MODE = 4
    STAT_IND_INP_1_8 = 5
    STAT_IND_INP_9_16 = 6
    STAT_IND_INP_17_24 = 7
    STAT_IND_AD_1 = 8
    STAT_IND_AD_2 = 9
    STAT_IND_OUT_1_8 = 10
    STAT_IND_OUT_9_16 = 11
    STAT_IND_OUT_17_24 = 12
    STAT_IND_USE_230V = 13
    STAT_IND_DIM_1 = 14
    STAT_IND_DIM_2 = 15
    STAT_IND_DIM_3 = 16
    STAT_IND_DIM_4 = 17
    STAT_IND_AOUT_1 = 18
    STAT_IND_AOUT_2 = 19
    STAT_IND_TEMP_ROOM = 20
    STAT_IND_TEMP_PWR = 22
    STAT_IND_TEMP_EXT = 24
    STAT_IND_HUM = 26
    STAT_IND_AQI = 27
    STAT_IND_LUM = 28
    STAT_IND_MOV = 30
    STAT_IND_LED_I = 31
    STAT_IND_IR_H = 32
    STAT_IND_IR_L = 33
    STAT_IND_WIND = 32
    STAT_IND_WINDP = 33
    STAT_IND_ROLL_T = 34  # 1..8
    STAT_IND_ROLL_POS = 42  # 1..8
    STAT_IND_T_SETP_0 = 49  # low/high, alter Stand?
    STAT_IND_BLAD_T = 50  # 1..8
    STAT_IND_BLAD_POS = 58  # 1..8
    STAT_IND_T_SHORT = 66
    STAT_IND_T_LONG = 67
    STAT_IND_T_DIM = 68
    STAT_IND_SWMOD_1_8 = 69
    STAT_IND_SWMOD_9_16 = 70
    STAT_IND_SWMOD_17_24 = 71
    STAT_IND_T_SETP_1 = 72
    STAT_IND_T_SETP_2 = 74
    STAT_IND_T_LIM = 75
    STAT_IND_RAIN = 79
    STAT_IND_MOV_LVL = 91
    STAT_IND_MOV_TIME = 92
    STAT_IND_END = 92


class MMirrIdx:
    """Definition of medium mirror index values"""

    STAT_IND_ADDR = 1
    STAT_IND_MODE = 4
    STAT_IND_INP_1_8 = 5
    STAT_IND_INP_9_16 = 6
    STAT_IND_INP_17_24 = 7
    STAT_IND_AD_1 = 8
    STAT_IND_AD_2 = 9
    STAT_IND_OUT_1_8 = 10
    STAT_IND_OUT_9_16 = 11
    STAT_IND_OUT_17_24 = 12
    STAT_IND_USE_230V = 13
    STAT_IND_DIM_1 = 14
    STAT_IND_DIM_2 = 15
    STAT_IND_DIM_3 = 16
    STAT_IND_DIM_4 = 17
    STAT_IND_AOUT_1 = 18
    STAT_IND_AOUT_2 = 19
    STAT_IND_TEMP_ROOM = 20
    STAT_IND_TEMP_PWR = 22
    STAT_IND_TEMP_EXT = 24
    STAT_IND_HUM = 26
    STAT_IND_AQI = 27
    STAT_IND_LUM = 28
    STAT_IND_MOV = 30
    STAT_IND_ROLL_POS = 31  # 1..8
    STAT_IND_BLAD_POS = 39  # 1..8
    STAT_IND_WIND = 32
    STAT_IND_WINDP = 33
    STAT_IND_T_SETP_0 = 49  # low/high, alter Stand?
    STAT_IND_BLAD_T = 50  # 1..8
    STAT_IND_COUNTER = 58  # type, max_cnt, val
    STAT_IND_COUNTER_TYP = 58  # type, 5 for counter
    STAT_IND_COUNTER_MAX = 59  # max_cnt
    STAT_IND_COUNTER_VAL = 60  # cnt val
    STAT_IND_T_SHORT = 66
    STAT_IND_T_LONG = 67
    STAT_IND_T_DIM = 68
    STAT_IND_SWMOD_1_8 = 69
    STAT_IND_SWMOD_9_16 = 70
    STAT_IND_SWMOD_17_24 = 71
    STAT_IND_T_SETP_1 = 72
    STAT_IND_T_SETP_2 = 74
    STAT_IND_T_LIM = 75
    STAT_IND_RAIN = 79
    STAT_IND_MOV_LVL = 91
    STAT_IND_MOV_TIME = 92
    STAT_IND_END = 92


class SMirrIdx:
    """Definition of small mirror index values"""

    STAT_IND_ADDR = 1
    STAT_IND_MODE = 4
    STAT_IND_INP_1_8 = 5
    STAT_IND_INP_9_16 = 6
    STAT_IND_INP_17_24 = 7
    STAT_IND_AD_1 = 8
    STAT_IND_OUT_1_8 = 9
    STAT_IND_OUT_9_16 = 10
    STAT_IND_OUT_17_24 = 11
    STAT_IND_USE_230V = 12
    STAT_IND_DIM_1 = 13
    STAT_IND_DIM_2 = 14
    STAT_IND_AOUT_1 = 15
    STAT_IND_TEMP_ROOM = 16
    STAT_IND_TEMP_PWR = 18
    STAT_IND_TEMP_EXT = 20
    STAT_IND_HUM = 22
    STAT_IND_AQI = 23
    STAT_IND_LUM = 24
    STAT_IND_MOV = 25
    STAT_IND_IR_H = 26
    STAT_IND_IR_L = 27
    STAT_IND_ROLL_POS = 28  # 1..8
    STAT_IND_BLAD_POS = 33  # 1..8
    STAT_IND_T_SETP_1 = 38
    STAT_IND_T_SETP_2 = 40
    STAT_IND_END = 42
