"""Measure the running game's frame rate through the harness: presented frames per second, game-loop ticks per
second (d5_frame calls), the vsync interval the game passes to Present and the battle skit fast-forward state
(ff: the game's options always/level, the render divisor mult, and the harness setting: 'set skitff 0|2|3|4|-1').
Normal play: ~60 presents/s and ticks/s; during a fast-forwarded skit ticks/s = mult x presents/s.

python tools/fps.py [seconds] [focus on|off]
"""
import json
import sys
import time

from d5ctl import Ctl


def sample(c):
    s = json.loads(c.raw("state"))
    return s["presents"], s["frame"], s["ms"], s["sync"]


def measure(c, seconds=3.0):
    p0, f0, t0, _ = sample(c)
    time.sleep(seconds)
    p1, f1, t1, sync = sample(c)
    dt = max(1, t1 - t0) / 1000.0
    ff = json.loads(c.raw("state")).get("ff")
    return dict(presents_per_s=round((p1 - p0) / dt, 1), ticks_per_s=round((f1 - f0) / dt, 1), sync=sync, ff=ff)


if __name__ == "__main__":
    c = Ctl()
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    if len(sys.argv) > 3:
        c.cmd(f"focus {sys.argv[3]}")
        time.sleep(0.5)
    print(measure(c, secs))
