"""Battle cursor helpers (top view: W +y, A -x, S -y, D +x)."""
import json
import time

from d5ctl import Ctl


def state(c):
    return json.loads(c.raw("state"))


def cp(c):
    return state(c)["cpanel"]


def texts(c):
    return [x[4] for x in c.cmd("texts")["list"] if x[4]]


def goto(c, x, y, tries=30):
    for _ in range(tries):
        px, py = cp(c)
        if [px, py] == [x, y]:
            return True
        k = "D" if px < x else "A" if px > x else "W" if py < y else "S"
        c.keys(f"{k}:1:14")
        time.sleep(0.4)
    return cp(c) == [x, y]


def menu_pick(c, index, size=9):
    """command menu: go to the top, then down to `index` (0 Move, 1 Attack, 2 Special, ...)"""
    c.keys(" ".join(["W:1:10"] * size))
    time.sleep(0.4)
    if index:
        c.keys(" ".join(["S:1:10"] * index))
        time.sleep(0.4)
    c.keys("K:1:10")
    time.sleep(0.9)


def shots(c, prefix, n=10, gap=0.35, scale=0.5):
    for i in range(n):
        c.cmd(f"shot {prefix}{i}.bmp")
        time.sleep(gap)


MENU_HELP = {"move": "Choose where to move", "attack": "Choose target to perform attack", "special": "Use character's skill",
             "lift": "Choose target to lift", "defend": "Character will defend", "item": "Character will use an item",
             "overload": "Activate a strong skill", "equip": "Change character's equipment", "status": "Check character's stats"}


def menu(c, entry, tries=12):
    """unit command menu (open): select `entry` by its help line and confirm"""
    want = MENU_HELP[entry]
    for _ in range(tries):
        t = texts(c)
        if t and t[0].startswith(want):
            c.keys("K:1:10")
            time.sleep(1.0)
            return True
        c.keys("S:1:12")
        time.sleep(0.45)
    return False


# ------------------------------------------------------------------ whole steps
def enter_stage(c, guide=(283.0, -135.0, 477.0)):
    """hub -> the Dimension Guide -> the first stage of the first Netherworld; True when the battle runs"""
    from walk import teleport
    for _ in range(4):
        c.keys("L:4:30"); time.sleep(0.6)
    teleport(c, *guide)
    time.sleep(1)
    for _ in range(3):
        c.keys("K:4:60"); time.sleep(1.8)
    c.keys("K:4:60"); time.sleep(1.5)
    c.keys("K:4:60")
    for _ in range(30):
        if state(c).get("battle"):
            time.sleep(4)
            c.keys("V:1:20"); time.sleep(0.8)       # top view: W/A/S/D move the cursor along the grid
            return True
        time.sleep(1.5)
    return False


def deploy(c, name, to=None):
    """base panel -> dispatch `name` (searched in every group) -> optionally move it to `to`"""
    s = state(c)
    goto(c, *s["base"])
    c.keys("K:1:10"); time.sleep(1.2)

    def sel():
        t = texts(c)
        i = t.index("Choose a character to dispatch.") if "Choose a character to dispatch." in t else -1
        return (t[i + 1], t[i + 2]) if i >= 0 and i + 2 < len(t) else (None, None)
    for _ in range(3):
        for _ in range(45):
            if name in sel():
                break
            c.keys("S:1:8"); time.sleep(0.22)
        if name in sel():
            break
        c.keys("D:3:20"); time.sleep(0.8)
    if name not in sel():
        return False
    deploy.last = sel()[0]
    c.keys("K:1:10"); time.sleep(1.5)
    c.keys("K:1:10"); time.sleep(1.0)             # stay on the base panel (move mode right after dispatch is odd)
    for _ in range(2):
        if texts(c) and texts(c)[0].startswith("Choose where to move"):
            break
    if to:
        c.keys("L:1:10"); time.sleep(0.6)
        goto(c, *s["base"]); c.keys("K:1:10"); time.sleep(1.0)
        menu(c, "move"); time.sleep(0.4)
        goto(c, *to); c.keys("K:1:10"); time.sleep(2.5)
    return True


