#!/usr/bin/env python3
"""StackChan hub: keeps a realtime link to the robot and serves a local JSON API.

Same shape as the toio hub (client/toio_hub.py on 127.0.0.1:8765), so a scenario runner can
drive both the same way:

  python3 client/stackchan_hub.py                 # robot from $ROBOT_HOST or stackchan.local
  python3 client/stackchan_hub.py --host 192.168.100.29

API: POST http://127.0.0.1:8766/cmd with one JSON command, answered {"ok":true,...} or
{"ok":false,"error":"..."}. GET /status and GET /events?since=N also work.

Link to the robot: UDP (firmware realtime.h). Reliable commands carry a sequence number and are
retransmitted until acknowledged. The robot streams its state 20 times a second, with recent
events (speech_end, button_a/b/c, rover_up/down) riding along. Audio still goes over HTTP.

Commands (besides the robot's own: face, grip, servo, calibrate, torque, volume, beep):
  status                         cached robot state + link quality
  say    text [voice] [wait]     speak with macOS TTS; wait=true returns when speech has ended
  play   path [wait]             play a WAV file on the robot
  look   yaw pitch [speed]       stream a head target (latest wins, smooth; for tracking/gaze)
  head   yaw pitch [speed][wait] move the head; wait=true returns when it gets there
  drive  x y rot ms [wait]       wheels for ms (max 30000), kept alive against packet loss
  stop                           wheels, head and voice; also cancels a grid plan
  wait   event [timeout]         block until the next event with that name
  events [since]                 recent events
  grid_status / grid_set / grid_move / grid_step / grid_turn / grid_cal
  claw / catch                   gripper, and a chase onto a mat cell (see stackchan_grid.py)
Standard library only.
"""
import argparse
import collections
import itertools
import json
import os
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import stackchan_grid as gridlib
from urllib.parse import parse_qs, urlparse

