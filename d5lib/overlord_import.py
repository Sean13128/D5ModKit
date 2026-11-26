"""Import an Overlord-era save into a Kit + Overlord-package install (offline; works on copies).

An Overlord save and a Kit save are the same file format. What differs is what the *numbers* inside
it mean, because the two installs ship different database tables:

  learned evilities   one bit per **Skill.dat row position** (unit record +0x2E70, 1,000 bits).  His
                      table has 819 rows, ours has ours; the same bit therefore means a different
                      evility.  Every bit is decoded through *his* ordered id list and re-encoded
                      through *ours* (`d5lib.ordercheck.remap_bitmap`).  Ids that land past position
                      1,000 cannot be held by the bitmap at all: they go to the learned-evility store's
                      companion file (`d5lib.learned`, EVCAP).  Ids our table does not have are
                      quarantined -- reported and kept, never dropped silently.
  class row           unit +0x2E04 is the char.dat id, +0x2E0A the char.dat *row* of that id.  His
                      table has 811 rows, ours has ours, so the row number is recomputed from the id
                      (the runtime also re-points it, `d5lib/native/d5rows.inc.c`, but a save should
                      not depend on that having run).
  mastery             the six native slots at 0x30A4 + 47*24.  Our packed pool **is** Overlord's
                      encoding (P2 ported it, `d5lib.packedmastery`), so the area is already in the
                      target format and is left byte-identical: it is keyed by class family, not by
                      row or position.  The families it names are read out of the 24-bit headers (no
                      thresholds needed) and reported against the families the target build packs.
  ids >= 20000        his content.  No renumbering: the ownership manifest gives 20000-20500 to
                      Overlord, so those ids stay as they are.
  unlock flags        his WIP build uses 17283+ for custom classes (three bits per class).  The v3
                      release has no custom-class module, so a v3 save normally has none set; any that
                      *are* set are reported as unmappable rather than rewritten.

Nothing here touches the live game, the installed kit or a real save: paths under the live SaveData
folder are refused unless `--allow-live-paths` is given, and the output may never be the input.
"""
import os
import struct

from . import database, learned, ordercheck, savegame

LEARNED = 0x2E70
LEARNED_BYTES = 125
MASTERY = 0x30A4 + 47 * 24          # six native slots: 47..52 (d5lib.masterymigration.MASTERY)
MASTERY_SIZE = 144
PACKED_MAGIC = b"\xc5\x01"
FLAG_FIRST, FLAG_LAST = 17283, 17999
OVERLORD_ID_FIRST = 20000


# --------------------------------------------------------------------------------- table helpers
def table_ids(member_bytes, name="Skill.dat"):
    """the ordered id list of a member, which is what the learned bitmap addresses"""
    table = database.load_table(name, member_bytes)
    ids = ordercheck._ids(table)
    if ids is None:
        raise ValueError(f"{name}: no integer id key")
    return ids


def row_of_id(member_bytes, name="char.dat"):
    """{char.dat id: index of its first row} -- the game reads the first row of an id"""
    table = database.load_table(name, member_bytes)
    out = {}
    for i, row in enumerate(table.rows):
        out.setdefault(row["id"], i)
    return out


def mastery_entries(area):
    """[(family, completed_ranks, stored_counters)] from a packed area, without needing thresholds.

    The 3-byte headers of `d5lib.packedmastery` carry family//10 (13 bits), k (3) and n (3), so the
    families a pool names can be read even when the caller has no rank thresholds.
    """
    if len(area) != MASTERY_SIZE or area[:2] != PACKED_MAGIC:
        return None
    out, pos = [], 4
    while pos + 3 <= 120:
        h = int.from_bytes(area[pos:pos + 3], "little")
        if not h:
            break
        fid, k, n = h & 0x1FFF, (h >> 13) & 7, (h >> 16) & 7
        if h >> 19 or not fid or k > 6 or n > 6 - k:
            return None
        out.append((fid * 10, k, n))
        pos += 3 + 3 * n
    return out


