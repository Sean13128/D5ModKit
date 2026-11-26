"""Motion ids a unit's battle bank must hold (SHARKBANK1, 2026-11-21).

A bank the game selects a motion from falls back to the bank's FIRST animation (id 0, empty) when the id is
missing (`anm_actor_select_motion` 0x1402f4ba0), and a lookup with no record at all leaves the player's motion
pointer NULL (`anm_owner_restart_at_frame` null seek, 0x2F5512, ANMTRACE1).  Which ids the game asks a body for is
only partly written down (the skill scripts name caster motions: `choreo.py`, `skillmotions.py`; walking, lifting,
hurt, death are engine-side), so the list here is OBSERVED, not derived from the decomp:

* `monster`: every id present in at least `THRESHOLD` of the clean game's monster banks (body_type 1; 69 banks,
  2026-11-21, includes the template monster's normal attack 2071/2077 = motion 207).
* `humanoid`: the same rule over the humanoid banks (80): only 0, 6001, 6007 (the shared resident block 1 carries
  the rest, docs/ANM.md section 5).
* `common`: ids in 50 to 90 percent of the monster banks.  Informational: vanilla monsters lack them and run.

`data/required_motions.json` is written by `tools/required_motions.py` (clean game only) and holds the counts, so a
reviewer can see which evidence each id has.  This is a gate for the "bank lacks a motion the vanilla bodies all
have" class of defect.  It is NOT shown to be the cause of the Shark Dragon crash (SHARKBANK1-REPORT.md).
"""
from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).with_name("data") / "required_motions.json"
THRESHOLD = 0.9


def load(path=None):
    return json.loads(Path(path or DATA).read_text(encoding="utf-8"))


def required(body_type, doc=None):
    """sorted motion ids every bank of this body kind (0 humanoid, 1 monster) should hold"""
    doc = doc or load()
    return list(doc["required"]["monster" if int(body_type) == 1 else "humanoid"])


def missing(animation_ids, body_type, doc=None):
    """the required ids absent from `animation_ids` (an iterable of the bank's animation ids)"""
    have = set(int(i) for i in animation_ids)
    return [m for m in required(body_type, doc) if m not in have]
