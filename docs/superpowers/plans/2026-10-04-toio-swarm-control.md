# toio 9 台制御 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mac 上の AI やスクリプトから、toio コア キューブ 9 台を「3 番を 4 列 2 行のマスへ」のような命令で動かせるようにする。

**Architecture:** 常駐ハブ（`client/toio_hub.py`、Python + bleak）が 9 台との BLE 接続を保持し、`127.0.0.1:8765` の `POST /cmd` で JSON コマンドを受ける。CLI 兼ライブラリ（`client/toio.py`、標準ライブラリのみ）はハブに HTTP で話すだけ。バイト列の組み立て（`toio_protocol.py`）とマット座標の計算（`toio_field.py`）は BLE に依存しない純粋関数に分け、単体テストする。

**Tech Stack:** Python、bleak 0.21 以上（ハブと検証スクリプトのみ。uv のスクリプトメタデータで宣言）、標準ライブラリの `asyncio` `http.server` `unittest`。

**Spec:** `docs/superpowers/specs/2026-10-04-toio-swarm-control-design.md`

## Global Constraints

- StackChan 系（`client/robot.py`、`client/presenter.py`、`firmware/`、`firmware-rover/`）には触れない。toio は Core2 を経由しない。
- `client/toio.py`、`client/toio_protocol.py`、`client/toio_field.py` は標準ライブラリのみ。bleak を import してよいのは `toio_hub.py` と `toio_spike.py` だけで、`toio_hub.py` では関数の中で遅延 import する（テストが bleak なしで走るため）。
- `toio_hub.py` と `toio_spike.py` 以外のコードとテストは、`python3` 3.9 以降で動くこと（この Mac の `python3` は 3.14）。`match` 文と `X | Y` の型注釈は使わない。
- ハブは `127.0.0.1` だけで待ち受ける。ポートは 8765。
- キューブ番号は 1〜9。個体は広告名 `toio-XXX` の末尾 3 文字で識別する。
- マットは開発用プレイマットの表面: `x_min` 98、`y_min` 142、`x_max` 402、`y_max` 358、7 列 × 5 行。
- 目標は端から 15 単位以上内側、他のキューブの現在地と実行中の目標から 35 単位以上離す。
- 時間無制限の駆動命令は提供しない（`drive` の `ms` は 10〜2550）。
- BLE の書き込みは `write_gatt_char(uuid, data)` と `response` 引数を省いて呼ぶ（bleak が characteristic の属性から選ぶ）。
- コード中のコメントと出力メッセージは英語（既存コードに合わせる）。
- テストの実行は `cd client && python3 -m unittest test_toio test_toio_hub -v`。
- コミットメッセージの末尾に次の 2 行を付ける。

  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01ATCCJV3ixmQ2QnB9xZ3mY7
  ```

## Review Focus

仕様が暗に求めるが、放っておくとどのテストも踏まない入力と故障。各行のテストは持ち主のタスクに入れてある。

1. **移動中にキューブが切断される** — `move` は待ち続けず、結果 `disconnected` で返る。（Task 4: `test_disconnect_during_move`）
2. **マットに載っていないキューブへの `move`** — 何も書き込まず、「not on the mat」で拒否する。（Task 4: `test_move_rejects_cube_off_mat`）
3. **壊れた入力**（JSON でない本文、オブジェクトでない JSON、未知の cmd、欠けた引数、文字列の数値） — エラー応答を返し、どのキューブにも書き込まない。ハブは落ちない。（Task 4: `test_bad_input_moves_nothing`、Task 5: `test_http_rejects_invalid_json`）
4. **ハブが起動していないときの CLI** — スタックトレースではなく、起動方法を含む 1 行を出して終了コード 2。（Task 6: `test_unreachable_hub`）
5. **設定の不備と見つからないキューブ** — 番号が重複した設定は起動時にエラー。設定にあるが見つからないキューブがあってもハブは動き、`status` で `connected: false`、そのキューブへの命令は「not connected」。（Task 5: `test_load_config_rejects_duplicate_ids`、Task 4: `test_missing_cube`）

## ファイル構成

| ファイル | 責務 |
|---|---|
| `client/toio_protocol.py` | UUID、命令バイト列の組み立て、notify の解釈。純粋関数 |
| `client/toio_field.py` | マット範囲、マスと座標の変換、目標の検査。純粋関数 |
| `client/toio_spike.py` | 9 台同時接続の検証スクリプト（実機で実行） |
| `client/toio_hub.py` | 常駐ハブ。`Cube`（1 台の状態と移動の完了待ち）、`Hub`（コマンド処理）、BLE 接続維持、HTTP、番号割り当て |
| `client/toio_config.json` | マット範囲とキューブ名の対応 |
| `client/toio.py` | CLI 兼ライブラリ |
| `client/test_toio.py` | `toio_protocol`、`toio_field`、`toio.py` のテスト |
| `client/test_toio_hub.py` | `Cube` と `Hub`、設定読み込み、HTTP のテスト |

設計書のファイル一覧に対して `toio_field.py`、`toio_spike.py`、`test_toio_hub.py` を追加している（Task 7 で設計書も直す）。

---

### Task 1: toio_protocol（バイト列）

**Files:**
- Create: `client/toio_protocol.py`
- Test: `client/test_toio.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - 定数 `SERVICE` `ID_INFO` `MOTOR` `LIGHT` `SOUND` `BATTERY` `CONFIG`（UUID 文字列、小文字）
  - 定数 `STOP` `LED_OFF` `BLINK` `REQUEST_VERSION`（`bytes`）、`MAX_SPEED = 115`、`MOVE_RESULTS`（`dict[int, str]`）
  - `drive(left, right, ms) -> bytes`、`move_to(control_id, x, y, angle=None, speed=80, timeout=10) -> bytes`
  - `led(r, g, b, ms=0) -> bytes`、`sound(effect, volume=255) -> bytes`
  - `parse_id(data) -> dict | None`（`{"on_mat": True, "x", "y", "angle"}` か `{"on_mat": False}`）
  - `parse_move_result(data) -> (control_id, result_str) | None`、`parse_version(data) -> str | None`
  - 範囲外の引数は `ValueError`