def unit(c, name):
    return next((u for u in state(c)["units"] if u["name"] == name), None)


def set_sp(c, name, sp=999):
    import struct
    u = unit(c, name)
    up = int(u["unit"], 16)
    v = struct.pack("<q", sp).hex()
    for off in (0x2cd0, 0x2ce0, 0x2d20):       # current, max, base max SP (max is recomputed from the base)
        c.cmd(f"wr {up + off:#x} {v}")


def cast(c, name, skill, target, menu_open=False):
    """queue unit `name`'s skill on panel `target` (x, y); menu_open: the unit's command menu is already up (it
    opens by itself after a move -- cancelling it would undo the move)"""
    if not menu_open:
        u = unit(c, name)
        goto(c, *u["p"]); c.keys("K:1:10"); time.sleep(1.0)
    if not menu(c, "special"):
        return False
    for _ in range(20):
        t = texts(c)
        i = t.index("Special Skill List") if "Special Skill List" in t else -1
        if i >= 0 and t[i + 1] == skill:
            break
        c.keys("S:1:12"); time.sleep(0.4)
    else:                                   # not in the list: don't cast whatever is highlighted
        for _ in range(3):
            c.keys("L:1:10"); time.sleep(0.4)
        return False
    c.keys("K:1:10"); time.sleep(1.0)
    if texts(c) and texts(c)[0].startswith("Select range"):
        c.keys("K:1:10"); time.sleep(0.8)
    goto(c, *target)
    c.keys("K:1:10"); time.sleep(1.0)
    return True


def execute(c, shots_prefix=None, n=20, gap=0.3):
    """battle menu -> Execute; optionally screenshots while the actions play"""
    for _ in range(2):
        t = texts(c)
        if t and t[0].startswith(";044;"):
            break
        c.keys("L:1:10"); time.sleep(0.6)
    c.keys("R:1:20"); time.sleep(1.0)
    c.keys("K:1:10")
    files = []
    if shots_prefix:
        for i in range(n):
            f = f"{shots_prefix}{i:02d}.png"
            c.shot(f, 0.5)
            files.append(f)
            time.sleep(gap)
    time.sleep(2)
    return files


def burst(c, prefix, n=40):
    """raw screenshots as fast as the harness gives them (one per presented frame batch) -> BMP paths"""
    out = []
    for i in range(n):
        p = f"{prefix}{i:03d}.bmp"
        c.cmd("shot " + p)
        out.append(p)
    return out


def execute_burst(c, prefix, n=60):
    c.keys("R:1:20"); time.sleep(1.0)
    c.keys("K:1:10")
    files = burst(c, prefix, n)
    time.sleep(2)
    return files


def end_turn(c):
    """battle menu -> End Turn (confirm) -> wait for the enemy turn to finish"""
    c.keys("R:1:20"); time.sleep(1.0)
    for _ in range(10):
        t = texts(c)
        if t and t[0].startswith("End your turn"):
            break
        c.keys("S:1:10"); time.sleep(0.4)
    c.keys("K:1:10"); time.sleep(1.0)
    t = texts(c)
    if any("YES" in x.upper() for x in t) or any("end" in x.lower() for x in t):
        c.keys("K:1:10")
    for _ in range(60):
        time.sleep(2)
        t = texts(c)
        if any(x.startswith(";044;") for x in t[:3]):     # the player phase's help bar (after a unit panel, if any)
            return True
    return False


