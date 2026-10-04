#!/usr/bin/env python3
"""PC-side CLI / library for the toio cubes. Standard library only. Talks to client/toio_hub.py.

  toio.py status
  toio.py move 3 --cell 4,2                 cube 3 to column 4, row 2 (columns from the left, rows from the top)
  toio.py move 3 --xy 250,250 --angle 90
  toio.py move-all 1:1,1 2:2,1 3:3,1        number:column,row  (--xy for number:x,y)
  toio.py drive 3 --left 50 --right 50 --ms 500
  toio.py led all 0 255 0
  toio.py sound 3 6
  toio.py identify 5
  toio.py stop

Start the hub first: uv run client/toio_hub.py
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


class Toio:
    def __init__(self, host="127.0.0.1", port=8765, timeout=300):
        self.base = "http://%s:%d" % (host, port)
        self.timeout = timeout      # a move can legitimately take up to 255 s

    def cmd(self, name, **args):
        args = {k: v for k, v in args.items() if v is not None}
        req = urllib.request.Request(self.base + "/cmd", data=json.dumps({"cmd": name, **args}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read() or b'{"ok":false,"error":"http error"}')

    def status(self):
        return self.cmd("status")

    def move(self, id, cell=None, xy=None, angle=None, speed=None, timeout=None, wait=True):
        """Send one cube to a cell (col, row) or to mat coordinates (x, y). Waits for arrival unless wait=False."""
        if (cell is None) == (xy is None):
            raise ValueError("give exactly one of cell or xy")
        where = {"col": cell[0], "row": cell[1]} if cell is not None else {"x": xy[0], "y": xy[1]}
        return self.cmd("move", id=id, angle=angle, speed=speed, timeout=timeout,
                        wait=None if wait else False, **where)

    def move_all(self, targets, xy=False, speed=None, timeout=None, wait=True):
        """targets: {cube id: (col, row)}, or {cube id: (x, y)} with xy=True."""
        a, b = ("x", "y") if xy else ("col", "row")
        items = [{"id": cid, a: p[0], b: p[1]} for cid, p in targets.items()]
        return self.cmd("move_all", speed=speed, timeout=timeout, wait=None if wait else False, targets=items)

    def drive(self, id, left, right, ms=500):
        return self.cmd("drive", id=id, left=left, right=right, ms=ms)

    def led(self, id, r, g, b, ms=None):
        return self.cmd("led", id=id, r=r, g=g, b=b, ms=ms)

    def sound(self, id, effect):
        return self.cmd("sound", id=id, effect=effect)

    def identify(self, id):
        return self.cmd("identify", id=id)

    def stop(self, id=None):
        return self.cmd("stop", id=id)


def _id(text):
    return "all" if text == "all" else int(text)


def _pair(text):
    a, b = text.split(",")
    return int(a), int(b)


def _numbered(text):
    cid, pair = text.split(":")
    return int(cid), _pair(pair)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status")

    s = sub.add_parser("move", help="send one cube to a cell or to coordinates")
    s.add_argument("id", type=int)
    where = s.add_mutually_exclusive_group(required=True)
    where.add_argument("--cell", type=_pair, metavar="COL,ROW")
    where.add_argument("--xy", type=_pair, metavar="X,Y")
    s.add_argument("--angle", type=int)

    m = sub.add_parser("move-all", help="send several cubes at once")
    m.add_argument("targets", nargs="+", type=_numbered, metavar="ID:COL,ROW")
    m.add_argument("--xy", action="store_true", help="targets are ID:X,Y")

    for q in (s, m):
        q.add_argument("--speed", type=int, help="10..115, default 80")
        q.add_argument("--timeout", type=int, help="seconds, default 10")
        q.add_argument("--no-wait", action="store_true", help="return at once; see busy / last_result in status")

    s = sub.add_parser("drive", help="run the wheels for a fixed time (works off the mat)")
    s.add_argument("id", type=_id)
    s.add_argument("--left", type=int, default=0, help="-115..115")
    s.add_argument("--right", type=int, default=0, help="-115..115")
    s.add_argument("--ms", type=int, default=500, help="10..2550")

    s = sub.add_parser("led")
    s.add_argument("id", type=_id)
    s.add_argument("r", type=int)
    s.add_argument("g", type=int)
    s.add_argument("b", type=int)
    s.add_argument("--ms", type=int, help="0 or omitted = stay on")

    s = sub.add_parser("sound")
    s.add_argument("id", type=_id)
    s.add_argument("effect", type=int, help="0..10")

    s = sub.add_parser("identify", help="blink and beep one cube")
    s.add_argument("id", type=int)

    s = sub.add_parser("stop", help="stop one cube, or all of them")
    s.add_argument("id", type=_id, nargs="?")

    a = p.parse_args(argv)
    t = Toio(a.host, a.port)
    c = a.command
    try:
        if c == "status":
            res = t.status()
        elif c == "move":
            res = t.move(a.id, cell=a.cell, xy=a.xy, angle=a.angle, speed=a.speed, timeout=a.timeout,
                         wait=not a.no_wait)
        elif c == "move-all":
            res = t.move_all(dict(a.targets), xy=a.xy, speed=a.speed, timeout=a.timeout, wait=not a.no_wait)
        elif c == "drive":
            res = t.drive(a.id, a.left, a.right, a.ms)
        elif c == "led":
            res = t.led(a.id, a.r, a.g, a.b, a.ms)
        elif c == "sound":
            res = t.sound(a.id, a.effect)
        elif c == "identify":
            res = t.identify(a.id)
        else:
            res = t.stop(a.id)
    except (urllib.error.URLError, OSError) as e:
        print("cannot reach the toio hub at %s: %s\nstart it with: uv run client/toio_hub.py" % (t.base, e),
              file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
