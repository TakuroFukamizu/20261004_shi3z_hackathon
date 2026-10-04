#!/usr/bin/env python3
"""Tests for the AI scenario runner. No real robot and no real LLM.

  python3 client/scenario/test_scenario.py
"""
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, CLIENT)

import fake_toio_hub  # noqa: E402
from executor import run  # noqa: E402
from fake_toio_hub import HubState, make_server, plan_moves  # noqa: E402
from formations import FORMATIONS, assign, cell_center, clear_of_robot  # noqa: E402
from generate import generate  # noqa: E402
from normalize import ScenarioError, normalize  # noqa: E402
from stackchan import StackChan  # noqa: E402
from toio_client import Toio  # noqa: E402


fake_toio_hub.VERBOSE = False


def _serve(httpd):
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return thread


def _stop(httpd):
    httpd.shutdown()
    httpd.server_close()


def _step(**overrides):
    step = {
        "say": "こんにちは", "face": "happy", "look": "center", "body": "none",
        "toio_move": "none", "toio_group": "all", "toio_color": "none",
        "toio_sound": "none", "pause": 0,
    }
    step.update(overrides)
    return step


class FormationTests(unittest.TestCase):
    def test_each_formation_is_nine_distinct_cells(self):
        for name, cells in FORMATIONS.items():
            self.assertEqual(len(cells), 9, name)
            self.assertEqual(len(set(cells)), 9, name)
            for col, row in cells:
                self.assertIn(col, range(1, 8), name)
                self.assertIn(row, range(1, 6), name)

    def test_assign_is_optimal_and_unique(self):
        # Cube 1 is already on the far cell. Id order would send it the wrong way.
        far = cell_center(7, 5)
        near = cell_center(1, 1)
        cubes = [
            {"id": 1, "connected": True, "x": far[0], "y": far[1]},
            {"id": 2, "connected": True, "x": near[0], "y": near[1]},
        ]
        cells = [(1, 1), (7, 5)]
        got = assign(cubes, cells)
        self.assertEqual(got, {1: (7, 5), 2: (1, 1)})

        # A cube with no position takes the cell that is left, in id order.
        placed = cell_center(1, 1)
        mixed = [
            {"id": 3, "connected": True},
            {"id": 1, "connected": True, "x": placed[0], "y": placed[1]},
        ]
        self.assertEqual(assign(mixed, cells), {1: (1, 1), 3: (7, 5)})

        # Fewer cubes than cells: keep the cells nearest the formation centre.
        # The middle of the square is (4, 3); the next ring is the orthogonal neighbours.
        only = [{"id": 1, "connected": True}]
        self.assertEqual(assign(only, FORMATIONS["square"]), {1: (4, 3)})
        pair = [{"id": 1, "connected": True}, {"id": 2, "connected": True}]
        got = assign(pair, FORMATIONS["square"])
        self.assertEqual(got[1], (4, 3))
        self.assertIn(got[2], {(3, 3), (5, 3), (4, 2), (4, 4)})

        home = FORMATIONS["home"]
        crowd = []
        for index, cell in enumerate(reversed(home), start=1):
            x, y = cell_center(*cell)
            crowd.append({"id": index, "connected": True, "x": x, "y": y})
        full = assign(crowd, FORMATIONS["square"])
        self.assertEqual(len(full), 9)
        self.assertEqual(len(set(full.values())), 9)
        self.assertTrue(set(full.values()) <= set(FORMATIONS["square"]))

    def test_clear_of_robot_replaces_its_cell_and_the_cell_in_front(self):
        # (4, 5) and the cell north of it are blocked. Ties break toward the smaller column.
        out = clear_of_robot([(4, 5), (4, 4), (1, 1)], 4, 5, "N")
        # (4, 4) is closer than a sideways neighbour because a cell is slightly wider than it is tall.
        self.assertEqual(out, [(3, 5), (4, 3), (1, 1)])
        cleared = clear_of_robot(FORMATIONS["square"], 4, 5, "N")
        self.assertEqual(len(cleared), 9)
        self.assertEqual(len(set(cleared)), 9)
        self.assertNotIn((4, 4), cleared)
        self.assertNotIn((4, 5), cleared)
        self.assertTrue(all(1 <= col <= 7 and 1 <= row <= 5 for col, row in cleared))
        # Facing west on the left edge, the cell in front is off the mat.
        edge = clear_of_robot([(1, 1), (2, 1)], 1, 1, "W")
        self.assertEqual(len(set(edge)), 2)
        self.assertNotIn((1, 1), edge)
        self.assertTrue(all(1 <= col <= 7 and 1 <= row <= 5 for col, row in edge))


