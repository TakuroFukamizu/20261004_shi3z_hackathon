#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["bleak>=0.21"]
# ///
"""Hub that keeps BLE connections to the toio cubes and takes JSON commands over HTTP.

  uv run client/toio_hub.py --assign     light each cube in turn and give it a number 1-9
  uv run client/toio_hub.py              run the hub (127.0.0.1:8765, POST /cmd)

Talk to it with client/toio.py. Ctrl-C stops every cube and quits.
"""
import asyncio

import toio_protocol as P
from toio_field import check_targets


class CmdError(Exception):
    """A command the hub refuses; the message goes back to the caller."""


class Cube:
    GRACE = 2   # seconds to wait for a move result beyond the cube's own timeout

    def __init__(self, cid, name):
        self.id, self.name = cid, name
        self.client = None          # anything with `async write_gatt_char(uuid, data)`
        self.connected = False
        self.x = self.y = self.angle = None
        self.on_mat = False
        self.battery = None
        self.target = None          # (x, y) of the move in progress
        self.last_result = None
        self._seq = 0
        self._waiters = {}          # control id -> future resolved with the result name
        self._lock = asyncio.Lock()

    @property
    def busy(self):
        return bool(self._waiters)

    async def write(self, char, data):
        async with self._lock:
            await self.client.write_gatt_char(char, data)

    # BLE callbacks
    def on_id(self, _sender, data):
        info = P.parse_id(bytes(data))
        if info is None:
            return
        self.on_mat = info["on_mat"]
        if self.on_mat:
            self.x, self.y, self.angle = info["x"], info["y"], info["angle"]

    def on_motor(self, _sender, data):
        result = P.parse_move_result(bytes(data))
        if result:
            self._finish(*result)

    def on_battery(self, _sender, data):
        if data:
            self.battery = data[0]

    def on_disconnect(self):
        self.connected = False
        self.on_mat = False
        self._finish_all("disconnected")

    def _finish(self, control_id, result):
        fut = self._waiters.get(control_id)
        if fut and not fut.done():
            fut.set_result(result)

    def _finish_all(self, result):
        for control_id in list(self._waiters):
            self._finish(control_id, result)

    async def move(self, x, y, angle=None, speed=80, timeout=10):
        """Send the cube to (x, y) and wait for its answer. Returns a result name, never raises."""
        self._seq = (self._seq + 1) % 256
        control_id = self._seq
        fut = asyncio.get_running_loop().create_future()
        self._waiters[control_id] = fut
        self.target = (x, y)
        try:
            await self.write(P.MOTOR, P.move_to(control_id, x, y, angle, speed, timeout))
            result = await asyncio.wait_for(fut, timeout + self.GRACE)
        except asyncio.TimeoutError:
            result = "no_response"
        except Exception:
            result = "write_failed"
        finally:
            self._waiters.pop(control_id, None)
            if self._seq == control_id:
                self.target = None
        self.last_result = result
        return result

    async def stop(self):
        self._finish_all("interrupted")
        await self.write(P.MOTOR, P.STOP)

    def status(self, mat):
        here = self.connected and self.on_mat
        cell = mat.cell_of(self.x, self.y) if here else None
        return {"id": self.id, "name": self.name, "connected": self.connected, "on_mat": here,
                "x": self.x if here else None, "y": self.y if here else None,
                "angle": self.angle if here else None,
                "col": cell[0] if cell else None, "row": cell[1] if cell else None,
                "battery": self.battery, "busy": self.busy, "last_result": self.last_result}


