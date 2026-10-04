"""Play a normalized scenario on StackChan and the toio cubes.

Each step runs three tracks at once: face/look/speech, the in-place body
move, and the cubes. The show logs hub errors and keeps going. Ctrl-C stops
both hubs and is re-raised.
"""
import json
import threading
import time

from formations import FORMATIONS, assign, clear_of_robot

LOOK = {
    "center": (0, 45),
    "left": (40, 50),
    "right": (-40, 50),
    "up": (0, 80),
    "down": (0, 15),
    "toio": (0, 20),
}

COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "purple": (160, 0, 255),
    "white": (255, 255, 255),
}
# A different lamp for each cube. Index follows connected-id order.
RAINBOW = (
    (255, 0, 0), (255, 127, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255),
    (0, 128, 255), (0, 0, 255), (160, 0, 255), (255, 0, 180),
)
# Hub effect ids: 0 enter, 2 cancel, 3 cursor, 6-8 get.
SOUNDS = {"ok": 0, "ng": 2, "beep": 3, "cheer": 6}

STEP_TIMEOUT = 40


class _Side:
    """One hub, or a printer when dry_run is set. Never raises."""

    def __init__(self, name, client, dry_run, log):
        self.name = name
        self.client = client
        self.dry_run = dry_run
        self.log = log

    def call(self, cmd, **args):
        shown = {k: v for k, v in args.items() if v is not None}
        if self.dry_run:
            self.log(f"[dry-run] {self.name} {cmd} {json.dumps(shown, ensure_ascii=False)}")
            return {"ok": True, "cubes": _dry_cubes()}
        try:
            res = self.client.cmd(cmd, **args)
        except Exception as exc:  # hub bugs should not kill the show
            self.log(f"{self.name} {cmd} error: {exc}")
            return {"ok": False, "error": str(exc)}
        if not isinstance(res, dict):
            self.log(f"{self.name} {cmd} failed: bad response")
            return {"ok": False, "error": "bad response"}
        if not res.get("ok"):
            self.log(f"{self.name} {cmd} failed: {res.get('error')}")
        return res


def _dry_cubes():
    return [{"id": i, "connected": True} for i in range(1, 10)]


def _pause(seconds, dry_run, log, reason):
    if seconds <= 0:
        return
    if dry_run:
        log(f"[dry-run] wait {seconds:.1f}s ({reason})")
        return
    time.sleep(seconds)


def _ids(cubes, group=None):
    if cubes:
        ids = []
        for cube in cubes:
            if not cube.get("connected", True):
                continue
            try:
                ids.append(int(cube["id"]))
            except (TypeError, ValueError):
                continue
    else:
        ids = list(range(1, 10))
    if group == "odd":
        ids = [i for i in ids if i % 2]
    elif group == "even":
        ids = [i for i in ids if i % 2 == 0]
    return sorted(ids)


def _drive_group(side, group, ids, left, right, ms):
    if group == "all":
        side.call("drive", id="all", left=left, right=right, ms=ms)
    else:
        for cube_id in ids:
            side.call("drive", id=cube_id, left=left, right=right, ms=ms)


def _stackchan_pose(side, dry_run):
    """(col, row, heading). A dry run assumes the south-centre cell, facing north.

    Live, a missing pose means the caller should not guess.
    """
    if dry_run:
        return (4, 5, "N")
    if side is None:
        return None
    res = side.call("grid_status")
    pose = res.get("pose") if isinstance(res, dict) else None
    if not isinstance(pose, dict) or pose.get("col") is None or pose.get("row") is None:
        return None
    heading = str(pose.get("heading") or "N").upper()
    if heading not in ("N", "E", "S", "W"):
        heading = "N"
    try:
        return int(pose["col"]), int(pose["row"]), heading
    except (TypeError, ValueError):
        return None


def _dry_chase_cubes():
    """Home formation, so a dry run still has a nearest cube to catch."""
    return [{"id": index, "connected": True, "col": col, "row": row}
            for index, (col, row) in enumerate(FORMATIONS["home"], start=1)]


