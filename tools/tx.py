"""print the screen text (drawn last frame) compactly: python tools/tx.py [keys...]"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from d5ctl import Ctl
c = Ctl()
if len(sys.argv) > 1:
    c.keys(" ".join(sys.argv[1:]))
d = c.cmd("texts")
st = c.state()
print(f"mode {st['mode']} iw {st['iw']}/{st['floormap']} battle {st['battle']} flags {st['flags']}  sms " +
      " ".join(f"{e[0]}:{e[2]}" for e in c.cmd('sms').get('list', [])))
for e in d.get("list", []):
    print(f"  ({e[0]:4},{e[1]:4}) a{e[2]:<3} {e[3]} c{e[5] if len(e) > 5 else ''} {e[4]!r}")
