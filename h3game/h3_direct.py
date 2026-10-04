"""
DOF Reality H3 を USB(シリアル) で直接動かすためのドライバ。
H3 の制御ボードは SMC3 (Arduino) 互換。
  通信: 500000 baud
  コマンド: '[' + 文字 + 上位バイト + 下位バイト + ']'
    'A','B','C' = モーター1,2,3 の目標位置 (0..1023, 中央=512)
  15秒データが来ないとボードは自動で力を弱める(安全機構)

使い方:
    from h3_direct import H3
    with H3() as rig:            # ポートは自動検出。指定は H3("/dev/cu.usbserial-xxx")
        rig.move(pitch=0.3, roll=-0.2, yaw=0.0)   # 各 -1.0..1.0
"""
import glob, sys, time
import serial

CENTER = 512
DEFAULT_GAIN = 0.35   # 最初は弱め。慣れたら上げる (最大 1.0)


def find_port():
    cands = glob.glob("/dev/cu.usbserial*") + glob.glob("/dev/cu.usbmodem*") \
          + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    if not cands:   # Windows(COM番号)など
        try:
            from serial.tools import list_ports
            ps = list(list_ports.comports())
            cands = [p.device for p in ps if "DOF" in (p.description or "") or "Arduino" in (p.description or "")] or [p.device for p in ps]
        except Exception:
            pass
    if not cands:
        raise RuntimeError("H3 の USB が見つかりません。ケーブルと電源を確認してください。")
    return cands[0]


class H3:
    def __init__(self, port=None, gain=DEFAULT_GAIN, max_step=40):
        self.port = port or find_port()
        self.gain = gain              # 全体の振れ幅 (0..1)
        self.max_step = max_step      # 1回の送信で動かす最大量(急な動きを抑える)
        self.cur = [CENTER, CENTER, CENTER]
        self.ser = serial.Serial(self.port, 500000, timeout=0.05)
        time.sleep(1.5)               # Arduino のリセット待ち
        self.center()

    # --- 低レベル ---
    def _send(self, ch, val):
        val = max(0, min(1023, int(val)))
        self.ser.write(b"[" + ch.encode() + bytes([val >> 8, val & 0xFF]) + b"]")

    def set_motors(self, m1, m2, m3):
        """モーター生値 (0..1023)。急変を抑えつつ送る。"""
        tgt = [m1, m2, m3]
        for i in range(3):
            d = max(-self.max_step, min(self.max_step, tgt[i] - self.cur[i]))
            self.cur[i] += d
        for ch, v in zip("ABC", self.cur):
            self._send(ch, v)
        self.ser.flush()

    # --- 高レベル ---
    def move(self, pitch=0.0, roll=0.0, yaw=0.0):
        """
        pitch: +で前が下がる方向(仮)  roll: +で右が下がる(仮)  yaw: 後ろの横振り
        いずれも -1.0..1.0。実機で向きが逆なら符号を変える。
        H3 の並び: モーター1=左前, 2=右前, 3=後ろ(横振り) を想定。
        """
        g = self.gain * 511
        m1 = CENTER + g * ( pitch + roll)
        m2 = CENTER + g * ( pitch - roll)
        m3 = CENTER + g * yaw
        self.set_motors(m1, m2, m3)

    def center(self, steps=30, dt=0.03):
        for _ in range(steps):
            self.set_motors(CENTER, CENTER, CENTER)
            time.sleep(dt)

    def close(self):
        try:
            self.center()
        finally:
            self.ser.close()

    def __enter__(self): return self
    def __exit__(self, *a): self.close()


if __name__ == "__main__":
    # 動作テスト: ゆっくり左右→前後→横振り の順に揺れて中央に戻る
    import math
    with H3(port=sys.argv[1] if len(sys.argv) > 1 else None) as rig:
        print("接続:", rig.port)
        t0 = time.time()
        while time.time() - t0 < 12:
            t = time.time() - t0
            if t < 4:   rig.move(roll=math.sin(t * 2) * 0.6)
            elif t < 8: rig.move(pitch=math.sin(t * 2) * 0.6)
            else:       rig.move(yaw=math.sin(t * 2) * 0.6)
            time.sleep(1 / 60)
        print("テスト終了、中央に戻します")