def learn(c, name, skill):
    """teach a unit a skill in memory only (never saved): skill list unit+0xcc0 (16-byte entries: u32 exp,
    u32 skill id, u8 level, u8 1, u16 0, i16 -1, u8 1, u8 1), count unit+0x2cc0 -> True when added"""
    import struct
    up = int(unit(c, name)["unit"], 16)
    n = struct.unpack("<I", bytes.fromhex(c.cmd(f"rd {up + 0x2cc0:#x} 4")["hex"]))[0]
    have = bytes.fromhex(c.cmd(f"rd {up + 0xcc0:#x} {16 * max(1, n)}")["hex"])
    if any(struct.unpack_from("<I", have, 16 * k + 4)[0] == skill for k in range(n)):
        return False
    c.cmd(f"wr {up + 0xcc0 + 16 * n:#x} {struct.pack('<IIBBHhBB', 0, skill, 1, 1, 0, -1, 1, 1).hex()}")
    c.cmd(f"wr {up + 0x2cc0:#x} {struct.pack('<I', n + 1).hex()}")
    return True


def set_hp(c, name, hp=999):
    import struct
    up = int(unit(c, name)["unit"], 16)
    v = struct.pack("<q", hp).hex()
    for off in (0x2cc8, 0x2cd8, 0x2d18):       # current, max, base max HP
        c.cmd(f"wr {up + off:#x} {v}")


def cast_self(c, name, skill):
    """queue a support skill on the caster itself (range type -> default target = self)"""
    goto(c, *unit(c, name)["p"]); c.keys("K:1:10"); time.sleep(1.0)
    if not menu(c, "special"):
        return False
    for _ in range(20):
        t = texts(c)
        i = t.index("Special Skill List") if "Special Skill List" in t else -1
        if i >= 0 and t[i + 1] == skill:
            break
        c.keys("S:1:12"); time.sleep(0.4)
    c.keys("K:1:10"); time.sleep(1.0)
    if texts(c) and texts(c)[0].startswith("Select range"):
        c.keys("K:1:10"); time.sleep(0.8)
    c.keys("K:1:10"); time.sleep(1.0)
    return True


def run_actions(c, prefix=None, n=70):
    for _ in range(3):
        c.keys("R:1:20"); time.sleep(1.0)
        t = texts(c)
        if t and t[0].startswith("Commence"):
            break
    c.keys("K:2:10")
    files = burst(c, prefix, n) if prefix else []
    time.sleep(3)
    return files


def give_up(c):
    """battle menu -> Give Up -> Return to the pocket Netherworld -> YES"""
    c.keys("R:1:20"); time.sleep(1.0)
    for _ in range(10):
        t = texts(c)
        if t and t[0].startswith("Finish battle"):
            break
        c.keys("S:1:10"); time.sleep(0.4)
    c.keys("K:2:10"); time.sleep(1.2)
    for _ in range(4):
        if texts(c) and texts(c)[-1].startswith("Lose progress and return"):
            break
        c.keys("S:1:10"); time.sleep(0.5)
    c.keys("K:2:10"); time.sleep(1.5)
    c.keys("W:2:10"); time.sleep(0.5)              # YES
    c.keys("K:2:10")
    for _ in range(40):
        if not state(c).get("battle"):
            break
        time.sleep(1.5)
    time.sleep(6)
    return not state(c).get("battle")


def ready_next_to_enemy(c, name, tries=5):
    """deploy `name` if needed and walk it until an enemy stands next to it; the turn is ended after each walk
    (a fresh turn: the unit can act).  -> (unit, nearest enemy) or None"""
    from _attack_again import foes, dist
    from _attack_with import move_toward
    if not unit(c, name):
        deploy(c, name)
    for _ in range(tries):
        u = unit(c, name)
        if not u:
            return None
        f = min(foes(c), key=lambda e: dist(u["p"], e["p"]))
        if dist(u["p"], f["p"]) <= 1 and tuple(u["p"]) != tuple(state(c)["base"]):
            return u, f
        move_toward(c, name, f["p"])
        time.sleep(1.0)
        end_turn(c)
    return None
