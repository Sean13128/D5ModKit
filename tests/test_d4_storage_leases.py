"""D4 quest/help id pins (D4-FIX4): the lease table keeps every held id, nothing collides."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import d4unique  # noqa: E402

LEASES = Path(__file__).resolve().parents[1] / "d5lib/importers/d4-leases.json"
HELD = {"170": (302, 519, 22682), "70": (386, 608, 22855), "610": (395, 617, 22864)}   # held 11-08


def chars():
    return json.loads(LEASES.read_text())["characters"]


def test_every_character_is_pinned_without_collision():
    c = chars()
    pins = [(k, v["storage"]) for k, v in c.items()]
    assert all(s for _k, s in pins), [k for k, s in pins if not s]
    for field in ("quest_id", "quest_slot", "help_id"):
        vals = [s[field] for _k, s in pins]
        assert len(vals) == len(set(vals)), field
    for k, (q, slot, h) in HELD.items():
        assert (c[k]["storage"]["quest_id"], c[k]["storage"]["quest_slot"], c[k]["storage"]["help_id"]) == (q, slot, h)


def tables(quests=(), helps=()):
    return {"Quest.dat": NS(rows=[{"id": i, "sort_order": s} for i, s in quests]),
            "charhelp.dat": NS(rows=[{"id": h, "char_id": h} for h in helps])}


def test_pin_is_reproduced_and_occupied_pin_fails():
    pin = {"quest_id": 302, "quest_slot": 519, "help_id": 22682}
    assert d4unique._import_storage(tables(), pinned=pin) == (22682, 302, 519)
    with pytest.raises(ValueError):
        d4unique._import_storage(tables(quests=[(302, 1)]), pinned=pin)
    with pytest.raises(ValueError):
        d4unique._import_storage(tables(helps=[22682]), pinned=pin)


def test_fresh_allocation_skips_other_pins():
    reserved = [s["storage"] for s in chars().values()]
    helpid, qid, slot = d4unique._import_storage(tables(quests=[(300, 5)], helps=[22000]), reserved=reserved)
    assert helpid > max(r["help_id"] for r in reserved)
    assert qid > max(r["quest_id"] for r in reserved)
    assert slot not in {r["quest_slot"] for r in reserved}
