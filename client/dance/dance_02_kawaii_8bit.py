#!/usr/bin/env python3
"""02 KAWAII 8-BIT BONUS, 120 BPM, 16.0 s.  Style: BOUNCY. Quick staccato pops on every off-beat.

The head pops up on the beat and drops on the off-beat. Wheels step, hop and wiggle in short bursts.
A step-step -> B hop and chomp -> C swing turns and COMBO -> D hop fanfare, GET!

  python3 client/dance/dance_02_kawaii_8bit.py --dry-run
  python3 client/dance/dance_02_kawaii_8bit.py --host 192.168.100.29
Options: --robot-audio  --no-audio  --no-drive  --no-grip  --power 0.7  --wait  (see --help)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Score, main  # noqa: E402

BPM = 120
WAV = "02_kawaii_8bit_bonus_120bpm.wav"


def build(beats):
    s = Score(BPM)

    # A (0-8) step-step: side step on every beat, head tilts and bobs
    s.mark(0, "A  ぴょこぴょこステップ")
    s.face(0, "happy", "")
    for b in range(8):
        sign = 1 if b % 2 == 0 else -1
        s.head(b, 30 * sign, 62, 1.3)
        s.head(b + 0.5, 30 * sign, 38, 1.3)
        s.drive(b, x=-60 * sign, dur=0.3)

    # B (8-16) hop forward and back every 2 beats, claw chomps every half beat
    s.mark(8, "B  ホップ & パクパク")
    s.face(8, "happy", "!")
    for i in range(4):
        b = 8 + 2 * i
        s.drive(b, y=75, dur=0.25)
        s.drive(b + 1, y=-75, dur=0.25)
        for t, pitch in ((0, 82), (0.5, 35), (1, 70), (1.5, 35)):
            s.head(b + t, 0, pitch, 1.4)
    for j in range(16):
        s.grip(8 + j * 0.5, 100 if j % 2 == 0 else 0)

    # C (16-24) swing turns, then COMBO wiggles at sixteenth notes
    s.mark(16, "C  くるくる")
    s.face(16, "happy", "")
    for b in range(16, 20):
        sign = 1 if b % 2 == 0 else -1
        s.drive(b, rot=80 * sign, dur=0.3)
        s.head(b, 40 * sign, 60, 1.4)
        s.head(b + 0.5, 40 * sign, 35, 1.4)
    s.mark(20, "COMBO!")
    s.face(20, "happy", "COMBO!")
    for j in range(16):
        b = 20 + j * 0.25
        sign = 1 if j % 2 == 0 else -1
        s.head(b, 35 * sign, 62 if sign > 0 else 40, 1.6)
        s.drive(b, x=60 * sign, dur=0.2)

    # D (24-32) fanfare: hop and tilt, then GET! claw snaps, then a spin
    s.mark(24, "D  ボーナス")
    s.face(24, "happy", "")
    for i in range(4):
        b = 24 + i
        sign = 1 if i % 2 == 0 else -1
        s.head(b, 30 * sign, 80, 1.4)
        s.head(b + 0.5, 30 * sign, 35, 1.4)
        s.drive(b, y=70, dur=0.2)
        s.drive(b + 0.5, y=-70, dur=0.2)
    s.mark(28, "GET!")
    s.face(28, "happy", "GET!")
    s.head(28, 0, 80, 1.4)
    for j in range(5):
        s.grip(28 + j * 0.5, 100 if j % 2 == 0 else 0)
    s.head(30, 0, 85, 1.4)
    s.drive(30, rot=100, dur=0.6)                    # spin and un-spin
    s.drive(31, rot=-100, dur=0.6)
    s.face(31, "happy", "")
    return s


if __name__ == "__main__":
    sys.exit(main("02 KAWAII 8-BIT BONUS", WAV, BPM, build))
