"""
スティック・ペダルを Mac 側で直接読む(ブラウザに頼らない)。
bridge.py が子プロセスとして起動し、1行1JSON で 60回/秒 受け取る。
抜き差しにも追従する。
"""
import os, sys, json, time
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")   # 画面の仕組みを使わない(Xreal接続中に固まるのを避ける)
import pygame

pygame.joystick.init(); pygame.display.init()   # pygame.init() は音の機器の確認で固まることがある(Xreal接続時)
joys = []

def rebuild():
    global joys
    joys = []
    for i in range(pygame.joystick.get_count()):
        try:
            j = pygame.joystick.Joystick(i); j.init(); joys.append(j)
        except Exception:
            pass

rebuild()
last_count = -1
while True:
    hot = False
    for ev in pygame.event.get():
        if ev.type in (pygame.JOYDEVICEADDED, pygame.JOYDEVICEREMOVED):
            hot = True
    if hot or pygame.joystick.get_count() != len(joys):
        rebuild()
    out = []
    for i, j in enumerate(joys):
        try:
            out.append({"id": j.get_name(), "index": i,
                        "axes": [round(j.get_axis(a), 3) for a in range(j.get_numaxes())],
                        "buttons": [bool(j.get_button(b)) for b in range(j.get_numbuttons())]})
        except Exception:
            pass
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n"); sys.stdout.flush()
    time.sleep(1 / 60)
