"""Re-lease a mod pack's database ids from the ownership manifest (offline, copy-only).

A pack built in isolation picks ids from the free pool it can see.  Two packs built that way can pick
the same id, and then two mods append the same row: DUPFIX found that across the installed set (491-495,
the D4 skill band, 17 copies of charPersonal 132-134).  The fix is not to edit an installed folder but
to re-lease the ids **at the pack source**:

  plan()   compares the pack's `patches/db/*.json` claims with every other mod's claims (and with the
           vanilla table) and leases a fresh id for each one that collides, from the band the manifest
           gives that namespace;
  apply()  copies the pack folder to an output directory and rewrites the ids there -- added rows, and
           the references inside the pack's own char.dat rows (`evility1..4`, `learn*_skill`) -- so the
           copy is self-consistent.

Nothing here writes to the pack, to the installed kit or to the game: `apply()` copies to a new folder
and rewrites the copy.  `tools/release_pack_ids.py` is the CLI.
"""
import json
import os
import re
import shutil

from . import modclaims

# member -> (manifest namespace, preferred allocation range, what the id is)
MEMBERS = {
    "Skill.dat": ("evility_id", (7000, 7999), "evility row"),
    "magic.dat": ("special_id", (13000, 39999), "skill row"),
    "charPersonal.dat": ("personality_id", (132, 65535), "personality row"),
}

# char.dat fields that name another table's row (the pack's own references into Skill.dat / magic.dat)
REF_FIELDS = ("evility1", "evility2", "evility3", "evility4") + tuple(
    f"learn{n}_skill" for n in range(1, 17))


class Lease:
    __slots__ = ("member", "namespace", "old", "new", "reason")

    def __init__(self, member, namespace, old, new, reason=""):
        self.member, self.namespace = member, namespace
        self.old, self.new, self.reason = int(old), int(new), reason

    def as_dict(self):
        return dict(member=self.member, namespace=self.namespace, old=self.old, new=self.new,
                    reason=self.reason)

    def __str__(self):
        return f"{self.member}[{self.old}] -> {self.new} ({self.namespace})"


class Plan:
    def __init__(self, pack):
        self.pack = pack
        self.leases = []
        self.findings = []              # (kind, member, id, detail) -- what this tool cannot fix

    @property
    def ok(self):
        return not self.findings

    def map_for(self, member):
        return {l.old: l.new for l in self.leases if l.member == member}

    def as_dict(self):
        return dict(pack=self.pack, leases=[l.as_dict() for l in self.leases],
                    unfixable=[dict(kind=k, member=m, id=i, detail=d) for k, m, i, d in self.findings])


def _band_owner(manifest, namespace, rid):
    ns = manifest.namespace(namespace)
    if ns is None or ns.kind != "range":
        return None, None
    for band in ns.bands:
        if band.start <= rid <= band.end:
            return band.owner, band
    return None, None


def free_id(manifest, namespace, lo, hi, used):
    """The lowest id in `lo..hi` that nobody uses and the manifest gives to the kit."""
    for rid in range(lo, hi + 1):
        if rid in used:
            continue
        owner, _band = _band_owner(manifest, namespace, rid)
        if owner == "kit":
            return rid
    return None


def plan(pack_dir, scan_others, vanilla_ids, manifest, only_ids=None):
    """Lease fresh ids for every claim of `pack_dir` that collides with `scan_others` or vanilla.

    `only_ids` = {member: {ids}} restricts the re-lease to those claims (the ids a pack should yield;
    the canonical copy of a shared row stays where it is).  Ids the pack already owns are never handed
    out again, so a pack can never be given one of its own ids.
    """
    mod = os.path.basename(os.path.normpath(pack_dir))
    scan = modclaims.scan_mods(os.path.dirname(os.path.abspath(pack_dir)), only=[mod])
    result = Plan(mod)

    for member in sorted(MEMBERS):
        namespace, (lo, hi), what = MEMBERS[member]
        ids = sorted(scan.added.get(member, {}))
        if not ids:
            continue
        others = set(scan_others.added.get(member, {}))
        vanilla = set(vanilla_ids.get(member, {}))
        used = others | vanilla | set(ids)
        if only_ids is not None and member in only_ids:
            ids = [i for i in ids if i in set(only_ids[member])]
        elif only_ids is not None:
            continue
        for rid in ids:
            holders = sorted(scan_others.added.get(member, {}).get(rid, []))
            if rid in vanilla:
                reason = f"vanilla {member} already has id {rid}"
            elif holders:
                reason = f"also appended by {', '.join(holders)}"
            else:
                continue
            new = free_id(manifest, namespace, lo, hi, used | set(result.map_for(member).values()))
            if new is None:
                result.findings.append(("no_free_id", member, rid, f"no free {namespace} id in {lo}..{hi}"))
                continue
            used.add(new)
            result.leases.append(Lease(member, namespace, rid, new, reason))

    # A row-index patch cannot be re-leased: it edits a vanilla row, so two mods patching it differently
    # is a source problem (the DRPG sample used to write outfit slot 490 = vanilla row 48).  Report it.
    for member in sorted(scan.patched):
        for index in sorted(scan.patched[member]):
            mine = scan.patch_payloads.get((member, index), {}).get(mod)
            theirs = scan_others.patch_payloads.get((member, index), {})
            if mine is None or not theirs:
                continue
            try:
                mine_row = json.loads(mine)
            except ValueError:
                continue
            fields = []
            for field, value in mine_row.items():
                for blob in theirs.values():
                    try:
                        row = json.loads(blob)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and field in row and row[field] != value:
                        fields.append(field)
                        break
            if fields:
                result.findings.append((
                    "row_patch_conflict", member, index,
                    f"row index {index} is also patched by {', '.join(sorted(theirs))} and disagrees on "
                    f"{', '.join(sorted(fields)[:6])}; a row index cannot be re-leased, fix the pack source"))
    return result