- [ ] **Step 1: 失敗するテストを書く**

`client/test_toio.py`:

```python
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
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd client && python3 -m unittest test_toio -v`
Expected: `ModuleNotFoundError: No module named 'toio_protocol'`

- [ ] **Step 3: 実装する**

`client/toio_protocol.py`:

```python
"""toio Core Cube BLE byte formats. Pure functions, no BLE dependency.

Spec: https://toio.github.io/toio-spec/docs/ble_communication_overview
"""
import struct


def _uuid(n):
    return "10b2%04x-5b3b-4571-9508-cf3efcd7bbae" % n


SERVICE = _uuid(0x0100)
ID_INFO = _uuid(0x0101)   # read / notify: position on the mat
MOTOR = _uuid(0x0102)     # write: drive commands, notify: result of a move
LIGHT = _uuid(0x0103)
SOUND = _uuid(0x0104)
BATTERY = _uuid(0x0108)   # read / notify: percent
CONFIG = _uuid(0x01FF)

MAX_SPEED = 115
MOVE_RESULTS = {0: "reached", 1: "timeout", 2: "off_mat", 3: "bad_parameters",
                4: "bad_state", 5: "interrupted", 6: "unsupported"}

STOP = bytes([0x01, 0x01, 0x01, 0x00, 0x02, 0x01, 0x00])
LED_OFF = bytes([0x01])
# 5 x (300 ms white, 300 ms off) = 3 s
BLINK = bytes([0x04, 5, 2, 30, 1, 1, 255, 255, 255, 30, 1, 1, 0, 0, 0])
REQUEST_VERSION = bytes([0x01, 0x00])
_NO_ANGLE = 0x05 << 13    # top 3 bits of theta: no target angle, no final turn


def _wheel(v):
    v = int(v)
    if not -MAX_SPEED <= v <= MAX_SPEED:
        raise ValueError("wheel speed must be -115..115")
    return (0x01 if v >= 0 else 0x02), abs(v)


def drive(left, right, ms):
    """Run both wheels for `ms` milliseconds, then stop. There is no unlimited form on purpose."""
    ms = int(ms)
    if not 10 <= ms <= 2550:
        raise ValueError("ms must be 10..2550")
    ld, ls = _wheel(left)
    rd, rs = _wheel(right)
    return bytes([0x02, 0x01, ld, ls, 0x02, rd, rs, ms // 10])


def move_to(control_id, x, y, angle=None, speed=80, timeout=10):
    """Drive to mat coordinates; the cube steers itself and answers with parse_move_result()."""
    x, y, speed, timeout = int(x), int(y), int(speed), int(timeout)
    if not (0 <= x < 0xFFFF and 0 <= y < 0xFFFF):
        raise ValueError("x and y must be 0..65534")
    if not 10 <= speed <= MAX_SPEED:
        raise ValueError("speed must be 10..115")
    if not 1 <= timeout <= 255:
        raise ValueError("timeout must be 1..255")
    theta = _NO_ANGLE if angle is None else int(angle) % 360
    return struct.pack("<7B3H", 0x03, control_id & 0xFF, timeout, 0x00, speed, 0x00, 0x00, x, y, theta)


def led(r, g, b, ms=0):
    """Light the lamp. ms 0 keeps it on."""
    r, g, b, ms = int(r), int(g), int(b), int(ms)
    if not all(0 <= v <= 255 for v in (r, g, b)):
        raise ValueError("r, g, b must be 0..255")
    if not 0 <= ms <= 2550:
        raise ValueError("ms must be 0..2550")
    return bytes([0x03, ms // 10, 0x01, 0x01, r, g, b])


def sound(effect, volume=255):
    effect, volume = int(effect), int(volume)
    if not 0 <= effect <= 10:
        raise ValueError("effect must be 0..10")
    if not 0 <= volume <= 255:
        raise ValueError("volume must be 0..255")
    return bytes([0x02, effect, volume])


def parse_id(data):
    """ID_INFO value -> {"on_mat": True, "x", "y", "angle"} / {"on_mat": False} / None if unknown."""
    if not data:
        return None
    if data[0] == 0x01 and len(data) >= 7:
        x, y, angle = struct.unpack_from("<HHH", data, 1)
        return {"on_mat": True, "x": x, "y": y, "angle": angle}
    if data[0] in (0x02, 0x03, 0x04):   # on a card, or lifted
        return {"on_mat": False}
    return None


def parse_move_result(data):
    """MOTOR notification -> (control_id, result name), or None if it is not a move result."""
    if len(data) < 3 or data[0] != 0x83:
        return None
    return data[1], MOVE_RESULTS.get(data[2], "error_0x%02x" % data[2])


def parse_version(data):
    """CONFIG notification -> BLE protocol version string, or None."""
    if len(data) < 3 or data[0] != 0x81:
        return None
    return bytes(data[2:]).decode("ascii", "replace")
```

- [ ] **Step 4: 通ることを確認する**

Run: `cd client && python3 -m unittest test_toio -v`
Expected: 13 tests, `OK`

- [ ] **Step 5: コミット**

```bash
git add client/toio_protocol.py client/test_toio.py
git commit -m "feat: toio BLE byte formats"
```

---

### Task 2: toio_field（マットと目標の検査）

**Files:**
- Create: `client/toio_field.py`
- Modify: `client/test_toio.py`（テストクラスを追加）

**Interfaces:**
- Consumes: なし
- Produces:
  - `MARGIN = 15`、`MIN_GAP = 35`
  - `Mat(x_min, y_min, x_max, y_max, cols=None, rows=None)`
  - `Mat.contains(x, y, margin=MARGIN) -> bool`
  - `Mat.cell_center(col, row) -> (x, y)`（整数。マス目なし、または範囲外は `ValueError`）
  - `Mat.cell_of(x, y) -> (col, row) | None`
  - `check_targets(mat, targets, obstacles=()) -> str | None`。`targets` は `{id: (x, y)}`、`obstacles` は `[(label, x, y)]`。問題があれば英語のエラー文、なければ `None`

- [ ] **Step 1: 失敗するテストを書く**

`client/test_toio.py` の import に追加し、`if __name__` の前にクラスを足す:

