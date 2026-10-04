#!/usr/bin/env python3
"""01 CHILL QUEST / LO-FI, 85 BPM, 22.6 s. Slow exploring: look left/right, find an item, LEVEL UP.

  python3 client/dance/dance_01_chill_quest.py --dry-run     # show the timeline only
  python3 client/dance/dance_01_chill_quest.py --host 192.168.100.29
Options: --robot-audio  --no-audio  --no-drive  --no-grip  --power 0.7  --wait  (see --help)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import main  # noqa: E402

BPM = 85
WAV = "01_chill_quest_85bpm.wav"


def left(s, c):
    s.face(c, "doubt", "")
    s.head(c, 35 * s.k, 52)
    s.drive(c, x=-50, dur=0.5)
    s.head(c + 0.5, 45 * s.k, 48)


def keep_left(s, c):
    s.face(c, "neutral")
    s.head(c, 42 * s.k, 48)
    s.head(c + 0.5, 42 * s.k, 43)


def front(s, c):
    s.face(c, "happy")
    s.head(c, 0, 45)
    s.head(c + 0.5, 0, 50)


def right(s, c):
    s.face(c, "doubt")
    s.head(c, -35 * s.k, 52)
    s.drive(c, x=50, dur=0.5)
    s.head(c + 0.5, -45 * s.k, 48)


def keep_right(s, c):
    s.face(c, "neutral")
    s.head(c, -42 * s.k, 48)
    s.head(c + 0.5, -42 * s.k, 43)


def item(s, c):
    s.face(c, "doubt")
    s.head(c, 0, 18, 0.8)                   # look down at the item
    s.head(c + 0.5, 0, 72, 1.3)             # pop up, surprised
    s.face(c + 0.5, "happy", "!")
    s.grip(c + 0.5, 100)
    s.grip(c + 1.0, 0)


def level_up(s, c):
    s.face(c, "happy", "LEVEL UP!")
    s.head(c, 0, 80, 1.4)
    s.drive(c, rot=70 if s.loop % 2 == 0 else -70, dur=0.8, scale=False)  # spin; direction alternates so it nets out
    s.head(c + 0.5, 0, 55)


MOVES = [("左へ探索", left), ("キープ", keep_left), ("正面", front), ("右へ探索", right),
         ("キープ", keep_right), ("正面", front), ("アイテム発見", item), ("LEVEL UP!", level_up)]

if __name__ == "__main__":
    sys.exit(main("01 CHILL QUEST", WAV, BPM, MOVES))
