"""Test new classes in battle through the harness (never saves): boot the game if needed, hire one unit of each
class, enter the first stage and deploy them.  Prints the deployed units' names.

    python tools/class_battle_test.py "Onmyo Monk" "Beast Master"

Then cast with battle_nav (cast / run_actions / end_turn), e.g. tools/class_battle_test.py --cast Mud "Talisman Storm" 7 5
"""
import sys
import time

import battle_nav as b
import hire_test as h
from d5ctl import Ctl

POS = [(7, 3), (6, 2), (8, 2), (7, 2)]


def dispatch_names(c):
    """names and class titles in the base panel's dispatch list"""
    b.goto(c, *b.state(c)["base"])
    c.keys("K:1:10"); time.sleep(1.2)
    seen = []
    for _ in range(3):
        for _ in range(40):
            t = b.texts(c)
            if "Choose a character to dispatch." in t:
                i = t.index("Choose a character to dispatch.")
                seen.append(tuple(t[i + 1:i + 3]))
            c.keys("S:1:8"); time.sleep(0.2)
        c.keys("D:3:20"); time.sleep(0.8)
    c.keys("L:1:10"); time.sleep(0.8)
    return list(dict.fromkeys(seen))


def main(classes):
    c = Ctl()
    if not b.state(c).get("battle"):
        for name in classes:
            h.open_hire(c)
            print(name, "class:", h.pick_class(c, name), "hired:", h.create(c, log=lambda *a: None))
            for _ in range(4):
                c.keys("L:4:30"); time.sleep(0.6)
        print("battle:", b.enter_stage(c))
    names = dispatch_names(c)
    titles = [t for n, t in names]
    hired = [n for n, t in names][-len(classes):]
    for name, pos in zip(hired, POS):
        print("deploy", name, b.deploy(c, name, to=pos), b.unit(c, name) and b.unit(c, name)["p"])
        b.set_hp(c, name)
        b.set_sp(c, name)
    print("units:", [(u["name"], u["team"], u["p"]) for u in b.state(c)["units"]], titles[-len(classes):])


if __name__ == "__main__":
    if sys.argv[1:2] == ["--cast"]:
        c = Ctl()
        name, skill, x, y = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
        print("cast", b.cast(c, name, skill, (x, y)))
        prefix = sys.argv[6] if len(sys.argv) > 6 else None
        print(len(b.run_actions(c, prefix=prefix, n=90)), "frames")
    else:
        main(sys.argv[1:])