```python
from toio_field import Mat, check_targets

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
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd client && python3 -m unittest test_toio -v`
Expected: `ModuleNotFoundError: No module named 'toio_field'`

- [ ] **Step 3: 実装する**

`client/toio_field.py`:

```python
"""Mat geometry for the toio hub: bounds, grid cells, and the checks a target must pass."""
import math

MARGIN = 15    # a target must be this far inside the mat edge (mat units, 1 unit = about 1.38 mm)
MIN_GAP = 35   # a target must be this far from other cubes and other targets (a cube is about 23 units)


class Mat:
    def __init__(self, x_min, y_min, x_max, y_max, cols=None, rows=None):
        self.x_min, self.y_min, self.x_max, self.y_max = x_min, y_min, x_max, y_max
        self.cols, self.rows = cols, rows

    def contains(self, x, y, margin=MARGIN):
        return (self.x_min + margin <= x <= self.x_max - margin
                and self.y_min + margin <= y <= self.y_max - margin)

    def _cell_size(self):
        if not self.cols or not self.rows:
            raise ValueError("this mat has no grid; use x and y")
        return (self.x_max - self.x_min) / self.cols, (self.y_max - self.y_min) / self.rows

    def cell_center(self, col, row):
        """Centre of a cell. col counts from the left, row from the top, both from 1."""
        w, h = self._cell_size()
        if not (1 <= col <= self.cols and 1 <= row <= self.rows):
            raise ValueError("cell must be col 1..%d, row 1..%d" % (self.cols, self.rows))
        return round(self.x_min + (col - 0.5) * w), round(self.y_min + (row - 0.5) * h)

    def cell_of(self, x, y):
        """(col, row) containing a point, or None if off the mat or the mat has no grid."""
        if not self.cols or not self.rows:
            return None
        if not (self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max):
            return None
        w, h = self._cell_size()
        return (min(self.cols, int((x - self.x_min) / w) + 1),
                min(self.rows, int((y - self.y_min) / h) + 1))


def check_targets(mat, targets, obstacles=()):
    """targets: {cube id: (x, y)}. obstacles: [(label, x, y)]. Returns an error string, or None if fine."""
    for cid, (x, y) in targets.items():
        if not mat.contains(x, y):
            return "cube %s: target (%d, %d) is outside the mat" % (cid, x, y)
    items = list(targets.items())
    for i, (a, (ax, ay)) in enumerate(items):
        for b, (bx, by) in items[i + 1:]:
            if math.hypot(ax - bx, ay - by) < MIN_GAP:
                return "cubes %s and %s: targets are too close together" % (a, b)
        for label, ox, oy in obstacles:
            if math.hypot(ax - ox, ay - oy) < MIN_GAP:
                return "cube %s: target is too close to %s" % (a, label)
    return None
```

- [ ] **Step 4: 通ることを確認する**

Run: `cd client && python3 -m unittest test_toio -v`
Expected: 23 tests, `OK`

- [ ] **Step 5: コミット**

```bash
git add client/toio_field.py client/test_toio.py
git commit -m "feat: toio mat grid and target checks"
```

---

### Task 3: 9 台同時接続の検証スクリプト

実機が必要なので、自動テストはない。スクリプトを書いて構文と `--help` を確認し、実行はユーザーに依頼する。
結果が不合格でも Task 4 以降はそのまま有効（ESP32 ブリッジに替える場合も、変わるのは `toio_hub.py` の
接続部分だけ）なので、結果を待たずに次へ進んでよい。

**Files:**
- Create: `client/toio_spike.py`

**Interfaces:**
- Consumes: `toio_protocol` の `SERVICE` `ID_INFO` `MOTOR` `LIGHT` `BATTERY` `CONFIG` `REQUEST_VERSION` `LED_OFF` `led` `move_to` `parse_id` `parse_move_result` `parse_version`
- Produces: なし（他のタスクは使わない）

- [ ] **Step 1: スクリプトを書く**

`client/toio_spike.py`:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["bleak>=0.21"]
# ///
"""Checks whether this Mac can hold N toio cubes at once.

  uv run client/toio_spike.py                    connect to every cube found, soak for 10 minutes
  uv run client/toio_spike.py --minutes 1        shorter soak
  uv run client/toio_spike.py --move             also send one cube to the mat centre (250, 250)

Turn all cubes on and put them on the mat first. PASS means: --expect cubes connected,
no disconnects, median config round trip under 100 ms.
"""
import argparse
import asyncio
import statistics
import sys
import time

from bleak import BleakClient, BleakScanner

import toio_protocol as P

COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]


async def connect(dev, name):
    c = {"name": name, "drops": 0, "ids": 0, "pos": None, "rt": [], "version": None, "pong": None, "moved": None}

    def lost(_client):
        c["drops"] += 1
        print("  LOST %s" % name)

    def on_id(_sender, data):
        c["ids"] += 1
        info = P.parse_id(bytes(data))
        if info and info["on_mat"]:
            c["pos"] = (info["x"], info["y"], info["angle"])

    def on_config(_sender, data):
        version = P.parse_version(bytes(data))
        if version:
            c["version"] = version
            if c["pong"]:
                c["pong"].set()

    def on_motor(_sender, data):
        result = P.parse_move_result(bytes(data))
        if result and c["moved"] and not c["moved"].done():
            c["moved"].set_result(result[1])

    client = BleakClient(dev, disconnected_callback=lost)
    t0 = time.monotonic()
    await client.connect()
    c["client"] = client
    await client.start_notify(P.ID_INFO, on_id)
    await client.start_notify(P.CONFIG, on_config)
    await client.start_notify(P.MOTOR, on_motor)
    on_id(None, await client.read_gatt_char(P.ID_INFO))
    c["battery"] = (await client.read_gatt_char(P.BATTERY))[0]
    print("  %s connected in %.1f s, battery %d%%" % (name, time.monotonic() - t0, c["battery"]))
    return c


async def ping(c):
    """Config round trip: write a version request, wait for its notification."""
    c["pong"] = asyncio.Event()
    t0 = time.monotonic()
    await c["client"].write_gatt_char(P.CONFIG, P.REQUEST_VERSION)
    try:
        await asyncio.wait_for(c["pong"].wait(), 2)
        c["rt"].append((time.monotonic() - t0) * 1000)
    except asyncio.TimeoutError:
        c["rt"].append(2000.0)


