"""Tests for the hub's command handling. No BLE: cubes get a fake client.
Run: cd client && python3 -m unittest test_toio_hub -v"""
import asyncio
import json
import os
import struct
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request

import toio_protocol as P
from toio_field import Mat
from toio_hub import Cube, Hub, load_config, serve_http, suffix

GRID = dict(x_min=98, y_min=142, x_max=402, y_max=358, cols=7, rows=5)


class FakeClient:
    def __init__(self):
        self.writes = []
        self.fail = False

    async def write_gatt_char(self, char, data, response=None):
        if self.fail:
            raise OSError("link lost")
        self.writes.append((char, bytes(data)))


class HubCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # cube 4 is in the config but never connects
        self.hub = Hub(Mat(**GRID), [(1, "toio-a1B"), (2, "toio-c2D"), (3, "toio-e3F"), (4, "toio-g4H")])
        for cid, cell in ((1, (1, 1)), (2, (2, 1)), (3, (7, 5))):
            cube = self.hub.cubes[cid]
            cube.client = FakeClient()
            cube.connected = True
            self.put(cid, *self.hub.mat.cell_center(*cell))

    def put(self, cid, x, y):
        self.hub.cubes[cid].on_id(None, struct.pack("<B6H", 0x01, x, y, 0, x, y, 0))

    def writes(self, cid):
        return self.hub.cubes[cid].client.writes

    def all_writes(self):
        return [w for c in self.hub.cubes.values() if c.client for w in c.client.writes]

    async def start(self, req):
        """Run a command in the background and let it reach its BLE write."""
        task = asyncio.ensure_future(self.hub.handle(req))
        for _ in range(10):
            await asyncio.sleep(0)
        return task

    def answer(self, cid, code):
        """Deliver the cube's result notification for its most recent move."""
        control_id = [d for ch, d in self.writes(cid) if ch == P.MOTOR and d[0] == 0x03][-1][1]
        self.hub.cubes[cid].on_motor(None, bytes([0x83, control_id, code]))

    async def test_status(self):
        res = await self.hub.handle({"cmd": "status"})
        self.assertTrue(res["ok"])
        self.assertEqual([c["id"] for c in res["cubes"]], [1, 2, 3, 4])
        one = res["cubes"][0]
        self.assertEqual((one["x"], one["y"], one["col"], one["row"]), (120, 164, 1, 1))
        self.assertEqual((one["connected"], one["on_mat"], one["busy"]), (True, True, False))
        self.assertEqual((res["cubes"][3]["connected"], res["cubes"][3]["x"]), (False, None))

    async def test_move_by_cell_reaches(self):
        task = await self.start({"cmd": "move", "id": 1, "col": 4, "row": 3})
        char, data = self.writes(1)[-1]
        self.assertEqual(char, P.MOTOR)
        self.assertEqual(data[7:11], struct.pack("<HH", 250, 250))
        self.assertTrue(self.hub.cubes[1].busy)
        self.answer(1, 0x00)
        self.assertEqual(await task, {"ok": True, "results": {"1": "reached"}})
        self.assertFalse(self.hub.cubes[1].busy)
        self.assertEqual(self.hub.cubes[1].last_result, "reached")

    async def test_move_by_xy_with_angle(self):
        task = await self.start({"cmd": "move", "id": 1, "x": 200, "y": 300, "angle": 90, "speed": 50, "timeout": 5})
        self.assertEqual(self.writes(1)[-1][1], P.move_to(1, 200, 300, 90, 50, 5))
        self.answer(1, 0x00)
        self.assertTrue((await task)["ok"])

    async def test_move_reports_cube_failure(self):
        task = await self.start({"cmd": "move", "id": 1, "col": 4, "row": 3})
        self.answer(1, 0x01)
        res = await task
        self.assertFalse(res["ok"])
        self.assertEqual(res["results"], {"1": "timeout"})
        self.assertIn("cube 1: timeout", res["error"])

    async def test_move_rejects_target_outside_mat(self):
        res = await self.hub.handle({"cmd": "move", "id": 1, "x": 50, "y": 250})
        self.assertFalse(res["ok"])
        self.assertIn("outside the mat", res["error"])
        self.assertEqual(self.all_writes(), [])

    async def test_move_rejects_target_on_another_cube(self):
        res = await self.hub.handle({"cmd": "move", "id": 1, "col": 2, "row": 1})   # cube 2 sits there
        self.assertIn("too close to cube 2", res["error"])
        self.assertEqual(self.all_writes(), [])

    async def test_move_rejects_target_of_a_moving_cube(self):
        task = await self.start({"cmd": "move", "id": 2, "col": 4, "row": 3})
        res = await self.hub.handle({"cmd": "move", "id": 1, "col": 4, "row": 3})
        self.assertIn("too close to the target of cube 2", res["error"])
        self.answer(2, 0x00)
        await task

    async def test_move_rejects_cube_off_mat(self):
        self.hub.cubes[1].on_id(None, bytes([0x03]))
        res = await self.hub.handle({"cmd": "move", "id": 1, "col": 4, "row": 3})
        self.assertIn("cube 1 is not on the mat", res["error"])
        self.assertEqual(self.all_writes(), [])

    async def test_missing_cube(self):
        res = await self.hub.handle({"cmd": "move", "id": 4, "col": 4, "row": 3})
        self.assertIn("cube 4 is not connected", res["error"])
        res = await self.hub.handle({"cmd": "led", "id": 9, "r": 1, "g": 1, "b": 1})
        self.assertIn("no cube 9", res["error"])

    async def test_move_all(self):
        task = await self.start({"cmd": "move_all", "targets": [
            {"id": 1, "col": 3, "row": 3}, {"id": 2, "col": 4, "row": 3}, {"id": 3, "x": 300, "y": 300}]})
        self.answer(1, 0x00)
        self.answer(2, 0x00)
        self.answer(3, 0x02)
        res = await task
        self.assertEqual(res["results"], {"1": "reached", "2": "reached", "3": "off_mat"})
        self.assertFalse(res["ok"])

    async def test_move_all_lets_cubes_swap_places(self):
        # a cube in the same command is not an obstacle at its current position
        task = await self.start({"cmd": "move_all", "targets": [
            {"id": 1, "col": 2, "row": 1}, {"id": 2, "col": 1, "row": 1}]})
        self.answer(1, 0x00)
        self.answer(2, 0x00)
        self.assertTrue((await task)["ok"])

    async def test_move_all_rejects_bad_sets(self):
        cases = [
            ([{"id": 1, "col": 4, "row": 3}, {"id": 1, "col": 5, "row": 3}], "appears twice"),
            ([{"id": 1, "col": 4, "row": 3}, {"id": 2, "col": 4, "row": 3}], "too close together"),
            ([], "non-empty list"),
            ("nope", "non-empty list"),
        ]
        for targets, message in cases:
            res = await self.hub.handle({"cmd": "move_all", "targets": targets})
            self.assertIn(message, res["error"])
        self.assertEqual(self.all_writes(), [])

    async def test_move_without_wait(self):
        res = await self.hub.handle({"cmd": "move", "id": 1, "col": 4, "row": 3, "wait": False})
        self.assertEqual(res, {"ok": True, "started": [1]})
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertTrue((await self.hub.handle({"cmd": "status"}))["cubes"][0]["busy"])
        self.answer(1, 0x00)
        for _ in range(10):
            await asyncio.sleep(0)
        one = (await self.hub.handle({"cmd": "status"}))["cubes"][0]
        self.assertEqual((one["busy"], one["last_result"]), (False, "reached"))

    async def test_move_no_response(self):
        self.addCleanup(setattr, Cube, "GRACE", Cube.GRACE)
        Cube.GRACE = 0
        res = await self.hub.handle({"cmd": "move", "id": 1, "col": 4, "row": 3, "timeout": 1})
        self.assertEqual(res["results"], {"1": "no_response"})
        self.assertIsNone(self.hub.cubes[1].target)

    async def test_disconnect_during_move(self):
        task = await self.start({"cmd": "move", "id": 1, "col": 4, "row": 3})
        self.hub.cubes[1].on_disconnect()
        res = await asyncio.wait_for(task, 1)
        self.assertEqual(res["results"], {"1": "disconnected"})
        self.assertFalse(self.hub.cubes[1].connected)

    async def test_move_write_failure(self):
        self.hub.cubes[1].client.fail = True
        res = await self.hub.handle({"cmd": "move", "id": 1, "col": 4, "row": 3})
        self.assertEqual(res["results"], {"1": "write_failed"})

    async def test_stop_interrupts_moves(self):
        task = await self.start({"cmd": "move", "id": 1, "col": 4, "row": 3})
        res = await self.hub.handle({"cmd": "stop"})
        self.assertEqual(res, {"ok": True, "ids": [1, 2, 3]})
        self.assertEqual((await task)["results"], {"1": "interrupted"})
        for cid in (1, 2, 3):
            self.assertEqual(self.writes(cid)[-1], (P.MOTOR, P.STOP))

    async def test_stop_one(self):
        self.assertEqual(await self.hub.handle({"cmd": "stop", "id": 2}), {"ok": True, "ids": [2]})
        self.assertEqual(self.writes(1), [])

    async def test_drive_led_sound_identify(self):
        res = await self.hub.handle({"cmd": "drive", "id": "all", "left": 50, "right": -50, "ms": 500})
        self.assertEqual(res, {"ok": True, "ids": [1, 2, 3]})     # cube 4 is skipped, not an error
        self.assertEqual(self.writes(3)[-1], (P.MOTOR, P.drive(50, -50, 500)))
        await self.hub.handle({"cmd": "led", "id": 2, "r": 0, "g": 255, "b": 0})
        self.assertEqual(self.writes(2)[-1], (P.LIGHT, P.led(0, 255, 0)))
        await self.hub.handle({"cmd": "sound", "id": 2, "effect": 3})
        self.assertEqual(self.writes(2)[-1], (P.SOUND, P.sound(3)))
        await self.hub.handle({"cmd": "identify", "id": 3})
        self.assertEqual(self.writes(3)[-2:], [(P.LIGHT, P.BLINK), (P.SOUND, P.sound(6))])

    async def test_bad_input_moves_nothing(self):
        bad = [
            "move", None, [1, 2], {}, {"cmd": "fly"}, {"cmd": "_move"},
            {"cmd": "move", "id": "abc", "col": 1, "row": 1},
            {"cmd": "move", "id": 1},
            {"cmd": "move", "id": 1, "col": 9, "row": 1},
            {"cmd": "move", "id": 1, "col": 4, "row": 3, "speed": 500},
            {"cmd": "move", "id": 1, "col": 4, "row": 3, "timeout": 0},
            {"cmd": "move", "id": "all", "col": 4, "row": 3},
            {"cmd": "drive", "id": 1, "left": 50, "right": 50},
            {"cmd": "drive", "id": "all", "left": 50, "right": 50, "ms": 0},
            {"cmd": "led", "id": 1, "r": 300, "g": 0, "b": 0},
            {"cmd": "sound", "id": 1, "effect": "loud"},
            {"cmd": "identify"},
        ]
        for req in bad:
            res = await self.hub.handle(req)
            self.assertFalse(res["ok"], req)
            self.assertTrue(res["error"], req)
        self.assertEqual(self.all_writes(), [])


