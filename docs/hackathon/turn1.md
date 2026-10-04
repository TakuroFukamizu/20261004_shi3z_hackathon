# ハッカソン turn 1 記録: StackChan + RoverC Pro の制御基盤

- 日付: 2026-10-04
- git タグ: `hackathon-turn1`（この記録を含むコミット）
- ブランチ: `stackchan-control-setup`

## 目的

M5Stack 公式 StackChan のボディ（K151）を RoverC Pro に載せた機体を PC から動かす。
顔と声が出せること。具体的な振る舞いは後で決めるので、全部品を動かせる土台を作る。

## ハードウェア構成（実機で確認済み）

| 部品 | 内容 |
|------|------|
| StackChan の頭 | **Core2**（CoreS3 ではない）。ボディのサーボ TX=G27 / RX=G19、IO エキスパンダ 0x6F |
| RoverC Pro | 自前の **M5StickC Plus** が I2C（G0/G26）で制御。Core2 とはケーブルで繋がっていない |
| 接続 | PC ─ Wi-Fi(HTTP) ─ Core2 ─ ESP-NOW ─ StickC Plus |
| Wi-Fi | 会場の `gikenbase-member`、Core2 の IP は `192.168.100.29`（`stackchan.local`） |

## 作ったもの

| 場所 | 内容 |
|------|------|
| `firmware/` | Core2 用。顔（M5Stack-Avatar）、声（WAV 再生と口パク）、首（BSP のサーボ部品を Core2 向けに初期化）、HTTP とシリアルの JSON コマンド、ESP-NOW で走行系を転送 |
| `firmware-rover/` | StickC Plus 用。車輪（メカナム）とグリッパー。Core2 のビーコンでチャンネルを自動追従、途切れたら停止 |
| `client/robot.py` | PC 用 CLI 兼ライブラリ。`say` は macOS の `say` で合成して送る |
| `client/dance/` | `res/` の 3 曲用の固定振付スクリプト。曲ごとに動きの性格を変え、車輪は元の位置に戻る |

コマンドは `face` `head` `calibrate` `torque` `drive` `grip` `servo` `stop` `volume` `beep` `status`、
音声は `POST /speak`。詳細は README。

## 確認できたこと

- 両方のマイコンへの書き込み、起動、ボディとサーボと RoverC の検出、ESP-NOW のリンク
- PC から Wi-Fi 経由で状態取得、表情、発話。ユーザーが「全部動いた」と確認
- 振付スクリプトは疑似ロボット相手に、全コマンドが予定時刻から 8 ms 以内に届くこと

## 決めたこと・分かったこと

- StackChan-BSP の `M5StackChan.begin()` は GPIO6/7 固定で Core2 では使えない。部品を個別に使う
- ボディのタッチセンサ（0x68）と Core2 の IMU が衝突するため、両方使わない
- Core2 から StickC への指示は ESP-NOW（ユーザー提案）。送りっぱなしで 240 バイトまで
- ビルドは `uvx --python 3.12 platformio run`。StickC の書き込みは 115200 bps
- 元のファームウェアは `backup/`（git 管理外）

## 残課題（turn 1 時点）

- 振付スクリプトは実機未確認。曲 3 は毎秒約 9 コマンドで最も負荷が高い
- コマンドは 1 回ごとの HTTP で、機体からの状態通知がない。turn 2 でリアルタイム化する