class NormalizeTests(unittest.TestCase):
    def test_bad_values_coerced_and_empty_steps_dropped(self):
        raw = {
            "title": "  実験  ",
            "steps": [
                {"say": "  やあ  ", "face": "NOPE", "look": "sideways", "body": "jump",
                 "toio_move": "triangle", "toio_group": "left", "toio_color": "pink",
                 "toio_sound": "boom", "pause": 9},
                {"say": "   ", "face": "neutral", "look": "center", "body": "none",
                 "toio_move": "none", "toio_group": "all", "toio_color": "none",
                 "toio_sound": "none", "pause": 1},
                {"say": "あ" * 80, "face": "happy", "look": "up", "body": "nod",
                 "toio_move": "heart", "toio_group": "odd", "toio_color": "red",
                 "toio_sound": "ok", "pause": -3},
            ],
        }
        out = normalize(raw)
        self.assertEqual(out["title"], "実験")
        self.assertEqual(len(out["steps"]), 2)
        first = out["steps"][0]
        self.assertEqual(first["say"], "やあ")
        self.assertEqual(first["face"], "neutral")
        self.assertEqual(first["look"], "center")
        self.assertEqual(first["body"], "none")
        self.assertEqual(first["toio_move"], "none")
        self.assertEqual(first["toio_group"], "all")
        self.assertEqual(first["toio_color"], "none")
        self.assertEqual(first["toio_sound"], "none")
        self.assertEqual(first["pause"], 5)
        second = out["steps"][1]
        self.assertEqual(len(second["say"]), 60)
        self.assertEqual(second["pause"], 0)
        self.assertEqual(second["toio_move"], "heart")

    def test_caps_at_ten_and_rejects_empty(self):
        steps = [_step(say=f"n{i}", face="happy" if i % 2 == 0 else "sad") for i in range(12)]
        out = normalize({"title": "x", "steps": steps})
        self.assertEqual(len(out["steps"]), 10)
        with self.assertRaises(ScenarioError):
            normalize({"title": "x", "steps": [_step(say="", face="neutral")]})


class _LLM(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.requests.append(json.loads(raw))
        self.server.hits += 1
        if self.server.hits <= self.server.bad_first:
            content = "NOT JSON {"
        else:
            content = json.dumps(self.server.scenario, ensure_ascii=False)
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _llm_server(port, scenario, bad_first):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _LLM)
    httpd.requests = []
    httpd.hits = 0
    httpd.scenario = scenario
    httpd.bad_first = bad_first
    _serve(httpd)
    return httpd


