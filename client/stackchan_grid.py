"""Dead reckoning on the 7×5 toio mat for StackChan's mecanum base.

No network and no clock. The hub turns these segments into wheel commands.
Column 1 is on the left, row 1 is at the top, the same grid as the cubes.
Heading N faces row 1, E faces column 7, S faces row 5, W faces column 1.

Hub wheel frame: x > 0 strafes right, y > 0 drives forward, rot > 0 turns
left (counter-clockwise). `rot_sign` flips only the rot value on the wire.

The numbers in stackchan_grid.json are guesses. Calibrate them on the mat
(client/stackchan.py grid test / grid cal) before trusting a chase.
"""
import json
from dataclasses import dataclass
from pathlib import Path

COLS, ROWS = 7, 5
HEADINGS = ("N", "E", "S", "W")
# One cell of travel. North decreases the row.
WORLD = {"N": (0, -1), "E": (1, 0), "S": (0, 1), "W": (-1, 0)}
RIGHT = {"N": "E", "E": "S", "S": "W", "W": "N"}
OPP = {"N": "S", "S": "N", "E": "W", "W": "E"}

CAL_PATH = Path(__file__).with_name("stackchan_grid.json")
CAL_FIELDS = (
    "speed",
    "fwd_ms_per_cell",
    "strafe_ms_per_cell",
    "start_ms",
    "turn_ms_per_90",
    "settle_ms",
    "rot_sign",
)


@dataclass
class Pose:
    col: int
    row: int
    heading: str
    uncertain: bool = False


@dataclass
class Calibration:
    """Wheel timing. Defaults match stackchan_grid.json and are on-site guesses:
    speed is the wheel value, fwd/strafe/turn are milliseconds, start_ms is added
    once per straight leg for acceleration, rot_sign is +1 or -1.
    """
    speed: int = 50
    fwd_ms_per_cell: int = 700
    strafe_ms_per_cell: int = 900
    start_ms: int = 80
    turn_ms_per_90: int = 650
    settle_ms: int = 150
    rot_sign: int = 1


@dataclass
class Segment:
    """One continuous wheel command. `pose` is the pose after the whole segment.

    cells is how many grid cells (or 90° steps) the segment covers.
    turn_sign is +1 counter-clockwise, -1 clockwise, 0 when translating.
    world_dir is N/E/S/W while translating, empty while turning.
    """
    x: int
    y: int
    rot: int
    ms: int
    pose: Pose
    cells: int
    turn_sign: int
    world_dir: str


def clamp_cell(col, row):
    return max(1, min(COLS, int(col))), max(1, min(ROWS, int(row)))


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def wheels(heading, world_dir, speed):
    """Robot-frame (x, y) that translates toward world_dir without rotating.

    Heading N moving E is a right strafe (x = +speed). Heading E moving N is a
    left strafe (x = -speed). Moving the way the robot faces is y = +speed.
    """
    forward = WORLD[heading]
    right = WORLD[RIGHT[heading]]
    move = WORLD[world_dir]
    return int(speed * _dot(move, right)), int(speed * _dot(move, forward))


def _longitudinal(heading, world_dir):
    return world_dir == heading or world_dir == OPP[heading]


def _leg(pose, world_dir, cells, cal):
    x, y = wheels(pose.heading, world_dir, cal.speed)
    per = cal.fwd_ms_per_cell if _longitudinal(pose.heading, world_dir) else cal.strafe_ms_per_cell
    dc, dr = WORLD[world_dir]
    end = Pose(pose.col + dc * cells, pose.row + dr * cells, pose.heading)
    return Segment(x, y, 0, cal.start_ms + cells * per, end, cells, 0, world_dir)


def plan_move(pose, col, row, cal):
    """Manhattan path: the whole horizontal leg, then the whole vertical leg.

    Each leg is one segment. ms = start_ms + cells * (forward or strafe time).
    The target is clamped onto the mat. The heading does not change.
    """
    col, row = clamp_cell(col, row)
    segments = []
    cur = pose
    if col != cur.col:
        direction = "E" if col > cur.col else "W"
        segments.append(_leg(cur, direction, abs(col - cur.col), cal))
        cur = segments[-1].pose
    if row != cur.row:
        direction = "S" if row > cur.row else "N"
        segments.append(_leg(cur, direction, abs(row - cur.row), cal))
    return segments


def _cw_delta(src, dst):
    return (HEADINGS.index(dst) - HEADINGS.index(src)) % 4


def plan_turn(pose, heading, cal):
    """Shortest rotation, as one segment of 90° steps.

    A half turn is sent counter-clockwise (rot > 0 when rot_sign is +1).
    n of 0 (already facing heading) yields no segment.
    """
    heading = str(heading).upper()
    if heading not in HEADINGS:
        raise ValueError(f"unknown heading {heading!r}")
    delta = _cw_delta(pose.heading, heading)
    if delta == 0:
        return []
    if delta == 3:
        sign, steps = 1, 1
    elif delta == 2:
        sign, steps = 1, 2
    else:
        sign, steps = -1, 1
    rot = int(sign * cal.rot_sign * cal.speed)
    end = Pose(pose.col, pose.row, heading)
    return [Segment(0, 0, rot, cal.turn_ms_per_90 * steps, end, steps, sign, "")]