class FakeBleClient(FakeClient):
    """Stands in for bleak.BleakClient: a cube sitting on cell (4, 3) with 80% battery."""
    made = []

    def __init__(self, device, disconnected_callback=None):
        super().__init__()
        self.device, self.lost = device, disconnected_callback
        FakeBleClient.made.append(self)

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def start_notify(self, char, callback):
        pass

    async def read_gatt_char(self, char):
        return bytes([80]) if char == P.BATTERY else struct.pack("<B6H", 0x01, 250, 250, 0, 250, 250, 0)


class ConnectionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.scans = []     # what each scan returns; an exception is raised instead
        case = self

        class Scanner:
            @staticmethod
            async def discover(timeout, return_adv, service_uuids):
                result = case.scans.pop(0) if case.scans else {}
                if isinstance(result, Exception):
                    raise result
                return result

        FakeBleClient.made = []
        sys.modules["bleak"] = types.SimpleNamespace(BleakScanner=Scanner, BleakClient=FakeBleClient)
        self.addCleanup(sys.modules.pop, "bleak")
        self.addCleanup(setattr, Hub, "RETRY", Hub.RETRY)
        Hub.RETRY = 0.01
        self.hub = Hub(Mat(**GRID), [(1, "toio-a1B")])
        task = asyncio.ensure_future(self.hub.keep_connected())
        self.addCleanup(task.cancel)

    def seen(self, local_name):
        return {"addr": ("device", types.SimpleNamespace(local_name=local_name))}

    async def until(self, condition):
        for _ in range(200):
            if condition():
                return
            await asyncio.sleep(0.01)
        self.fail("condition not reached")

    async def test_connects_by_name_suffix_and_reads_state(self):
        self.scans += [self.seen("toio-zzz"), self.seen("toio Core Cube-a1B")]
        cube = self.hub.cubes[1]
        await self.until(lambda: cube.connected)
        self.assertEqual((cube.battery, cube.on_mat, cube.x, cube.y), (80, True, 250, 250))

    async def test_scan_failure_does_not_kill_the_hub(self):
        self.scans += [OSError("Bluetooth is turned off"), self.seen("toio-a1B")]
        await self.until(lambda: self.hub.cubes[1].connected)

    async def test_reconnects_after_a_drop(self):
        self.scans += [self.seen("toio-a1B")]
        cube = self.hub.cubes[1]
        await self.until(lambda: cube.connected)
        FakeBleClient.made[-1].lost(FakeBleClient.made[-1])
        self.assertFalse(cube.connected)
        self.scans += [self.seen("toio-a1B")]
        await self.until(lambda: cube.connected)
        self.assertEqual(len(FakeBleClient.made), 2)

    async def test_shutdown_stops_and_releases_cubes(self):
        self.scans += [self.seen("toio-a1B")]
        await self.until(lambda: self.hub.cubes[1].connected)
        await self.hub.shutdown()
        self.assertEqual(FakeBleClient.made[-1].writes, [(P.MOTOR, P.STOP), (P.LIGHT, P.LED_OFF)])


