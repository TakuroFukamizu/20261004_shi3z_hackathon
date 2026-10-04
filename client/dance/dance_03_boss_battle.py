#!/usr/bin/env python3
"""03 BOSS BATTLE / EDM, 140 BPM, 13.7 s.  Style: AGGRESSIVE. Hard hits, headbang, build-up and DROP.

Head slams on the kick at full spring speed, wheels punch, vibrate and dash.
A warning (stalk) -> B headbang -> C build-up (8th then 16th shakes) -> D DROP

  python3 client/dance/dance_03_boss_battle.py --dry-run
  python3 client/dance/dance_03_boss_battle.py --host 192.168.100.29
Options: --robot-audio  --no-audio  --no-drive  --no-grip  --power 0.7  --wait  (see --help)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Score, main  # noqa: E402

BPM = 140
WAV = "03_boss_battle_edm_140bpm.wav"


def build(beats):
    s = Score(BPM)

    # A (0-8) warning: low menacing scan, creeping forward then back
    s.mark(0, "A  WARNING")
    s.face(0, "angry", "")
    for i, b in enumerate(range(0, 8, 2)):
        s.head(b, 60 * (1 if i % 2 == 0 else -1), 15, 0.5)
    s.drive(0, y=30, dur=3.5)
    s.drive(4, y=-30, dur=3.5)
    s.face(6, "angry", "WARNING")
    s.face(7, "angry", "!!")

    # B (8-16) headbang: slam down on the kick, snap up on the off-beat, punch the base
    s.mark(8, "B  HEADBANG")
    s.face(8, "angry", "BANG!")
    for b in range(8, 16):
        s.head(b, 0, 12, 1.25)
        s.head(b + 0.5, 0, 62, 1.25)
        s.drive(b, y=60, dur=0.2)
        s.drive(b + 0.5, y=-60, dur=0.2)
    s.face(12, "angry", "")

    # C (16-24) build-up: shakes at 8th notes, then 16th notes, claw clenched
    s.mark(16, "C  CHARGE")
    s.face(16, "angry", "CHARGE")
    s.grip(16, 100)
    for j in range(8):
        sign = 1 if j % 2 == 0 else -1
        s.head(16 + j * 0.5, 14 * sign, 18, 1.5)
        s.drive(16 + j * 0.5, rot=45 * sign, dur=0.2)
    for j in range(16):
        sign = 1 if j % 2 == 0 else -1
        s.head(20 + j * 0.25, 14 * sign, 18, 1.5)
        s.drive(20 + j * 0.25, rot=45 * sign, dur=0.12)
    s.head(23.5, 0, 85, 1.5)                         # freeze before the drop
    s.face(23.5, "doubt", "...")

    # D (24-32) DROP: spin, diagonal dashes, headbang, FINISH
    s.mark(24, "D  DROP!!")
    s.face(24, "angry", "DROP!!")
    s.grip(24, 0)
    s.head(24, 0, 12, 1.5)
    s.drive(24, rot=100, dur=0.5)
    for i, b in enumerate(range(25, 29)):
        sign = 1 if i % 2 == 0 else -1
        s.head(b, 50 * sign, 15, 1.5)
        s.head(b + 0.5, 50 * sign, 70, 1.5)
        s.drive(b, x=90 * sign, y=70, dur=0.35)
        s.drive(b + 0.5, x=-90 * sign, y=-70, dur=0.35)
    for b in (29, 29.5, 30, 30.5):                   # last headbang before the finish
        s.head(b, 0, 12 if b % 1 == 0 else 70, 1.5)
    s.drive(30, rot=-100, dur=0.5)                   # spin back
    s.mark(30, "FINISH!")
    s.face(30, "happy", "FINISH!")
    s.head(30.5, 0, 85, 1.5)
    s.grip(30.5, 100)
    s.grip(31.2, 0)
    return s


if __name__ == "__main__":
    sys.exit(main("03 BOSS BATTLE", WAV, BPM, build))
