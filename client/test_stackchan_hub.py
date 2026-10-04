#!/usr/bin/env python3
"""Tests the hub against a fake robot that drops 20% of UDP datagrams each way.
Run: python3 client/test_stackchan_hub.py   (about 15 s, no hardware needed)"""
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stackchan import StackChan  # noqa: E402

DROP = 0.2
RT, HTTP, API = 18790, 18791, 18766
random.seed(1)


class FakeRobot:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", RT))
        self.client = None
        self.executed = []          # every command actually executed
        self.replies = {}
        self.events = []
        self.next_ev = 1
        self.clip = 0
        self.speaking = False
        self.yaw = 0.0
        self.pitch = 45.0
        self.target = (0.0, 45.0)
        self.telemetry = True
        self.lock = threading.Lock()
        for f in (self._rx, self._tx):
            threading.Thread(target=f, daemon=True).start()

    def event(self, name, arg=0):
        with self.lock:
            self.events.append({"id": self.next_ev, "e": name, "a": arg})
            self.next_ev += 1

    def _rx(self):
        while True:
            data, addr = self.sock.recvfrom(4096)
            if random.random() < DROP:
                continue
            d = json.loads(data)
            self.client = addr
            if d.get("cmd") == "ping":
                continue
            key = (d.get("sid"), d.get("seq"))
            if d.get("seq") and key in self.replies:
                self._send(self.replies[key], addr)
                continue
            self.executed.append(d)
            if d.get("cmd") == "head":
                self.target = (d["yaw"], d["pitch"])
            res = {"ok": True}
            if d.get("seq"):
                res["ack"] = d["seq"]
                self.replies[key] = res
                self._send(res, addr)

    def _send(self, obj, addr):
        if random.random() >= DROP:
            self.sock.sendto(json.dumps(obj).encode(), addr)

    def _tx(self):
        while True:
            time.sleep(0.05)
            # head approaches its target
            self.yaw += (self.target[0] - self.yaw) * 0.3
            self.pitch += (self.target[1] - self.pitch) * 0.3
            if self.client and self.telemetry:
                with self.lock:
                    ev = self.events[-8:]
                st = {"t": "state", "yaw": round(self.yaw, 1), "pitch": round(self.pitch, 1), "speaking": self.speaking,
                      "clip": self.clip, "rover": True, "battery": 90, "ev": ev}
                self._send(st, self.client)

    def speak(self, seconds):
        self.clip += 1
        clip = self.clip
        self.speaking = True
        self.event("speech_start", clip)

        def end():
            time.sleep(seconds)
            self.speaking = False
            self.event("speech_end", clip)
        threading.Thread(target=end, daemon=True).start()
        return clip


robot = FakeRobot()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        assert body[:4] == b"RIFF"
        secs = (len(body) - 44) / 32000
        clip = robot.speak(secs)
        out = json.dumps({"ok": True, "id": clip, "seconds": secs}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


threading.Thread(target=ThreadingHTTPServer(("127.0.0.1", HTTP), H).serve_forever, daemon=True).start()
hub = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "stackchan_hub.py"),
                        "--host", "127.0.0.1", "--rt-port", str(RT), "--http-port", str(HTTP), "--port", str(API)],
                       stdout=subprocess.DEVNULL)
sc = StackChan(f"http://127.0.0.1:{API}")
fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS " if cond else "FAIL ") + name, detail)
    fails += 0 if cond else 1


