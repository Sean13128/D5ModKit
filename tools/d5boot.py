"""d5boot -- start Disgaea 5 through the test harness and load a save (development tool).

    python tools/d5boot.py [slot]        slot = row in the load list counted from the top (0 = autosave), default:
                                         leave the cursor where the game puts it (the last used save)

Title: the movie / logos are skipped with L (cancel -- never picks a menu entry); CONTINUE is the default entry
once the title menu has settled.  Load list -> K, "Load this data?" defaults to NO -> W, K.
"""
import sys
import time

from d5ctl import Ctl, launch

TITLE_VT = "0x1409bcef0"


def sm_states(c):
    return [(e[0], e[2]) for e in c.cmd("sms").get("list", [])]


def boot(slot=None, log=print):
    c = launch()
    c.cmd("focus on")
    t0 = time.time()
    while True:
        st = sm_states(c)
        if (TITLE_VT, 1) in st:
            break
        if time.time() - t0 > 120:
            raise RuntimeError("the title menu did not come up")
        if not any(v == TITLE_VT for v, s in st):
            c.keys("L:4:30")
        c.wait(30)
    c.wait(200)                               # the menu settles on CONTINUE
    c.keys("K:4:60")                          # -> load list
    if slot is not None:
        c.keys(" ".join(["W:3:8"] * 6))       # to the top (autosave)
        if slot:
            c.keys(" ".join(["S:3:8"] * slot))
    c.keys("K:4:40 W:4:20 K:4:10")            # load this data? -> YES
    t0 = time.time()
    while c.state().get("mode") != 8:
        if time.time() - t0 > 60:
            raise RuntimeError("the save did not load")
        c.wait(30)
    c.wait(120)
    log("loaded (Pocket Netherworld)")
    return c


def texts(c):
    return [e[4] for e in c.cmd("texts").get("list", [])]


def wait_text(c, needle, timeout=15.0, step=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if any(needle in t for t in texts(c)):
            return True
        c.wait(step)
    return False


def enter_iw(c, item=None, log=print):
    """from the hub, standing at the Item World NPC (Makoto): into the Item World of the first item in the bag
    (or the one named `item`)"""
    if not any("Makoto" in t for t in texts(c)):
        raise RuntimeError("not next to the Item World NPC")
    c.keys("K:4:40")                                   # talk
    for _ in range(10):                                # the greeting: advance until the menu shows
        if wait_text(c, "Make a selection.", 1.0):
            break
        c.keys("K:4:30")
    c.wait(40)                                         # the menu slides in and ignores keys meanwhile
    c.keys("K:4:60")                                   # Go to Item World
    if not wait_text(c, "Which item's Item World", 10):
        raise RuntimeError("the item list did not open")
    if item:
        for _ in range(60):
            names = [e for e in c.cmd("texts")["list"] if e[3] == "0x1404213dd" and e[0] == 861]
            if names and names[0][4] == item:
                break
            c.keys("S:3:8")
    c.wait(30)
    c.keys("K:4:40")                                   # the item
    if not wait_text(c, "Enter the Item World?", 5):
        raise RuntimeError("no 'Enter the Item World?' prompt")
    c.wait(20)
    c.keys("K:4:20")                                   # YES (the default)
    t0 = time.time()
    while True:
        st = c.state()
        if st.get("battle") == 1 and st.get("mode") == 2:
            break
        if time.time() - t0 > 60:
            raise RuntimeError("the floor did not load")
        c.wait(30)
    log("in the Item World")
    return c


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "iw":
        enter_iw(Ctl(), args[1] if len(args) > 1 else None)
    else:
        boot(int(args[0]) if args else None)
