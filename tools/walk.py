"""Move the hub leader: walk to a hub position (TownFuncCharCenter pos_x / pos_y), or teleport next to an NPC.

    python walk.py X Z            walk there
    python walk.py --npc NAME     teleport next to a known NPC (tools/hub_spots.json)

W = (+x, +z), D = (+x, -z), S = (-x, -z), A = (-x, +z); position = leader actor 0x142349160 + 8 (x, height, z),
kept in three copies (+0x8, +0x34, +0x90): writing all three teleports the leader (as battle_nav.enter_stage does
for the Dimension Guide).  NPC spots are learned: the first visit walks there (face_npc) and records the exact
position in hub_spots.json; later visits teleport straight to it.
"""
import json
import os
import struct
import sys
import time

from d5ctl import Ctl, game_addr

LEADER = 0x142349160                     # launch build; game_addr() gives it in the running build (Steam: 0x141e2cd60)
POS = 8
POS_COPIES = (0x8, 0x34, 0x90)
SPOTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub_spots.json")
SPOTS = {"Dimension Guide": [283.0, -135.0, 477.0], "Recruiter": [303.0, -75.0, 142.0]}


def pos(c):
    x, _, z = struct.unpack("<fff", bytes.fromhex(c.cmd(f"rd {game_addr(LEADER) + POS:#x} 12")["hex"]))
    return x, z


def walk(c, tx, tz, tol=15, steps=60):
    stuck = 0
    for _ in range(steps):
        x, z = pos(c)
        dx, dz = tx - x, tz - z
        if abs(dx) < tol and abs(dz) < tol:
            break
        a, b = (dx - dz) / 2, (-dx - dz) / 2          # amounts along D and S
        ka = "D" if a > 0 else "A"
        kb = "S" if b > 0 else "W"
        keys = [ka, kb] if abs(a) >= abs(b) else [kb, ka]
        k = keys[stuck % 2] if stuck < 4 else "WDSA"[stuck % 4]     # blocked: the other axis, then any way
        n = int(min(20, max(4, max(abs(a), abs(b)) / 1.3)))
        c.keys(f"{k}:{n}:4")
        time.sleep(n / 60 + 0.15)
        nx, nz = pos(c)
        stuck = stuck + 1 if abs(nx - x) + abs(nz - z) < 3 else 0
    return pos(c)


def pos3(c):
    return struct.unpack("<fff", bytes.fromhex(c.cmd(f"rd {game_addr(LEADER) + POS:#x} 12")["hex"]))


def teleport(c, x, y, z):
    xyz = struct.pack("<fff", x, y, z).hex()
    for o in POS_COPIES:
        c.cmd(f"wr {game_addr(LEADER) + o:#x} {xyz}")


def spots():
    d = dict(SPOTS)
    try:
        with open(SPOTS_FILE) as f:
            d.update(json.load(f))
    except (OSError, ValueError):
        pass
    return d


def _npc_shown(c, name):
    return name in [e[4] for e in c.cmd("texts")["list"]]


def go_to_npc(c, name, approx=None, tries=14):
    """teleport next to NPC `name` (its info panel shows); unknown spot: walk there once (approx = (x, z)) and
    remember it.  -> True when the NPC's panel is up"""
    for _ in range(4):                       # out of any menu
        c.keys("L:4:30")
        time.sleep(0.5)
    spot = spots().get(name)
    if spot:
        teleport(c, *spot)
        time.sleep(1.0)
        if _npc_shown(c, name):
            return True
        for k in "WDSA":                     # facing the wrong way: a tiny step each way
            c.keys(f"{k}:2:4")
            time.sleep(0.4)
            if _npc_shown(c, name):
                return True
    if approx is None:
        return False
    if not face_npc(c, *approx, name, tries):
        return False
    d = spots()
    d[name] = [round(v, 2) for v in pos3(c)]
    with open(SPOTS_FILE, "w") as f:
        json.dump({k: v for k, v in d.items() if k not in SPOTS or v != SPOTS[k]}, f, indent=1)
    return True



def face_npc(c, x, z, name, tries=8):
    """walk next to an NPC until its info panel (name) shows"""
    import random
    for t in range(tries):
        walk(c, x, z, tol=6)
        time.sleep(0.4)
        if name in [e[4] for e in c.cmd("texts")["list"]]:
            return True
        x += random.choice((-6, 6))
        z += random.choice((-6, 6))
    return False


if __name__ == "__main__":
    if sys.argv[1:2] == ["--npc"]:
        print(go_to_npc(Ctl(), sys.argv[2]))
    else:
        print(walk(Ctl(), float(sys.argv[1]), float(sys.argv[2])))