async def run(a):
    print("scanning 6 s ...")
    found = await BleakScanner.discover(timeout=6.0, return_adv=True, service_uuids=[P.SERVICE])
    named = sorted(((adv.local_name or dev.name or "?", dev) for dev, adv in found.values()), key=lambda t: t[0])
    print("found %d cubes" % len(named))
    cubes = []
    for name, dev in named:
        try:
            cubes.append(await connect(dev, name))
        except Exception as e:
            print("  %s: connect failed: %s" % (name, e))

    try:
        if a.move:
            on_mat = [c for c in cubes if c["pos"]]
            if on_mat:
                c = on_mat[0]
                c["moved"] = asyncio.get_running_loop().create_future()
                await c["client"].write_gatt_char(P.MOTOR, P.move_to(1, 250, 250))
                try:
                    print("move %s -> (250, 250): %s" % (c["name"], await asyncio.wait_for(c["moved"], 12)))
                except asyncio.TimeoutError:
                    print("move %s: no answer (firmware may not support target moves)" % c["name"])
            else:
                print("move: no cube is on the mat")

        deadline = time.monotonic() + a.minutes * 60
        tick = 0
        print("soaking for %g minutes ..." % a.minutes)
        while time.monotonic() < deadline:
            for c in cubes:
                if not c["client"].is_connected:
                    continue
                try:
                    await c["client"].write_gatt_char(P.LIGHT, P.led(*COLORS[tick % 3]))
                    await ping(c)
                except Exception as e:
                    print("  %s: %s" % (c["name"], e))
            tick += 1
            await asyncio.sleep(1)
    finally:
        print("\n%-10s %-8s %-6s %-9s %-16s %s" % ("name", "version", "drops", "id-notif", "position", "round trip ms (median / max)"))
        medians = []
        for c in cubes:
            med = statistics.median(c["rt"]) if c["rt"] else float("nan")
            medians.append(med)
            print("%-10s %-8s %-6d %-9d %-16s %.0f / %.0f" % (
                c["name"], c["version"], c["drops"], c["ids"], c["pos"], med, max(c["rt"], default=float("nan"))))
            try:
                if c["client"].is_connected:
                    await c["client"].write_gatt_char(P.LIGHT, P.LED_OFF)
                    await c["client"].disconnect()
            except Exception:
                pass
        ok = (len(cubes) >= a.expect and all(c["drops"] == 0 for c in cubes)
              and bool(medians) and all(m < 100 for m in medians))
        print("\n%s: %d of %d cubes connected" % ("PASS" if ok else "FAIL", len(cubes), a.expect))
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--minutes", type=float, default=10)
    p.add_argument("--expect", type=int, default=9, help="number of cubes that must connect")
    p.add_argument("--move", action="store_true", help="send the first cube on the mat to (250, 250)")
    try:
        return asyncio.run(run(p.parse_args(argv)))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 構文と `--help` を確認する**

Run: `python3 -m py_compile client/toio_spike.py && uv run client/toio_spike.py --help`
Expected: エラーなし。使い方が表示される（初回は uv が bleak を取得する）。

- [ ] **Step 3: コミット**

```bash
git add client/toio_spike.py
git commit -m "feat: toio multi-cube connection check script"
```

- [ ] **Step 4: ユーザーに実機での実行を依頼する**

依頼文: 「9 台の電源を入れてマットに載せ、`uv run client/toio_spike.py --minutes 1 --move` を実行して、
出力の最後の表と PASS / FAIL を教えてください。初回は macOS がターミナルの Bluetooth 利用許可を求めます。
問題なければ `--minutes 10` でも実行してください。」

結果の扱い:
- PASS: そのまま続行。
- FAIL（接続台数が足りない、切断がある、遅延が大きい）: Task 4 以降は続け、結果を報告して ESP32 ブリッジの設計に入るかをユーザーに確認する。
- `move` が `unsupported` または無応答: キューブのファームウェア更新が必要。ユーザーに伝える。
- `position` 列の座標が (98, 142)〜(402, 358) に収まらない: マットの面が想定と違う。`toio_config.json` の `mat` を実測に合わせる。

---

### Task 4: ハブのコマンド処理（Cube と Hub）

BLE を使わない部分。`Cube.client` は `write_gatt_char(uuid, data)` を持つ何かで、テストでは偽物を差す。

**Files:**
- Create: `client/toio_hub.py`
- Test: `client/test_toio_hub.py`

**Interfaces:**
- Consumes: `toio_protocol`（Task 1）、`toio_field.Mat` `check_targets`（Task 2）
- Produces:
  - `CmdError(Exception)`
  - `Cube(cid, name)`。属性 `id` `name` `client` `connected` `x` `y` `angle` `on_mat` `battery` `target` `last_result`、プロパティ `busy`、クラス属性 `GRACE = 2`
  - `Cube.on_id(sender, data)` `Cube.on_motor(sender, data)` `Cube.on_battery(sender, data)` `Cube.on_disconnect()`（bleak のコールバックとして使える形）
  - `async Cube.write(char, data)`、`async Cube.move(x, y, angle=None, speed=80, timeout=10) -> str`、`async Cube.stop()`
  - `Hub(mat, entries)`。`entries` は `[(id, name)]`。属性 `mat`、`cubes`（`{id: Cube}`）
  - `async Hub.handle(req) -> dict`。必ず `{"ok": bool, ...}` を返し、例外を外に出さない
  - `move` の結果文字列: `reached` `timeout` `off_mat` `bad_parameters` `bad_state` `interrupted` `unsupported` `no_response` `disconnected` `write_failed`

- [ ] **Step 1: 失敗するテストを書く**

`client/test_toio_hub.py`:

```python
"""Tests for the hub's command handling. No BLE: cubes get a fake client.
Run: cd client && python3 -m unittest test_toio_hub -v"""
import asyncio
import struct
import unittest

import toio_protocol as P
from toio_field import Mat
from toio_hub import Cube, Hub

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd client && python3 -m unittest test_toio_hub -v`
Expected: `ModuleNotFoundError: No module named 'toio_hub'`

