"""Tests for toio_protocol, toio_field and the toio.py client. Run: cd client && python3 -m unittest test_toio -v"""
import unittest

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


if __name__ == "__main__":
    unittest.main()
