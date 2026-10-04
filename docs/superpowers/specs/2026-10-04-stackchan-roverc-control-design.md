# StackChan + RoverC Pro 制御ソフト基盤 設計書

- 日付: 2026-10-04
- 状態: 実装済み（Core2 向けビルド確認済み、実機未確認）。実際のコマンド仕様は README を正とする

## 1. 目的

M5Stack 公式 StackChan のボディ（K151）に RoverC Pro（K036-B）を組み合わせたロボットを、
PC から自由に動かせるソフト基盤を整備する。具体的な振る舞いは後で決めるため、
今回は「部品を全部動かせる土台」と「PC から叩けるコマンド口」までを作る。

### ユーザーが明示した要件

- StackChan と RoverC Pro を組み合わせた機体を制御できること
- StackChan は顔と声が出せること
- 具体的な制御内容は後で考える
- コントローラは CoreS3 ではなく **M5Stack Core2**

### こちらで置いた前提（レビューで訂正してください）

| # | 前提 | 根拠 |
|---|------|------|
| A1 | ボディは K151 付属のもの（シリアルバスサーボ SCS0009 ×2、IO エキスパンダ、LED 12 個）で、Core2 を M-Bus に挿している | 製品リンクとユーザーの指摘 |
| A2 | RoverC Pro は Core2 の Port A（赤い Grove、G32/G33）に I2C で接続 | 写真で赤い Grove ポートが見える。RoverC は I2C アドレス 0x38 |
| A3 | 開発環境は PlatformIO + Arduino フレームワーク | PlatformIO がインストール済み |
| A4 | 「声」は日本語の任意テキスト発話。音声合成は PC 側で行い、機体は受け取った音声を再生して口パクする | 制御内容が未定のため、機体側を固定しない方が後で楽 |
| A5 | 操作は PC から Wi-Fi（HTTP）と USB シリアルの両方で行える | 走行する機体なので無線が必要。シリアルはデバッグ用 |

## 2. 調査で確定した事実

- **StackChan-BSP 1.1.0 は Core2 ではそのまま使えない。** `M5StackChan.begin()` がサーボ UART を
  GPIO6/7 に固定している。Core2（ESP32）では GPIO6/7 は SPI フラッシュ用で、使うとクラッシュする。
- BSP 内の部品（`SCSCL` サーボバス、`PY32IOExpander_Class`、`stackchan::motion::Motion`）は
  個別にインクルードでき、Core2 向けにビルドが通る（使い捨てプローブで確認済み）。
- BSP には顔と音声の API は無い。顔は M5Stack-Avatar、音は M5Unified の `M5.Speaker` を使う。
- BSP は arduino-esp32 3.x 系が必要。標準の PlatformIO `espressif32` プラットフォームではなく
  pioarduino 版を使う。pioarduino は Python 3.10 以上が必要で、この Mac の `pio`（Python 3.9）では
  動かない。`uvx --python 3.12 platformio` なら動く。
- M5-RoverC ライブラリは使わない。`setServoPulse` が 16bit 値の 1 バイトしか書かないバグがあり、
  `begin()` が `Wire` を取り直して M5Unified と競合する。

### ビルド確認済みの構成

| 項目 | 値 |
|------|----|
| platform | pioarduino `platform-espressif32` stable（espressif32@55.3.312） |
| board | `m5stack-core2` |
| M5Unified | 0.2.25 |
| StackChan-BSP | 1.1.0（git 8d4d6fc） |
| M5Stack-Avatar | 0.10.0 |

### M-Bus のピン対応（CoreS3 → Core2）

| 役割 | CoreS3 | Core2 | 備考 |
|------|--------|-------|------|
| 内部 I2C SDA/SCL | G12/G11 | G21/G22 | M5Unified の `In_I2C` が自動対応 |
| サーボ TX/RX | G6/G7 | G27/G19 | バス位置 21/22 の対応から TX=G27、RX=G19 を初期値とする |
| Port A SDA/SCL | G2/G1 | G32/G33 | M5Unified の `Ex_I2C` が自動対応 |

### 実機でしか確認できない点

1. サーボ TX=G27、RX=G19 で ID1 に ping が通るか。通らない場合だけ入れ替えを検討する。
   半二重バスなので、気軽に両方試すことはしない。
2. ボディの IO エキスパンダ（0x6F）と電流計（0x41）が Core2 の内部 I2C から見えるか。
3. ボディのタッチセンサ Si12T（0x68）は Core2 内蔵 IMU の MPU6886（0x68）と衝突する。
   今回はタッチセンサも IMU も使わない。`M5.begin()` の設定で `internal_imu = false` にして、
   M5Unified が 0x68 に IMU の設定値を書き込まないようにする。
4. RoverC のグリッパーがサーボ ch0 と ch1 のどちらか。
5. Grove ケーブルの 5V。Core2 と RoverC（16340 電池）の両方が 5V を出す可能性がある。
   通電前に M5Stack の資料で確認するか、5V 線を外すことを推奨する。
6. 首の原点。Core2 には校正値が保存されていないため BSP の既定値に戻る。
   pitch の端で無理をするとサーボが壊れると資料にあるので、初回起動時に必ず原点校正を行う。