- [ ] **Step 3: 実装する**

`client/toio_hub.py`（このタスクではコマンド処理まで。BLE、HTTP、`main` は Task 5 で同じファイルに足す）:

```python
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
```

注意点（実装者向け）:
- `{"cmd": "move", "id": "all", ...}` は `_ready("all")` の `int("all")` が `ValueError` になり、`bad arguments` で返る。`move` は 1 台指定のみ。
- `{"cmd": "_move"}` は `_cmd__move` を探すので、内部メソッド `_move` には届かない。
- 検査と引数の解釈は、最初の書き込みより前にすべて終える。これで「エラーなら何も動かない」が保たれる。

- [ ] **Step 4: 通ることを確認する**

Run: `cd client && python3 -m unittest test_toio_hub -v`
Expected: 20 tests, `OK`（`test_move_no_response` が約 1 秒かかる）

- [ ] **Step 5: コミット**

```bash
git add client/toio_hub.py client/test_toio_hub.py
git commit -m "feat: toio hub command handling"
```

---

### Task 5: ハブの BLE 接続、HTTP、番号割り当て

**Files:**
- Modify: `client/toio_hub.py`（import を足し、`Hub` にメソッドを足し、末尾に関数を足す）
- Create: `client/toio_config.json`
- Modify: `client/test_toio_hub.py`（テストクラスを追加）

**Interfaces:**
- Consumes: Task 4 の `Cube` `Hub`
- Produces:
  - `load_config(path) -> (Mat, [(id, name)])`。番号が 1〜9 でない、または重複していれば `ValueError`
  - `suffix(name) -> str`（`"toio-a1B"` も `"toio Core Cube-a1B"` も `"a1B"`）
  - `serve_http(hub, loop, port) -> ThreadingHTTPServer`（別スレッドで動き始めた状態で返す。`port` に 0 を渡すと空きポート）
  - `async Hub.keep_connected()`（戻らない）、`async Hub.shutdown()`
  - `main(argv=None) -> int`
  - 定数 `HOST = "127.0.0.1"`、`PORT = 8765`、`CONFIG_PATH`

- [ ] **Step 1: 失敗するテストを書く**

`client/test_toio_hub.py` の import を次のように変える:

```python
import asyncio
import json
import os
import struct
import tempfile
import unittest
import urllib.error
import urllib.request

import toio_protocol as P
from toio_field import Mat
from toio_hub import Cube, Hub, load_config, serve_http, suffix
```

`if __name__` の前にクラスを足す:

```python
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
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd client && python3 -m unittest test_toio_hub -v`
Expected: `ImportError: cannot import name 'load_config' from 'toio_hub'`

- [ ] **Step 3: 設定ファイルを作る**

`client/toio_config.json`:

```json
{
  "mat": {"x_min": 98, "y_min": 142, "x_max": 402, "y_max": 358, "cols": 7, "rows": 5},
  "cubes": []
}
```

- [ ] **Step 4: 実装する**

`client/toio_hub.py` の import 部分を次に置き換える:

```python
import argparse
import asyncio
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import toio_protocol as P
from toio_field import Mat, check_targets

HOST, PORT = "127.0.0.1", 8765
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toio_config.json")
```

`Hub` クラスの末尾（`_cmd_stop` の後）にメソッドを足す:

```python
    async def _connect(self, cube, device):
        from bleak import BleakClient

        def lost(_client):
            print("cube %d (%s) disconnected" % (cube.id, cube.name))
            cube.on_disconnect()

        client = BleakClient(device, disconnected_callback=lost)
        await client.connect()
        cube.client = client
        await client.start_notify(P.ID_INFO, cube.on_id)
        await client.start_notify(P.MOTOR, cube.on_motor)
        await client.start_notify(P.BATTERY, cube.on_battery)
        cube.on_id(None, await client.read_gatt_char(P.ID_INFO))
        cube.on_battery(None, await client.read_gatt_char(P.BATTERY))
        cube.connected = True
        print("cube %d (%s) connected, battery %s%%" % (cube.id, cube.name, cube.battery))

    async def keep_connected(self):
        """Connect every configured cube, one at a time, and reconnect the ones that drop. Never returns."""
        from bleak import BleakScanner

        while True:
            missing = [c for _, c in sorted(self.cubes.items()) if not c.connected]
            if missing:
                found = await BleakScanner.discover(timeout=4.0, return_adv=True, service_uuids=[P.SERVICE])
                by_suffix = {suffix(adv.local_name or dev.name): dev for dev, adv in found.values()}
                for cube in missing:
                    device = by_suffix.get(suffix(cube.name))
                    if device is None:
                        continue
                    try:
                        await self._connect(cube, device)
                    except Exception as e:
                        print("cube %d (%s): connect failed: %s" % (cube.id, cube.name, e))
            await asyncio.sleep(2)

    async def shutdown(self):
        """Stop and release every cube. Called on exit, so each step is best effort."""
        for cube in self.cubes.values():
            if not cube.connected:
                continue
            try:
                await cube.stop()
                await cube.write(P.LIGHT, P.LED_OFF)
                await cube.client.disconnect()
            except Exception:
                pass
```

ファイルの末尾に足す:

