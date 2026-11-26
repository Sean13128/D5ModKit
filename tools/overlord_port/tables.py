"""Is a complete Overlord table replacement expressible as a Kit row patch?

Overlord v3 ships 15 `Database_0` members as **full-table replacements** (RELEASE.md §5). The Kit
writes *row patches* into the same archive members, so two complete replacements cannot both be
applied: whichever writes the member last wins, and every Kit row in it is lost. Converting a
replacement into row patches at install time is option (b) in TASK-OLCOMPAT. This module answers,
per member and with a byte-level proof, whether that conversion is faithful.

Patches address rows **by position**, so three cases exist and only the third is refused:

  convertible        the table has a key column (`char.dat` id, `Skill.dat` id, `item.dat` id) and
                     the key at every baseline index is the same on both sides: the patch edits
                     the row it means, and the ids it appends are reportable for ownership.
  convertible-unkeyed the table has no usable key (`charPersonal.dat`, `SugorokuMapSetting.dat`) or
                     repeating keys (`charhelp.dat`). The patch still reproduces the replacement
                     byte for byte, but "row 12" is only a position: a second mod editing the same
                     member cannot be reasoned about, so this member is not composable.
  refused            a keyed table whose keys moved position (`item.dat` puts the new rows at
                     1207 instead of at the end). A position-addressed patch would edit the wrong
                     rows, so it is refused rather than half-applied.

In every accepted case the patch must reproduce the replacement's canonical serialisation byte for
byte after `dbpatch.apply_patch`, which also catches header, string-pool, padding and added-row
placement differences.

A PASS proves representability in isolation only. It says nothing about ownership or the saved
state that references those rows; `package.py` does that check.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from d5lib import database, dbpatch, ordercheck   # noqa: E402

CONVERTIBLE = "convertible"
UNKEYED = "convertible-unkeyed"
INSERTED = "convertible-inserted"       # the replacement inserts rows inside the table; the patch says where
MIGRATION = "convertible-needs-migration"   # faithful, but saved positions shift: ship it with the importer
REFUSED = "refused"


class Refused(ValueError):
    pass


class Result:
    def __init__(self, table):
        self.table = table
        self.status = REFUSED
        self.reason = ""
        self.patch = None
        self.changed_rows = 0
        self.added_rows = 0
        self.inserted_rows = 0
        self.insert_anchors = []
        self.added_ids = []
        self.changed_row_ids = []
        self.duplicate_keys = False
        self.baseline_sha256 = None
        self.target_sha256 = None
        self.positional = []

    @property
    def convertible(self):
        return self.status in (CONVERTIBLE, UNKEYED, INSERTED, MIGRATION)

    @property
    def composable(self):
        return self.status in (CONVERTIBLE, INSERTED, MIGRATION)

    def as_dict(self):
        return {"table": self.table, "status": self.status, "reason": self.reason,
                "changed_rows": self.changed_rows, "added_rows": self.added_rows,
                "inserted_rows": self.inserted_rows, "insert_anchors": self.insert_anchors,
                "added_ids": self.added_ids, "changed_row_ids": self.changed_row_ids,
                "duplicate_keys": self.duplicate_keys, "composable": self.composable,
                "positional": self.positional,
                "baseline_sha256": self.baseline_sha256, "target_sha256": self.target_sha256}


def _key(base, target):
    key = base.schema.key
    rows = list(base.rows) + list(target.rows)
    if key and all(key in row for row in rows):
        return key
    # a few tables name their identity column but do not declare it as the schema key
    if all("id" in row for row in rows):
        return "id"
    return None


def check_positions(base, target):
    """How the target's keys line up with the baseline: ('same'|'insert'|None, key, duplicate_keys).

    'same'   every baseline key still sits at its own index: a positional patch addresses the right rows.
    'insert' the baseline is a subsequence of the target -- rows were put *inside* the table.  A
             position-addressed patch would edit the wrong rows, but a key-anchored `insert` entry
             says exactly where they go, so the member stays composable.
    None     no usable key (or a repeated one): rows are only positions here.
    Raises Refused for a deletion or a re-ordering, which neither form can express.
    """
    if len(target.rows) < len(base.rows):
        raise Refused("row deletion/truncation is not composable")
    key = _key(base, target)
    if key is None:
        return None, None, False
    base_keys = [row[key] for row in base.rows]
    tgt_keys = [row[key] for row in target.rows]
    dup = len(set(base_keys)) != len(base_keys)
    if dup:
        return None, key, True
    if base_keys == tgt_keys:
        return "same", key, False
    if base_keys == tgt_keys[:len(base_keys)] and len(tgt_keys) > len(base_keys):
        return "same", key, False
    # is the baseline an ordered subsequence of the target (insertions only, no reordering)?
    it = iter(tgt_keys)
    if all(k in it for k in base_keys):
        return "insert", key, False
    for i, (a, b) in enumerate(zip(base.rows, target.rows)):
        if a[key] != b[key]:
            raise Refused(f"row key/order changes at index {i}: {a[key]} -> {b[key]}")
    return "same", key, False


def audit(name, vanilla_bytes, replacement_bytes, *, allow_positional=False):
    """Diff, apply and compare. Returns a Result; never raises for a refusal."""
    out = Result(name)
    out.baseline_sha256 = hashlib.sha256(vanilla_bytes).hexdigest()
    out.target_sha256 = hashlib.sha256(replacement_bytes).hexdigest()
    try:
        base = database.load_table(name, vanilla_bytes)
        target = database.load_table(name, replacement_bytes)
    except (KeyError, ValueError, IndexError) as exc:
        out.reason = f"no schema/parse for this member: {exc}"
        return out
    try:
        form, key, dup = check_positions(base, target)
        patch = dbpatch.diff_table(base, target)
        if form == "insert" and not patch.get("insert"):
            raise Refused("keys moved but the diff did not express the change as an insertion")
        applied = database.load_table(name, vanilla_bytes)
        dbpatch.apply_patch(applied, patch, strict=True)
        if applied.to_bytes() != target.to_bytes():
            raise Refused("Kit patch does not reproduce canonical target bytes")
    except (Refused, ValueError, KeyError, IndexError, TypeError) as exc:
        out.reason = str(exc)
        return out
    if dup or form is None:
        out.status = UNKEYED
        out.reason = ("the identity column repeats (several rows share one id), so a row is only a "
                      "position here: not composable with another mod's edits") if dup else \
                     "no usable row key: a row is only a position here, not composable"
    elif form == "insert":
        out.status = INSERTED
    else:
        out.status = CONVERTIBLE
    out.patch = patch
    out.duplicate_keys = dup
    out.changed_rows = len(patch.get("rows") or {})
    added = patch.get("added") or []
    out.added_rows = len(added)
    inserts = patch.get("insert") or []
    out.inserted_rows = sum(len(i.get("rows") or []) for i in inserts)
    out.insert_anchors = [i.get("before", i.get("after")) for i in inserts]
    if key and not dup:
        new_rows = list(added) + [r for i in inserts for r in (i.get("rows") or [])]
        out.added_ids = sorted({int(r[key]) for r in new_rows if key in r})
        out.changed_row_ids = sorted({int(base.rows[int(i)][key]) for i in (patch.get("rows") or {})
                                      if int(i) < len(base.rows)})
        # does this change move a position something saved already points at?
        base_ids = [r[key] for r in base.rows]
        target_ids = [r[key] for r in target.rows]
        out.positional = ordercheck.positional_errors(name, base_ids, target_ids)
        if out.positional:
            out.status = MIGRATION
            out.reason = "; ".join(out.positional)
            if not allow_positional:
                out.status = REFUSED
                out.reason += " (pass --allow-positional-changes to convert it anyway and ship the importer)"
    return out
