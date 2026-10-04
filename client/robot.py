#!/usr/bin/env python3
"""PC-side CLI / library for the StackChan + RoverC Pro robot. Standard library only.

  robot.py status
  robot.py say "こんにちは"
  robot.py face happy --text "やあ"
  robot.py head --yaw 30 --pitch 45
  robot.py drive --y 50 --ms 1000
  robot.py grip 100
  robot.py stop

Host: --host, or $ROBOT_HOST, default stackchan.local (192.168.4.1 in access-point mode).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


class Robot:
    def __init__(self, host=None, timeout=10):
        self.base = "http://" + (host or os.environ.get("ROBOT_HOST") or "stackchan.local")
        self.timeout = timeout

    def _post(self, path, data, content_type):
        req = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read() or b'{"ok":false,"error":"http error"}')

    def cmd(self, name, **args):
        args = {k: v for k, v in args.items() if v is not None}
        return self._post("/cmd", json.dumps({"cmd": name, **args}).encode(), "application/json")

    def speak_wav(self, wav_bytes):
        """Play a 16-bit PCM WAV (mono or stereo, up to 2 MB)."""
        return self._post("/speak", wav_bytes, "audio/wav")

    def say(self, text, voice="Kyoko", balloon=True):
        """Synthesize `text` with macOS `say` and play it on the robot."""
        with tempfile.TemporaryDirectory() as d:
            wav = os.path.join(d, "say.wav")
            subprocess.run(["say", "-v", voice, "-o", wav, "--data-format=LEI16@16000", text], check=True)
            data = open(wav, "rb").read()
        if balloon:
            self.cmd("face", text=text)
        return self.speak_wav(data)

    # convenience wrappers
    def status(self): return self.cmd("status")
    def face(self, expression=None, text=None): return self.cmd("face", expression=expression, text=text)
    def head(self, yaw=0, pitch=45, speed=500): return self.cmd("head", yaw=yaw, pitch=pitch, speed=speed)
    def drive(self, x=0, y=0, rot=0, ms=500): return self.cmd("drive", x=x, y=y, rot=rot, ms=ms)
    def grip(self, percent): return self.cmd("grip", percent=percent)
    def stop(self): return self.cmd("stop")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("stop")

    s = sub.add_parser("say", help="speak text (macOS say)")
    s.add_argument("text")
    s.add_argument("--voice", default="Kyoko")
    s.add_argument("--no-balloon", action="store_true")

    s = sub.add_parser("speak", help="play a 16-bit PCM WAV file")
    s.add_argument("wav")

    s = sub.add_parser("face")
    s.add_argument("expression", nargs="?", choices=["neutral", "happy", "angry", "sad", "doubt", "sleepy"])
    s.add_argument("--text")

    s = sub.add_parser("head")
    s.add_argument("--yaw", type=float, default=0)
    s.add_argument("--pitch", type=float, default=45)
    s.add_argument("--speed", type=int, default=500)

    s = sub.add_parser("calibrate", help="store the current head pose as home")
    s.add_argument("--default", action="store_true", help="use factory default zero positions instead")

    s = sub.add_parser("torque")
    s.add_argument("state", choices=["on", "off"])

    s = sub.add_parser("drive")
    s.add_argument("--x", type=int, default=0, help="strafe right, -100..100")
    s.add_argument("--y", type=int, default=0, help="forward, -100..100")
    s.add_argument("--rot", type=int, default=0, help="rotate, -100..100")
    s.add_argument("--ms", type=int, default=500, help="duration, max 5000")

    s = sub.add_parser("grip")
    s.add_argument("percent", type=int, help="0 = open, 100 = closed")

    s = sub.add_parser("servo", help="raw RoverC servo")
    s.add_argument("ch", type=int, choices=[0, 1])
    s.add_argument("angle", type=int)

    s = sub.add_parser("volume")
    s.add_argument("value", type=int)

    sub.add_parser("beep")

    s = sub.add_parser("raw", help="send a raw JSON command")
    s.add_argument("json")

    a = p.parse_args(argv)
    r = Robot(a.host)
    c = a.command
    try:
        if c == "say":
            res = r.say(a.text, a.voice, not a.no_balloon)
        elif c == "speak":
            res = r.speak_wav(open(a.wav, "rb").read())
        elif c == "face":
            res = r.face(a.expression, a.text)
        elif c == "head":
            res = r.head(a.yaw, a.pitch, a.speed)
        elif c == "calibrate":
            res = r.cmd("calibrate", default=a.default)
        elif c == "torque":
            res = r.cmd("torque", on=a.state == "on")
        elif c == "drive":
            res = r.drive(a.x, a.y, a.rot, a.ms)
        elif c == "grip":
            res = r.grip(a.percent)
        elif c == "servo":
            res = r.cmd("servo", ch=a.ch, angle=a.angle)
        elif c == "volume":
            res = r.cmd("volume", value=a.value)
        elif c == "raw":
            res = r._post("/cmd", a.json.encode(), "application/json")
        else:
            res = r.cmd(c)
    except (urllib.error.URLError, OSError) as e:
        print(f"cannot reach robot at {r.base}: {e}", file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
