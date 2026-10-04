#!/usr/bin/env python3
"""A toio hub with nine simulated cubes, for demos before the real hub exists.

Cubes start on the home cells. move / move_all reach the target after 0.5 s
(wait=true blocks until then) and reject targets closer than 35 units, or off
the mat, the same way the real hub does.

  python3 client/scenario/fake_toio_hub.py --port 18765
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from formations import FORMATIONS, X_MAX, X_MIN, Y_MAX, Y_MIN, cell_center

MIN_SEP = 35.0
MOVE_SECONDS = 0.5
VERBOSE = True


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


class HubState:
    def __init__(self):
        self.lock = threading.Lock()
        self.cubes = {}
        for cube_id, (col, row) in enumerate(FORMATIONS["home"], start=1):
            x, y = cell_center(col, row)
            self.cubes[cube_id] = {
                "id": cube_id, "connected": True, "x": x, "y": y, "angle": 0,
                "col": col, "row": row, "busy": False,
            }

    def snapshot(self):
        with self.lock:
            return [dict(cube) for cube in self.cubes.values()]


def _target_point(item):
    """Resolve one target to (col, row, x, y) or raise ValueError."""
    has_cell = item.get("col") is not None and item.get("row") is not None
    if has_cell:
        col, row = int(item["col"]), int(item["row"])
        if not (1 <= col <= 7 and 1 <= row <= 5):
            raise ValueError(f"outside the mat: col={col} row={row}")
        x, y = cell_center(col, row)
        return col, row, x, y
    if item.get("x") is None or item.get("y") is None:
        raise ValueError("target needs col,row or x,y")
    x, y = float(item["x"]), float(item["y"])
    if not (X_MIN <= x <= X_MAX and Y_MIN <= y <= Y_MAX):
        raise ValueError(f"outside the mat: x={x} y={y}")
    # Nearest cell, for the status fields. The cube still stops at x,y.
    best, best_d = (4, 3), float("inf")
    for col in range(1, 8):
        for row in range(1, 6):
            d = _dist((x, y), cell_center(col, row))
            if d < best_d:
                best, best_d = (col, row), d
    return best[0], best[1], x, y


def plan_moves(state, requests):
    """Check the 35-unit rule. Return update dicts, or raise ValueError.

    `requests` is a list of {"id", "col"/"row" or "x"/"y", optional "angle"}.
    """
    with state.lock:
        cubes = {i: dict(c) for i, c in state.cubes.items()}
    updates = []
    for item in requests:
        try:
            cube_id = int(item["id"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("move needs an id") from None
        if cube_id not in cubes:
            raise ValueError(f"unknown cube {cube_id}")
        col, row, x, y = _target_point(item)
        update = {"id": cube_id, "col": col, "row": row, "x": x, "y": y}
        if item.get("angle") is not None:
            update["angle"] = int(item["angle"])
        updates.append(update)
    moving = {u["id"] for u in updates}
    for i, a in enumerate(updates):
        for b in updates[i + 1:]:
            if _dist((a["x"], a["y"]), (b["x"], b["y"])) < MIN_SEP:
                raise ValueError(
                    f"cubes {a['id']} and {b['id']} would finish closer than {MIN_SEP:.0f}")
    for update in updates:
        for cube in cubes.values():
            if cube["id"] in moving:
                continue
            if _dist((update["x"], update["y"]), (cube["x"], cube["y"])) < MIN_SEP:
                raise ValueError(
                    f"cube {update['id']} would finish closer than {MIN_SEP:.0f} "
                    f"to cube {cube['id']}, which is not moving")
    return updates


def _apply_later(state, updates, wait):
    ids = [u["id"] for u in updates]

    def finish():
        time.sleep(MOVE_SECONDS)
        with state.lock:
            for update in updates:
                cube = state.cubes[update["id"]]
                cube.update(update)
                cube["busy"] = False

    with state.lock:
        for cube_id in ids:
            state.cubes[cube_id]["busy"] = True
    worker = threading.Thread(target=finish, daemon=True)
    worker.start()
    if wait:
        worker.join()


def _as_bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() not in ("0", "false", "no")


def _cube_ids(state, id_arg):
    if id_arg is None or id_arg == "all":
        return sorted(state.cubes)
    try:
        cube_id = int(id_arg)
    except (TypeError, ValueError):
        raise ValueError(f"bad id {id_arg}") from None
    if cube_id not in state.cubes:
        raise ValueError(f"unknown cube {cube_id}")
    return [cube_id]


def dispatch(state, req):
    cmd = req.get("cmd")
    if cmd == "status":
        return {"ok": True, "cubes": state.snapshot()}
    if cmd == "move":
        updates = plan_moves(state, [req])
        wait = _as_bool(req.get("wait"), True)
        _apply_later(state, updates, wait)
        return {"ok": True, "results": {str(updates[0]["id"]): "reached" if wait else "started"}}
    if cmd == "move_all":
        targets = req.get("targets") or []
        if not targets:
            raise ValueError("move_all needs targets")
        updates = plan_moves(state, targets)
        wait = _as_bool(req.get("wait"), True)
        _apply_later(state, updates, wait)
        word = "reached" if wait else "started"
        return {"ok": True, "results": {str(u["id"]): word for u in updates}}
    if cmd == "drive":
        left, right, ms = int(req["left"]), int(req["right"]), int(req["ms"])
        if not (-115 <= left <= 115 and -115 <= right <= 115):
            raise ValueError("left/right must be -115..115")
        if not (0 <= ms <= 2550):
            raise ValueError("ms must be 0..2550")
        _cube_ids(state, req.get("id"))
        return {"ok": True}
    if cmd == "led":
        _cube_ids(state, req.get("id"))
        for channel in ("r", "g", "b"):
            value = int(req[channel])
            if not (0 <= value <= 255):
                raise ValueError(f"{channel} must be 0..255")
        return {"ok": True}
    if cmd == "sound":
        _cube_ids(state, req.get("id"))
        effect = int(req["effect"])
        if not (0 <= effect <= 10):
            raise ValueError("effect must be 0..10")
        return {"ok": True}
    if cmd == "stop":
        _cube_ids(state, req.get("id"))
        with state.lock:
            for cube_id in _cube_ids(state, req.get("id")):
                state.cubes[cube_id]["busy"] = False
        return {"ok": True}
    raise ValueError(f"unknown cmd {cmd}")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            req = {"cmd": "?"}
        if VERBOSE:
            print(json.dumps(req, ensure_ascii=False), flush=True)
        started = time.monotonic()
        try:
            if self.path != "/cmd":
                raise ValueError("POST /cmd")
            res = dispatch(self.server.state, req)
            code = 200
        except Exception as exc:
            res = {"ok": False, "error": str(exc)}
            code = 400
        event = {"t0": started, "t1": time.monotonic(), "cmd": req.get("cmd"), "req": req}
        with self.server.event_lock:
            self.server.events.append(event)
        body = json.dumps(res).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(host, port):
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.state = HubState()
    httpd.events = []
    httpd.event_lock = threading.Lock()
    return httpd


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    httpd = make_server(args.host, args.port)
    print(f"fake toio hub on http://{args.host}:{args.port} (9 cubes at home)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