def _nearest_cube(cubes, col, row):
    best = None
    for cube in cubes:
        if not cube.get("connected", True):
            continue
        if cube.get("col") is None or cube.get("row") is None:
            continue
        try:
            cube_id = int(cube.get("id", 10**9))
            cube_col, cube_row = int(cube["col"]), int(cube["row"])
        except (TypeError, ValueError):
            continue
        rank = (abs(cube_col - col) + abs(cube_row - row), cube_id)
        if best is None or rank < best[0]:
            best = (rank, cube_col, cube_row)
    if best is None:
        return None
    return best[1], best[2]


def _chase(side, toio_side, dry_run, log):
    pose = _stackchan_pose(side, dry_run)
    if pose is None:
        log("chase skipped: StackChan pose unknown")
        return
    if toio_side is None:
        log("chase skipped: no toio")
        return
    if dry_run:
        cubes = _dry_chase_cubes()
    else:
        res = toio_side.call("status")
        cubes = res.get("cubes") if isinstance(res, dict) else None
        cubes = cubes or []
    target = _nearest_cube(cubes, pose[0], pose[1])
    if target is None:
        log("chase skipped: no cube position")
        return
    side.call("catch", col=target[0], row=target[1], wait=True)


def _body(side, kind, toio_side, dry_run, log):
    """In-place gestures, or a grid chase / grab / return to centre."""
    if kind == "chase":
        _chase(side, toio_side, dry_run, log)
        return
    if kind == "grab":
        side.call("claw", state="close")
        _pause(0.6, dry_run, log, "grab")
        side.call("claw", state="open")
        return
    if kind == "go_center":
        side.call("grid_move", col=4, row=3, wait=True)
        return

    def pulse(x=0, y=0, rot=0, ms=250):
        side.call("drive", x=x, y=y, rot=rot, ms=ms, wait=True)

    def wiggle():
        for x in (40, -40, 40):
            pulse(x=x, ms=250)

    def turn_left():
        pulse(rot=50, ms=600)

    def turn_right():
        pulse(rot=-50, ms=600)

    if kind == "wiggle":
        wiggle()
    elif kind == "turn_left":
        turn_left()
    elif kind == "turn_right":
        turn_right()
    elif kind == "nod":
        pulse(y=40, ms=300)
        pulse(y=-40, ms=300)
    elif kind == "dance":
        wiggle()
        turn_left()
        turn_right()


def _speech(side, step):
    side.call("face", expression=step["face"], text=step["say"] or None)
    yaw, pitch = LOOK.get(step["look"], LOOK["center"])
    side.call("head", yaw=yaw, pitch=pitch, speed=500, wait=False)
    if step["say"]:
        side.call("say", text=step["say"], wait=True)


def _cubes_now(side):
    res = side.call("status")
    cubes = res.get("cubes") if isinstance(res, dict) else None
    return cubes or []


def _color(side, step, ids):
    color = step["toio_color"]
    if color == "none":
        return
    if color == "off":
        side.call("led", id="all", r=0, g=0, b=0)
        return
    if color == "rainbow":
        for index, cube_id in enumerate(ids):
            r, g, b = RAINBOW[index % len(RAINBOW)]
            side.call("led", id=cube_id, r=r, g=g, b=b)
        return
    r, g, b = COLORS[color]
    side.call("led", id="all", r=r, g=g, b=b)


