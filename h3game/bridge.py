"""
ブラウザの画面から H3 を動かす橋渡しサーバー。
  ./start.command   (または python3 bridge.py)
  → ブラウザで http://localhost:8891 を開く(大きいディスプレイに出す)
H3 が未接続でも「空回りモード」で画面だけ動く。
H3_DRY=1 を付けると、H3 がつながっていても席には何も送らない(画面の確認用)。
"""
import json, os, sys, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PORT = int(os.environ.get("H3_PORT", 8891))
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
INPUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input.json")   # 機器の割り当て
rig = None
pads = {"list": [], "t": 0.0}   # joy_reader.py から届く スティック・ペダルの最新値

def joy_thread():
    # joy_reader.py を子プロセスで動かし、止まったら起動し直す
    import subprocess
    me = os.path.dirname(os.path.abspath(__file__))
    while True:
        try:
            pr = subprocess.Popen([sys.executable, "-u", os.path.join(me, "joy_reader.py")],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            for line in pr.stdout:
                try:
                    pads["list"] = json.loads(line); pads["t"] = time.time()
                except Exception:
                    pass
        except Exception as e:
            print("joy_reader エラー:", e)
        pads["list"] = []
        time.sleep(2)

def gemini(prompt, want_json=False, image_b64=None, timeout=25, audio_b64=None):
    """Gemini に聞く(ゲームの仕掛け人など)。キーは ~/.gemini_env の GEMINI_API_KEY。失敗したら "" を返す。"""
    import urllib.request, re
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        try:
            for line in open(os.path.expanduser("~/.gemini_env")):
                m = re.search(r'GEMINI_API_KEY\s*=\s*"?([^"\s]+)', line)
                if m: key = m.group(1)
        except Exception: pass
    if not key: return ""
    parts = [{"text": prompt}]
    if image_b64: parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
    if audio_b64: parts.append({"inline_data": {"mime_type": "audio/wav", "data": audio_b64}})   # マイクの録音(WAV)
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": 1.0, "maxOutputTokens": 4096,
                                 "thinkingConfig": {"thinkingBudget": 0}}}   # 考える枠を切って速く・切れずに答えさせる
    if want_json: body["generationConfig"]["responseMimeType"] = "application/json"
    req = urllib.request.Request("https://generativelanguage.googleapis.com/",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    # 混み合い(429)なら少し待って再試行、それでもだめなら軽いモデル(flash-lite)で一度だけ
    for attempt, model in enumerate(["gemini-2.5-flash", "gemini-2.5-flash", "gemini-2.5-flash-lite"]):
        req.full_url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (model, key)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
            return "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
        except Exception as e:
            print("Gemini エラー(%s, %d回目):" % (model, attempt + 1), e)
            if "429" in str(e): time.sleep(2.5); continue
            return ""
    return ""

LLM_URL = os.environ.get("H3_LLM_URL", "http://192.168.100.143:8080/v1/chat/completions")   # OpenAI 互換の chat/completions(llama.cpp server, Ollama など)
LLM_MODEL = os.environ.get("H3_LLM_MODEL", "")   # Ollama のようにモデル名が必要なサーバーでは指定する

def llm(prompt, want_json=False, timeout=15):
    """文字だけの LLM に聞く(音声は渡せない)。失敗したら "" を返す。"""
    import urllib.request
    body = {"messages": [{"role": "user", "content": prompt}], "temperature": 0.8, "max_tokens": 300}
    if LLM_MODEL: body["model"] = LLM_MODEL
    if want_json: body["response_format"] = {"type": "json_object"}
    try:
        req = urllib.request.Request(LLM_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    except Exception as e:
        print("LLM エラー:", e)
        return ""

def hid_list():
    """Mac が見ている USB の入力機器(スティック・ペダルなど)。Apple 内蔵は除く。"""
    import re, subprocess
    try: out = subprocess.run(["ioreg", "-c", "IOHIDDevice", "-r", "-l"], capture_output=True, text=True, timeout=5).stdout
    except Exception: return []
    res, seen = [], set()
    for blk in out.split("+-o ")[1:]:
        head = blk.split("\n", 1)[0]
        if "IOHIDDevice" not in head: continue
        def f(k):
            m = re.search(r'"%s" = "?([^"\n]*)"?' % k, blk); return m.group(1).strip() if m else ""
        prod, ven, man = f("Product"), f("VendorID"), f("Manufacturer")
        if not prod or ven in ("1452", "0", "") or man == "Apple": continue
        key = (prod, ven, f("ProductID"))
        if key in seen: continue
        seen.add(key); res.append({"product": prod, "manufacturer": man, "vendor": ven, "productId": f("ProductID")})
    return res
state = {"pitch": 0.0, "roll": 0.0, "yaw": 0.0, "connected": False, "port": None, "gain": 0.35,
         "auto": False}  # auto=True: 誰も操作していない間は自動でゆっくり揺れる(乗り降りの邪魔になるので既定は切)
last_cmd = 0.0          # 最後に画面から指示が来た時刻
sync = {"text": "{}", "frame": b""}   # 観戦用: プレイ中の画面の様子(ハチ公の位置など)
owner = 0               # 一番新しく開いた画面だけを受け付ける(古いタブの信号は無視)

DRY = bool(os.environ.get("H3_DRY"))   # 席に何も送らない

def connect():
    global rig
    if DRY:
        state["connected"], state["port"] = False, None
        return print("H3_DRY: 席には送りません(空回りモード)")
    try:
        from h3_direct import H3
        rig = H3(gain=state["gain"])
        state["connected"], state["port"] = True, rig.port
        print("H3 接続:", rig.port)
    except Exception as e:
        state["connected"], state["port"] = False, None
        print("H3 未接続(空回りモード):", e)

def auto_sway(t):
    # 波のようにゆっくり揺れる(前後・左右・横振りを少しずつ違う速さで)
    import math
    return (math.sin(t * 0.9) * 0.5,          # pitch
            math.sin(t * 0.6 + 1.0) * 0.6,    # roll
            math.sin(t * 0.4 + 2.0) * 0.3)    # yaw

def watcher():
    # 未接続のあいだ 3秒ごとに USB を探して、見つかったら自動でつなぐ
    while True:
        time.sleep(3)
        if not state["connected"] and not DRY:
            try:
                from h3_direct import find_port
                find_port()
                connect()
            except Exception:
                pass

def sender():
    global rig
    # 60回/秒で最新の傾きを送り続ける(止めると本体が力を弱めるため)
    while True:
        if state["auto"] and time.time() - last_cmd > 2.0:
            state["pitch"], state["roll"], state["yaw"] = auto_sway(time.time())
        elif not state["auto"] and time.time() - last_cmd > 1.0:
            # 画面からの信号が止まったら(タブを閉じた等)ゆっくり中央へ戻す
            for k in ("pitch", "roll", "yaw"): state[k] *= 0.95
        if rig:
            try:
                rig.gain = state["gain"]
                rig.move(state["pitch"], state["roll"], state["yaw"])
            except Exception as e:
                print("送信エラー:", e)
                try: rig.ser.close()
                except Exception: pass
                rig = None; state["connected"], state["port"] = False, None
        time.sleep(1 / 60)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        try: self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError): pass   # 相手が先に切っただけ。ログに出さない
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/pads": return self._json({"pads": pads["list"] if time.time() - pads["t"] < 1.0 else [], "src": "mac"})
        if path == "/frame.jpg":                      # プレイ画面の最新の1枚
            b = sync["frame"]; self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(b))); self.end_headers()
            try: self.wfile.write(b)
            except (BrokenPipeError, ConnectionResetError): pass
            return
        if path == "/sync":                           # 観戦ページが読む
            b = sync["text"].encode(); self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers()
            try: self.wfile.write(b)
            except (BrokenPipeError, ConnectionResetError): pass
            return
        if path == "/state":
            state["last_cmd_age"] = round(time.time() - last_cmd, 1) if last_cmd else None
            return self._json(state)
        if path == "/reconnect": connect(); return self._json(state)
        if path == "/hid": return self._json(hid_list())
        if path == "/claim":                          # 席の操作権をこの画面に移す(確認画面の「席を試す」用)
            global owner; owner += 1; return self._json({"owner": owner})
        if path == "/input.json":
            try: return self._json(json.load(open(INPUT_JSON)))
            except Exception: return self._json({})
        # 画面: /=ゲーム  /devices=機器の確認  /template=雛形  それ以外は web/ の中のファイル
        name = {"/": "index.html"}.get(path, path.lstrip("/"))
        p = os.path.join(WEB, os.path.basename(name))
        if not os.path.isfile(p): self.send_response(404); self.end_headers(); return
        b = open(p, "rb").read()
        if p.endswith(".html"):
            peek = "peek" in self.path or name == "devices.html" or path == "/watch" or self.client_address[0] not in ("127.0.0.1", "::1")   # 他のPCから開いた画面は操作権を取らない   # 確認用の画面は操作権を奪わない
            if not peek: owner += 1
            my = owner if not peek else -1
            b = b.replace(b"__OWNER__", str(my).encode()); ctype = "text/html; charset=utf-8"
        else: ctype = "application/javascript; charset=utf-8" if p.endswith(".js") else "audio/mpeg" if p.endswith(".mp3") else "application/octet-stream"
        self.send_response(200); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers()
        try: self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError): pass   # 相手が先に切っただけ。ログに出さない
    def do_POST(self):
        global last_cmd
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) or b"{}"
        if self.client_address[0] not in ("127.0.0.1", "::1") and self.path.split("?")[0] in ("/", "/sync", "/frame"):
            return self._json({"ignored": True})      # 他のPCの画面は席・観戦の映像を動かせない(見るだけ)
        if self.path.split("?")[0] == "/frame":        # プレイ画面の絵(JPEG)
            sync["frame"] = raw; return self._json({"ok": True})
        if self.path.split("?")[0] == "/sync":         # プレイ中の画面が様子を送る
            sync["text"] = raw.decode("utf-8", "replace"); return self._json({"ok": True})
        d = json.loads(raw)
        if self.path.split("?")[0] == "/ai":           # AI に聞く {prompt, json}
            # Gemini のキーがあれば音声ごと渡す。無ければ会場の LLM に文字だけで聞く
            text = gemini(d.get("prompt", ""), bool(d.get("json")), d.get("image") or None, audio_b64=d.get("audio") or None) \
                or llm(d.get("prompt", ""), bool(d.get("json")))
            return self._json({"text": text})
        if self.path.split("?")[0] == "/input.json":   # 機器の割り当てを保存
            json.dump(d, open(INPUT_JSON, "w"), ensure_ascii=False, indent=1); return self._json({"saved": True})
        global owner
        o = int(d.get("owner", -1))
        if o > owner: owner = o            # サーバー再起動後も、開いたままの画面(番号が大きい)を引き継ぐ
        if o != owner:
            state["ignored"] = state.get("ignored", 0) + 1
            return self._json({"ignored": True})
        state["last_cmd_age"] = 0.0
        if "auto" in d: state["auto"] = bool(d["auto"])
        if any(k in d for k in ("pitch", "roll", "yaw")): last_cmd = time.time()
        for k in ("pitch", "roll", "yaw"):
            if k in d: state[k] = max(-1.0, min(1.0, float(d[k])))
        if "gain" in d: state["gain"] = max(0.0, min(1.0, float(d["gain"])))
        self._json(state)

if __name__ == "__main__":
    connect()
    threading.Thread(target=sender, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()
    threading.Thread(target=joy_thread, daemon=True).start()
    print(f"画面: http://localhost:{PORT}")
    try:
        ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
    finally:
        if rig: rig.close()
