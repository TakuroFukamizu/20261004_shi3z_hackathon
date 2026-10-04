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
  stop                           wheels, head and voice
  wait   event [timeout]         block until the next event with that name
  events [since]                 recent events
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


class Hub:
    PASS = {"face", "grip", "servo", "calibrate", "torque", "volume", "beep"}

    def __init__(self, link):
        self.link = link
        self.drive = Drive(link)
        self.look = Look(link)

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
        if not self.link.up():
            return {"ok": False, "error": "robot offline"}
        if cmd in self.PASS:
            return self.link.call(d)
        if cmd == "stop":
            self.drive.stop()
            return self.link.call({"cmd": "stop"})
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