## 3. 全体構成

```
PC (Python クライアント)  ──HTTP / USB シリアル──▶  Core2 ファームウェア
  ・テキスト→音声合成                               ├─ Face   (M5Stack-Avatar)
  ・コマンド送信                                    ├─ Voice  (M5.Speaker で PCM 再生 + 口パク)
                                                    ├─ Head   (BSP Motion + 自前のボディ初期化)
                                                    ├─ Rover  (自前 I2C ドライバ, Ex_I2C, 0x38)
                                                    └─ Command (JSON コマンドの解釈)
```

リポジトリ構成:

```
firmware/            PlatformIO プロジェクト
  platformio.ini
  include/config.h   ピン、Wi-Fi、各種上限値
  src/main.cpp
  src/body/          ボディ初期化（IO エキスパンダ、サーボ電源、サーボバス）
  src/face/  src/voice/  src/head/  src/rover/  src/command/
  test/              ホスト上で走る単体テスト（メカナム計算、コマンド解釈）
client/              Python パッケージ（uv 管理）と CLI
docs/                配線、書き込み手順、実機確認手順
```

## 4. モジュール

### Body
BSP の `M5StackChan.begin()` の代わり。`M5.begin()` の後、IO エキスパンダでサーボ電源を入れ、
`config.h` のピンでサーボバスを開く。IO エキスパンダが見つからなければ Head を無効にして続行する。

### Face
M5Stack-Avatar の薄いラッパー。表情（neutral / happy / angry / sad / sleepy / doubt）、
吹き出し文字、口の開き具合を設定できる。Avatar の初期化は Body 初期化の後に行う。

### Voice
インターフェースは「16bit モノラル PCM を再生する」と「再生中か」の 2 つ。
再生中は音量から口の開き具合を計算して Face に渡す。
機体側は合成エンジンを持たない。動作確認用にビープ音と内蔵の短い音声 1 つを持つ。

音声合成の候補（PC 側で差し替え可能）:

| 方式 | 長所 | 短所 |
|------|------|------|
| **macOS `say`（初期値として推奨）** | 追加インストール不要、無料 | 声質は普通 |
| VOICEVOX | 声質が良い、無料 | PC で VOICEVOX エンジンの起動が必要 |
| 機体内蔵 AquesTalk | Wi-Fi 不要 | 評価版以外は有償ライセンス。今回は採用しない |

### Head
BSP の `Motion` を使う。yaw は ±128°、pitch は資料の警告に従い 5〜85° に制限する。
BSP の `ScsServo` は非公開クラスなので、同等の約 100 行を自前で持つ。
原点校正（今の姿勢を原点として保存）を提供する。校正が済むまで首は動かさない。

### Rover
`M5.Ex_I2C` で 0x38 に直接書く自前ドライバ。

| レジスタ | 内容 |
|----------|------|
| 0x00〜0x03 | 4 輪の速度、int8、-100〜100 |
| 0x10, 0x11 | サーボ角度、0〜180 |

- `drive(x, y, rot)` はメカナムの混合計算を行う（純粋関数として分離し、ホストでテスト）。
- **ウォッチドッグ**: 最後の走行コマンドから 500 ms 以内に次が来なければ車輪を止める。
- グリッパーは `grip(0〜100%)`。開閉角度とチャンネルは `config.h` で調整する。
- RoverC が見つからなくても、顔・声・首は動く。

### Command
1 行 1 JSON。HTTP（`POST /cmd`）とシリアルで同じ形式を使う。

```json
{"cmd":"face","expression":"happy"}
{"cmd":"head","yaw":30,"pitch":45,"speed":500}
{"cmd":"drive","x":0,"y":50,"rot":0}
{"cmd":"grip","percent":100}
{"cmd":"calibrate"}
{"cmd":"stop"}
{"cmd":"status"}
```

音声は `POST /speak` に WAV を送る。応答は `{"ok":true}` か `{"ok":false,"error":"..."}`。

### PC クライアント
Python パッケージと CLI。例:

```
robot say "こんにちは"
robot face happy
robot drive --y 50 --for 1.0
```

`say` は PC で音声を合成して WAV を機体に送る。

## 5. エラー処理と安全

- 各ハードは起動時に検出し、無ければその機能だけ無効にする。`status` で検出結果を返す。
- 不正なコマンドはエラー応答を返し、機体の状態は変えない。
- 通信が切れると車輪はウォッチドッグで止まる。`stop` は車輪と首の両方を止める。
- Wi-Fi の認証情報は git 管理外のファイルに置く。

## 6. テスト

- **ホスト単体テスト**: メカナム混合計算、角度の制限、コマンド解釈、ウォッチドッグの時間判定。
- **ビルド確認**: `m5stack-core2` 向けにファームウェアがビルドできること。
- **実機確認**: 2 章の 6 項目を順に確かめる手順書を `docs/` に用意する。
  現在 Mac に機体が接続されていないため、実機確認はユーザーが行う。

## 7. 今回やらないこと

- 自律動作、会話 AI、カメラ、マイク入力、NFC、赤外線、LED 演出
- スマホアプリ、OTA 更新