try:
    for _ in range(50):
        time.sleep(0.1)
        try:
            if sc.status().get("link_up"):
                break
        except Exception:
            pass
    st = sc.status()
    check("link comes up", st.get("link_up"), f"state age {st.get('state_age_ms')} ms")

    # reliable commands survive 20% loss, and run exactly once
    before = len(robot.executed)
    for i in range(30):
        sc.face("happy", text=f"n{i}")
    faces = [d for d in robot.executed[before:] if d.get("cmd") == "face"]
    st = sc.status()
    check("30 face commands each executed exactly once", len(faces) == 30 and len({d["text"] for d in faces}) == 30,
          f"executed {len(faces)}, retries {st['retries']}, lost {st['lost']}, rtt {st['rtt_ms']} ms")

    # head with wait returns when the reported angle gets there
    t = time.time()
    r = sc.head(30, 60, wait=True)
    check("head wait reaches target", r.get("reached") is True, f"{time.time() - t:.2f}s")

    # look is streamed and coalesced
    before = len(robot.executed)
    t = time.time()
    for i in range(200):
        sc.cmd("look", yaw=i % 40, pitch=50)
    time.sleep(0.2)
    looks = [d for d in robot.executed[before:] if d.get("cmd") == "head" and d.get("sync") is False]
    rate = len(looks) / (time.time() - t)
    check("look coalesced to <= ~30 Hz", 0 < rate <= 35, f"{len(looks)} sent, {rate:.0f}/s")

    # drive is refreshed in short chunks and stops
    before = len(robot.executed)
    t = time.time()
    sc.drive(y=40, ms=1000, wait=True)
    took = time.time() - t
    time.sleep(0.4)
    drives = [d for d in robot.executed[before:] if d.get("cmd") == "drive"]
    check("drive refreshed in <=400 ms chunks for ~1 s", len(drives) >= 4 and all(d["ms"] <= 400 for d in drives)
          and 0.9 < took < 1.4, f"{len(drives)} packets (with 20% loss), took {took:.2f}s")
    after = [d for d in robot.executed[before + len(drives):] if d.get("cmd") == "drive"]
    check("no drive packets after it ended", not after)

    # say waits for speech_end of its own clip
    t = time.time()
    r = sc.say("テストです", balloon=False)
    took = time.time() - t
    check("say waits for speech_end", r.get("finished") is True and took >= r["seconds"], f"{r['seconds']:.2f}s audio, returned after {took:.2f}s")

    # wait for a button event
    threading.Timer(0.5, robot.event, args=("button_b",)).start()
    t = time.time()
    r = sc.wait("button_b", timeout=5)
    check("wait button_b", r.get("ok") and 0.4 < time.time() - t < 1.5, f"{time.time() - t:.2f}s")

    # stop cancels a running drive
    sc.drive(x=30, ms=5000)
    time.sleep(0.3)
    sc.stop()
    time.sleep(0.4)
    n = len(robot.executed)
    time.sleep(0.5)
    late = [d for d in robot.executed[n:] if d.get("cmd") == "drive"]
    check("stop cancels drive refresh", not late and not sc.status()["driving"])

    # Grid motion is dead reckoning. Fast calibration keeps this section short.
    # Restore the on-disk guesses afterwards: grid_cal writes stackchan_grid.json.
    cal_path = os.path.join(os.path.dirname(__file__), "stackchan_grid.json")
    with open(cal_path, encoding="utf-8") as cal_file:
        cal_backup = cal_file.read()
    try:
        r = sc.grid_set(4, 5, "N")
        pose = r.get("pose") or {}
        check("grid_set declares the pose",
              r.get("ok") and (pose.get("col"), pose.get("row"), pose.get("heading")) == (4, 5, "N")
              and pose.get("uncertain") is False, str(pose))
        sc.grid_cal(speed=40, fwd_ms_per_cell=150, strafe_ms_per_cell=200,
                    start_ms=50, settle_ms=30, turn_ms_per_90=80, rot_sign=1)
        before = len(robot.executed)
        started = time.time()
        r = sc.grid_move(2, 3, wait=True)
        took = time.time() - started
        expect = ((50 + 2 * 200) + (50 + 2 * 150) + 2 * 30) / 1000.0
        kinds = []
        for packet in robot.executed[before:]:
            if packet.get("cmd") != "drive":
                continue
            x, y = packet.get("x", 0), packet.get("y", 0)
            if x < 0 and y == 0:
                kinds.append("strafe")
            elif y > 0 and x == 0:
                kinds.append("forward")
        pose = r.get("pose") or {}
        check("grid_move strafes left then drives forward",
              "strafe" in kinds and "forward" in kinds and kinds.index("strafe") < kinds.index("forward")
              and abs(took - expect) <= 0.2
              and (pose.get("col"), pose.get("row"), pose.get("heading")) == (2, 3, "N")
              and pose.get("uncertain") is False,
              f"took {took:.3f}s expect {expect:.3f}s pose {pose} moves {kinds}")

        sc.grid_set(4, 5, "N")
        before = len(robot.executed)
        r = sc.catch(4, 3, wait=True)
        grips = [packet.get("percent") for packet in robot.executed[before:] if packet.get("cmd") == "grip"]
        pose = r.get("pose") or {}
        check("catch opens then closes and stays on the approach cell",
              grips and grips[0] == 0 and grips[-1] == 100
              and (pose.get("col"), pose.get("row"), pose.get("heading")) == (4, 4, "N")
              and pose.get("uncertain") is False,
              f"grips {grips} pose {pose}")

        sc.grid_cal(fwd_ms_per_cell=1500, start_ms=40, settle_ms=20)
        sc.grid_set(4, 5, "N")
        sc.grid_move(4, 1, wait=False)
        time.sleep(0.25)
        sc.stop()
        time.sleep(0.3)
        pose = sc.grid_status().get("pose") or {}
        check("stop during grid_move marks the pose uncertain", pose.get("uncertain") is True, str(pose))
    finally:
        with open(cal_path, "w", encoding="utf-8") as cal_file:
            cal_file.write(cal_backup)

    # link loss is detected and commands are refused
    robot.telemetry = False
    time.sleep(2.0)
    st = sc.status()
    r = StackChan(f"http://127.0.0.1:{API}", raise_errors=False).face("sad")
    check("link down detected, commands refused", not st["link_up"] and r.get("error") == "robot offline")
    robot.telemetry = True
    time.sleep(0.5)
    check("link recovers", sc.status()["link_up"])
finally:
    hub.terminate()
    hub.wait(5)
print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
