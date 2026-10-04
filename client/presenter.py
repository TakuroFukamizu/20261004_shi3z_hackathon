#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pynput"]
# ///
"""Drive the robot from a presenter remote (Canon PR7-HY) or any keyboard.

The remote shows up as an ordinary keyboard, so this just maps key presses to robot commands.

  presenter.py --learn      print the name of every key pressed (find out what each button sends)
  presenter.py --dry-run    print the robot commands instead of sending them
  presenter.py              send them

By default keys are read from this terminal, so it must stay focused. With --global, keys are
picked up whichever app is focused (needs pynput: `uv run client/presenter.py --global`, and
macOS asks for Input Monitoring permission for the terminal). In --global mode, typing a bound
key on the Mac's own keyboard also moves the robot.

Edit BINDINGS below to change what each button does.
"""
import argparse
import os
import queue
import sys
import threading
import urllib.error

from robot import Robot

# key name (as printed by --learn) -> list of (Robot method, keyword arguments)
BINDINGS = {
    "page_down": [("drive", {"y": 50, "ms": 800})],     # slide forward button
    "page_up":   [("drive", {"y": -50, "ms": 800})],    # slide back button
    "up":        [("drive", {"y": 50, "ms": 800})],
    "down":      [("drive", {"y": -50, "ms": 800})],
    "right":     [("drive", {"rot": 50, "ms": 500})],
    "left":      [("drive", {"rot": -50, "ms": 500})],
    "f5":        [("face", {"expression": "happy"}), ("say", {"text": "こんにちは"})],
    "b":         [("face", {"expression": "sleepy"})],  # blackout button
    ".":         [("face", {"expression": "sleepy"})],
    "esc":       [("stop", {})],
}

CSI = {"A": "up", "B": "down", "C": "right", "D": "left", "H": "home", "F": "end",
       "5~": "page_up", "6~": "page_down", "15~": "f5"}
PLAIN = {"\x1b": "esc", "\r": "enter", "\n": "enter", "\t": "tab", " ": "space", "\x7f": "backspace"}


def tokens(text):
    """Split raw terminal input into key names. Unknown escape sequences come back as repr()."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "\x1b" and text[i + 1:i + 2] in ("[", "O"):
            j = i + 2
            while j < len(text) and not "@" <= text[j] <= "~":
                j += 1
            seq = text[i + 2:j + 1]
            out.append(CSI.get(seq) or repr(text[i:j + 1]))
            i = j + 1
        else:
            out.append(PLAIN.get(text[i], text[i].lower()))
            i += 1
    return out


class DryRobot:
    def __getattr__(self, name):
        return lambda **kw: print(f"  -> {name} {kw}") or {"ok": True}


class Dispatcher:
    """Runs bound actions off the input thread. Keys that arrive while busy are dropped,
    so held buttons and a slow robot never build up a backlog. stop always goes out at once."""

    def __init__(self, robot):
        self.robot = robot
        self.q = queue.Queue(maxsize=1)
        threading.Thread(target=self._work, daemon=True).start()

    def press(self, key):
        actions = BINDINGS.get(key)
        if not actions:
            return
        print(key)
        if actions == [("stop", {})]:
            threading.Thread(target=self._run, args=(actions,), daemon=True).start()
            return
        try:
            self.q.put_nowait(actions)
        except queue.Full:
            pass

    def _work(self):
        while True:
            self._run(self.q.get())

    def _run(self, actions):
        try:
            for method, kwargs in actions:
                res = getattr(self.robot, method)(**kwargs)
                if not res.get("ok"):
                    print(f"  robot error: {res}", file=sys.stderr)
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"  cannot reach robot: {e}", file=sys.stderr)


def read_terminal(on_key):
    import termios
    import tty
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        while data := os.read(fd, 64):
            for key in tokens(data.decode(errors="ignore")):
                on_key(key)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def read_global(on_key, learn):
    try:
        from pynput import keyboard
    except ImportError:
        sys.exit("--global needs pynput: run with `uv run client/presenter.py --global`")
    held = set()

    def name(key):
        if isinstance(key, keyboard.Key):
            return key.name
        return key.char.lower() if key.char else f"vk{key.vk}"

    def on_press(key):
        n = name(key)
        if n in held:       # autorepeat
            return
        held.add(n)
        vk = key.value.vk if isinstance(key, keyboard.Key) else key.vk
        on_key(f"{n}  (vk={vk})" if learn else n)

    with keyboard.Listener(on_press=on_press, on_release=lambda k: held.discard(name(k))) as listener:
        listener.join()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host")
    p.add_argument("--learn", action="store_true", help="only print key names")
    p.add_argument("--dry-run", action="store_true", help="print robot commands instead of sending")
    p.add_argument("--global", dest="global_", action="store_true", help="capture keys in any app (pynput)")
    a = p.parse_args(argv)

    if a.learn:
        on_key = print
    else:
        on_key = Dispatcher(DryRobot() if a.dry_run else Robot(a.host, timeout=3)).press
    print("Ctrl-C to quit." + ("" if a.global_ else " Keep this terminal focused."))
    try:
        if a.global_:
            read_global(on_key, a.learn)
        else:
            read_terminal(on_key)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
