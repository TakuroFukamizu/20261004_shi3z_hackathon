#!/usr/bin/env python3
"""02 KAWAII 8-BIT BONUS, 120 BPM, 16.0 s. Bouncy: left, right, JUMP, crouch, tilts, COMBO, GET.

  python3 client/dance/dance_02_kawaii_8bit.py --dry-run
  python3 client/dance/dance_02_kawaii_8bit.py --host 192.168.100.29
Options: --robot-audio  --no-audio  --no-drive  --no-grip  --power 0.7  --wait  (see --help)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import main  # noqa: E402

BPM = 120
WAV = "02_kawaii_8bit_bonus_120bpm.wav"


def left(s, c):
    s.face(c, "happy", "")
    s.head(c, 45 * s.k, 55)
    s.drive(c, x=-70, dur=0.4)


def right(s, c):
    s.face(c, "happy")
    s.head(c, -45 * s.k, 55)
    s.drive(c, x=70, dur=0.4)


def jump(s, c):
    s.face(c, "happy", "JUMP!")
    s.head(c, 0, 80, 1.4)
    s.head(c + 0.5, 0, 35, 1.2)
    s.drive(c, y=80, dur=0.3)               # hop forward...
    s.drive(c + 0.5, y=-80, dur=0.3)        # ...and back


def down(s, c):
    s.face(c, "sad", "")
    s.head(c, 0, 10, 1.2)
    s.head(c + 0.5, 0, 25)


def tilt_left(s, c):
    s.face(c, "happy")
    s.head(c, 25 * s.k, 58)
    s.drive(c, rot=55, dur=0.35)


def tilt_right(s, c):
    s.face(c, "happy")
    s.head(c, -25 * s.k, 58)
    s.drive(c, rot=-55, dur=0.35)


def combo(s, c):
    s.face(c, "happy", "COMBO!")
    for i in range(4):                      # four quick wiggles, wheels pair up
        sign = 1 if i % 2 == 0 else -1
        s.head(c + i * 0.25, 35 * s.k * sign, 62 if i % 2 == 0 else 40, 1.5)
        s.drive(c + i * 0.25, x=60 * sign, dur=0.2)


def get(s, c):
    s.face(c, "happy", "GET!")
    s.head(c, 0, 78, 1.4)
    s.grip(c, 100)
    s.grip(c + 0.5, 0)


MOVES = [("LEFT", left), ("RIGHT", right), ("JUMP!", jump), ("DOWN", down),
         ("左かしげ", tilt_left), ("右かしげ", tilt_right), ("COMBO!", combo), ("GET!", get)]

if __name__ == "__main__":
    sys.exit(main("02 KAWAII 8-BIT BONUS", WAV, BPM, MOVES))
