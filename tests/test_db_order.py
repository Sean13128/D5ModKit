"""Id order of a table the game searches by id (Skill.dat), and the known-evility bitset cap.

Vanilla ships Skill.dat in ascending id order.  Every mod appends its own block, so the merged table
is not in order anymore, and the game's own binary search (0x14015e630, transcribed in these tests)
cannot reach the ids behind an inversion -- the ids of the evilities a custom class adds.  Synthetic
tables only: no game, no kit state, no installed kit.
"""
import os
import sys

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from d5lib import database, ordercheck  # noqa: E402

VAN = "/Volumes/Data/ai-tmp/charorder/vanilla/Database_0.dat"


def table(ids):
    """A Skill.dat with one row per id (all other fields default)."""
    base = database.load_table("Skill.dat", _vanilla_skill()) if os.path.exists(VAN) else None
    if base is None:
        return None
    t = base
    t.rows[:] = []
    for i in ids:
        r = t.new_row()
        r.set("id", i)
        r.set("name_EN", f"row {i}")
        t.rows.append(r)
    return t


def _vanilla_skill():
    return database.load_database(VAN)["Skill.dat"].to_bytes()


def search(ids, target):
    """The loop of FUN_14015e630 (0x14015e630): binary search over the id array."""
    lo, hi = 0, len(ids) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if ids[mid] == target:
            return mid
        if target > ids[mid]:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


def reached(ids):
    return [i for i in ids if search(ids, i) != ids.index(i)]


def test_binary_search_reaches_every_id_after_the_sort():
    ids = [10, 20, 30, 7000, 7001, 8100, 8101, 50, 60, 8200, 8201]
    assert len(reached(ids)) > 0                      # the merged shape: a block appended out of order
    t = table(ids)
    fixed, moved = ordercheck.sort_keyed("Skill.dat", t.to_bytes())
    assert moved > 0
    out = [r["id"] for r in database.load_table("Skill.dat", fixed).rows]
    assert out == sorted(ids)
    assert reached(out) == []


def test_findings_name_the_inversion():
    t = table([10, 20, 8100, 30])
    f = ordercheck.findings("Skill.dat", t.to_bytes())
    assert len(f) == 1 and "not in id order" in f[0] and "8100>30" in f[0]


def test_sorted_table_has_no_findings():
    t = table([10, 20, 30, 8100])
    assert ordercheck.findings("Skill.dat", t.to_bytes()) == []


def test_bitset_cap_is_reported_not_blocked():
    """Rows past the bitmap are held by the learned-evility store (EVCAP); they are reported, not refused.

    What is still fatal is a row *inserted below* a saved bit: `positional_errors` names it.
    """
    t = table(list(range(1, ordercheck.BITSET_CAP + 2)))
    f = ordercheck.findings("Skill.dat", t.to_bytes())
    assert any("learned-evility store" in x for x in f)
    # appending below the cap is safe; inserting inside it is not
    assert ordercheck.positional_errors("Skill.dat", [10, 20, 30], [10, 20, 30, 40]) == []
    moved = ordercheck.positional_errors("Skill.dat", [10, 20, 30], [10, 15, 20, 30])
    assert moved and "saved bit" in moved[0]


def test_other_tables_are_left_alone():
    """Only the tables the game searches by id are re-ordered (magic.dat ships unsorted in vanilla)."""
    assert ordercheck.ORDER_CRITICAL == ("Skill.dat",)
    out, moved = ordercheck.sort_keyed("magic.dat", b"\0\0\0\0")
    assert out == b"\0\0\0\0" and moved == 0