RT_PORT = 8790
API_PORT = 8766
RETRY_S = 0.1           # first resend of an unacknowledged command; backs off to 0.3 s
RETRIES = 8             # about 2 s in total before giving up
STATE_STALE_S = 1.5     # no telemetry for this long = link down
DRIVE_REFRESH_S = 0.15  # resend the current wheel command this often
DRIVE_CHUNK_MS = 400    # each refresh keeps the wheels going this long (auto-stop if the hub dies)
LOOK_HZ = 30


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class RobotLink:
    """UDP link to the Core2 firmware's realtime channel."""

    def __init__(self, host, port=RT_PORT, http_port=80):
        self.addr = (socket.gethostbyname(host), port)
        self.http = f"http://{self.addr[0]}:{http_port}"
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.settimeout(0.5)
        self.sid = random.randint(1, 2**31 - 1)
        self.seq = itertools.count(1)
        self.lock = threading.Lock()
        self.pending = {}               # seq -> [threading.Event, reply]
        self.state = {}
        self.state_at = 0.0
        self.cond = threading.Condition()
        self.events = collections.deque(maxlen=500)   # (id, name, arg, local_time)
        self.last_event_id = 0
        self.rtt = None
        self.sent = self.retries = self.lost = 0
        self.running = True
        threading.Thread(target=self._rx, daemon=True).start()
        threading.Thread(target=self._keepalive, daemon=True).start()

    # -- transport
    def _send(self, d):
        self.sock.sendto(json.dumps(d, separators=(",", ":")).encode(), self.addr)

    def stream(self, d):
        """Fire and forget (latest wins)."""
        self._send(d)

    def call(self, d, retries=RETRIES):
        """Reliable command: retransmitted until acknowledged. Returns the robot's reply dict."""
        seq = next(self.seq)
        ev = threading.Event()
        slot = [ev, None]
        with self.lock:
            self.pending[seq] = slot
        msg = dict(d, sid=self.sid, seq=seq)
        t0 = time.perf_counter()
        try:
            for attempt in range(retries):
                self._send(msg)
                self.sent += 1
                if attempt:
                    self.retries += 1
                if ev.wait(min(0.3, RETRY_S + 0.05 * attempt)):
                    rtt = time.perf_counter() - t0
                    self.rtt = rtt if self.rtt is None else self.rtt * 0.8 + rtt * 0.2
                    return slot[1]
            self.lost += 1
            return {"ok": False, "error": "robot did not answer (link down?)"}
        finally:
            with self.lock:
                self.pending.pop(seq, None)

    def _rx(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
                msg = json.loads(data)
            except (socket.timeout, ValueError):
                continue
            except OSError:
                return
            if "ack" in msg:
                with self.lock:
                    slot = self.pending.get(msg.pop("ack"))
                if slot:
                    slot[1] = msg
                    slot[0].set()
            elif msg.get("t") == "state":
                ev = msg.pop("ev", [])
                with self.cond:
                    first = not self.state
                    self.state, self.state_at = msg, time.time()
                    for e in ev:
                        if e["id"] > self.last_event_id:
                            if not first:   # do not replay events from before the hub started
                                self.events.append((e["id"], e["e"], e.get("a", 0), time.time()))
                                log("event", e["e"], e.get("a", ""))
                            self.last_event_id = e["id"]
                    self.cond.notify_all()

    def _keepalive(self):
        was_up = False
        while self.running:
            self.stream({"cmd": "ping"})
            up = self.up()
            if up != was_up:
                log("robot link", "UP" if up else "DOWN", self.addr[0])
                was_up = up
            time.sleep(0.5)

    # -- state
    def up(self):
        return time.time() - self.state_at < STATE_STALE_S

    def wait_event(self, name, timeout, since_id=None, match_arg=None):
        """Block until an event called `name` newer than since_id arrives."""
        deadline = time.time() + timeout
        with self.cond:
            if since_id is None:
                since_id = self.last_event_id
            while True:
                for eid, ename, arg, _ in self.events:
                    if eid > since_id and ename == name and (match_arg is None or arg == match_arg):
                        return {"ok": True, "event": ename, "arg": arg, "id": eid}
                left = deadline - time.time()
                if left <= 0:
                    return {"ok": False, "error": f"timeout waiting for {name}"}
                self.cond.wait(left)

    def wait_state(self, pred, timeout):
        deadline = time.time() + timeout
        with self.cond:
            while not pred(self.state):
                left = deadline - time.time()
                if left <= 0:
                    return False
                self.cond.wait(left)
            return True

    def upload_wav(self, data, timeout=30):
        req = urllib.request.Request(self.http + "/speak", data=data, headers={"Content-Type": "audio/wav"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read() or b'{"ok":false,"error":"http error"}')
        except OSError as e:
            return {"ok": False, "error": f"audio upload failed: {e}"}


class Drive:
    """Keeps a wheel command alive with short refreshes, so a lost packet does not stop the wheels
    and a dead hub stops them within DRIVE_CHUNK_MS."""

    def __init__(self, link):
        self.link = link
        self.cmd = None
        self.until = 0.0
        self.lock = threading.Lock()
        self.done = threading.Event()
        self.done.set()
        threading.Thread(target=self._run, daemon=True).start()

    def set(self, x, y, rot, ms):
        with self.lock:
            self.cmd = {"cmd": "drive", "x": int(x), "y": int(y), "rot": int(rot)}
            self.until = time.time() + ms / 1000.0
            self.done.clear()
        self._refresh()

    def stop(self):
        with self.lock:
            active = self.cmd is not None
            self.cmd = None
            self.done.set()
        if active:
            self.link.stream({"cmd": "drive", "x": 0, "y": 0, "rot": 0, "ms": 60})

    def _refresh(self):
        with self.lock:
            if self.cmd is None:
                return
            left = (self.until - time.time()) * 1000
            if left <= 0:
                self.cmd = None
                self.done.set()
                return
            self.link.stream(dict(self.cmd, ms=int(min(DRIVE_CHUNK_MS, left))))

    def _run(self):
        while True:
            time.sleep(DRIVE_REFRESH_S)
            self._refresh()


class Look:
    """Streams the latest head target at LOOK_HZ (coalesced)."""

    def __init__(self, link):
        self.link = link
        self.target = None
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def set(self, yaw, pitch, speed):
        with self.lock:
            self.target = {"cmd": "head", "yaw": round(float(yaw), 1), "pitch": round(float(pitch), 1),
                           "speed": int(speed), "sync": False}

    def _run(self):
        while True:
            time.sleep(1.0 / LOOK_HZ)
            with self.lock:
                t, self.target = self.target, None
            if t:
                self.link.stream(t)


class GridController:
    """Dead-reckoning plans on top of Drive. The human declares the pose with grid_set.

    A stop, or any new grid motion, cancels the plan that is running. Cancelling a
    segment keeps the cells (or quarter-turns) completed so far, rounded, and marks
    the pose uncertain until the next grid_set. Stopping while idle does not.
    """

    def __init__(self, drive, link):
        self.drive = drive
        self.link = link
        self.lock = threading.Lock()
        self.cal = gridlib.load_calibration()
        self.pose = gridlib.Pose(4, 5, "N", uncertain=True)
        self.cancel_ev = threading.Event()
        self.idle = threading.Event()
        self.idle.set()
        self._owner = None

    def snapshot(self):
        with self.lock:
            pose = self.pose
        return {"col": pose.col, "row": pose.row, "heading": pose.heading, "uncertain": pose.uncertain}

    def status(self):
        with self.lock:
            cal = self.cal
        return {"ok": True, "pose": self.snapshot(), "calibration": gridlib.calibration_dict(cal)}

    def _ok(self):
        return {"ok": True, "pose": self.snapshot()}

    def _pose(self):
        with self.lock:
            return self.pose

    def _cal(self):
        with self.lock:
            return self.cal

    def _store(self, pose):
        with self.lock:
            self.pose = pose

    def _mark_uncertain(self):
        with self.lock:
            pose = self.pose
            self.pose = gridlib.Pose(pose.col, pose.row, pose.heading, True)

    def cancel(self):
        """Ask the running plan to stop. Returns when it has released the wheels."""
        self.cancel_ev.set()
        self.drive.stop()
        if threading.current_thread() is not self._owner:
            self.idle.wait(8)

    def _finish(self):
        self.drive.stop()
        self._owner = None
        self.idle.set()

    def _launch(self, fn, wait):
        self.cancel()
        self.cancel_ev.clear()
        self.idle.clear()
        if wait:
            self._owner = threading.current_thread()
            try:
                fn()
            finally:
                self._finish()
            return self._ok()

        def background():
            self._owner = threading.current_thread()
            try:
                fn()
            finally:
                self._finish()

        threading.Thread(target=background, daemon=True).start()
        return self._ok()

    def set_pose(self, col, row, heading):
        text = str(heading).strip().upper()
        if text not in gridlib.HEADINGS:
            raise ValueError(f"unknown heading {heading!r}")
        col, row = gridlib.clamp_cell(col, row)
        self.cancel()
        self.cancel_ev.clear()
        self._store(gridlib.Pose(col, row, text, False))
        return self._ok()

    def calibrate(self, updates):
        updated = gridlib.apply_calibration(self._cal(), updates)
        gridlib.save_calibration(updated)
        with self.lock:
            self.cal = updated
        return self.status()

    def _run_segment(self, segment):
        if self.cancel_ev.is_set():
            self._mark_uncertain()
            return False
        self.drive.set(segment.x, segment.y, segment.rot, segment.ms)
        started = time.monotonic()
        cancelled = self.cancel_ev.wait(segment.ms / 1000.0)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self.drive.stop()
        if cancelled or self.cancel_ev.is_set():
            self._store(gridlib.partial_pose(self._pose(), segment, elapsed_ms))
            return False
        with self.lock:
            uncertain = self.pose.uncertain
        end = segment.pose
        self._store(gridlib.Pose(end.col, end.row, end.heading, uncertain))
        settle = self._cal().settle_ms
        if settle > 0 and self.cancel_ev.wait(settle / 1000.0):
            self._mark_uncertain()
            return False
        return True

    def _run_segments(self, segments):
        for segment in segments:
            if not self._run_segment(segment):
                return False
        return True

    def _pulse(self, x, y, rot, ms):
        """Timed wheels that do not move the recorded pose (the catch nudge)."""
        if self.cancel_ev.is_set():
            self._mark_uncertain()
            return False
        if ms > 0:
            self.drive.set(x, y, rot, ms)
            cancelled = self.cancel_ev.wait(ms / 1000.0)
            self.drive.stop()
            if cancelled or self.cancel_ev.is_set():
                self._mark_uncertain()
                return False
        settle = self._cal().settle_ms
        if settle > 0 and self.cancel_ev.wait(settle / 1000.0):
            self._mark_uncertain()
            return False
        return True

    def move(self, col, row, wait):
        def fn():
            self._run_segments(gridlib.plan_move(self._pose(), col, row, self._cal()))
        return self._launch(fn, wait)

    def step(self, direction, cells, wait):
        def fn():
            pose = self._pose()
            col, row = gridlib.step_target(pose, direction, cells)
            self._run_segments(gridlib.plan_move(pose, col, row, self._cal()))
        return self._launch(fn, wait)

    def turn(self, heading, wait):
        def fn():
            pose = self._pose()
            target = gridlib.resolve_heading(pose, heading)
            self._run_segments(gridlib.plan_turn(pose, target, self._cal()))
        return self._launch(fn, wait)

    def catch(self, col, row, wait):
        def fn():
            opened = self.link.call({"cmd": "grip", "percent": 0})
            if not opened.get("ok") or self.cancel_ev.is_set():
                if self.cancel_ev.is_set():
                    self._mark_uncertain()
                return
            pose = self._pose()
            segments, _approach = gridlib.plan_catch(pose, col, row, self._cal())
            if not self._run_segments(segments):
                return
            # 0.4 cell forward, close, then the same nudge backward. The recorded
            # cell stays the approach cell: the nudge is not a grid segment.
            ms = int(round(0.4 * self._cal().fwd_ms_per_cell))
            speed = self._cal().speed
            if not self._pulse(0, speed, 0, ms):
                return
            closed = self.link.call({"cmd": "grip", "percent": 100})
            if not closed.get("ok") or self.cancel_ev.is_set():
                if self.cancel_ev.is_set():
                    self._mark_uncertain()
                return
            self._pulse(0, -speed, 0, ms)
        return self._launch(fn, wait)


def _wait_flag(d):
    if "wait" not in d:
        return True
    value = d["wait"]
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no")
    return bool(value)


def _claw_percent(d):
    if d.get("percent") is not None:
        return max(0, min(100, int(d["percent"])))
    state = str(d.get("state", "")).strip().lower()
    if state == "open":
        return 0
    if state == "close":
        return 100
    raise ValueError("claw needs state open|close or percent")


class Hub:
    PASS = {"face", "grip", "servo", "calibrate", "torque", "volume", "beep"}

    def __init__(self, link):
        self.link = link
        self.drive = Drive(link)
        self.look = Look(link)
        self.grid = GridController(self.drive, link)

    def _need_rover(self):
        if not self.link.state.get("rover"):
            return {"ok": False, "error": "rover not connected"}
        return None

    def status(self):
        s = dict(self.link.state)
        s.update(ok=True, link_up=self.link.up(), state_age_ms=int((time.time() - self.link.state_at) * 1000),
                 rtt_ms=round(self.link.rtt * 1000, 1) if self.link.rtt else None,
                 sent=self.link.sent, retries=self.link.retries, lost=self.link.lost,
                 driving=not self.drive.done.is_set(), last_event_id=self.link.last_event_id)
        return s

    def handle(self, d):
        cmd = d.get("cmd", "")
        if cmd == "status":
            return self.status()
        if cmd == "events":
            since = int(d.get("since", 0))
            return {"ok": True, "events": [{"id": i, "event": n, "arg": a, "time": t}
                                           for i, n, a, t in list(self.link.events) if i > since]}
        if cmd == "wait":
            since = d.get("since")
            return self.link.wait_event(d["event"], float(d.get("timeout", 30)), None if since is None else int(since))
        if cmd == "grid_status":
            return self.grid.status()
        if cmd == "grid_set":
            return self.grid.set_pose(d.get("col"), d.get("row"), d.get("heading"))
        if cmd == "grid_cal":
            fields = {key: d[key] for key in gridlib.CAL_FIELDS if key in d}
            return self.grid.calibrate(fields)
        if not self.link.up():
            return {"ok": False, "error": "robot offline"}
        if cmd in self.PASS:
            return self.link.call(d)
        if cmd == "stop":
            self.grid.cancel()
            self.drive.stop()
            return self.link.call({"cmd": "stop"})
        if cmd == "claw":
            res = self.link.call({"cmd": "grip", "percent": _claw_percent(d)})
            if res.get("ok"):
                res = dict(res)
                res["pose"] = self.grid.snapshot()
            return res
        if cmd in ("grid_move", "grid_step", "grid_turn", "catch"):
            missing = self._need_rover()
            if missing:
                return missing
            wait = _wait_flag(d)
            if cmd == "grid_move":
                return self.grid.move(d.get("col"), d.get("row"), wait)
            if cmd == "grid_step":
                return self.grid.step(d.get("dir", d.get("direction")), d.get("cells", 1), wait)
            if cmd == "grid_turn":
                return self.grid.turn(d.get("heading"), wait)
            return self.grid.catch(d.get("col"), d.get("row"), wait)
        if cmd == "look":
            self.look.set(d.get("yaw", 0), d.get("pitch", 45), d.get("speed", 700))
            return {"ok": True}
        if cmd == "head":
            yaw, pitch = float(d.get("yaw", 0)), float(d.get("pitch", 45))
            res = self.link.call({"cmd": "head", "yaw": yaw, "pitch": pitch, "speed": int(d.get("speed", 500)),
                                  "sync": True})
            if res.get("ok") and d.get("wait"):
                near = lambda s: abs(s.get("yaw", 999) - yaw) < 4 and abs(s.get("pitch", 999) - pitch) < 4
                res["reached"] = self.link.wait_state(near, float(d.get("timeout", 3)))
            return res
        if cmd == "drive":
            ms = max(0, min(30000, int(d.get("ms", 500))))
            if not self.link.state.get("rover"):
                return {"ok": False, "error": "rover not connected"}
            self.drive.set(d.get("x", 0), d.get("y", 0), d.get("rot", 0), ms)
            if d.get("wait"):
                self.drive.done.wait(ms / 1000.0 + 1)
            return {"ok": True}
        if cmd in ("say", "play"):
            return self.speak(d)
        return {"ok": False, "error": f"unknown cmd {cmd!r}"}

    def speak(self, d):
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "a.wav")
            try:
                if d["cmd"] == "say":
                    text = str(d.get("text", ""))
                    if not text:
                        return {"ok": False, "error": "text is empty"}
                    args = ["say", "-v", d.get("voice", "Kyoko"), "-o", wav, "--data-format=LEI16@16000"]
                    if d.get("rate"):
                        args += ["-r", str(int(d["rate"]))]
                    subprocess.run(args + [text], check=True, timeout=30)
                    if d.get("balloon", True):
                        self.link.call({"cmd": "face", "text": text})
                else:
                    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", d["path"], wav],
                                   check=True, timeout=30)
            except (subprocess.SubprocessError, OSError, KeyError) as e:
                return {"ok": False, "error": f"audio prepare failed: {e}"}
            data = open(wav, "rb").read()
        since = self.link.last_event_id
        res = self.link.upload_wav(data)
        if res.get("ok") and d.get("wait", True):
            w = self.link.wait_event("speech_end", res.get("seconds", 10) + 5, since, res.get("id"))
            res["finished"] = w.get("ok", False)
        return res