# ------------------------------------------------------------------------------------------ importer
class Plan:
    """What the conversion would do, computed before a byte of the save changes."""

    def __init__(self, *, source_skill, target_skill, source_char=None, target_char=None,
                 packed_families=None):
        self.src_ids = table_ids(source_skill, "Skill.dat")
        self.tgt_ids = table_ids(target_skill, "Skill.dat")
        self.src_row = row_of_id(source_char) if source_char else None
        self.tgt_row = row_of_id(target_char) if target_char else None
        self.packed = set(int(f) for f in (packed_families or ()))
        self.units = []
        self.totals = dict(units=0, learned=0, moved=0, mapped=0, overflow=0, unknown=0,
                           classes_repointed=0, classes_unknown=0)
        self.unknown_ids = {}
        self.unknown_classes = {}
        self.mastery_families = {}
        self.mastery_unpacked = []
        self.flags = []

    # --- read
    def inspect(self, save):
        for unit in save.units():
            self.units.append(self._unit(unit, save, write=False))
        self._common(save)
        return self

    def apply(self, save):
        """Re-address every unit in place; the caller writes the file."""
        self.units = []
        for unit in save.units():
            self.units.append(self._unit(unit, save, write=True))
        self._common(save)
        return self

    def _unit(self, unit, save, write):
        base = unit.base
        off = base + LEARNED
        bitmap = bytes(save.state[off:off + LEARNED_BYTES])
        rec = {"serial": unit.serial, "name": unit.name, "class": unit.cls, "slot": unit.slot,
               "learned": 0, "overflow": [], "unknown": [], "moved": 0, "class_row": None}
        try:
            new, overflow, unknown, moved = ordercheck.remap_bitmap(bitmap, self.src_ids, self.tgt_ids)
        except ValueError as exc:
            rec["error"] = str(exc)
            return rec
        rec["learned"] = sum(bin(b).count("1") for b in bitmap[:LEARNED_BYTES])
        rec["overflow"], rec["unknown"], rec["moved"] = overflow, unknown, moved
        if write and new != bitmap:
            save.state[off:off + LEARNED_BYTES] = new
        for i in unknown:
            self.unknown_ids[i] = self.unknown_ids.get(i, 0) + 1
        cls = unit.cls
        if self.tgt_row is not None:
            row = self.tgt_row.get(cls)
            old = savegame._s16(save.state, base + savegame.U_ROW)
            if row is None:
                rec["class_unknown"] = True
                self.unknown_classes[cls] = self.unknown_classes.get(cls, 0) + 1
            elif row != old:
                rec["class_row"] = [old, row]
                if write:
                    struct.pack_into("<h", save.state, base + savegame.U_ROW, int(row))
        self.totals["learned"] += rec["learned"]
        self.totals["mapped"] += rec["learned"] - len(overflow) - len(unknown)
        self.totals["moved"] += moved
        self.totals["overflow"] += len(overflow)
        self.totals["unknown"] += len(unknown)
        if rec.get("class_row"):
            self.totals["classes_repointed"] += 1
        if rec.get("class_unknown"):
            self.totals["classes_unknown"] += 1
        return rec

    def _common(self, save):
        self.totals["units"] = len(self.units)
        fams = 0
        for unit in save.units():
            area = bytes(save.state[unit.base + MASTERY:unit.base + MASTERY + MASTERY_SIZE])
            entries = mastery_entries(area)
            if entries is None:
                if any(area):
                    self.mastery_unpacked.append({"serial": unit.serial, "name": unit.name})
                continue
            for family, _k, _n in entries:
                self.mastery_families[family] = self.mastery_families.get(family, 0) + 1
                fams += 1
        if self.packed:
            self.mastery_unpacked_families = sorted(set(self.mastery_families) - self.packed)
        self.flags = [n for n in range(FLAG_FIRST, FLAG_LAST + 1) if save.flag(n)]
        return self

    # --- results
    def overflow_by_serial(self):
        out = {}
        for rec in self.units:
            if rec.get("overflow"):
                out[int(rec["serial"])] = sorted(rec["overflow"])
        return out

    def as_dict(self):
        names = {int(r["serial"]): r["name"] for r in self.units if r.get("serial")}
        return {
            "source_rows": len(self.src_ids),
            "target_rows": len(self.tgt_ids),
            "totals": dict(self.totals),
            "units": self.units,
            "unmappable": {
                "evility_ids": sorted(self.unknown_ids),
                "class_ids": sorted(self.unknown_classes),
                "mastery_families_not_packed": sorted(getattr(self, "mastery_unpacked_families", [])),
                "mastery_unpacked_units": self.mastery_unpacked,
                "unlock_flags_17283_plus": self.flags,
            },
            "mastery_families": {str(k): v for k, v in sorted(self.mastery_families.items())},
            "unit_names": names,
            "notes": self.notes(),
        }

    def notes(self):
        out = []
        if self.totals["unknown"]:
            out.append(f"{self.totals['unknown']} learned evility id(s) are not in the target table: "
                       f"kept in the companion's quarantine, not learned in game")
        if self.totals["overflow"]:
            out.append(f"{self.totals['overflow']} learned evility id(s) sit past bitmap position "
                       f"{ordercheck.BITSET_CAP} in the target table: written to the learned-evility "
                       f"companion, which the runtime applies on load")
        if self.totals["classes_unknown"]:
            out.append(f"{self.totals['classes_unknown']} unit(s) are in a class the target char.dat "
                       f"does not have; their class is left as it is")
        if self.flags:
            out.append(f"unlock flags {self.flags[:8]} are set; the kit does not map Overlord's WIP "
                       f"custom-class flags, so they are left alone")
        if self.mastery_unpacked:
            out.append(f"{len(self.mastery_unpacked)} unit(s) hold mastery bytes that are neither all "
                       f"zero nor a packed pool; left untouched")
        if not out:
            out.append("every learned evility, class and mastery entry maps to the target tables")
        return out


