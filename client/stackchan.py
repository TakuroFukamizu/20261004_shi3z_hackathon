#!/usr/bin/env python3
"""Client for the StackChan hub (stackchan_hub.py). CLI and library, standard library only.

  python3 client/stackchan.py status
  python3 client/stackchan.py say "こんにちは"            # returns when it has finished speaking
  python3 client/stackchan.py face happy --text "やあ"
  python3 client/stackchan.py look 30 50                  # streamed head target
  python3 client/stackchan.py head 0 45 --wait
  python3 client/stackchan.py drive --y 40 --ms 1000 --wait
  python3 client/stackchan.py wait button_b --timeout 60
  python3 client/stackchan.py grid set 4 5 N             # place the robot, then declare the cell
  python3 client/stackchan.py grid move 2 3
  python3 client/stackchan.py grid test forward 2        # measure one calibration axis
  python3 client/stackchan.py claw open
  python3 client/stackchan.py catch 3 2
  python3 client/stackchan.py monitor                     # live state and events

  from stackchan import StackChan
  sc = StackChan()
  sc.face("happy"); sc.say("こんにちは"); sc.wait("button_b")
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


class HubError(RuntimeError):
    pass


class StackChan:
    def __init__(self, url=None, timeout=60, raise_errors=True):
        self.url = (url or os.environ.get("STACKCHAN_HUB") or "http://127.0.0.1:8766").rstrip("/")
        self.timeout = timeout
        self.raise_errors = raise_errors

    def cmd(self, name, **args):
        body = json.dumps({"cmd": name, **{k: v for k, v in args.items() if v is not None}}).encode()
        req = urllib.request.Request(self.url + "/cmd", data=body, headers={"Content-Type": "application/json"})
        wait = args.get("timeout") or 0
        try:
            with urllib.request.urlopen(req, timeout=self.timeout + float(wait)) as r:
                res = json.loads(r.read())
        except urllib.error.HTTPError as e:
            res = json.loads(e.read() or b'{"ok":false,"error":"http error"}')
        except OSError as e:
            res = {"ok": False, "error": f"hub not reachable at {self.url}: {e}"}
        if self.raise_errors and not res.get("ok"):
            raise HubError(f"{name}: {res.get('error')}")
        return res

    def status(self): return self.cmd("status")
    def say(self, text, wait=True, voice=None, balloon=True): return self.cmd("say", text=text, wait=wait, voice=voice, balloon=balloon)
    def play(self, path, wait=True): return self.cmd("play", path=os.path.abspath(path), wait=wait)
    def face(self, expression=None, text=None): return self.cmd("face", expression=expression, text=text)
    def look(self, yaw, pitch=45, speed=700): return self.cmd("look", yaw=yaw, pitch=pitch, speed=speed)
    def head(self, yaw=0, pitch=45, speed=500, wait=False): return self.cmd("head", yaw=yaw, pitch=pitch, speed=speed, wait=wait)
    def drive(self, x=0, y=0, rot=0, ms=500, wait=False): return self.cmd("drive", x=x, y=y, rot=rot, ms=ms, wait=wait)
    def grip(self, percent): return self.cmd("grip", percent=percent)
    def grid_status(self): return self.cmd("grid_status")
    def grid_set(self, col, row, heading): return self.cmd("grid_set", col=col, row=row, heading=heading)
    def grid_move(self, col, row, wait=True): return self.cmd("grid_move", col=col, row=row, wait=wait)
    def grid_step(self, direction, cells=1, wait=True):
        return self.cmd("grid_step", dir=direction, cells=cells, wait=wait)
    def grid_turn(self, heading, wait=True): return self.cmd("grid_turn", heading=heading, wait=wait)
    def claw(self, state=None, percent=None): return self.cmd("claw", state=state, percent=percent)
    def catch(self, col, row, wait=True): return self.cmd("catch", col=col, row=row, wait=wait)
    def grid_cal(self, **fields): return self.cmd("grid_cal", **fields)
    def stop(self): return self.cmd("stop")
    def wait(self, event, timeout=30): return self.cmd("wait", event=event, timeout=timeout)
    def events(self, since=0): return self.cmd("events", since=since)["events"]


def _grid_test(sc, kind, n):
    """Drive N cells or N quarter-turns with the saved calibration and say what to edit.

    This uses raw drive, so the remembered cell does not change.
    """
    st = sc.grid_status()
    if not st.get("ok"):
        return st
    cal = st.get("calibration") or {}
    n = int(n)
    speed = int(cal.get("speed", 50))
    if kind == "forward":
        per = int(cal.get("fwd_ms_per_cell", 700))
        start = int(cal.get("start_ms", 0))
        ms = start + n * per
        print(f"前方に {n} マス分、速度 {speed}、合計 {ms} ms（加速 {start} ms + {per} ms/マス）。")
        print("マスの中心まで届かなければ fwd_ms_per_cell を上げ、行き過ぎなら下げてください。")
        print("例: python3 client/stackchan.py grid cal --fwd-ms-per-cell 650")
        res = sc.drive(y=speed, ms=ms, wait=True)
    elif kind == "strafe":
        per = int(cal.get("strafe_ms_per_cell", 900))
        start = int(cal.get("start_ms", 0))
        ms = start + n * per
        print(f"右へ {n} マス分ストレーフ、速度 {speed}、合計 {ms} ms（加速 {start} ms + {per} ms/マス）。")
        print("届かなければ strafe_ms_per_cell を上げ、行き過ぎなら下げてください。")
        print("例: python3 client/stackchan.py grid cal --strafe-ms-per-cell 800")
        res = sc.drive(x=speed, ms=ms, wait=True)
    else:
        per = int(cal.get("turn_ms_per_90", 650))
        sign = int(cal.get("rot_sign", 1))
        ms = n * per
        print(f"左へ 90 度を {n} 回、1回 {per} ms、rot {sign * speed}、合計 {ms} ms。")
        print("角度が足りなければ turn_ms_per_90 を上げ、回り過ぎなら下げてください。")
        print("逆向きに回るときは rot_sign を 1 か -1 に反転してください。")
        print("例: python3 client/stackchan.py grid cal --turn-ms-per-90 650")
        res = sc.drive(rot=sign * speed, ms=ms, wait=True)
    print("この走行はマス位置を更新しません。ずれたら置き直して grid set してください。")
    return res


def _grid_command(sc, a):
    cmd = a.grid_cmd
    if cmd == "status":
        return sc.grid_status()
    if cmd == "set":
        return sc.grid_set(a.col, a.row, a.heading)
    if cmd == "move":
        return sc.grid_move(a.col, a.row, wait=not a.no_wait)
    if cmd == "step":
        return sc.grid_step(a.dir, a.cells, wait=not a.no_wait)
    if cmd == "turn":
        return sc.grid_turn(a.heading, wait=not a.no_wait)
    if cmd == "test":
        return _grid_test(sc, a.kind, a.n)
    fields = {
        "speed": a.speed,
        "fwd_ms_per_cell": a.fwd_ms_per_cell,
        "strafe_ms_per_cell": a.strafe_ms_per_cell,
        "start_ms": a.start_ms,
        "turn_ms_per_90": a.turn_ms_per_90,
        "settle_ms": a.settle_ms,
        "rot_sign": a.rot_sign,
    }
    return sc.grid_cal(**{key: value for key, value in fields.items() if value is not None})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hub", help="hub URL (default $STACKCHAN_HUB or http://127.0.0.1:8766)")
    sub = p.add_subparsers(dest="c", required=True)
    sub.add_parser("status")
    sub.add_parser("stop")
    sub.add_parser("monitor")
    s = sub.add_parser("say"); s.add_argument("text"); s.add_argument("--voice"); s.add_argument("--no-wait", action="store_true")
    s = sub.add_parser("play"); s.add_argument("wav"); s.add_argument("--no-wait", action="store_true")
    s = sub.add_parser("face"); s.add_argument("expression", nargs="?"); s.add_argument("--text")
    s = sub.add_parser("look"); s.add_argument("yaw", type=float); s.add_argument("pitch", type=float, nargs="?", default=45)
    s = sub.add_parser("head"); s.add_argument("yaw", type=float); s.add_argument("pitch", type=float, nargs="?", default=45)
    s.add_argument("--speed", type=int, default=500); s.add_argument("--wait", action="store_true")
    s = sub.add_parser("drive")
    for ax in ("x", "y", "rot"):
        s.add_argument("--" + ax, type=int, default=0)
    s.add_argument("--ms", type=int, default=500); s.add_argument("--wait", action="store_true")
    s = sub.add_parser("grip"); s.add_argument("percent", type=int)
    s = sub.add_parser("claw"); s.add_argument("state", nargs="?", choices=("open", "close"))
    s.add_argument("--percent", type=int)
    s = sub.add_parser("catch"); s.add_argument("col", type=int); s.add_argument("row", type=int)
    s.add_argument("--no-wait", action="store_true")
    g = sub.add_parser("grid")
    gsub = g.add_subparsers(dest="grid_cmd", required=True)
    gsub.add_parser("status")
    s = gsub.add_parser("set"); s.add_argument("col", type=int); s.add_argument("row", type=int); s.add_argument("heading")
    s = gsub.add_parser("move"); s.add_argument("col", type=int); s.add_argument("row", type=int)
    s.add_argument("--no-wait", action="store_true")
    s = gsub.add_parser("step"); s.add_argument("dir"); s.add_argument("cells", type=int, nargs="?", default=1)
    s.add_argument("--no-wait", action="store_true")
    s = gsub.add_parser("turn"); s.add_argument("heading"); s.add_argument("--no-wait", action="store_true")
    s = gsub.add_parser("cal")
    s.add_argument("--speed", type=int)
    s.add_argument("--fwd-ms-per-cell", type=int)
    s.add_argument("--strafe-ms-per-cell", type=int)
    s.add_argument("--start-ms", type=int)
    s.add_argument("--turn-ms-per-90", type=int)
    s.add_argument("--settle-ms", type=int)
    s.add_argument("--rot-sign", type=int, choices=(-1, 1))
    s = gsub.add_parser("test"); s.add_argument("kind", choices=("forward", "strafe", "turn")); s.add_argument("n", type=int)
    s = sub.add_parser("wait"); s.add_argument("event"); s.add_argument("--timeout", type=float, default=30)
    s = sub.add_parser("raw"); s.add_argument("json")
    a = p.parse_args(argv)
    sc = StackChan(a.hub, raise_errors=False)

    if a.c == "monitor":
        since = sc.status().get("last_event_id", 0)
        try:
            while True:
                st = sc.status()
                for e in sc.cmd("events", since=since).get("events", []):
                    print(f"\nEVENT {e['event']} {e['arg']}")
                    since = e["id"]
                print(f"\rlink={'UP' if st.get('link_up') else 'DOWN'} rtt={st.get('rtt_ms')}ms "
                      f"yaw={st.get('yaw')} pitch={st.get('pitch')} speaking={st.get('speaking')} "
                      f"rover={st.get('rover')} bat={st.get('battery')} rssi={st.get('rssi')}   ", end="", flush=True)
                time.sleep(0.2)
        except KeyboardInterrupt:
            print()
            return 0

    c = a.c
    if c == "say":
        res = sc.say(a.text, wait=not a.no_wait, voice=a.voice)
    elif c == "play":
        res = sc.play(a.wav, wait=not a.no_wait)
    elif c == "face":
        res = sc.face(a.expression, a.text)
    elif c == "look":
        res = sc.look(a.yaw, a.pitch)
    elif c == "head":
        res = sc.head(a.yaw, a.pitch, a.speed, a.wait)
    elif c == "drive":
        res = sc.drive(a.x, a.y, a.rot, a.ms, a.wait)
    elif c == "grip":
        res = sc.grip(a.percent)
    elif c == "claw":
        res = sc.claw(a.state, a.percent)
    elif c == "catch":
        res = sc.catch(a.col, a.row, wait=not a.no_wait)
    elif c == "grid":
        res = _grid_command(sc, a)
    elif c == "wait":
        res = sc.wait(a.event, a.timeout)
    elif c == "raw":
        d = json.loads(a.json)
        res = sc.cmd(d.pop("cmd"), **d)
    else:
        res = sc.cmd(c)
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
