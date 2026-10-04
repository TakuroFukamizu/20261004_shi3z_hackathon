# StackChan + RoverC Pro 制御

M5Stack 公式 StackChan のボディ（K151）に **Core2** を載せ、RoverC Pro に乗せた機体を PC から動かす。

- `firmware/` Core2 用ファームウェア（PlatformIO）。顔、声、首、車輪、グリッパー。
- `client/robot.py` PC 用 CLI 兼 Python ライブラリ（標準ライブラリのみ）。
- `docs/superpowers/specs/` 設計書。

## 配線

RoverC Pro を Core2 の Port A（赤い Grove、G32/G33）に繋ぐ。
Core2 と RoverC の両方が 5V を出す可能性があるので、初めて繋ぐ場合は 5V 線を確認すること。

## 書き込み

pioarduino は Python 3.10 以上が必要なので `uvx` 経由で実行する。

```sh
cd firmware
cp include/secrets.h.example include/secrets.h   # Wi-Fi を書く（省略可）
uvx --python 3.12 platformio run -t upload
uvx --python 3.12 platformio device monitor
```

`secrets.h` が無い、または接続できない場合は、機体がアクセスポイントになる。
SSID は `stackchan-rover`、パスワードは `stackchan`、アドレスは `192.168.4.1`。
起動すると IP アドレスが吹き出しに出る。

## 初回の確認手順

1. `python3 client/robot.py --host <IP> status` で `rover` `body` `servos` が `true` か見る。
   - `servos` が `false` なら `firmware/include/config.h` の `SERVO_TX_PIN` と `SERVO_RX_PIN` を入れ替える。
2. 首を手で「正面・水平」に向け、`robot.py calibrate` を実行する。校正するまで首は動かない。
   出荷時の既定値をそのまま使うなら `robot.py calibrate --default`。
3. `robot.py grip 0` と `robot.py grip 100` でグリッパーを確認する。
   動かなければ `robot.py servo 1 90` を試し、`config.h` の `GRIPPER_CH` と角度を直す。

## 使い方

```sh
export ROBOT_HOST=192.168.4.1     # または stackchan.local
python3 client/robot.py say "こんにちは"          # macOS の say で合成して再生、口パクする
python3 client/robot.py face happy --text "やあ"
python3 client/robot.py head --yaw 30 --pitch 45
python3 client/robot.py drive --y 50 --ms 1000    # 前進。指定時間で自動停止（最大 5 秒）
python3 client/robot.py drive --x 50              # 右へ平行移動
python3 client/robot.py drive --rot 50            # 旋回
python3 client/robot.py grip 100
python3 client/robot.py stop                      # 画面下の左ボタンでも停止
```

Python から:

```python
from robot import Robot
r = Robot("192.168.4.1")
r.face("happy"); r.say("こんにちは"); r.drive(y=50, ms=1000)
```

## コマンド

`POST /cmd` に JSON を送る。USB シリアル（115200 bps）に 1 行 1 JSON でも同じ。

| cmd | 引数 |
|-----|------|
| `status` | なし |
| `face` | `expression`: neutral / happy / angry / sad / doubt / sleepy、`text`: 吹き出し |
| `head` | `yaw` -120〜120、`pitch` 5〜85（度）、`speed` 1〜1000 |
| `calibrate` | `default`: true で既定値を採用 |
| `torque` | `on`: true / false |
| `drive` | `x` `y` `rot` -100〜100、`ms` 継続時間 |
| `grip` | `percent` 0（開）〜100（閉） |
| `servo` | `ch` 0/1、`angle` 0〜180（RoverC のサーボを直接） |
| `stop` | 車輪、首、音声を止める |
| `volume` | `value` 0〜255 |
| `beep` | `freq` `ms` |

`POST /speak` に 16bit PCM の WAV（2 MB まで）を送ると再生する。

## テスト

```sh
c++ -std=c++17 -Ifirmware/include firmware/test_host/test_mecanum.cpp -o /tmp/t && /tmp/t
```
