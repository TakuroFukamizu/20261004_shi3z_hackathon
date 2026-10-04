"""Tests for toio_protocol, toio_field and the toio.py client. Run: cd client && python3 -m unittest test_toio -v"""
import contextlib
import io
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import toio
import toio_protocol as P
from toio_field import Mat, check_targets


class ProtocolTest(unittest.TestCase):
    def test_uuids(self):
        self.assertEqual(P.SERVICE, "10b20100-5b3b-4571-9508-cf3efcd7bbae")
        self.assertEqual(P.MOTOR, "10b20102-5b3b-4571-9508-cf3efcd7bbae")
        self.assertEqual(P.CONFIG, "10b201ff-5b3b-4571-9508-cf3efcd7bbae")

    def test_drive_matches_spec_example(self):
        # spec: left forward 100, right backward 20, 100 ms
        self.assertEqual(P.drive(100, -20, 100), bytes.fromhex("02010164020214" "0a"))

    def test_drive_rejects_out_of_range(self):
        for args in ((116, 0, 100), (0, -116, 100), (50, 50, 0), (50, 50, 2551)):
            with self.assertRaises(ValueError):
                P.drive(*args)

    def test_stop_is_zero_speed_on_both_wheels(self):
        self.assertEqual(P.STOP, bytes.fromhex("01010100020100"))

    def test_move_to_matches_spec_example(self):
        # spec: control id 0, timeout 5 s, max speed 80, x 700, y 386, angle 90
        self.assertEqual(P.move_to(0, 700, 386, angle=90, speed=80, timeout=5),
                         bytes.fromhex("03000500500000" "bc02" "8201" "5a00"))

    def test_move_to_without_angle_does_not_rotate(self):
        data = P.move_to(7, 250, 250)
        self.assertEqual(data[1], 7)
        self.assertEqual(data[-2:], bytes.fromhex("00a0"))  # 0x05 << 13: no angle, no final turn

    def test_move_to_rejects_out_of_range(self):
        for kwargs in ({"speed": 9}, {"speed": 116}, {"timeout": 0}, {"timeout": 256}):
            with self.assertRaises(ValueError):
                P.move_to(0, 250, 250, **kwargs)
        with self.assertRaises(ValueError):
            P.move_to(0, -1, 250)

    def test_led_matches_spec_example(self):
        self.assertEqual(P.led(255, 0, 0, ms=160), bytes.fromhex("03100101ff0000"))
        self.assertEqual(P.led(0, 255, 0)[1], 0)  # 0 = stay on
        with self.assertRaises(ValueError):
            P.led(256, 0, 0)

    def test_sound(self):
        self.assertEqual(P.sound(4), bytes.fromhex("0204ff"))
        with self.assertRaises(ValueError):
            P.sound(11)

    def test_parse_id_matches_spec_example(self):
        data = bytes.fromhex("01" "c502" "7f01" "3201" "bc02" "8201" "3201")
        self.assertEqual(P.parse_id(data), {"on_mat": True, "x": 709, "y": 383, "angle": 306})

    def test_parse_id_off_mat(self):
        self.assertEqual(P.parse_id(bytes([0x03])), {"on_mat": False})
        self.assertEqual(P.parse_id(bytes.fromhex("02000038001500")), {"on_mat": False})  # on a card
        self.assertIsNone(P.parse_id(b""))
        self.assertIsNone(P.parse_id(bytes([0x01, 0x00])))  # truncated

    def test_parse_move_result(self):
        self.assertEqual(P.parse_move_result(bytes([0x83, 5, 0x00])), (5, "reached"))
        self.assertEqual(P.parse_move_result(bytes([0x83, 5, 0x02])), (5, "off_mat"))
        self.assertEqual(P.parse_move_result(bytes([0x83, 5, 0x63])), (5, "error_0x63"))
        self.assertIsNone(P.parse_move_result(bytes([0x01, 0x00, 0x00])))
        self.assertIsNone(P.parse_move_result(b""))

    def test_parse_version(self):
        self.assertEqual(P.parse_version(bytes([0x81, 0x00]) + b"2.4.0"), "2.4.0")
        self.assertIsNone(P.parse_version(bytes([0x98, 0x00, 0x00])))


GRID = dict(x_min=98, y_min=142, x_max=402, y_max=358, cols=7, rows=5)