def convert(save_path, out_path, *, source_skill, target_skill, source_char=None, target_char=None,
            packed_families=None, companion=True, log=print):
    """Copy `save_path` to `out_path`, re-addressing it, and write the learned-evility companion.

    Returns (report, companion_path|None).  The input file is only read.
    """
    if os.path.abspath(save_path) == os.path.abspath(out_path):
        raise ValueError("the output must be a different file from the input (work on a copy)")
    skill_src = as_bytes(source_skill)
    skill_tgt = as_bytes(target_skill)
    char_src = as_bytes(source_char) if source_char else None
    char_tgt = as_bytes(target_char) if target_char else None
    save = savegame.Save(save_path)
    plan = Plan(source_skill=skill_src, target_skill=skill_tgt, source_char=char_src,
                target_char=char_tgt, packed_families=packed_families)
    plan.apply(save)
    data = save.to_bytes()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(data)
    report = plan.as_dict()
    report["input"] = os.path.abspath(save_path)
    report["output"] = os.path.abspath(out_path)
    report["sha256_in"] = _sha(save_path)
    report["sha256_out"] = _sha(out_path)
    companion_path = None
    if companion and report["totals"]["overflow"]:
        doc = learned.sidecar_doc(out_path, plan.tgt_ids, plan.overflow_by_serial(),
                                  unit_names=report["unit_names"])
        companion_path = out_path + learned.SIDECAR_SUFFIX
        learned.sidecar_write(companion_path, doc)
        report["companion"] = companion_path
        log(f"  learned-evility companion: {companion_path} ({len(doc['units'])} unit(s))")
    return report, companion_path


def as_bytes(data):
    """a member or a path to one (the proof harness already holds the bytes)"""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    with open(data, "rb") as f:
        return f.read()


def _sha(path):
    import hashlib
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def live_save_roots():
    """directories the agent must not write to by accident (the game's own SaveData)"""
    roots = []
    try:
        roots.append(os.path.abspath(savegame.save_root()))
    except Exception:
        pass
    return roots


def under_live(save_root, path):
    p = os.path.abspath(path)
    return any(p == r or p.startswith(r + os.sep) for r in [os.path.abspath(save_root)])
