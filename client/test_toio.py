"""Tests for toio_protocol, toio_field and the toio.py client. Run: cd client && python3 -m unittest test_toio -v"""
import unittest

import toio_protocol as P


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


if __name__ == "__main__":
    unittest.main()
