"""toio Core Cube BLE byte formats. Pure functions, no BLE dependency.

Spec: https://toio.github.io/toio-spec/docs/ble_communication_overview
"""
import struct


def _uuid(n):
    return "10b2%04x-5b3b-4571-9508-cf3efcd7bbae" % n


SERVICE = _uuid(0x0100)
ID_INFO = _uuid(0x0101)   # read / notify: position on the mat
MOTOR = _uuid(0x0102)     # write: drive commands, notify: result of a move
LIGHT = _uuid(0x0103)
SOUND = _uuid(0x0104)
BATTERY = _uuid(0x0108)   # read / notify: percent
CONFIG = _uuid(0x01FF)

MAX_SPEED = 115
MOVE_RESULTS = {0: "reached", 1: "timeout", 2: "off_mat", 3: "bad_parameters",
                4: "bad_state", 5: "interrupted", 6: "unsupported"}

STOP = bytes([0x01, 0x01, 0x01, 0x00, 0x02, 0x01, 0x00])
LED_OFF = bytes([0x01])
# 5 x (300 ms white, 300 ms off) = 3 s
BLINK = bytes([0x04, 5, 2, 30, 1, 1, 255, 255, 255, 30, 1, 1, 0, 0, 0])
REQUEST_VERSION = bytes([0x01, 0x00])
_NO_ANGLE = 0x05 << 13    # top 3 bits of theta: no target angle, no final turn


def _wheel(v):
    v = int(v)
    if not -MAX_SPEED <= v <= MAX_SPEED:
        raise ValueError("wheel speed must be -115..115")
    return (0x01 if v >= 0 else 0x02), abs(v)


def drive(left, right, ms):
    """Run both wheels for `ms` milliseconds, then stop. There is no unlimited form on purpose."""
    ms = int(ms)
    if not 10 <= ms <= 2550:
        raise ValueError("ms must be 10..2550")
    ld, ls = _wheel(left)
    rd, rs = _wheel(right)
    return bytes([0x02, 0x01, ld, ls, 0x02, rd, rs, ms // 10])


def move_to(control_id, x, y, angle=None, speed=80, timeout=10, turn_first=True):
    """Drive to mat coordinates; the cube steers itself and answers with parse_move_result().
    turn_first: turn on the spot, then drive straight (False: steer while driving, in an arc)."""
    x, y, speed, timeout = int(x), int(y), int(speed), int(timeout)
    if not (0 <= x < 0xFFFF and 0 <= y < 0xFFFF):
        raise ValueError("x and y must be 0..65534")
    if not 10 <= speed <= MAX_SPEED:
        raise ValueError("speed must be 10..115")
    if not 1 <= timeout <= 255:
        raise ValueError("timeout must be 1..255")
    theta = _NO_ANGLE if angle is None else int(angle) % 360
    return struct.pack("<7B3H", 0x03, control_id & 0xFF, timeout,
                       0x02 if turn_first else 0x00, speed, 0x00, 0x00, x, y, theta)


def led(r, g, b, ms=0):
    """Light the lamp. ms 0 keeps it on."""
    r, g, b, ms = int(r), int(g), int(b), int(ms)
    if not all(0 <= v <= 255 for v in (r, g, b)):
        raise ValueError("r, g, b must be 0..255")
    if not 0 <= ms <= 2550:
        raise ValueError("ms must be 0..2550")
    return bytes([0x03, ms // 10, 0x01, 0x01, r, g, b])


def sound(effect, volume=255):
    effect, volume = int(effect), int(volume)
    if not 0 <= effect <= 10:
        raise ValueError("effect must be 0..10")
    if not 0 <= volume <= 255:
        raise ValueError("volume must be 0..255")
    return bytes([0x02, effect, volume])


def parse_id(data):
    """ID_INFO value -> {"on_mat": True, "x", "y", "angle"} / {"on_mat": False} / None if unknown."""
    if not data:
        return None
    if data[0] == 0x01 and len(data) >= 7:
        x, y, angle = struct.unpack_from("<HHH", data, 1)
        return {"on_mat": True, "x": x, "y": y, "angle": angle}
    if data[0] in (0x02, 0x03, 0x04):   # on a card, or lifted
        return {"on_mat": False}
    return None


def parse_move_result(data):
    """MOTOR notification -> (control_id, result name), or None if it is not a move result."""
    if len(data) < 3 or data[0] != 0x83:
        return None
    return data[1], MOVE_RESULTS.get(data[2], "error_0x%02x" % data[2])


def parse_version(data):
    """CONFIG notification -> BLE protocol version string, or None."""
    if len(data) < 3 or data[0] != 0x81:
        return None
    return bytes(data[2:]).decode("ascii", "replace")