class Hub:
    def __init__(self, mat, entries):
        self.mat = mat
        self.cubes = {cid: Cube(cid, name) for cid, name in entries}
        self._tasks = set()     # moves started with wait=false

    async def handle(self, req):
        """Run one command. Always returns {"ok": ...}; nothing moves when it returns an error
        raised before the first write."""
        try:
            if not isinstance(req, dict):
                raise CmdError("command must be a JSON object")
            fn = getattr(self, "_cmd_" + str(req.get("cmd")), None)
            if fn is None:
                raise CmdError("unknown cmd: %r" % (req.get("cmd"),))
            return await fn(req)
        except CmdError as e:
            return {"ok": False, "error": str(e)}
        except KeyError as e:
            return {"ok": False, "error": "bad arguments: missing %s" % e}
        except (TypeError, ValueError) as e:
            return {"ok": False, "error": "bad arguments: %s" % e}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def _ready(self, cid):
        cube = self.cubes.get(int(cid))
        if cube is None:
            raise CmdError("no cube %s" % cid)
        if not cube.connected:
            raise CmdError("cube %d is not connected" % cube.id)
        return cube

    def _select(self, cid):
        """One cube by number, or every connected cube for "all"."""
        if cid == "all":
            return [c for _, c in sorted(self.cubes.items()) if c.connected]
        return [self._ready(cid)]

    async def _send(self, cubes, char, data):
        await asyncio.gather(*(c.write(char, data) for c in cubes))
        return {"ok": True, "ids": [c.id for c in cubes]}

    async def _cmd_status(self, req):
        return {"ok": True, "cubes": [c.status(self.mat) for _, c in sorted(self.cubes.items())]}

    async def _cmd_move(self, req):
        return await self._move([req], req)

    async def _cmd_move_all(self, req):
        targets = req["targets"]
        if not isinstance(targets, list) or not targets:
            raise CmdError("targets must be a non-empty list")
        return await self._move(targets, req)

    async def _move(self, items, opts):
        speed, timeout = int(opts.get("speed", 80)), int(opts.get("timeout", 10))
        P.move_to(0, 0, 0, None, speed, timeout)    # raises ValueError on a bad speed or timeout
        plan = {}                                    # cube id -> (x, y, angle)
        for t in items:
            cube = self._ready(t["id"])
            if cube.id in plan:
                raise CmdError("cube %d appears twice" % cube.id)
            if not cube.on_mat:
                raise CmdError("cube %d is not on the mat" % cube.id)
            if "col" in t or "row" in t:
                x, y = self.mat.cell_center(int(t["col"]), int(t["row"]))
            else:
                x, y = int(t["x"]), int(t["y"])
            angle = t.get("angle")
            plan[cube.id] = (x, y, None if angle is None else int(angle))

        obstacles = []
        for cid, c in sorted(self.cubes.items()):
            if cid in plan or not c.connected:
                continue
            if c.on_mat:
                obstacles.append(("cube %d" % cid, c.x, c.y))
            if c.target:
                obstacles.append(("the target of cube %d" % cid, c.target[0], c.target[1]))
        err = check_targets(self.mat, {cid: (x, y) for cid, (x, y, _) in plan.items()}, obstacles)
        if err:
            raise CmdError(err)

        jobs = {cid: self.cubes[cid].move(x, y, angle, speed, timeout) for cid, (x, y, angle) in plan.items()}
        if opts.get("wait", True) is False:
            for coro in jobs.values():
                task = asyncio.ensure_future(coro)
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            return {"ok": True, "started": sorted(jobs)}
        results = dict(zip(jobs, await asyncio.gather(*jobs.values())))
        failed = ["cube %d: %s" % (cid, r) for cid, r in sorted(results.items()) if r != "reached"]
        res = {"ok": not failed, "results": {str(cid): r for cid, r in sorted(results.items())}}
        if failed:
            res["error"] = ", ".join(failed)
        return res

    async def _cmd_drive(self, req):
        data = P.drive(req["left"], req["right"], req["ms"])
        return await self._send(self._select(req["id"]), P.MOTOR, data)

    async def _cmd_led(self, req):
        data = P.led(req["r"], req["g"], req["b"], req.get("ms", 0))
        return await self._send(self._select(req["id"]), P.LIGHT, data)

    async def _cmd_sound(self, req):
        data = P.sound(req["effect"])
        return await self._send(self._select(req["id"]), P.SOUND, data)

    async def _cmd_identify(self, req):
        cube = self._ready(req["id"])
        await cube.write(P.LIGHT, P.BLINK)
        await cube.write(P.SOUND, P.sound(6))
        return {"ok": True, "ids": [cube.id]}

    async def _cmd_stop(self, req):
        cubes = self._select(req.get("id", "all"))
        await asyncio.gather(*(c.stop() for c in cubes))
        return {"ok": True, "ids": [c.id for c in cubes]}
