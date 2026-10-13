"""From the hub: talk to the Recruiter, pick a class in Hire Character and go through creation with the defaults
(name as given, Good-for-nothing, -5 on HP, level, personality, ...).  Prints the screen texts of every step.
python hire_test.py "Onmyo Monk" [steps]   -- never saves the game."""
import sys
import time

from d5ctl import Ctl
from walk import go_to_npc

RECRUITER = (303, 158)


def texts(c):
    return [x[4] for x in c.cmd("texts")["list"]]


def open_hire(c):
    """teleport to the Recruiter (walks there only the first time, to learn the spot) and open Hire Character"""
    for _ in range(3):
        if go_to_npc(c, "Recruiter", RECRUITER):
            break
    c.keys("K:4:60"); time.sleep(1.6)
    c.keys("K:4:60"); time.sleep(1.2)
    c.keys("K:4:90"); time.sleep(2.0)


def pick_class(c, name):
    for _ in range(60):
        t = texts(c)
        if t and t[0] == name:
            return True
        c.keys("A:4:20"); time.sleep(0.5)
    return False


def create(c, steps=10, log=print):
    """class chosen in the carousel -> through every creation screen with the defaults -> True when recruited"""
    c.keys("K:4:60"); time.sleep(1.5)                                     # class -> name entry
    c.keys(" ".join(["S:3:10"] * 6)); time.sleep(0.6)                     # cursor on Confirm
    c.keys("K:4:60"); time.sleep(1.4)                                     # name
    c.keys("K:4:60"); time.sleep(1.4)                                     # capability (default)
    for i in range(steps + 6):
        t = texts(c)
        log(i, t[:8])
        if any("recruited" in x for x in t):
            c.keys("K:4:60"); time.sleep(1.4)
            return True
        if any("Bonus Points" in x for x in t):
            # spend / take back the bonus on HP until the screen accepts it
            c.keys(" ".join(["D:2:6"] * 12)); time.sleep(0.5)
            c.keys("K:4:60"); time.sleep(1.2)
            if any("Bonus Points" in x for x in texts(c)):
                c.keys("L:2:10"); time.sleep(0.6)       # close the "points remaining" note
                c.keys(" ".join(["A:2:6"] * 24)); time.sleep(0.5)
                c.keys("K:4:60"); time.sleep(1.2)
            continue
        c.keys("K:4:60"); time.sleep(1.4)
    return False


if __name__ == "__main__":
    c = Ctl()
    open_hire(c)
    print("class:", pick_class(c, sys.argv[1]), texts(c)[:3])
    create(c, int(sys.argv[2]) if len(sys.argv) > 2 else 8)
