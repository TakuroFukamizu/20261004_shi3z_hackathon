# StackChan + RoverC Pro 制御

M5Stack 公式 StackChan のボディ（K151）に **Core2** を載せ、**M5StickC Plus** が制御する RoverC Pro に乗せた機体を PC から動かす。

```
PC ──HTTP / USB シリアル──▶ Core2（顔・声・首）──ESP-NOW──▶ StickC Plus（車輪・グリッパー）
```

PC は Core2 にだけ話しかける。走行系のコマンドは Core2 が ESP-NOW で StickC Plus に転送する。
StickC Plus に Wi-Fi 設定は不要で、Core2 のビーコンを探してチャンネルを自動で合わせる。

- `firmware/` Core2 用ファームウェア（PlatformIO）。顔、声、首、コマンド受付。
- `firmware-rover/` M5StickC Plus 用ファームウェア。車輪、グリッパー。
- `client/robot.py` PC 用 CLI 兼 Python ライブラリ（標準ライブラリのみ）。
- `docs/superpowers/specs/` 設計書。

## 書き込み

pioarduino は Python 3.10 以上が必要なので `uvx` 経由で実行する。

```sh
cd firmware
cp include/secrets.h.example include/secrets.h   # Wi-Fi を書く（省略可）
uvx --python 3.12 platformio run -t upload --upload-port /dev/cu.usbserial-XXXX   # Core2
uvx --python 3.12 platformio device monitor

cd ../firmware-rover
uvx --python 3.12 platformio run -t upload --upload-port /dev/cu.usbserial-YYYY   # StickC Plus
```

StickC Plus の画面は、Core2 と繋がると緑、探索中は黒、RoverC が見つからないと赤になる。
書き込み前の元ファームウェアは `backup/`（git 管理外）に保存してある。戻すには:

```sh
uvx --python 3.12 esptool --port <port> write-flash 0 backup/<file>.bin
```

`secrets.h` が無い、または接続できない場合は、機体がアクセスポイントになる。
SSID は `stackchan-rover`、パスワードは `stackchan`、アドレスは `192.168.4.1`。
起動すると IP アドレスが吹き出しに出る。

## 初回の確認手順

1. `python3 client/robot.py --host <IP> status` で `rover` `body` `servos` が `true` か見る。
   - `rover` が `false` なら StickC Plus の電源と RoverC の電源スイッチを確認する。
2. `robot.py calibrate --default` で首を有効にする（実機で既定の原点が合うことを確認済み）。
   校正するまで首は脱力していて動かない。`robot.py head --yaw 0 --pitch 45` で正面を向けば完了。
   ずれている場合だけ、首を手で正面・水平に保持したまま `robot.py calibrate` を実行する。
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

## プレゼンター（Canon PR7-HY）で操作する

リモコンはキーボードとして見えるので、キー入力を機体のコマンドに変換する。
ボタンと動作の対応は `client/presenter.py` 冒頭の `BINDINGS` で変える。

```sh
uv run client/presenter.py --global --learn   # 各ボタンが送るキー名を表示する
python3 client/presenter.py --dry-run         # 送るコマンドを表示するだけ
python3 client/presenter.py                   # 機体に送る（このターミナルが前面のときだけ）
uv run client/presenter.py --global           # どのアプリが前面でも拾う（入力監視の許可が必要）
```

## コマンド

`POST /cmd` に JSON を送る。USB シリアル（115200 bps）に 1 行 1 JSON でも同じ。
`drive` `grip` `servo` `stop` は StickC Plus の USB シリアルに直接送ることもできる。

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

## 曲に合わせた固定振付（ライブ解析が間に合わない時の保険）

`res/` の 3 曲それぞれに、BPM と尺に合わせて指示を送るスクリプトを用意してある。
振付は `stackchan-dance-controller.html` の 8 カウント名（左へ探索、JUMP!、ATTACK! など）を
そのまま使い、32 拍を 4 周する。周回ごとに動きが強くなり、車輪は往復を対にして元の位置に戻る。

| スクリプト | 曲 | BPM | 尺 |
|-----------|----|-----|----|
| `client/dance/dance_01_chill_quest.py` | 01_chill_quest | 85 | 22.6 秒 |
| `client/dance/dance_02_kawaii_8bit.py` | 02_kawaii_8bit_bonus | 120 | 16.0 秒 |
| `client/dance/dance_03_boss_battle.py` | 03_boss_battle_edm | 140 | 13.7 秒 |

```sh
export ROBOT_HOST=192.168.100.29
python3 client/dance/dance_03_boss_battle.py --dry-run     # 送る内容を表示するだけ
python3 client/dance/dance_03_boss_battle.py               # Mac で曲を流しながら踊る
python3 client/dance/dance_03_boss_battle.py --no-audio    # 曲は会場の音響で流す。開始と同時に Enter 代わりに起動
python3 client/dance/dance_03_boss_battle.py --robot-audio # 曲をロボットのスピーカーで鳴らす
```

主なオプション: `--wait`（Enter で開始）、`--delay 秒`、`--power 0.7`（車輪を弱める）、
`--no-drive`（首と顔だけ）、`--no-grip`、`--audio-latency`（Mac の音とずれる時に調整、既定 0.2 秒）、
`--lead-ms`（動きを早めに送る量、既定 60）、`--wav PATH`。
曲は `res/` を自動で探す。見つからなければ `--wav` か環境変数 `DANCE_RES` で指定する。
Ctrl-C で車輪・首・音声を止め、首を正面に戻す。首の校正が済んでいることが前提。
