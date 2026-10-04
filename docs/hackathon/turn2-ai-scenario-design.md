# turn 2: AI シナリオで StackChan と toio 9 台を同時に動かす 設計

- 日付: 2026-10-04 / 方針: Opus、実装: Grok Build / ブランチ: `ai-scenario`
- 前提: StackChan ハブ `client/stackchan_hub.py`（127.0.0.1:8766、実装・実機確認済み）、
  toio ハブ（127.0.0.1:8765、別ワークツリー smooth-closet で実装中。API は同計画書どおり）

## 流れ

```
短い行動方針（日本語 1 行）
  └─ generate: GPU マシンの Qwen2.5-3B（OpenAI 互換、JSON スキーマ制約付き）→ シナリオ JSON
       └─ normalize: 検証・補正（列挙外の値、長すぎるセリフ、空のステップ）
            └─ executor: ステップごとに StackChan と toio を並行実行し、両方終わったら次へ
                 ├─ StackChan ハブ :8766（say は喋り終わるまで待つ）
                 └─ toio ハブ :8765（move_all は到着まで待つ）
```

## 方針

1. **AI には語彙から選ばせ、座標は考えさせない。** 3B モデルは座標や台数の整合が苦手。
   隊形・踊り・色・表情・視線・体の動きを列挙値で選ばせ、マスや割り当てはプログラムが計算する。
2. **JSON スキーマ制約（llama.cpp の `response_format: json_schema`）で必ず形を守らせる。**
   実測: 4 ステップのシナリオが約 4 秒、壊れた JSON なし。
3. **単調さはプロンプトで防ぐ。** 語彙の意味、ステップごとに変化させる規則、別の方針での例を 1 つ渡す。
4. **生成と実行を分ける。** 生成結果は `scenarios/` に保存し、本番は保存済みを再生できる（デモの保険）。
5. **止まらないこと優先。** 片方のハブが無い、コマンドが失敗した、といった場合も記録して次へ進む。Ctrl-C で全停止。

## シナリオ JSON（AI の出力）

| キー | 値 |
|------|----|
| `title` | 30 文字以内 |
| `steps[]` | 3〜8 個。各ステップ: |
| `say` | StackChan のセリフ（40 文字以内、空可） |
| `face` | neutral / happy / angry / sad / doubt / sleepy |
| `look` | center / left / right / up / down / toio |
| `body` | none / wiggle / turn_left / turn_right / nod / dance（RoverC のその場の動き） |
| `toio_move` | none / square / circle / line / heart / x / scatter / home（隊形）、spin / wiggle / wave（その場の踊り） |
| `toio_group` | all / odd / even（踊りの対象。隊形は常に全台） |
| `toio_color` | none / red / green / blue / yellow / purple / white / rainbow / off |
| `toio_sound` | none / ok / ng / cheer / beep |
| `pause` | 0〜5 秒（ステップ後の間） |

## 実行の対応表

- 隊形: 7 × 5 マスに 9 マスずつ定義。今いる場所から近い順に台を割り当て、`move_all` で同時に動かす。
- toio の踊り: spin（その場回転）、wiggle（左右に小刻み）、wave（番号順に少しずつずらして回転）。`drive` で行う。
- StackChan の視線: center (0,45)、left (40,50)、right (-40,50)、up (0,80)、down (0,15)、toio (0,20)。
- StackChan の体: wiggle（左右に往復）、turn_left/right（その場旋回）、nod（前後に往復）、dance（組み合わせ）。
- 1 ステップ内は「表情 → 視線 → セリフ（終わるまで待つ）」「体の動き」「toio」の 3 本を並行。全部終わって `pause` 後に次へ。