class GenerateTests(unittest.TestCase):
    SCENARIO = {"title": "テスト", "steps": [_step(), _step(say="次"), _step(say="終わり")]}

    def test_valid_response_is_parsed(self):
        httpd = _llm_server(18781, self.SCENARIO, bad_first=0)
        try:
            got = generate("方針A", "http://127.0.0.1:18781/v1/chat/completions",
                           "qwen2.5-3b", 4, timeout=5)
        finally:
            _stop(httpd)
        self.assertEqual(got["title"], "テスト")
        self.assertEqual(len(got["steps"]), 3)
        request = httpd.requests[0]
        fmt = request["response_format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertEqual(fmt["json_schema"]["name"], "scenario")
        self.assertEqual(fmt["json_schema"]["schema"]["properties"]["steps"]["maxItems"], 4)
        self.assertEqual(httpd.hits, 1)

    def test_invalid_json_is_retried(self):
        httpd = _llm_server(18782, self.SCENARIO, bad_first=1)
        try:
            got = generate("方針B", "http://127.0.0.1:18782/v1/chat/completions",
                           "qwen2.5-3b", 6, timeout=5)
        finally:
            _stop(httpd)
        self.assertEqual(got["title"], "テスト")
        self.assertEqual(httpd.hits, 2)


class FakeHubTests(unittest.TestCase):
    def test_separation_rule(self):
        state = HubState()
        with self.assertRaises(ValueError):
            plan_moves(state, [
                {"id": 1, "col": 4, "row": 3},
                {"id": 2, "col": 4, "row": 3},
            ])
        # Cube 9 starts on (7, 4). Moving cube 1 there while 9 stays is too close.
        with self.assertRaises(ValueError):
            plan_moves(state, [{"id": 1, "col": 7, "row": 4}])
        with self.assertRaises(ValueError):
            plan_moves(state, [{"id": 1, "col": 9, "row": 1}])


class _Recorder(BaseHTTPRequestHandler):
    """Fake StackChan hub. say waits 0.3 s; drive waits for its ms when asked."""

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        req = json.loads(raw or b"{}")
        started = time.monotonic()
        cmd = req.get("cmd")
        if cmd == "say" and req.get("wait", True):
            time.sleep(0.3)
        if cmd == "drive" and req.get("wait"):
            time.sleep(max(0, int(req.get("ms") or 0)) / 1000)
        event = {"t0": started, "t1": time.monotonic(), "cmd": cmd, "req": req}
        with self.server.lock:
            self.server.events.append(event)
        body = json.dumps({"ok": True, "link_up": True, "rover": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _stackchan(port):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Recorder)
    httpd.lock = threading.Lock()
    httpd.events = []
    _serve(httpd)
    return httpd


def _overlaps(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


class ExecutorTests(unittest.TestCase):
    def test_dry_run_prints_commands_without_network(self):
        class Boom:
            def cmd(self, *args, **kwargs):
                raise AssertionError("dry-run touched the network")

        logs = []
        scenario = {"title": "予行", "steps": [
            _step(say="はじめ", face="happy", look="left", body="wiggle",
                  toio_move="square", toio_color="red", toio_sound="ok", pause=1),
            _step(say="まわる", face="angry", look="up", body="nod",
                  toio_move="spin", toio_group="odd", pause=0),
            _step(say="さね", face="sad", look="toio", body="none",
                  toio_move="wave", toio_group="all", pause=0),
        ]}
        run(scenario, Boom(), Boom(), dry_run=True, log=logs.append)
        text = "\n".join(logs)
        self.assertIn("stackchan face", text)
        self.assertIn("stackchan say", text)
        self.assertIn('"yaw": 40', text)
        self.assertIn("move_all", text)
        self.assertIn('"left": 60', text)
        self.assertIn("wave stagger", text)
        self.assertIn("wait 1.0s", text)

    def test_tracks_overlap_and_formations_are_distinct(self):
        sc_http = _stackchan(18783)
        toio_http = make_server("127.0.0.1", 18784)
        _serve(toio_http)
        scenario = {"title": "同時", "steps": [
            _step(say="いち", face="happy", look="left", body="wiggle",
                  toio_move="square", toio_color="red", toio_sound="ok"),
            _step(say="に", face="sad", look="right", body="nod",
                  toio_move="home", toio_color="blue", toio_sound="beep"),
        ]}
        try:
            run(scenario, StackChan("http://127.0.0.1:18783", raise_errors=False),
                Toio("http://127.0.0.1:18784", raise_errors=False), log=lambda *_: None)
        finally:
            _stop(sc_http)
            _stop(toio_http)

        faces = [e for e in sc_http.events if e["cmd"] == "face" and e["req"].get("text")]
        self.assertEqual(len(faces), 2)
        move_cells = []
        for index, face in enumerate(faces):
            window = faces[index + 1]["t0"] if index + 1 < len(faces) else float("inf")
            start = face["t0"] - 0.15
            says = [e for e in sc_http.events
                    if e["cmd"] == "say" and start <= e["t0"] < window]
            heads = [e for e in sc_http.events
                     if e["cmd"] == "head" and start <= e["t0"] < window]
            drives = [e for e in sc_http.events
                      if e["cmd"] == "drive" and start <= e["t0"] < window]
            toio_cmds = [e for e in toio_http.events
                         if e["cmd"] != "status" and start <= e["t0"] < window]
            self.assertTrue(says, index)
            self.assertLess(face["t0"], heads[0]["t0"])
            self.assertLess(heads[0]["t0"], says[0]["t0"])
            speech = (face["t0"], says[0]["t1"])
            body = (drives[0]["t0"], drives[-1]["t1"])
            cubes = (toio_cmds[0]["t0"], toio_cmds[-1]["t1"])
            self.assertTrue(_overlaps(*speech, *body), f"speech/body step {index}")
            self.assertTrue(_overlaps(*speech, *cubes), f"speech/toio step {index}")
            self.assertTrue(_overlaps(*body, *cubes), f"body/toio step {index}")
            for event in toio_cmds:
                if event["cmd"] == "move_all":
                    cells = [(t["col"], t["row"]) for t in event["req"]["targets"]]
                    self.assertEqual(len(cells), 9)
                    self.assertEqual(len(set(map(tuple, cells))), 9)
                    move_cells.append(set(map(tuple, cells)))
        self.assertEqual(move_cells[0], set(FORMATIONS["square"]))
        self.assertEqual(move_cells[1], set(FORMATIONS["home"]))

    def test_keyboard_interrupt_stops_both(self):
        sc_http = _stackchan(18785)
        toio_http = make_server("127.0.0.1", 18786)
        _serve(toio_http)

        def poke():
            time.sleep(0.6)
            import _thread
            _thread.interrupt_main()

        threading.Thread(target=poke, daemon=True).start()
        scenario = {"title": "停止", "steps": [
            _step(say="止めて", face="angry", look="left", body="none",
                  toio_color="red", pause=5),
        ]}
        try:
            with self.assertRaises(KeyboardInterrupt):
                run(scenario, StackChan("http://127.0.0.1:18785", raise_errors=False),
                    Toio("http://127.0.0.1:18786", raise_errors=False), log=lambda *_: None)
        finally:
            _stop(sc_http)
            _stop(toio_http)
        sc_cmds = [e["cmd"] for e in sc_http.events]
        self.assertIn("stop", sc_cmds)
        heads = [e for e in sc_http.events if e["cmd"] == "head" and e["req"].get("yaw") == 0]
        self.assertTrue(any(e["req"].get("pitch") == 45 for e in heads))
        self.assertIn("stop", [e["cmd"] for e in toio_http.events])

    def test_chase_grab_and_go_center(self):
        pose = {"col": 4, "row": 5, "heading": "N", "uncertain": False}
        cubes = [
            {"id": 1, "connected": True, "col": 1, "row": 1},
            {"id": 2, "connected": True, "col": 4, "row": 4},
        ]
        sc_http = _json_hub(18787, pose=pose)
        toio_http = _json_hub(18788, cubes=cubes)
        scenario = {"title": "追跡", "steps": [
            _step(say="追え", face="angry", look="toio", body="chase"),
            _step(say="つかめ", face="happy", look="down", body="grab"),
            _step(say="もどる", face="neutral", look="center", body="go_center"),
        ]}
        try:
            run(scenario, StackChan("http://127.0.0.1:18787", raise_errors=False),
                Toio("http://127.0.0.1:18788", raise_errors=False), log=lambda *_: None)
        finally:
            _stop(sc_http)
            _stop(toio_http)
        catches = [event for event in sc_http.events if event["cmd"] == "catch"]
        self.assertEqual(len(catches), 1)
        self.assertEqual(catches[0]["req"]["col"], 4)
        self.assertEqual(catches[0]["req"]["row"], 4)
        self.assertTrue(any(event["cmd"] == "grid_status" for event in sc_http.events))
        claws = [event for event in sc_http.events if event["cmd"] == "claw"]
        self.assertEqual([event["req"].get("state") for event in claws], ["close", "open"])
        self.assertGreaterEqual(claws[1]["t0"] - claws[0]["t0"], 0.5)
        moves = [event for event in sc_http.events if event["cmd"] == "grid_move"]
        self.assertEqual([(event["req"]["col"], event["req"]["row"]) for event in moves], [(4, 3)])
        self.assertTrue(moves[0]["req"]["wait"])

    def test_formation_leaves_stackchan_and_the_cell_in_front(self):
        pose = {"col": 4, "row": 5, "heading": "N", "uncertain": False}
        cubes = [{"id": index, "connected": True} for index in range(1, 10)]
        sc_http = _json_hub(18789, pose=pose)
        toio_http = _json_hub(18792, cubes=cubes)
        scenario = {"title": "よける", "steps": [
            _step(say="ならべ", face="happy", body="none", toio_move="square"),
        ]}
        try:
            run(scenario, StackChan("http://127.0.0.1:18789", raise_errors=False),
                Toio("http://127.0.0.1:18792", raise_errors=False), log=lambda *_: None)
        finally:
            _stop(sc_http)
            _stop(toio_http)
        move_all = [event for event in toio_http.events if event["cmd"] == "move_all"]
        self.assertEqual(len(move_all), 1)
        cells = [(target["col"], target["row"]) for target in move_all[0]["req"]["targets"]]
        self.assertEqual(set(map(tuple, cells)), set(clear_of_robot(FORMATIONS["square"], 4, 5, "N")))
        self.assertNotIn((4, 4), cells)
        self.assertNotIn((4, 5), cells)

    def test_dry_run_chase_catches_the_home_cube(self):
        class Boom:
            def cmd(self, *args, **kwargs):
                raise AssertionError("dry-run touched the network")

        logs = []
        run({"title": "予行追跡", "steps": [
            _step(say="いけ", face="angry", look="toio", body="chase"),
        ]}, Boom(), Boom(), dry_run=True, log=logs.append)
        text = "\n".join(logs)
        self.assertIn("stackchan catch", text)
        self.assertIn('"col": 4', text)
        self.assertIn('"row": 5', text)


class _JsonHub(BaseHTTPRequestHandler):
    """Tiny hub: grid_status can carry a pose, status can carry cubes."""

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        req = json.loads(raw or b"{}")
        event = {"t0": time.monotonic(), "cmd": req.get("cmd"), "req": req}
        with self.server.lock:
            self.server.events.append(event)
        resp = {"ok": True, "link_up": True, "rover": True}
        if req.get("cmd") == "grid_status" and self.server.pose is not None:
            resp["pose"] = self.server.pose
        if req.get("cmd") == "status" and self.server.cubes is not None:
            resp["cubes"] = self.server.cubes
        body = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _json_hub(port, pose=None, cubes=None):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _JsonHub)
    httpd.lock = threading.Lock()
    httpd.events = []
    httpd.pose = pose
    httpd.cubes = cubes
    _serve(httpd)
    return httpd


if __name__ == "__main__":
    unittest.main()
