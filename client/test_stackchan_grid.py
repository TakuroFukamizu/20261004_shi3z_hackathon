#!/usr/bin/env python3
"""Pure tests for StackChan grid planning. No network and no sleep.

  python3 client/test_stackchan_grid.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stackchan_grid import (  # noqa: E402
    Calibration,
    Pose,
    apply_calibration,
    load_calibration,
    partial_pose,
    plan_catch,
    plan_move,
    plan_turn,
    save_calibration,
    step_target,
    wheels,
)

SPEED = 50


def cal(**overrides):
    base = Calibration()
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class WheelFrameTests(unittest.TestCase):
    def test_all_headings(self):
        # (heading, world_dir) -> (x, y). Forward is +y, right strafe is +x.
        expect = {
            ("N", "N"): (0, SPEED),
            ("N", "E"): (SPEED, 0),
            ("N", "S"): (0, -SPEED),
            ("N", "W"): (-SPEED, 0),
            ("E", "N"): (-SPEED, 0),
            ("E", "E"): (0, SPEED),
            ("E", "S"): (SPEED, 0),
            ("E", "W"): (0, -SPEED),
            ("S", "N"): (0, -SPEED),
            ("S", "E"): (-SPEED, 0),
            ("S", "S"): (0, SPEED),
            ("S", "W"): (SPEED, 0),
            ("W", "N"): (SPEED, 0),
            ("W", "E"): (0, -SPEED),
            ("W", "S"): (-SPEED, 0),
            ("W", "W"): (0, SPEED),
        }
        for key, xy in expect.items():
            self.assertEqual(wheels(*key, SPEED), xy, key)


class MoveTests(unittest.TestCase):
    def test_horizontal_then_vertical_from_south_edge(self):
        pose = Pose(4, 5, "N")
        segments = plan_move(pose, 2, 3, cal())
        self.assertEqual(len(segments), 2)
        strafe, forward = segments
        self.assertEqual((strafe.x, strafe.y, strafe.rot), (-SPEED, 0, 0))
        self.assertEqual(strafe.ms, 80 + 2 * 900)
        self.assertEqual(strafe.cells, 2)
        self.assertEqual(strafe.world_dir, "W")
        self.assertEqual((strafe.pose.col, strafe.pose.row, strafe.pose.heading), (2, 5, "N"))
        self.assertEqual((forward.x, forward.y, forward.rot), (0, SPEED, 0))
        self.assertEqual(forward.ms, 80 + 2 * 700)
        self.assertEqual((forward.pose.col, forward.pose.row, forward.pose.heading), (2, 3, "N"))

    def test_backward_uses_forward_timing(self):
        # Facing east, west is straight back, so the forward-cell time applies.
        segments = plan_move(Pose(4, 3, "E"), 2, 3, cal())
        self.assertEqual(len(segments), 1)
        leg = segments[0]
        self.assertEqual((leg.x, leg.y), (0, -SPEED))
        self.assertEqual(leg.ms, 80 + 2 * 700)

    def test_clamp_and_zero_leg_omitted(self):
        segments = plan_move(Pose(4, 5, "N"), 0, 9, cal())
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].world_dir, "W")
        self.assertEqual(segments[0].cells, 3)
        self.assertEqual((segments[0].pose.col, segments[0].pose.row), (1, 5))
        self.assertEqual(plan_move(Pose(1, 1, "E"), 1, 1, cal()), [])

    def test_same_cell_is_empty(self):
        self.assertEqual(plan_move(Pose(3, 2, "S"), 3, 2, cal()), [])


class TurnTests(unittest.TestCase):
    def test_shortest_direction_and_half_turn_is_ccw(self):
        left = plan_turn(Pose(4, 5, "N"), "W", cal())
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0].turn_sign, 1)
        self.assertEqual(left[0].rot, SPEED)
        self.assertEqual(left[0].cells, 1)
        self.assertEqual(left[0].ms, 650)
        self.assertEqual(left[0].pose.heading, "W")

        right = plan_turn(Pose(4, 5, "N"), "E", cal())
        self.assertEqual(right[0].turn_sign, -1)
        self.assertEqual(right[0].rot, -SPEED)
        self.assertEqual(right[0].pose.heading, "E")

        half = plan_turn(Pose(4, 5, "N"), "S", cal())
        self.assertEqual(half[0].turn_sign, 1)
        self.assertEqual(half[0].cells, 2)
        self.assertEqual(half[0].ms, 1300)
        self.assertEqual(half[0].rot, SPEED)
        self.assertEqual(half[0].pose.heading, "S")
        self.assertEqual(plan_turn(Pose(2, 2, "E"), "E", cal()), [])

    def test_rot_sign_flips_the_wire_only(self):
        flipped = cal(rot_sign=-1)
        seg = plan_turn(Pose(1, 1, "N"), "W", flipped)[0]
        self.assertEqual(seg.turn_sign, 1)
        self.assertEqual(seg.rot, -SPEED)
        self.assertEqual(seg.pose.heading, "W")


class PartialTests(unittest.TestCase):
    def test_rounds_half_up_along_the_leg(self):
        pose = Pose(4, 5, "N")
        segment = plan_move(pose, 4, 1, cal())[0]
        self.assertEqual(segment.cells, 4)
        self.assertEqual(partial_pose(pose, segment, 0).row, 5)
        mid = partial_pose(pose, segment, segment.ms / 2)
        self.assertEqual((mid.col, mid.row, mid.heading), (4, 3, "N"))
        self.assertTrue(mid.uncertain)
        done = partial_pose(pose, segment, segment.ms)
        self.assertEqual(done.row, 1)
        self.assertTrue(done.uncertain)

    def test_cancelled_turn_keeps_the_cell(self):
        pose = Pose(3, 3, "N")
        segment = plan_turn(pose, "S", cal())[0]
        half = partial_pose(pose, segment, segment.ms / 2)
        self.assertEqual((half.col, half.row, half.heading), (3, 3, "W"))
        self.assertTrue(half.uncertain)


class CatchTests(unittest.TestCase):
    def test_prefers_the_cell_already_facing_the_target(self):
        segments, approach = plan_catch(Pose(4, 5, "N"), 4, 3, cal())
        self.assertEqual(approach["col"], 4)
        self.assertEqual(approach["row"], 4)
        self.assertEqual(approach["heading"], "N")
        self.assertEqual(approach["target_col"], 4)
        self.assertEqual(approach["target_row"], 3)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].y, SPEED)
        self.assertEqual(segments[0].pose.row, 4)

    def test_corner_target_picks_the_cheaper_turn(self):
        # (1, 2) facing N costs 4 cells and no turn.
        # (2, 1) facing W costs 4 cells and one turn.
        _, approach = plan_catch(Pose(4, 3, "N"), 1, 1, cal())
        self.assertEqual((approach["col"], approach["row"], approach["heading"]), (1, 2, "N"))

    def test_east_edge_prefers_the_shorter_path(self):
        segments, approach = plan_catch(Pose(4, 5, "N"), 7, 5, cal())
        self.assertEqual((approach["col"], approach["row"], approach["heading"]), (6, 5, "E"))
        self.assertEqual(segments[-1].pose.heading, "E")
        self.assertEqual(segments[-1].turn_sign, -1)

    def test_north_edge_drops_the_off_mat_neighbour(self):
        _, approach = plan_catch(Pose(4, 5, "N"), 4, 1, cal())
        self.assertEqual((approach["col"], approach["row"], approach["heading"]), (4, 2, "N"))

    def test_target_outside_the_mat_is_clamped(self):
        _, approach = plan_catch(Pose(4, 3, "S"), 9, 0, cal())
        self.assertEqual((approach["target_col"], approach["target_row"]), (7, 1))

    def test_already_there_adds_no_segment(self):
        segments, approach = plan_catch(Pose(4, 4, "N"), 4, 3, cal())
        self.assertEqual(segments, [])
        self.assertEqual((approach["col"], approach["row"], approach["heading"]), (4, 4, "N"))


class StepTests(unittest.TestCase):
    def test_robot_relative_and_world(self):
        pose = Pose(4, 3, "E")
        self.assertEqual(step_target(pose, "forward", 2), (6, 3))
        self.assertEqual(step_target(pose, "back", 1), (3, 3))
        self.assertEqual(step_target(pose, "left", 1), (4, 2))
        self.assertEqual(step_target(pose, "right", 1), (4, 4))
        self.assertEqual(step_target(pose, "W", 3), (1, 3))


class CalibrationTests(unittest.TestCase):
    def test_shipped_defaults_are_the_guesses(self):
        loaded = load_calibration()
        self.assertEqual(loaded, Calibration())

    def test_save_roundtrip_and_reject_bad_sign(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cal.json")
            updated = apply_calibration(Calibration(), {"fwd_ms_per_cell": 650, "rot_sign": -1})
            save_calibration(updated, path)
            self.assertEqual(load_calibration(path).fwd_ms_per_cell, 650)
            self.assertEqual(load_calibration(path).rot_sign, -1)
        with self.assertRaises(ValueError):
            apply_calibration(Calibration(), {"rot_sign": 2})
        with self.assertRaises(ValueError):
            apply_calibration(Calibration(), {"nope": 1})


if __name__ == "__main__":
    unittest.main()
