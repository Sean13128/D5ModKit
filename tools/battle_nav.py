"""Battle cursor helpers (top view: W +y, A -x, S -y, D +x).

The same four keys turn the caster for range-0 ("from the caster") skills and the normal Attack: W faces toward
LARGER y (not screen-up), S smaller y, D larger x, A smaller x (proved live, LIVE1120C 2026-11-20).  Use
facing_key(caster_xy, target_xy) instead of guessing the key."""
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



# ------------------------------------------------------------------ queue check (SPECTOOLS1)
BM_PTR = 0x147b58e70             # DAT_147b58e70: the battle manager pointer (decomp: special_alloc_ctx)
BM_QUEUE_COUNT = 0x950           # BM+2384: queued ActionContexts. The turn menu's Execute (14063aa20 case 0) does
                                 # NOTHING (menu stays open, no event) while this is < 1.
TARGET_ERRORS = ("Out of range.", "No target.", "Attack zone obstructed.", "Attack zone height problem.",
                 "This Special Skill cannot be used here.", "The target is too far off the center of the skill.")


def queue_count(c):
    """number of queued actions (BM+2384), or None when it cannot be read"""
    try:
        bm = int.from_bytes(bytes.fromhex(c.cmd(f"rd {BM_PTR:#x} 8")["hex"]), "little")
        if not bm:
            return None
        return int.from_bytes(bytes.fromhex(c.cmd(f"rd {bm + BM_QUEUE_COUNT:#x} 4")["hex"]), "little", signed=True)
    except Exception:           # noqa: BLE001 - a probe, never a reason to stop a run
        return None


def target_error(c):
    """the target selector's red error line ("No target." ...) when one is showing, else None"""
    for line in texts(c)[:6]:
        if any(line.startswith(e) for e in TARGET_ERRORS):
            return line
    return None


FACING_KEYS = {(0, 1): "W", (0, -1): "S", (1, 0): "D", (-1, 0): "A"}   # grid step (dx, dy) -> d-pad key


def facing_key(src, dst):
    """The d-pad key that turns a unit at grid `src` toward the tile `dst` (the dominant axis wins; a tie prefers x).
    W is toward LARGER y.  None when both are the same tile."""
    dx, dy = dst[0] - src[0], dst[1] - src[1]
    if dx == 0 and dy == 0:
        return None
    if abs(dx) >= abs(dy):
        return FACING_KEYS[(1 if dx > 0 else -1, 0)]
    return FACING_KEYS[(0, 1 if dy > 0 else -1)]


def cast(c, name, skill, target, menu_open=False, facing=None):
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
    before = queue_count(c)
    if facing:                              # range-0 ("from the caster") skill: the d-pad turns the caster, the
        c.keys(f"{facing}:1:14"); time.sleep(0.5)    # cursor does not move, so goto() can never arrive
    else:
        goto(c, *target)
    err = target_error(c)
    if err:                                 # the game refuses the confirm (SE 4) and queues nothing
        cast.last_error = err
        for _ in range(3):
            c.keys("L:1:10"); time.sleep(0.4)
        return False
    c.keys("K:1:10"); time.sleep(1.0)
    after = queue_count(c)
    cast.last_error = None
    # True only when the game queued something (BM+2384 rose); unreadable counts as before (old behaviour)
    return True if before is None or after is None else after > before


cast.last_error = None


def execute(c, shots_prefix=None, n=20, gap=0.3):
    """battle menu -> Execute; optionally screenshots while the actions play"""
    for _ in range(2):
        if on_map(texts(c)):            # EXECDROP1: never L on the map (it undoes the cursor unit's queued action)
            break
        c.keys("L:1:10"); time.sleep(0.6)
    battle_menu(c)
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


def execute_checked(c, wait=6.0):
    """battle menu -> Execute, but say what happened: {"queued": BM+2384 before, "left_menu": bool, "texts": [...]}.
    Execute is a silent no-op while nothing is queued, so a False `left_menu` with queued == 0 means the cast
    never reached the queue (a cast() that returned True was wrong or the entry was dropped before Execute)."""
    out = {"queued": queue_count(c)}
    out["menu_open"] = battle_menu(c)
    if out["queued"] is not None and out["queued"] < 1:
        out["left_menu"] = False
        out["note"] = "nothing queued: Execute would be ignored"
        return out
    c.keys("K:1:10")
    t0 = time.time()
    while time.time() - t0 < wait:
        t = texts(c)
        if not (t and t[0].startswith("Commence")):
            out["left_menu"] = True
            break
        time.sleep(0.4)
    else:
        out["left_menu"] = False
    out["texts"] = texts(c)[:3]
    return out


def burst(c, prefix, n=40):
    """raw screenshots as fast as the harness gives them (one per presented frame batch) -> BMP paths"""
    out = []
    for i in range(n):
        p = f"{prefix}{i:03d}.bmp"
        c.cmd("shot " + p)
        out.append(p)
    return out


def execute_burst(c, prefix, n=60):
    battle_menu(c)
    c.keys("K:1:10")
    files = burst(c, prefix, n)
    time.sleep(2)
    return files


def on_map(t):
    """True while the battle map (field cursor) has the input: its help bar shows the ";044; Menu" prompt, as the
    first line on an empty panel or after the unit panel's two name lines when the cursor is on a unit."""
    return any(x.startswith(";044;") for x in (t or [])[:5])


def battle_menu(c):
    """open the battle menu (Execute / End Turn ...): R with the launch build's default keys, I with the Steam
    build's -> True when it is open.

    EXECDROP1: L is pressed only when a key really opened another screen (the map's ";044;" help bar is gone).
    On the map L is the game's Cancel = undo (cursor_ctl_s0_update 0x1405FE450, action 5 ->
    cursor_undo_last_action_stack_entry 0x1404CF660): with the cursor on a player unit it removes that unit's queued
    ActionContexts (BM+0x950 falls, Execute then does nothing) or undoes its move.  After an Attack or a range-0
    skill the cursor sits on the actor, so the old "not ;0 -> L" test (t[0] is the unit's name there) undid it."""
    for key in ("R", "I"):
        c.keys(f"{key}:1:20"); time.sleep(1.0)
        t = texts(c)
        if t and t[0].startswith(("Commence", "End your turn")):
            return True
        if t and not on_map(t):                          # something else opened (not the map): close it
            c.keys("L:1:10"); time.sleep(0.5)
    return False


def end_turn(c):
    """battle menu -> End Turn (confirm) -> wait for the enemy turn to finish"""
    battle_menu(c)
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
        battle_menu(c)
        t = texts(c)
        if t and t[0].startswith("Commence"):
            break
    c.keys("K:2:10")
    files = burst(c, prefix, n) if prefix else []
    time.sleep(3)
    return files


def give_up(c):
    """battle menu -> Give Up -> Return to the pocket Netherworld -> YES"""
    battle_menu(c)
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