def _toio(side, step, dry_run, log, stackchan_side=None):
    cubes = [] if dry_run else _cubes_now(side)
    everyone = _ids(cubes)
    dancers = _ids(cubes, step["toio_group"])
    _color(side, step, everyone or dancers)
    if step["toio_sound"] != "none":
        side.call("sound", id="all", effect=SOUNDS[step["toio_sound"]])
    move = step["toio_move"]
    if move in FORMATIONS:
        if not dry_run:
            cubes = _cubes_now(side) or cubes
        cells = FORMATIONS[move]
        if dry_run or stackchan_side is not None:
            pose = _stackchan_pose(stackchan_side, dry_run)
            if pose:
                cells = clear_of_robot(cells, *pose)
        mapping = assign(cubes or _dry_cubes(), cells)
        targets = [{"id": cube_id, "col": col, "row": row}
                   for cube_id, (col, row) in sorted(mapping.items())]
        if targets:
            side.call("move_all", targets=targets, timeout=12, wait=True)
    elif move == "spin":
        _drive_group(side, step["toio_group"], dancers, 60, -60, 1500)
        _pause(1.5, dry_run, log, "spin")
    elif move == "wiggle":
        for left, right in ((40, -40), (-40, 40), (40, -40), (-40, 40)):
            _drive_group(side, step["toio_group"], dancers, left, right, 250)
            _pause(0.25, dry_run, log, "wiggle")
    elif move == "wave":
        for index, cube_id in enumerate(dancers):
            if index:
                _pause(0.2, dry_run, log, "wave stagger")
            side.call("drive", id=cube_id, left=60, right=-60, ms=600)
        _pause(0.6, dry_run, log, "wave")


def _guard(label, fn, log):
    try:
        fn()
    except Exception as exc:
        log(f"{label} error: {exc}")


def _join(tracks, log):
    started = time.monotonic()
    for thread in tracks:
        thread.start()
    for thread in tracks:
        left = STEP_TIMEOUT - (time.monotonic() - started)
        if left <= 0:
            log(f"step timed out after {STEP_TIMEOUT}s")
            return
        thread.join(left)
    if any(thread.is_alive() for thread in tracks):
        log(f"step timed out after {STEP_TIMEOUT}s")


def _estop(stackchan, toio, dry_run, log):
    if dry_run:
        log("[dry-run] estop")
        return
    if stackchan is not None:
        _guard("stackchan stop", lambda: stackchan.call("stop"), log)
        _guard("stackchan head", lambda: stackchan.call("head", yaw=0, pitch=45, speed=500, wait=False), log)
    if toio is not None:
        _guard("toio stop", lambda: toio.call("stop"), log)


def _end_pose(stackchan, toio, log):
    if stackchan is not None:
        stackchan.call("face", expression="neutral", text="")
        stackchan.call("head", yaw=0, pitch=45, speed=500, wait=False)
    if toio is not None:
        toio.call("stop")


def _reachable(side, log):
    if side is None:
        return None
    res = side.call("status")
    if res.get("ok"):
        return side
    log(f"warning: {side.name} hub unreachable, skipping that side ({res.get('error')})")
    return None


def run(scenario, stackchan, toio, dry_run=False, log=print):
    """Run every step. `stackchan` and `toio` are hub clients, or None to skip."""
    sc = _Side("stackchan", stackchan, dry_run, log) if stackchan is not None else None
    cubes = _Side("toio", toio, dry_run, log) if toio is not None else None
    if not dry_run:
        sc = _reachable(sc, log)
        cubes = _reachable(cubes, log)
    steps = scenario.get("steps") or []
    try:
        for index, step in enumerate(steps, start=1):
            line = step.get("say") or "（セリフなし）"
            log(f"[{index}/{len(steps)}] {line}  体={step.get('body')} toio={step.get('toio_move')}")
            tracks = []
            if sc is not None:
                tracks.append(threading.Thread(
                    target=_guard, args=("stackchan", lambda s=step: _speech(sc, s), log), daemon=True))
                if step.get("body") not in (None, "none"):
                    tracks.append(threading.Thread(
                        target=_guard,
                        args=("stackchan body", lambda s=step: _body(sc, s["body"], cubes, dry_run, log), log),
                        daemon=True))
            if cubes is not None and _toio_needed(step):
                tracks.append(threading.Thread(
                    target=_guard,
                    args=("toio", lambda s=step: _toio(cubes, s, dry_run, log, sc), log),
                    daemon=True))
            if tracks:
                _join(tracks, log)
            _pause(int(step.get("pause") or 0), dry_run, log, "pause")
        _end_pose(sc, cubes, log)
    except KeyboardInterrupt:
        log("stopping")
        _estop(sc, cubes, dry_run, log)
        raise


def _toio_needed(step):
    return not (
        step.get("toio_move") in (None, "none")
        and step.get("toio_color") in (None, "none")
        and step.get("toio_sound") in (None, "none")
    )
