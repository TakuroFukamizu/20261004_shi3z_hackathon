"""Ask a local OpenAI-compatible LLM for a scenario constrained by JSON schema."""
import copy
import json
import sys
import urllib.error
import urllib.request

from schema import SCENARIO_SCHEMA

# One worked example for a policy the caller is not using. The model copies
# this shape; the rules below tell it not to copy the subject or the sequence.
EXAMPLE_POLICY = "じゃんけんで勝負する"
EXAMPLE = {
    "title": "じゃんけん大会",
    "steps": [
        {"say": "じゃんけんで勝負だよ", "face": "happy", "look": "center",
         "body": "nod", "toio_move": "home", "toio_group": "all",
         "toio_color": "blue", "toio_sound": "ok", "pause": 1},
        {"say": "ぐー、丸く集まれ", "face": "doubt", "look": "toio",
         "body": "none", "toio_move": "circle", "toio_group": "all",
         "toio_color": "yellow", "toio_sound": "beep", "pause": 1},
        {"say": "奇数チーム、くるっと回って", "face": "sleepy", "look": "left",
         "body": "wiggle", "toio_move": "spin", "toio_group": "odd",
         "toio_color": "rainbow", "toio_sound": "none", "pause": 1},
        {"say": "ちょきの勝ち、またね", "face": "sad", "look": "down",
         "body": "turn_right", "toio_move": "line", "toio_group": "all",
         "toio_color": "purple", "toio_sound": "cheer", "pause": 2},
    ],
}

SYSTEM = """\
あなたはステージの脚本家です。司会ロボット StackChan と、マット上の toio キューブ9台が、渡された方針どおりに短い芝居をします。出力はスキーマどおりの JSON だけです。

登場:
- StackChan は司会。toio と同じ 7列×5行のマットをマス単位で移動し、前のクローでキューブをつかむ。顔、声、首、その場の動きも使う。
- toio はマットに9台。選ぶのは隊形の名前だけ。座標や台数は書かない。

フィールドの意味:
- say: 話す日本語。40文字以内の話し言葉。空文字も可。同じ文を二度使わない。
- face: neutral 普通 / happy うれしい / angry 怒り / sad かなしい / doubt 疑問 / sleepy 眠そう
- look: center 正面 / left 左 / right 右 / up 上 / down 下 / toio キューブを見る
- body: none 静止 / wiggle 左右に揺れる / turn_left 左を向く / turn_right 右を向く / nod うなずく / dance 揺れて左右を向く / chase いちばん近い toio を追ってクローを閉じる / grab その場でクローを閉じてから開く / go_center マット中央のマスへ移動
- toio_move: none 動かない / square 中央の正方形 / circle 円陣 / line 二列 / heart ハート / x バツ印 / scatter 散開 / home 下段へ戻る / spin その場回転 / wiggle 左右に小刻み / wave 番号順に時間差で回転
- toio_group: all 全員 / odd 奇数番号 / even 偶数番号。効くのは spin・wiggle・wave だけ。隊形はいつも9台全員。
- toio_color: none 変えない / red / green / blue / yellow / purple / white / rainbow 台ごとに別の色 / off 消灯
- toio_sound: none 無音 / ok 決定音 / ng キャンセル / beep クリック / cheer ファンファーレ
- pause: ステップのあとに待つ秒。整数 0 から 5。

方針の言葉は toio_move の値にする（セリフだけにしない）:
- ハート → heart を1ステップ
- 円・丸・輪 → circle
- 列・並ぶ・競争のスタート → line
- ばらける・散る → scatter
- 戻る・ホーム → home
- バツ・交差 → x
- 四角 → square
- 回る → spin、ゆれる → wiggle、順番に → wave

規則:
1. 最初のステップは挨拶か自己紹介で、say を入れる。最後のステップは締めのあいさつで、say を入れる。
2. 隣り合うステップで同じ face を使わない。隣り合うステップで同じ toio_move を使わない。circle を毎ステップ使わない。
3. toio_move は none 以外を 3 種類以上。look と body も変え、全部を none にしない。
4. title は今回の方針を短く言う。見本の題名は禁止。
5. 見本の題名・セリフ・隊形の順番をコピーしない。前半を後半で繰り返さない。
6. ステップ数は指定どおり。全キーを埋める。静かな方針では cheer を使わず、sleepy か sad を混ぜる。
7. 逃げる・追いかける・捕まえる方針では、いずれかのステップの body を chase にする。その場でつかむだけなら grab、中央へ戻るなら go_center。
"""


def schema_for(max_steps):
    """Schema whose steps array is capped at max_steps (clamped to 3..8)."""
    count = max(3, min(8, int(max_steps)))
    schema = copy.deepcopy(SCENARIO_SCHEMA)
    schema["properties"]["steps"]["minItems"] = 3
    schema["properties"]["steps"]["maxItems"] = count
    return schema, count


def _strip_fence(text):
    body = text.strip()
    if body.startswith("```"):
        body = body.split("\n", 1)[-1] if "\n" in body else body
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
    return body.strip()


def _scenario_from_body(raw):
    """Pull the scenario object out of an OpenAI chat-completions body."""
    data = json.loads(raw)
    if isinstance(data, dict) and "choices" in data:
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, dict):
            data = content
        else:
            data = json.loads(_strip_fence(content))
    if not isinstance(data, dict) or "steps" not in data:
        raise ValueError("response has no scenario")
    return data


def _post(url, payload, timeout):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def generate(policy, url, model, max_steps, temperature=0.7, seed=None, timeout=60):
    """Return a raw scenario dict. Retry up to twice on HTTP or JSON failure."""
    schema, count = schema_for(max_steps)
    user = (
        f"方針: {policy}\n"
        f"ステップ数: {count}\n"
        "見本とは別のシナリオにする。見本の題名とセリフは使わない。title は方針の要約。\n"
        "各ステップで、直前と違う face、違う look、違う body、違う toio_move を選ぶ。\n"
        "toio_move は none 以外を3種類以上。同じ動きだけで埋めない。\n"
        "方針の形はセリフだけでなく toio_move の値にする"
        "（ハート=heart、円=circle、列=line、ばらける=scatter、戻る=home）。\n"
        "say はすべて別の文。最初は挨拶、最後は締め。同じ3ステップを繰り返さない。"
    )
    payload = {
        "model": model,
        "temperature": temperature,
        "max_tokens": 900,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"方針: {EXAMPLE_POLICY}\nステップ数: 4"},
            {"role": "assistant", "content": json.dumps(EXAMPLE, ensure_ascii=False)},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "scenario", "schema": schema},
        },
    }
    if seed is not None:
        payload["seed"] = int(seed)
    last = None
    for attempt in range(3):
        try:
            return _scenario_from_body(_post(url, payload, timeout))
        except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError, RuntimeError, KeyError, IndexError) as exc:
            last = exc
            if attempt < 2:
                print(f"generate retry {attempt + 1}: {exc}", file=sys.stderr)
    raise RuntimeError(f"generate failed after 3 attempts: {last}") from last