def _turn_steps(src, dst):
    delta = _cw_delta(src, dst)
    return 1 if delta == 3 else delta


def _apply_turn(heading, sign, steps):
    """sign +1 is counter-clockwise (N becomes W)."""
    idx = (HEADINGS.index(heading) - sign * steps) % 4
    return HEADINGS[idx]


def plan_catch(pose, target_col, target_row, cal):
    """Move to the best free neighbour of the target, then face it.

    Cost is Manhattan cells plus the number of 90° turns from the current
    heading. Ties prefer fewer turns, then fewer cells, then N, E, S, W.
    Returns (segments, approach) with approach col/row/heading and the
    clamped target cell.
    """
    target_col, target_row = clamp_cell(target_col, target_row)
    best = None
    for index, direction in enumerate(HEADINGS):
        dc, dr = WORLD[direction]
        col, row = target_col + dc, target_row + dr
        if not (1 <= col <= COLS and 1 <= row <= ROWS):
            continue
        heading = OPP[direction]
        cells = abs(pose.col - col) + abs(pose.row - row)
        turns = _turn_steps(pose.heading, heading)
        rank = (cells + turns, turns, cells, index)
        if best is None or rank < best[0]:
            best = (rank, col, row, heading)
    _, col, row, heading = best
    segments = plan_move(pose, col, row, cal)
    arrived = segments[-1].pose if segments else pose
    segments = segments + plan_turn(arrived, heading, cal)
    approach = {
        "col": col,
        "row": row,
        "heading": heading,
        "target_col": target_col,
        "target_row": target_row,
    }
    return segments, approach


def partial_pose(start, segment, elapsed_ms):
    """Pose after a cancelled segment. Cells (or quarter-turns) are rounded.

    Half a cell rounds away from zero (int(fraction * cells + 0.5)). The result
    is always marked uncertain.
    """
    if segment.ms <= 0:
        frac = 1.0
    else:
        frac = max(0.0, min(1.0, float(elapsed_ms) / float(segment.ms)))
    done = int(frac * segment.cells + 0.5)
    done = max(0, min(segment.cells, done))
    if segment.turn_sign:
        heading = _apply_turn(start.heading, segment.turn_sign, done)
        return Pose(start.col, start.row, heading, True)
    dc, dr = WORLD[segment.world_dir]
    col, row = clamp_cell(start.col + dc * done, start.row + dr * done)
    return Pose(col, row, start.heading, True)


def resolve_heading(pose, spec):
    """N/E/S/W, or left (90° CCW), right (90° CW), around (180°)."""
    text = str(spec).strip()
    upper = text.upper()
    if upper in HEADINGS:
        return upper
    low = text.lower()
    idx = HEADINGS.index(pose.heading)
    if low == "left":
        return HEADINGS[(idx - 1) % 4]
    if low == "right":
        return HEADINGS[(idx + 1) % 4]
    if low == "around":
        return HEADINGS[(idx + 2) % 4]
    raise ValueError(f"unknown heading {spec!r}")


def step_target(pose, direction, cells=1):
    """Cell reached by `cells` steps. World letters, or forward/back/left/right."""
    cells = max(0, int(cells))
    text = str(direction).strip()
    if text.upper() in WORLD:
        dc, dr = WORLD[text.upper()]
    else:
        low = text.lower()
        if low in ("forward", "fwd"):
            dc, dr = WORLD[pose.heading]
        elif low in ("back", "backward"):
            dc, dr = WORLD[OPP[pose.heading]]
        elif low == "left":
            dc, dr = WORLD[resolve_heading(pose, "left")]
        elif low == "right":
            dc, dr = WORLD[resolve_heading(pose, "right")]
        else:
            raise ValueError(f"unknown direction {direction!r}")
    return pose.col + dc * cells, pose.row + dr * cells


def calibration_dict(cal):
    return {name: getattr(cal, name) for name in CAL_FIELDS}


def apply_calibration(cal, updates):
    data = calibration_dict(cal)
    for key, value in updates.items():
        if key not in data:
            raise ValueError(f"unknown calibration field {key!r}")
        value = int(value)
        if key == "rot_sign" and value not in (1, -1):
            raise ValueError("rot_sign must be 1 or -1")
        data[key] = value
    return Calibration(**data)


def load_calibration(path=None):
    file = Path(path) if path else CAL_PATH
    if not file.exists():
        return Calibration()
    raw = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{file} must be a JSON object")
    return apply_calibration(Calibration(), raw)


def save_calibration(cal, path=None):
    file = Path(path) if path else CAL_PATH
    text = json.dumps(calibration_dict(cal), indent=2) + "\n"
    file.write_text(text, encoding="utf-8")
