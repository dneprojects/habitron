"""Module test_command"""
from .communicate import HbtnComm as hbtn_com
from .const import SMARTIP_COMMAND_STRINGS


async def test_command(cmd_str, mod, arg1, arg2) -> None:

    """Send command patches module and output numbers"""
    cmd_str = SMARTIP_COMMAND_STRINGS[cmd_str]
    cmd_str = cmd_str.replace("\xff", chr(mod))
    cmd_str = cmd_str.replace("\xfe", chr(arg1))
    cmd_str = cmd_str.replace("\xfd", chr(arg2))
    print_hex(cmd_str.encode("iso8859-1"))
    resp = await hbtn_com().send_command(cmd_str)
    print(resp)
    print_hex(resp)


async def test_string(cmd_str, mod, arg1, arg2) -> None:

    """Send command patches module and output numbers"""
    cmd_str = cmd_str.replace("\xff", chr(mod))
    cmd_str = cmd_str.replace("\xfe", chr(arg1))
    cmd_str = cmd_str.replace("\xfd", chr(arg2))
    print_hex(cmd_str.encode("iso8859-1"))
    resp = await hbtn_com().send_command(cmd_str)
    print(resp)
    print_hex(resp)


def print_hex(byte_str) -> None:

    """Pretty print byte string"""
    lbs = len(byte_str)
    ptr = 0
    while ptr < lbs:
        line = ""
        end_l = min([ptr + 10, lbs])
        for i in range(end_l - ptr):
            line = line + f"{'{:02X}'.format(byte_str[ptr+i])} "
        line = line + "   "
        for i in range(end_l - ptr):
            line = line + f"{'{:3d}'.format(byte_str[ptr+i])} "
        print(line)
        ptr += 10
