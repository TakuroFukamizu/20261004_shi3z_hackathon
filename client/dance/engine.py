"""Pre-programmed dance runner: plays a song and sends beat-timed commands to the robot.

Fallback for when the live music analysis is not ready. Each song script defines its
BPM and an 8-count choreography (the same move names as stackchan-dance-controller.html);
this module repeats it over the length of the WAV file, getting stronger every 8 counts.

Commands go to the Core2 over HTTP (head/face directly, drive/grip forwarded to the rover).
Wheel moves are paired so the robot ends up where it started. Ctrl-C always stops the
robot and returns the head to centre.
"""
import argparse
import http.client
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field

K_BY_LOOP = [0.7, 0.85, 1.0, 1.0]  # intensity of each 8-count round
STALE_S = 0.35  # drop head/drive commands that are this late (they would look like jitter)


# --------------------------------------------------------------------------- score

@dataclass(order=True)
class Event:
    t: float                       # beats from the start of the song
    seq: int
    kind: str = field(compare=False)   # head | face | drive | grip | mark
    args: dict = field(compare=False, default_factory=dict)


class Score:
    def __init__(self, bpm):
        self.bpm = bpm
        self.beat = 60.0 / bpm
        self.k = 1.0       # intensity of the current 8-count round
        self.loop = 0      # which 8-count round we are in
        self.events = []
        self._seq = 0
        # head spring speed: slower songs get softer moves
        self.speed = int(min(900, max(300, 450 + (bpm - 85) * 350 / 55)))

    def _add(self, t, kind, **args):
        self._seq += 1
        self.events.append(Event(t, self._seq, kind, args))

    def head(self, c, yaw=0.0, pitch=45.0, fast=1.0):
        """yaw: + is left (deg, +-120). pitch: 5 (down) .. 85 (up)."""
        yaw = max(-120.0, min(120.0, yaw))
        pitch = max(5.0, min(85.0, pitch))
        speed = int(max(1, min(1000, self.speed * fast)))
        self._add(c, "head", yaw=round(yaw, 1), pitch=round(pitch, 1), speed=speed)

    def face(self, c, expression=None, text=None):
        """text="" clears the speech balloon, None leaves it as is."""
        self._add(c, "face", expression=expression, text=text)

    def drive(self, c, x=0, y=0, rot=0, dur=0.5, scale=True):
        """x: strafe right(+), y: forward(+), rot: turn, -100..100. dur in beats.
        scale=False ignores the round intensity (use for moves that must cancel exactly)."""
        k = self.k if scale else 1.0
        ms = int(max(60, min(5000, dur * self.beat * 1000)))
        self._add(c, "drive", x=int(x * k), y=int(y * k), rot=int(rot * k), ms=ms)

    def grip(self, c, percent):
        """0 = open, 100 = closed."""
        self._add(c, "grip", percent=int(percent))

    def mark(self, c, text):
        self._add(c, "mark", text=text)


def build_score(bpm, beats, moves):
    s = Score(bpm)
    for beat in range(beats):
        s.loop = beat // 8
        s.k = K_BY_LOOP[min(s.loop, len(K_BY_LOOP) - 1)]
        name, fn = moves[beat % 8]
        s.mark(beat, f"{beat + 1:2d}/{beats}  {name}")
        fn(s, float(beat))
    s.events.sort()
    return s


def net_motion(score):
    """Sum of wheel command x duration per axis (unit*seconds). Near zero = ends where it started."""
    n = {"x": 0.0, "y": 0.0, "rot": 0.0}
    for e in score.events:
        if e.kind == "drive":
            for a in n:
                n[a] += e.args[a] * e.args["ms"] / 1000.0
    return n


def to_command(e, power=1.0):
    a = e.args
    if e.kind == "head":
        return {"cmd": "head", "yaw": a["yaw"], "pitch": a["pitch"], "speed": a["speed"]}
    if e.kind == "face":
        return {"cmd": "face", **{k: v for k, v in a.items() if v is not None}}
    if e.kind == "drive":
        clamp = lambda v: int(max(-100, min(100, v * power)))
        return {"cmd": "drive", "x": clamp(a["x"]), "y": clamp(a["y"]), "rot": clamp(a["rot"]), "ms": a["ms"]}
    if e.kind == "grip":
        return {"cmd": "grip", "percent": a["percent"]}
    return None


