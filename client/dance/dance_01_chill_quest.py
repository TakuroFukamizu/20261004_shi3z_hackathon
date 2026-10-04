#!/usr/bin/env python3
"""01 CHILL QUEST / LO-FI, 85 BPM, 22.6 s.  Style: FLOATING. Slow, smooth, half-time.

Long 2-beat head sweeps with soft springs, no hits. Wheels drift and circle at low power.
A sway -> B look around -> C drift in a circle -> D find an item, LEVEL UP.

  python3 client/dance/dance_01_chill_quest.py --dry-run
  python3 client/dance/dance_01_chill_quest.py --host 192.168.100.29
Options: --robot-audio  --no-audio  --no-drive  --no-grip  --power 0.7  --wait  (see --help)
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import Score, main  # noqa: E402

BPM = 85
WAV = "01_chill_quest_85bpm.wav"
SOFT = 0.55  # head spring speed multiplier: slow and rounded


def build(beats):
    s = Score(BPM)

    # A (0-8) sway: look and lean one way for 2 beats, then the other
    s.mark(0, "A  ゆらゆら")
    s.face(0, "sleepy", "")
    for i, b in enumerate(range(0, 8, 2)):
        sign = 1 if i % 2 == 0 else -1
        s.head(b, 25 * sign, 48, SOFT)
        s.head(b + 1, 22 * sign, 42, SOFT)           # breathe out
        s.drive(b, x=-25 * sign, dur=1.6)            # drift toward where it looks
    s.face(4, "neutral")

    # B (8-16) look around: turn, look, hold, look the other way
    s.mark(8, "B  きょろきょろ")
    s.face(8, "doubt", "?")
    s.head(8, 50, 58, SOFT)
    s.drive(8, rot=25, dur=3)
    s.head(10.5, 20, 40, SOFT)
    s.face(11, "neutral", "")
    s.head(11, 0, 48, SOFT)
    s.drive(11, rot=-25, dur=3)                      # turn back
    s.face(12, "doubt", "?")
    s.head(12, -50, 58, SOFT)
    s.head(14.5, -20, 40, SOFT)
    s.face(15, "happy", "")
    s.head(15, 0, 48, SOFT)

    # C (16-24) float: head draws a slow figure of eight while the base arcs one way and back
    s.mark(16, "C  ふわふわ周回")
    s.face(16, "happy", "")
    for i in range(16):
        t = i * 0.5
        s.head(16 + t, 45 * math.sin(2 * math.pi * t / 4), 47 + 9 * math.sin(2 * math.pi * t / 2), 0.6)
    s.drive(16, x=25, rot=25, dur=3.5)
    s.drive(20, x=-25, rot=-25, dur=3.5)

    # D (24-32) discover, then LEVEL UP
    s.mark(24, "D  みつけた")
    s.face(24, "doubt", "")
    s.head(24, 0, 12, 0.5)                           # look down slowly
    s.head(26, 0, 75, 1.1)                           # pop up
    s.face(26, "happy", "!")
    for j in range(4):                               # wave the claw, slowly
        s.grip(26.5 + j, 100 if j % 2 == 0 else 0)
    s.mark(28, "LEVEL UP!")
    s.face(28, "happy", "LEVEL UP!")
    s.head(28, 0, 85, 1.1)
    s.drive(28, rot=60, dur=1.5)                     # slow spin and back
    s.drive(30, rot=-60, dur=1.5)
    s.head(30, 0, 55, 0.8)
    s.face(31, "happy", "")
    return s


if __name__ == "__main__":
    sys.exit(main("01 CHILL QUEST", WAV, BPM, build))