class FieldTest(unittest.TestCase):
    def setUp(self):
        self.mat = Mat(**GRID)

    def test_cell_centers(self):
        self.assertEqual(self.mat.cell_center(1, 1), (120, 164))
        self.assertEqual(self.mat.cell_center(4, 3), (250, 250))
        self.assertEqual(self.mat.cell_center(7, 5), (380, 336))

    def test_cell_center_rejects_out_of_grid(self):
        for cell in ((0, 1), (8, 1), (1, 0), (1, 6)):
            with self.assertRaises(ValueError):
                self.mat.cell_center(*cell)

    def test_cell_center_needs_a_grid(self):
        with self.assertRaises(ValueError):
            Mat(98, 142, 402, 358).cell_center(1, 1)

    def test_cell_of(self):
        self.assertEqual(self.mat.cell_of(250, 250), (4, 3))
        self.assertEqual(self.mat.cell_of(98, 142), (1, 1))
        self.assertEqual(self.mat.cell_of(402, 358), (7, 5))   # the far edge belongs to the last cell
        self.assertIsNone(self.mat.cell_of(97, 250))
        self.assertIsNone(Mat(98, 142, 402, 358).cell_of(250, 250))

    def test_every_cell_center_is_inside_the_margin(self):
        for col in range(1, 8):
            for row in range(1, 6):
                self.assertTrue(self.mat.contains(*self.mat.cell_center(col, row)))

    def test_contains_uses_margin(self):
        self.assertTrue(self.mat.contains(113, 157))
        self.assertFalse(self.mat.contains(112, 157))
        self.assertFalse(self.mat.contains(250, 344))

    def test_check_accepts_neighbouring_cells(self):
        targets = {1: self.mat.cell_center(1, 1), 2: self.mat.cell_center(2, 1), 3: self.mat.cell_center(1, 2)}
        self.assertIsNone(check_targets(self.mat, targets))

    def test_check_rejects_target_outside_mat(self):
        self.assertIn("outside the mat", check_targets(self.mat, {3: (50, 250)}))

    def test_check_rejects_targets_too_close_to_each_other(self):
        self.assertIn("cubes 1 and 2", check_targets(self.mat, {1: (250, 250), 2: (270, 250)}))

    def test_check_rejects_target_near_an_obstacle(self):
        err = check_targets(self.mat, {1: (250, 250)}, [("cube 5", 260, 260)])
        self.assertIn("too close to cube 5", err)
        self.assertIsNone(check_targets(self.mat, {1: (250, 250)}, [("cube 5", 285, 250)]))


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.reply = (200, {"ok": True})
        case = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                case.requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                code, body = case.reply
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = toio.main(["--port", str(self.port)] + list(args))
        return code, out.getvalue(), err.getvalue()

    def test_cli_commands(self):
        cases = [
            (["status"], {"cmd": "status"}),
            (["move", "3", "--cell", "4,2"], {"cmd": "move", "id": 3, "col": 4, "row": 2}),
            (["move", "3", "--xy", "250,250", "--angle", "90", "--speed", "50", "--no-wait"],
             {"cmd": "move", "id": 3, "x": 250, "y": 250, "angle": 90, "speed": 50, "wait": False}),
            (["move-all", "1:1,1", "2:2,1"],
             {"cmd": "move_all", "targets": [{"id": 1, "col": 1, "row": 1}, {"id": 2, "col": 2, "row": 1}]}),
            (["move-all", "--xy", "1:120,164", "--timeout", "5"],
             {"cmd": "move_all", "targets": [{"id": 1, "x": 120, "y": 164}], "timeout": 5}),
            (["drive", "all", "--left", "50", "--right", "-50", "--ms", "300"],
             {"cmd": "drive", "id": "all", "left": 50, "right": -50, "ms": 300}),
            (["led", "all", "0", "255", "0"], {"cmd": "led", "id": "all", "r": 0, "g": 255, "b": 0}),
            (["sound", "2", "6"], {"cmd": "sound", "id": 2, "effect": 6}),
            (["identify", "5"], {"cmd": "identify", "id": 5}),
            (["stop"], {"cmd": "stop"}),
            (["stop", "4"], {"cmd": "stop", "id": 4}),
        ]
        for args, expected in cases:
            code, out, _ = self.run_cli(*args)
            self.assertEqual(code, 0, args)
            self.assertEqual(self.requests[-1], expected, args)
            self.assertEqual(json.loads(out), {"ok": True}, args)

    def test_cli_exit_code_follows_hub_error(self):
        self.reply = (400, {"ok": False, "error": "cube 3 is not connected"})
        code, out, _ = self.run_cli("identify", "3")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"], "cube 3 is not connected")

    def test_cli_rejects_bad_arguments_before_sending(self):
        for args in (["move", "3"], ["move", "3", "--cell", "4,2", "--xy", "1,1"],
                     ["move", "3", "--cell", "4"], ["move-all", "1-1,1"], ["led", "x", "0", "0", "0"]):
            with self.assertRaises(SystemExit):
                self.run_cli(*args)
        self.assertEqual(self.requests, [])

    def test_unreachable_hub(self):
        with socket.socket() as s:      # a port nothing listens on
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = toio.main(["--port", str(free_port), "status"])
        self.assertEqual(code, 2)
        self.assertIn("cannot reach the toio hub", err.getvalue())
        self.assertIn("toio_hub.py", err.getvalue())

    def test_library(self):
        t = toio.Toio(port=self.port)
        t.move(3, cell=(4, 2))
        self.assertEqual(self.requests[-1], {"cmd": "move", "id": 3, "col": 4, "row": 2})
        t.move(3, xy=(250, 250), angle=90)
        self.assertEqual(self.requests[-1], {"cmd": "move", "id": 3, "x": 250, "y": 250, "angle": 90})
        t.move_all({1: (1, 1), 2: (2, 1)}, wait=False)
        self.assertEqual(self.requests[-1], {"cmd": "move_all", "wait": False, "targets": [
            {"id": 1, "col": 1, "row": 1}, {"id": 2, "col": 2, "row": 1}]})
        t.stop()
        self.assertEqual(self.requests[-1], {"cmd": "stop"})
        with self.assertRaises(ValueError):
            t.move(3)
        with self.assertRaises(ValueError):
            t.move(3, cell=(1, 1), xy=(120, 164))


if __name__ == "__main__":
    unittest.main()