class ConfigTest(unittest.TestCase):
    def load(self, raw):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            with open(path, "w") as f:
                json.dump(raw, f)
            return load_config(path)

    def test_load_config(self):
        mat, entries = self.load({"mat": GRID, "cubes": [{"name": "toio-a1B", "id": 2}]})
        self.assertEqual(mat.cell_center(4, 3), (250, 250))
        self.assertEqual(entries, [(2, "toio-a1B")])

    def test_load_config_without_cubes(self):
        self.assertEqual(self.load({"mat": GRID})[1], [])

    def test_load_config_rejects_duplicate_ids(self):
        with self.assertRaises(ValueError):
            self.load({"mat": GRID, "cubes": [{"name": "toio-a1B", "id": 1}, {"name": "toio-c2D", "id": 1}]})

    def test_load_config_rejects_id_out_of_range(self):
        with self.assertRaises(ValueError):
            self.load({"mat": GRID, "cubes": [{"name": "toio-a1B", "id": 10}]})

    def test_shipped_config_is_valid(self):
        mat, entries = load_config(os.path.join(os.path.dirname(os.path.abspath(__file__)), "toio_config.json"))
        self.assertEqual((mat.x_min, mat.y_min, mat.x_max, mat.y_max, mat.cols, mat.rows), (98, 142, 402, 358, 7, 5))

    def test_suffix(self):
        self.assertEqual(suffix("toio-a1B"), "a1B")
        self.assertEqual(suffix("toio Core Cube-a1B"), "a1B")
        self.assertEqual(suffix(None), "")


class HttpTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop = asyncio.get_running_loop()
        server = serve_http(Hub(Mat(**GRID), [(1, "toio-a1B")]), self.loop, 0)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertEqual(server.server_address[0], "127.0.0.1")
        self.url = "http://127.0.0.1:%d" % server.server_address[1]

    async def post(self, path, body):
        def call():
            req = urllib.request.Request(self.url + path, data=body)
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                with e:
                    return e.code, json.loads(e.read())
        return await self.loop.run_in_executor(None, call)

    async def test_http_status(self):
        code, res = await self.post("/cmd", b'{"cmd": "status"}')
        self.assertEqual(code, 200)
        self.assertEqual(res["cubes"][0]["name"], "toio-a1B")

    async def test_http_command_error_is_400(self):
        code, res = await self.post("/cmd", b'{"cmd": "fly"}')
        self.assertEqual((code, res["ok"]), (400, False))

    async def test_http_rejects_invalid_json(self):
        for body in (b"{not json", b"\xff\xfe", b""):
            code, res = await self.post("/cmd", body)
            self.assertEqual((code, res), (400, {"ok": False, "error": "invalid JSON"}))

    async def test_http_unknown_path(self):
        code, res = await self.post("/other", b"{}")
        self.assertEqual((code, res["ok"]), (404, False))


if __name__ == "__main__":
    unittest.main()