# --------------------------------------------------------------------------- robot link

class Link:
    """Persistent HTTP connection to the Core2 (one per sender thread)."""

    def __init__(self, host, timeout=3):
        self.timeout = timeout
        name, _, port = host.partition(":")
        try:
            name = socket.gethostbyname(name)  # resolve .local once, not per request
        except OSError:
            pass
        self.host = f"{name}:{port}" if port else name
        self.conn = None

    def close(self):
        if self.conn:
            try:
                self.conn.close()
            except OSError:
                pass
        self.conn = None

    def request(self, method, path, body=None, ctype="application/json"):
        for attempt in (0, 1):
            try:
                if not self.conn:
                    self.conn = http.client.HTTPConnection(self.host, timeout=self.timeout)
                self.conn.request(method, path, body=body, headers={"Content-Type": ctype} if body else {})
                data = self.conn.getresponse().read()
                return json.loads(data or b"{}")
            except (OSError, http.client.HTTPException, ValueError):
                self.close()
        return None

    def cmd(self, d):
        return self.request("POST", "/cmd", json.dumps(d).encode())

    def status(self):
        return self.request("GET", "/status")


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.sent = self.failed = self.dropped = 0
        self.late = []
        self.errors = {}

    def ok(self, late):
        with self.lock:
            self.sent += 1
            self.late.append(late)

    def fail(self, cmd, msg):
        with self.lock:
            self.failed += 1
            key = f"{cmd}: {msg}"
            self.errors[key] = self.errors.get(key, 0) + 1

    def drop(self):
        with self.lock:
            self.dropped += 1


def worker(q, link, stats):
    while True:
        item = q.get()
        if item is None:
            return
        due, cmd = item
        late = time.perf_counter() - due
        if late > STALE_S and cmd["cmd"] in ("head", "drive"):
            stats.drop()
            continue
        res = link.cmd(cmd)
        if res is None:
            stats.fail(cmd["cmd"], "no response")
        elif not res.get("ok"):
            stats.fail(cmd["cmd"], res.get("error", "error"))
        else:
            stats.ok(late)


# --------------------------------------------------------------------------- helpers

def find_res():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.environ.get("DANCE_RES"), os.path.join(here, "..", "..", "res")]
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=here,
                                capture_output=True, text=True, check=True).stdout.strip()
        cands.append(os.path.join(os.path.dirname(common), "res"))  # main checkout's res/ from a worktree
    except (OSError, subprocess.CalledProcessError):
        pass
    for c in cands:
        if c and os.path.isdir(c):
            return os.path.abspath(c)
    return None


def wav_seconds(path):
    with wave.open(path, "rb") as w:
        return w.getnframes() / w.getframerate()


def print_timeline(score, power):
    for e in score.events:
        if e.kind == "mark":
            print(f"\n[{e.t * score.beat:6.2f}s  beat {e.t:5.2f}] {e.args['text']}")
        else:
            print(f"   {e.t * score.beat:6.2f}s  {to_command(e, power)}")
    n = net_motion(score)
    print(f"\nnet wheel motion (unit*s, ~0 = returns to start): x={n['x']:.1f} y={n['y']:.1f} rot={n['rot']:.1f}")


# --------------------------------------------------------------------------- main