```python
def suffix(name):
    """The 3 characters that identify a cube: "toio-a1B" and "toio Core Cube-a1B" both give "a1B"."""
    return (name or "").rsplit("-", 1)[-1]


def load_config(path):
    with open(path) as f:
        raw = json.load(f)
    mat = Mat(**raw["mat"])
    entries = [(int(c["id"]), str(c["name"])) for c in raw.get("cubes", [])]
    ids = [cid for cid, _ in entries]
    if len(set(ids)) != len(ids) or any(not 1 <= cid <= 9 for cid in ids):
        raise ValueError("cube ids in %s must be unique and 1..9" % path)
    return mat, entries


def serve_http(hub, loop, port):
    """Serve POST /cmd on localhost from a background thread; commands run on `loop`."""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/cmd":
                return self._reply(404, {"ok": False, "error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if length > 65536:
                    raise ValueError("too large")
                req = json.loads(self.rfile.read(length))
            except ValueError:
                return self._reply(400, {"ok": False, "error": "invalid JSON"})
            res = asyncio.run_coroutine_threadsafe(hub.handle(req), loop).result()
            self._reply(200 if res.get("ok") else 400, res)

        def _reply(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((HOST, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


async def assign(path):
    """Light each cube found, ask which number it is, and save the answers to the config."""
    from bleak import BleakClient, BleakScanner

    with open(path) as f:
        raw = json.load(f)
    print("scanning 6 s ... (turn every cube on)")
    found = await BleakScanner.discover(timeout=6.0, return_adv=True, service_uuids=[P.SERVICE])
    named = sorted(((adv.local_name or dev.name or "?", dev) for dev, adv in found.values()), key=lambda t: t[0])
    print("found %d cubes" % len(named))
    loop = asyncio.get_running_loop()
    cubes, used = [], set()
    for name, dev in named:
        try:
            async with BleakClient(dev) as client:
                await client.write_gatt_char(P.LIGHT, P.led(255, 255, 255))
                await client.write_gatt_char(P.SOUND, P.sound(6))
                prompt = "%s is lit. number 1-9 (blank to skip): " % name
                answer = (await loop.run_in_executor(None, input, prompt)).strip()
                await client.write_gatt_char(P.LIGHT, P.LED_OFF)
        except Exception as e:
            print("  %s: %s" % (name, e))
            continue
        if not answer:
            continue
        if not answer.isdigit() or not 1 <= int(answer) <= 9 or int(answer) in used:
            print("  skipped: need an unused number 1-9")
            continue
        used.add(int(answer))
        cubes.append({"name": name, "id": int(answer)})
    raw["cubes"] = sorted(cubes, key=lambda c: c["id"])
    with open(path, "w") as f:
        json.dump(raw, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("saved %d cubes to %s" % (len(cubes), path))


async def run(args):
    if args.assign:
        return await assign(args.config)
    mat, entries = load_config(args.config)
    if not entries:
        sys.exit("no cubes in %s: run with --assign first" % args.config)
    hub = Hub(mat, entries)
    server = serve_http(hub, asyncio.get_running_loop(), args.port)
    print("hub on http://%s:%d/cmd, %d cubes configured. Ctrl-C to quit." % (HOST, args.port, len(entries)))
    try:
        await hub.keep_connected()
    finally:
        server.shutdown()
        await hub.shutdown()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--assign", action="store_true", help="give each cube a number and save the config")
    p.add_argument("--config", default=CONFIG_PATH)
    p.add_argument("--port", type=int, default=PORT)
    try:
        asyncio.run(run(p.parse_args(argv)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 通ることを確認する**

Run: `cd client && python3 -m unittest test_toio_hub -v`
Expected: 30 tests, `OK`

Run: `uv run client/toio_hub.py --help`
Expected: 使い方が表示される。

Run: `uv run client/toio_hub.py`
Expected: `no cubes in .../toio_config.json: run with --assign first` と表示して終了コード 1（設定にキューブがまだ無いため）。

- [ ] **Step 6: コミット**

```bash
git add client/toio_hub.py client/toio_config.json client/test_toio_hub.py
git commit -m "feat: toio hub BLE connections, HTTP endpoint and cube numbering"
```

---

### Task 6: toio.py（CLI 兼ライブラリ）

**Files:**
- Create: `client/toio.py`
- Modify: `client/test_toio.py`（テストクラスを追加）

**Interfaces:**
- Consumes: ハブの `POST /cmd`（Task 4 のコマンド表）。`toio_hub` は import しない
- Produces:
  - `Toio(host="127.0.0.1", port=8765, timeout=300)`
  - `Toio.cmd(name, **args) -> dict`（値が `None` の引数は送らない）
  - `Toio.status()`、`Toio.move(id, cell=None, xy=None, angle=None, speed=None, timeout=None, wait=True)`、`Toio.move_all(targets, xy=False, speed=None, timeout=None, wait=True)`（`targets` は `{id: (列, 行)}`、`xy=True` なら `{id: (x, y)}`）
  - `Toio.drive(id, left, right, ms=500)`、`Toio.led(id, r, g, b, ms=None)`、`Toio.sound(id, effect)`、`Toio.identify(id)`、`Toio.stop(id=None)`
  - `main(argv=None) -> int`。成功 0、ハブがエラーを返したら 1、ハブに届かなければ 2

- [ ] **Step 1: 失敗するテストを書く**

`client/test_toio.py` の先頭の import を次のように変える:

```python
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
```

`if __name__` の前にクラスを足す:

```python
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
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd client && python3 -m unittest test_toio -v`
Expected: `ModuleNotFoundError: No module named 'toio'`

- [ ] **Step 3: 実装する**

`client/toio.py`:

```python
#!/usr/bin/env python3
"""PC-side CLI / library for the toio cubes. Standard library only. Talks to client/toio_hub.py.

  toio.py status
  toio.py move 3 --cell 4,2                 cube 3 to column 4, row 2 (columns from the left, rows from the top)
  toio.py move 3 --xy 250,250 --angle 90
  toio.py move-all 1:1,1 2:2,1 3:3,1        number:column,row  (--xy for number:x,y)
  toio.py drive 3 --left 50 --right 50 --ms 500
  toio.py led all 0 255 0
  toio.py sound 3 6
  toio.py identify 5
  toio.py stop

Start the hub first: uv run client/toio_hub.py
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


class Toio:
    def __init__(self, host="127.0.0.1", port=8765, timeout=300):
        self.base = "http://%s:%d" % (host, port)
        self.timeout = timeout      # a move can legitimately take up to 255 s

    def cmd(self, name, **args):
        args = {k: v for k, v in args.items() if v is not None}
        req = urllib.request.Request(self.base + "/cmd", data=json.dumps({"cmd": name, **args}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read() or b'{"ok":false,"error":"http error"}')

    def status(self):
        return self.cmd("status")

    def move(self, id, cell=None, xy=None, angle=None, speed=None, timeout=None, wait=True):
        """Send one cube to a cell (col, row) or to mat coordinates (x, y). Waits for arrival unless wait=False."""
        if (cell is None) == (xy is None):
            raise ValueError("give exactly one of cell or xy")
        where = {"col": cell[0], "row": cell[1]} if cell is not None else {"x": xy[0], "y": xy[1]}
        return self.cmd("move", id=id, angle=angle, speed=speed, timeout=timeout,
                        wait=None if wait else False, **where)

    def move_all(self, targets, xy=False, speed=None, timeout=None, wait=True):
        """targets: {cube id: (col, row)}, or {cube id: (x, y)} with xy=True."""
        a, b = ("x", "y") if xy else ("col", "row")
        items = [{"id": cid, a: p[0], b: p[1]} for cid, p in targets.items()]
        return self.cmd("move_all", speed=speed, timeout=timeout, wait=None if wait else False, targets=items)

    def drive(self, id, left, right, ms=500):
        return self.cmd("drive", id=id, left=left, right=right, ms=ms)

    def led(self, id, r, g, b, ms=None):
        return self.cmd("led", id=id, r=r, g=g, b=b, ms=ms)

    def sound(self, id, effect):
        return self.cmd("sound", id=id, effect=effect)

    def identify(self, id):
        return self.cmd("identify", id=id)

    def stop(self, id=None):
        return self.cmd("stop", id=id)


def _id(text):
    return "all" if text == "all" else int(text)


def _pair(text):
    a, b = text.split(",")
    return int(a), int(b)


def _numbered(text):
    cid, pair = text.split(":")
    return int(cid), _pair(pair)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status")

    s = sub.add_parser("move", help="send one cube to a cell or to coordinates")
    s.add_argument("id", type=int)
    where = s.add_mutually_exclusive_group(required=True)
    where.add_argument("--cell", type=_pair, metavar="COL,ROW")
    where.add_argument("--xy", type=_pair, metavar="X,Y")
    s.add_argument("--angle", type=int)

    m = sub.add_parser("move-all", help="send several cubes at once")
    m.add_argument("targets", nargs="+", type=_numbered, metavar="ID:COL,ROW")
    m.add_argument("--xy", action="store_true", help="targets are ID:X,Y")

    for q in (s, m):
        q.add_argument("--speed", type=int, help="10..115, default 80")
        q.add_argument("--timeout", type=int, help="seconds, default 10")
        q.add_argument("--no-wait", action="store_true", help="return at once; see busy / last_result in status")

    s = sub.add_parser("drive", help="run the wheels for a fixed time (works off the mat)")
    s.add_argument("id", type=_id)
    s.add_argument("--left", type=int, default=0, help="-115..115")
    s.add_argument("--right", type=int, default=0, help="-115..115")
    s.add_argument("--ms", type=int, default=500, help="10..2550")

    s = sub.add_parser("led")
    s.add_argument("id", type=_id)
    s.add_argument("r", type=int)
    s.add_argument("g", type=int)
    s.add_argument("b", type=int)
    s.add_argument("--ms", type=int, help="0 or omitted = stay on")

    s = sub.add_parser("sound")
    s.add_argument("id", type=_id)
    s.add_argument("effect", type=int, help="0..10")

    s = sub.add_parser("identify", help="blink and beep one cube")
    s.add_argument("id", type=int)

    s = sub.add_parser("stop", help="stop one cube, or all of them")
    s.add_argument("id", type=_id, nargs="?")

    a = p.parse_args(argv)
    t = Toio(a.host, a.port)
    c = a.command
    try:
        if c == "status":
            res = t.status()
        elif c == "move":
            res = t.move(a.id, cell=a.cell, xy=a.xy, angle=a.angle, speed=a.speed, timeout=a.timeout,
                         wait=not a.no_wait)
        elif c == "move-all":
            res = t.move_all(dict(a.targets), xy=a.xy, speed=a.speed, timeout=a.timeout, wait=not a.no_wait)
        elif c == "drive":
            res = t.drive(a.id, a.left, a.right, a.ms)
        elif c == "led":
            res = t.led(a.id, a.r, a.g, a.b, a.ms)
        elif c == "sound":
            res = t.sound(a.id, a.effect)
        elif c == "identify":
            res = t.identify(a.id)
        else:
            res = t.stop(a.id)
    except (urllib.error.URLError, OSError) as e:
        print("cannot reach the toio hub at %s: %s\nstart it with: uv run client/toio_hub.py" % (t.base, e),
              file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 通ることを確認する**

Run: `cd client && python3 -m unittest test_toio test_toio_hub -v`
Expected: 58 tests, `OK`

Run: `python3 client/toio.py status`（ハブを起動していない状態）
Expected: 標準エラーに `cannot reach the toio hub at http://127.0.0.1:8765: ...` と `start it with: uv run client/toio_hub.py`。終了コード 2。

- [ ] **Step 5: コミット**

```bash
git add client/toio.py client/test_toio.py
git commit -m "feat: toio CLI and Python library"
```

---

### Task 7: README と設計書の更新

**Files:**
- Modify: `README.md`（末尾の「## テスト」の前に章を追加し、「## テスト」に 1 行追加）
- Modify: `docs/superpowers/specs/2026-10-04-toio-swarm-control-design.md`（状態とファイル一覧）

**Interfaces:**
- Consumes: Task 1〜6 の CLI とコマンド
- Produces: なし

- [ ] **Step 1: README に章を追加する**

`README.md` の `## テスト` の直前に入れる:

````markdown
## toio を 9 台動かす

StackChan とは別系統。Mac が BLE で toio コア キューブに直接つなぐ（Core2 は経由しない）。

```
AI / スクリプト ──HTTP (127.0.0.1:8765)──▶ toio ハブ（常駐）──BLE──▶ キューブ 1〜9
```

- `client/toio_hub.py` 常駐ハブ。接続を保持し、`POST /cmd` で JSON コマンドを受ける。
- `client/toio.py` CLI 兼 Python ライブラリ（標準ライブラリのみ）。
- `client/toio_config.json` マットの範囲と、キューブ名と番号の対応。

マットは toio 開発用プレイマットの表面（7 × 5 マスの面）を使う。座標は左上 (98, 142)、右下 (402, 358)。
マスは左から 1〜7 列、上から 1〜5 行。

### 初回の準備

1. 全台の電源を入れてマットに載せ、接続を確かめる。初回は macOS が Bluetooth の利用許可を求める。

   ```sh
   uv run client/toio_spike.py --minutes 1 --move
   ```

   最後に `PASS` と出れば、この Mac で全台を同時に扱える。
2. 番号を割り当てる。1 台ずつ白く光るので、その台に付ける番号（1〜9）を入力し、番号シールを貼る。

   ```sh
   uv run client/toio_hub.py --assign
   ```

### 使い方

```sh
uv run client/toio_hub.py                          # ハブを起動（別のターミナルで動かしたままにする）
python3 client/toio.py status                      # 全台の接続、位置、マス、電池
python3 client/toio.py move 3 --cell 4,2           # 3 番を 4 列 2 行のマスへ。到着まで待つ
python3 client/toio.py move 3 --xy 250,250 --angle 90
python3 client/toio.py move-all 1:1,1 2:2,1 3:3,1  # 番号:列,行。まとめて動かす
python3 client/toio.py drive 3 --left 50 --right 50 --ms 500   # マットの外でも使える
python3 client/toio.py led all 0 255 0
python3 client/toio.py identify 5                  # 5 番を点滅させて鳴らす
python3 client/toio.py stop                        # 全台停止
```

Python から:

```python
from toio import Toio
t = Toio()
t.move(3, cell=(4, 2))
t.move_all({1: (1, 1), 2: (2, 1)})
```

### コマンド

`POST http://127.0.0.1:8765/cmd` に JSON を送る。応答は `{"ok":true,...}` か `{"ok":false,"error":"..."}`。

| cmd | 引数 |
|-----|------|
| `status` | なし |
| `move` | `id`、`col` `row` または `x` `y`、任意で `angle` `speed`（10〜115、既定 80）`timeout`（秒、既定 10）`wait` |
| `move_all` | `targets`: `[{id, col, row}]` または `[{id, x, y}]`、任意で `speed` `timeout` `wait` |
| `drive` | `id`、`left` `right` -115〜115、`ms` 10〜2550 |
| `led` | `id`、`r` `g` `b` 0〜255、任意で `ms` |
| `sound` | `id`、`effect` 0〜10 |
| `identify` | `id` |
| `stop` | 任意で `id`。省くと全台 |

`id` は 1〜9。`drive` `led` `sound` `stop` は `"all"` も取れる。

`move` の結果は `reached`（到着）、`timeout`、`off_mat`（マットから外れた）、`interrupted`（`stop` や別の命令で中断）、
`disconnected`、`no_response` など。`"wait": false` を付けるとすぐ返り、結果は `status` の `busy` と `last_result` で見る。

次の目標は、何も動かさずに拒否する。

- マットの端から 15 単位以内
- 他のキューブの現在地、または移動中のキューブの目標から 35 単位（約 48 mm）以内

隣り合うマスの中心は約 43 単位離れているので、1 マスに 1 台なら隣同士に置ける。
走行中の経路が交差してぶつかることは防がない。
````

`## テスト` のコードブロックに 1 行足す:

```sh
c++ -std=c++17 -Ifirmware/include firmware/test_host/test_mecanum.cpp -o /tmp/t && /tmp/t
(cd client && python3 -m unittest test_toio test_toio_hub)
```

- [ ] **Step 2: 設計書を実装に合わせる**

`docs/superpowers/specs/2026-10-04-toio-swarm-control-design.md`:

- 冒頭の `- 状態: 設計のみ（未実装、実機未確認）` を `- 状態: 実装済み（単体テスト通過、実機未確認）。コマンド仕様は README を正とする` に変える。
- 3 章のファイル一覧のコードブロックを次に置き換える。

```
client/
  toio.py            CLI 兼ライブラリ。robot.py と同じ流儀で、標準ライブラリのみ
  toio_hub.py        常駐ハブ。uv のスクリプトメタデータで bleak を宣言（presenter.py と同じ方式）
  toio_protocol.py   バイト列の組み立てと解釈。純粋関数のみで BLE に依存しない
  toio_field.py      マット範囲、マスと座標の変換、目標の検査。純粋関数のみ
  toio_spike.py      9 台同時接続の検証スクリプト
  toio_config.json   マット範囲、キューブ名と番号の対応（git 管理する）
  test_toio.py       toio_protocol、toio_field、toio.py の単体テスト
  test_toio_hub.py   ハブのコマンド処理、設定読み込み、HTTP の単体テスト
```

- [ ] **Step 3: 全テストを通す**

Run: `cd client && python3 -m unittest test_toio test_toio_hub -v`
Expected: 58 tests, `OK`

- [ ] **Step 4: コミット**

```bash
git add README.md docs/superpowers/specs/2026-10-04-toio-swarm-control-design.md
git commit -m "docs: toio usage in README, spec status"
```

- [ ] **Step 5: 実機確認をユーザーに依頼する**

実機が無いと確かめられない項目。ハブを起動した状態で順に実行してもらう。

| 手順 | 期待する結果 |
|------|--------------|
| `uv run client/toio_hub.py --assign` | 1 台ずつ白く光り、番号を入力すると `toio_config.json` に保存される |
| `uv run client/toio_hub.py` | 9 台分の `cube N (toio-XXX) connected` が出る |
| `python3 client/toio.py status` | 全台 `connected: true`、`on_mat: true`。置いたマスと `col` `row` が合う |
| `python3 client/toio.py identify 5` | 5 番のシールを貼った台だけが点滅して鳴る |
| `python3 client/toio.py move 1 --cell 4,3` | 1 番が中央のマスへ走り、`{"ok": true, "results": {"1": "reached"}}` |
| `python3 client/toio.py move 2 --cell 4,3` | 動かずに `too close to cube 1` で拒否される |
| `python3 client/toio.py move 2 --xy 50,250` | 動かずに `outside the mat` で拒否される |
| `move` の途中で別のターミナルから `python3 client/toio.py stop` | 全台が止まり、`move` 側は `interrupted` を返す |
| 走行中のキューブを持ち上げる | `move` が `off_mat` を返す |
| 1 台の電源を切り、入れ直す | ハブに `disconnected` が出て、数秒後に `connected` に戻る |
| ハブを Ctrl-C で止める | 全台が止まり、ランプが消える |