# ----------------------------------------------------------------------------------------------- apply
def _load(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def _dump(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(data, indent=1, ensure_ascii=False))
        fh.write("\n")


def _renumber_added(patch, mapping):
    """Rewrite `added[].id` (and sections) for one member; returns the number of rows changed."""
    changed = 0
    for row in patch.get("added") or ():
        if not isinstance(row, dict) or "id" not in row:
            continue
        old = int(row["id"])
        if old in mapping:
            row["id"] = mapping[old]
            changed += 1
    for _name, sub in (patch.get("sections") or {}).items():
        if isinstance(sub, dict):
            changed += _renumber_added(sub, mapping)
    return changed


def _repoint(row, mapping, changed):
    for field in REF_FIELDS:
        if field in row and isinstance(row[field], int) and row[field] in mapping:
            row[field] = mapping[row[field]]
            changed.add(field)


def _repoint_mod_json(node, mapping, hits):
    """`mod.json` provenance carries the same ids (fields.evility1, learn*_skill, d5_id)."""
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key in ("evility1", "evility2", "evility3", "evility4", "d5_id") or re.fullmatch(
                    r"learn\d+_skill", key):
                if isinstance(value, int) and value in mapping:
                    node[key] = mapping[value]
                    hits.append(key)
            else:
                _repoint_mod_json(value, mapping, hits)
    elif isinstance(node, list):
        for item in node:
            _repoint_mod_json(item, mapping, hits)


def apply(pack_dir, out_dir, plan_):
    """Copy `pack_dir` to `out_dir/<mod>` and rewrite the planned ids there.  Returns a receipt."""
    mod = plan_.pack
    dest = os.path.join(out_dir, mod)
    if os.path.abspath(dest) == os.path.abspath(pack_dir):
        raise ValueError("apply() writes a copy: the destination must differ from the source pack")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(pack_dir, dest, symlinks=True)

    skill_map = plan_.map_for("Skill.dat")
    magic_map = plan_.map_for("magic.dat")
    ref_map = dict(skill_map)
    ref_map.update(magic_map)

    written = []
    dbdir = os.path.join(dest, "patches", "db")
    for name in sorted(os.listdir(dbdir)) if os.path.isdir(dbdir) else ():
        if not name.lower().endswith(".json"):
            continue
        member = name[:-5]
        path = os.path.join(dbdir, name)
        patch = _load(path)
        before = json.dumps(patch, sort_keys=True)
        mapping = plan_.map_for(member)
        changed_rows = _renumber_added(patch, mapping) if mapping else 0
        ref_fields = set()
        if member == "char.dat" and ref_map:
            for row in patch.get("added") or ():
                if isinstance(row, dict):
                    _repoint(row, ref_map, ref_fields)
            for row in (patch.get("rows") or {}).values():
                if isinstance(row, dict):
                    _repoint(row, ref_map, ref_fields)
        if json.dumps(patch, sort_keys=True) != before:
            _dump(path, patch)
            written.append(dict(file=f"patches/db/{name}", rows=changed_rows,
                                reference_fields=sorted(ref_fields)))

    mod_json = os.path.join(dest, "mod.json")
    hits = []
    if os.path.exists(mod_json) and ref_map:
        data = _load(mod_json)
        _repoint_mod_json(data, ref_map, hits)
        if hits:
            _dump(mod_json, data)
            written.append(dict(file="mod.json", reference_fields=sorted(set(hits))))

    return dict(mod=mod, source=os.path.abspath(pack_dir), out=os.path.abspath(dest),
                leases=[l.as_dict() for l in plan_.leases], written=written,
                unfixable=plan_.as_dict()["unfixable"])