def make_handler(hub):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _send(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/status"):
                return self._send(hub.status())
            if u.path == "/events":
                since = int(parse_qs(u.query).get("since", ["0"])[0])
                return self._send(hub.handle({"cmd": "events", "since": since}))
            self._send({"ok": False, "error": "not found"}, 404)

        def do_POST(self):
            try:
                d = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except ValueError:
                return self._send({"ok": False, "error": "invalid JSON"}, 400)
            try:
                res = hub.handle(d)
            except Exception as e:  # keep the hub alive whatever a caller sends
                res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            self._send(res, 200 if res.get("ok") else 400)

    return H


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("ROBOT_HOST") or "stackchan.local")
    ap.add_argument("--port", type=int, default=API_PORT, help="local API port (default 8766)")
    ap.add_argument("--rt-port", type=int, default=RT_PORT)
    ap.add_argument("--http-port", type=int, default=80, help="robot HTTP port for audio (default 80)")
    ap.add_argument("--listen", default="127.0.0.1", help="API bind address (default localhost only)")
    a = ap.parse_args()

    try:
        link = RobotLink(a.host, a.rt_port, a.http_port)
    except OSError as e:
        sys.exit(f"cannot resolve {a.host}: {e}")
    hub = Hub(link)
    srv = ThreadingHTTPServer((a.listen, a.port), make_handler(hub))
    srv.daemon_threads = True
    log(f"StackChan hub: robot {link.addr[0]}:{link.addr[1]}, API http://{a.listen}:{a.port}/cmd")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log("stopping robot")
        hub.drive.stop()
        link.call({"cmd": "stop"}, retries=3)
        link.running = False


if __name__ == "__main__":
    main()
