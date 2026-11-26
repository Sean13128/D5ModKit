#!/usr/bin/env python3
"""D4GAP1: measure which ids are free for new D4 uniques (offline, read-only).

    D5_INSTALLED_MODS=<holding>/mods python tools/d4gap1_leases.py DIRTY_SLOTS.json [--n 9]

Claim sources (same index as the LEASEGATE1 `used_ids` gate, `importcore.UsedIds`): vanilla tables and anm numbers,
every importer's recorded lease, every mod folder under the live kit, the holding folder and the uninstalled
builds (DRPGBUILD2, UNIQUESKILLS1, ROSTERGAP1, LEASEGATE1, D4GAP1 itself), plus the quest slots a known save marks
(DRPG-SAVESLOT1 `tools/save_quest_slots.py --out`).  Prints the first free art windows, identities, help ids,
quest ids and quest slots.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
P = Path("/Volumes/Data/Projects/D5")
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
STATE = GAME / "D5ModKit/state/games/Disgaea_5_Complete-d8040a88"
BUILD_ROOTS = [P / f"Builds/{b}/mods" for b in ()]


def build_mod_roots(skip=()):
    out = []
    for name in ("DRPGBUILD2-20261109", "UNIQUESKILLS1-20261109", "ROSTERGAP1-20261109", "LEASEGATE1-20261109",
                 "D4GAP1-20261109"):
        for sub in sorted((P / "Builds" / name).glob("*/mods")) + sorted((P / "Builds" / name).glob("*/*/mods")):
            if sub.is_dir() and not any(s in str(sub) for s in skip):
                out.append(sub)
    return out


def measure(dirty, skip=()):
    from d5lib import importcore, dbpatch
    roots = importcore.default_extra_roots(build_mod_roots(skip))
    used = importcore.UsedIds(GAME, STATE, roots)
    idx = used.index()
    _tables, vanilla_anm = used.vanilla()

    def taken(kind, i):
        if (kind, i) in idx:
            return True
        hit = used.vanilla_ids(kind).get(i) if kind not in ("anm", "face") else None
        return bool(hit and not hit[1])

    out = {}
    anm_taken = {i for (k, i) in idx if k == "anm"} | set(vanilla_anm)
    windows = []
    from d5lib import slots
    for lo, hi in slots.SPRITE_LEASE_RUNS:
        for n in range(lo, hi + 1):
            keys = {n, n + 1, n + 2, 10000 + n, 10001 + n}
            if keys & anm_taken or taken("char.dat", n) or any(taken("char.dat", n + k) for k in range(3)):
                continue
            if any(abs(n - w) < 3 for w in windows):
                continue
            windows.append(n)
    out["art_windows"] = windows
    out["identity_10k"] = [i for i in range(10000, 10991, 10) if not taken("char.dat", i)
                           and not any(taken("char.dat", i + k) for k in range(6))]
    out["identity_18k"] = [i for i in range(18100, 18991, 10) if not taken("char.dat", i)
                           and not any(taken("char.dat", i + k) for k in range(6))][:12]
    help_used = [i for (k, i) in idx if k == "charhelp.dat"]
    van_help = used.vanilla_ids("charhelp.dat")
    out["help_next"] = max(help_used + [i for i in van_help if i < 30000] + [22681]) + 1
    quest_used = [i for (k, i) in idx if k == "Quest.dat"]
    van_q = used.vanilla_ids("Quest.dat")
    out["quest_next"] = max(i for i in set(quest_used) | set(van_q) if i < dbpatch.PLACEHOLDER_FIRST) + 1
    slot_used = {i for (k, i) in idx if k == importcore.QUEST_SLOT} | set(used.vanilla_ids(importcore.QUEST_SLOT))
    dirty_set = {int(x) for x in json.loads(Path(dirty).read_text())["slots"]} if dirty else set()
    out["dirty_slots"] = len(dirty_set)
    out["slot_free"] = [s for s in range(0, max(slot_used) + 60) if s not in slot_used and s not in dirty_set
                        and s > max(slot_used) - 40][:20]
    out["slot_top"] = max(slot_used)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("dirty", nargs="?")
    ap.add_argument("--skip", nargs="*", default=[], help="build roots whose claims are this card's own")
    a = ap.parse_args()
    print(json.dumps(measure(a.dirty, a.skip), indent=1))
