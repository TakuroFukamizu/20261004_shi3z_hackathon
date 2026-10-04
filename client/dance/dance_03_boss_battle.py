#!/usr/bin/env python3
"""03 BOSS BATTLE / EDM, 140 BPM, 13.7 s. Fast and aggressive: attack, dodge, charge, rush, finish.

  python3 client/dance/dance_03_boss_battle.py --dry-run
  python3 client/dance/dance_03_boss_battle.py --host 192.168.100.29
Options: --robot-audio  --no-audio  --no-drive  --no-grip  --power 0.7  --wait  (see --help)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import main  # noqa: E402

BPM = 140
WAV = "03_boss_battle_edm_140bpm.wav"


def attack(s, c):
    s.face(c, "angry", "ATTACK!")
    s.head(c, 0, 22, 1.5)
    s.drive(c, y=75, dur=0.3)
    s.head(c + 0.5, 0, 50, 1.2)


def dodge(side):
    def move(s, c):
        s.face(c, "doubt", "DODGE!")
        s.head(c, 55 * s.k * side, 60, 1.5)
        s.drive(c, x=70 * side, y=-75, dur=0.3)   # back-step to the side; left and right rounds cancel
    return move


def charge(s, c):
    s.face(c, "angry", "CHARGE")
    s.grip(c, 100)
    for i in range(4):                      # trembling
        sign = 1 if i % 2 == 0 else -1
        s.head(c + i * 0.25, 12 * sign, 15, 2.0)
        s.drive(c + i * 0.25, rot=40 * sign, dur=0.2)


def up(s, c):
    s.face(c, "happy", "UP!")
    s.head(c, 0, 85, 1.5)
    s.grip(c, 0)


def rush(s, c):
    s.face(c, "angry", "RUSH!")
    s.head(c, 0, 30, 1.5)
    s.drive(c, y=85, dur=0.7)
    s.head(c + 0.5, 15 * s.k, 40, 1.5)


def finish(s, c):
    s.face(c, "happy", "FINISH!")
    s.head(c, 0, 80, 1.5)
    s.drive(c, rot=100 if s.loop % 2 == 0 else -100, dur=0.3, scale=False)   # spin, direction alternates
    s.drive(c + 0.3, y=-85, dur=0.7)                            # retreat, cancels the rush
    s.grip(c + 0.5, 100)
    s.grip(c + 0.9, 0)


MOVES = [("ATTACK!", attack), ("DODGE!", dodge(-1)), ("ATTACK!", attack), ("DODGE!", dodge(1)),
         ("CHARGE", charge), ("UP!", up), ("RUSH!", rush), ("FINISH!", finish)]

if __name__ == "__main__":
    sys.exit(main("03 BOSS BATTLE", WAV, BPM, MOVES))