def main(title, wav_name, bpm, moves):
    ap = argparse.ArgumentParser(description=f"{title}: dance to {wav_name} ({bpm} BPM)")
    ap.add_argument("--host", default=os.environ.get("ROBOT_HOST") or "stackchan.local")
    ap.add_argument("--wav", help="path to the song (default: res/%s)" % wav_name)
    ap.add_argument("--dry-run", action="store_true", help="print the timeline, send nothing, play nothing")
    ap.add_argument("--wait", action="store_true", help="wait for Enter before starting")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds to wait before starting")
    ap.add_argument("--no-audio", action="store_true", help="do not play the song (play it elsewhere)")
    ap.add_argument("--robot-audio", action="store_true", help="play the song on the robot's speaker instead of the Mac")
    ap.add_argument("--audio-latency", type=float, default=0.2, help="seconds from launching afplay to sound (default 0.2)")
    ap.add_argument("--lead-ms", type=float, default=60, help="send commands this early to absorb latency (default 60)")
    ap.add_argument("--power", type=float, default=1.0, help="wheel strength multiplier (default 1.0)")
    ap.add_argument("--no-drive", action="store_true", help="head and face only")
    ap.add_argument("--no-grip", action="store_true")
    ap.add_argument("--no-head", action="store_true")
    a = ap.parse_args()

    wav = a.wav
    if not wav:
        res = find_res()
        wav = os.path.join(res, wav_name) if res else wav_name
    if not os.path.isfile(wav):
        sys.exit(f"song not found: {wav}  (use --wav PATH or set DANCE_RES)")
    dur = wav_seconds(wav)
    beats = round(dur * bpm / 60)
    if abs(beats * 60 / bpm - dur) > 0.25:
        print(f"warning: {dur:.2f}s is not a whole number of beats at {bpm} BPM; using {beats} beats")
    score = build_score(bpm, beats, moves)
    skip = set()
    if a.no_drive: skip.add("drive")
    if a.no_grip: skip.add("grip")
    if a.no_head: skip.add("head")
    events = [e for e in score.events if e.kind not in skip]

    print(f"{title}: {bpm} BPM, {dur:.2f}s, {beats} beats, {beats // 8} rounds of 8 counts")
    if a.dry_run:
        print_timeline(score, a.power)
        return 0

    link = Link(a.host)
    st = link.status()
    if not st:
        sys.exit(f"cannot reach robot at {a.host}")
    print(f"robot: battery {st.get('battery')}%, rover {st.get('rover_link', st.get('rover'))}, "
          f"head calibrated {st.get('head_calibrated')}")
    if not st.get("head_calibrated") and "head" not in skip:
        print("warning: head not calibrated, head moves will fail. Run: robot.py calibrate --default")
    if not st.get("rover") and not ({"drive", "grip"} <= skip):
        print("warning: rover not linked, wheel and gripper moves will fail")

    qa, qb = queue.Queue(), queue.Queue()   # head/face | drive/grip
    stats = Stats()
    threads = [threading.Thread(target=worker, args=(q, Link(a.host), stats), daemon=True) for q in (qa, qb)]
    for t in threads:
        t.start()

    player = None
    tmp = None
    try:
        link.cmd({"cmd": "face", "expression": "neutral", "text": ""})
        if not a.no_head:
            link.cmd({"cmd": "head", "yaw": 0, "pitch": 45, "speed": 500})
        if a.wait:
            input("Enter to start > ")
        if a.delay > 0:
            time.sleep(a.delay)

        if a.robot_audio:
            tmp = tempfile.mkdtemp()
            small = os.path.join(tmp, "song16k.wav")
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", wav, small], check=True)
            data = open(small, "rb").read()
            res = link.request("POST", "/speak", data, "audio/wav")
            if not res or not res.get("ok"):
                sys.exit(f"robot refused the audio: {res}")
            t0 = time.perf_counter()
        elif a.no_audio:
            t0 = time.perf_counter()
        else:
            if not shutil.which("afplay"):
                sys.exit("afplay not found (use --no-audio or --robot-audio)")
            player = subprocess.Popen(["afplay", wav])
            t0 = time.perf_counter() + a.audio_latency
        lead = a.lead_ms / 1000.0

        for e in events:
            due = t0 + e.t * score.beat
            wait = due - lead - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
            if e.kind == "mark":
                print(f"{time.perf_counter() - t0:6.2f}s  {e.args['text']}")
                continue
            (qb if e.kind in ("drive", "grip") else qa).put((due - lead, to_command(e, a.power)))
        wait = t0 + dur - time.perf_counter()
        if wait > 0:
            time.sleep(wait)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        for q in (qa, qb):
            q.put(None)
        for t in threads:
            t.join(timeout=1.5)
        if player and player.poll() is None:
            player.terminate()
        end = Link(a.host)
        end.cmd({"cmd": "stop"})
        if not a.no_head:
            end.cmd({"cmd": "head", "yaw": 0, "pitch": 45, "speed": 500})
        if not a.no_grip:
            end.cmd({"cmd": "grip", "percent": 0})
        end.cmd({"cmd": "face", "expression": "happy", "text": ""})
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)

    late = sorted(stats.late)
    med = late[len(late) // 2] * 1000 if late else 0
    print(f"done: sent {stats.sent}, failed {stats.failed}, dropped {stats.dropped}, median lateness {med:.0f} ms")
    for k, v in stats.errors.items():
        print(f"  {v}x {k}")
    return 0 if not stats.failed else 1
