#!/usr/bin/env python3
"""Tiny client for the toio hub. Standard library only, same shape as StackChan.

  from toio_client import Toio
  toio = Toio(raise_errors=False)
  toio.move_all([{"id": 1, "col": 4, "row": 3}], wait=True)
"""
import json
import os
import urllib.error
import urllib.request


class HubError(RuntimeError):
    pass


class Toio:
    def __init__(self, url=None, timeout=30, raise_errors=True):
        self.url = (url or os.environ.get("TOIO_HUB") or "http://127.0.0.1:8765").rstrip("/")
        self.timeout = timeout
        self.raise_errors = raise_errors

    def cmd(self, name, **args):
        body = json.dumps({"cmd": name, **{k: v for k, v in args.items() if v is not None}}).encode()
        req = urllib.request.Request(
            self.url + "/cmd", data=body, headers={"Content-Type": "application/json"})
        wait = args.get("timeout") or 0
        try:
            with urllib.request.urlopen(req, timeout=self.timeout + float(wait)) as response:
                res = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                res = json.loads(exc.read() or b'{"ok":false}')
            except json.JSONDecodeError:
                res = {"ok": False, "error": f"http {exc.code}"}
        except OSError as exc:
            res = {"ok": False, "error": f"hub not reachable at {self.url}: {exc}"}
        if self.raise_errors and not res.get("ok"):
            raise HubError(f"{name}: {res.get('error')}")
        return res

    def status(self):
        return self.cmd("status")

    def move(self, id, col=None, row=None, x=None, y=None, angle=None,
             speed=None, timeout=None, wait=None):
        return self.cmd("move", id=id, col=col, row=row, x=x, y=y, angle=angle,
                        speed=speed, timeout=timeout, wait=wait)

    def move_all(self, targets, speed=None, timeout=None, wait=None):
        return self.cmd("move_all", targets=targets, speed=speed, timeout=timeout, wait=wait)

    def drive(self, id, left, right, ms):
        return self.cmd("drive", id=id, left=left, right=right, ms=ms)

    def led(self, id, r, g, b, ms=None):
        return self.cmd("led", id=id, r=r, g=g, b=b, ms=ms)

    def sound(self, id, effect):
        return self.cmd("sound", id=id, effect=effect)

    def stop(self, id=None):
        return self.cmd("stop", id=id)
