"""DRPG v2 lease/pin manifest: 146 low base rows + 89 high-art costume looks.

The costume-only route (DRPGHIGHID2) keeps every base a low unique row and gives
each costume its own high class id with art at a high `N` (``sprite_id ==
color_id == N``).  This module builds that manifest from the installed kit's
read-only inventory and the private research pins, and re-runs the collision
audit against it.  It never installs, launches or writes outside its own output.

A manifest that no longer matches the pinned inventory/proposal hashes is
invalid by definition: the checker reports the pin mismatch instead of trusting
stale rows.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import _drpg_text

SCHEMA = "drpg-leases/2"
STATUS = "LEASE v2 (costume-only route) - offline, not installed"

# Native/prior-art bands.  Overlord's custom characters live at 20000..21999.
OVERLORD_BAND = (20000, 21999)
# Measured-free high class band from the CORERPG2 audit (step 10, signed-short safe).
COSTUME_CLASS_BAND = (30000, 32760)
# Measured-free high art band from the CORERPG2 audit (the candidate, not a grant).
ART_BAND = (14560, 19990)

# Melodia 5 (257, 970, 33, 277, 284), Noel 3 (267, 287, 294), Citri 1 (264),
# Zed 1 (217): existing installed rows that stay reserved for compatibility.
SAMPLE_ZED_ROWS = (33, 217, 257, 264, 267, 277, 284, 287, 294, 970)

# A lease owns the class row plus the two slot-keyed files the Kit writer emits
# (slot+2 standing icon, slot+10000 portrait) and the row-keyed resident face and
# banner anims.  The body art is an independent high group N (see ART_BAND): the
# Kit's create_drpg_character already sets sprite_id to a free sprite, and the
# CORERPG2 193-row enumeration deliberately does not consume the row's own
# sprite number.  Requiring `anm<n>` too would leave only 102 rows.
BASE_SLOT_OFFSETS = (2, 10000)
COSTUME_FILE_OFFSETS = (0, 1, 2)
RESIDENT_SPAN = 10  # N..N+9 and 10000+N..10009+N carved exactly

MANIFEST = Path(__file__).with_name("drpg-leases.json")


def load(path=None):
    """The v2 manifest as a dict.  Read-only: no inventory walk, no rebuild (K1 then reads, never recomputes)."""
    return copy.deepcopy(_drpg_text.load(Path(path or MANIFEST)))        # names are @authored in the file (TEXTHASH-DRPG)


def index(manifest):
    """({'drpg:<base id>': base lease}, {'drpg:<look id>': costume lease})."""
    bases = {b["lease"]: b for b in manifest.get("bases") or []}
    costumes = {c["lease"]: c for c in manifest.get("costumes") or []}
    return bases, costumes


def verify(manifest, inventory=None, grouping_path=None):
    """Problems that make the manifest unusable without a rebuild.  The inventory pin can only be re-checked
    against a live inventory (`check`); the file pins are re-hashed here."""
    problems = []
    pins = manifest.get("pins") or {}
    # SOURCEPREP4-DRPG: the grouping-decisions pin is re-hashed only when the maintainer names that file; a build reads
    # no research folder (the roster is drpg-roster.json).
    for key, path in ((("grouping_sha256", Path(grouping_path)),) if grouping_path else ()):
        if path.is_file() and pins.get(key) and _sha256_file(path) != pins[key]:
            problems.append(f"pin {key} does not match {path} (inputs moved; rebuild the manifest)")
    for b in manifest.get("bases") or []:
        if b.get("sprite_id") != b.get("art") or b.get("class_id", 0) >= 1000:
            problems.append(f"{b.get('lease')}: base must be a low row with sprite = its own art group")
        if b.get("art", 0) < 1000:
            problems.append(f"{b.get('lease')}: base art {b.get('art')!r} is its row, not an independent sprite "
                            "(K0: sprite = row leaves 102 low rows instead of 193)")
    for c in manifest.get("costumes") or []:
        if c.get("class_id", 0) < 1000:
            problems.append(f"{c.get('lease')}: costume class id {c.get('class_id')!r} is not high")
        if c.get("sprite_id") != c.get("art") or c.get("color_id") != c.get("art"):
            problems.append(f"{c.get('lease')}: costume art must be sprite_id = color_id = N")
    return problems



def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


class Inventory:
    """Every claim the manifest must avoid, plus the pins a manifest records.

    `pins` is the dict written into a manifest: inventory fingerprint, proposal
    hashes, ownership manifest hash.  Tests construct this directly; the live
    reader is `collect`.
    """

    def __init__(self, *, vanilla_ids, installed_char_ids, used_art,
                 face_anims, banner_anims, lease_identities=(),
                 dummy_rows=(470, 480, 490, 950, 960, 970, 980, 990),
                 helper_ids=(), pins=None):
        self.vanilla_ids = set(vanilla_ids)
        self.installed_char_ids = set(installed_char_ids)
        self.used_art = set(used_art)
        self.face_anims = set(face_anims)
        self.banner_anims = set(banner_anims)
        self.lease_identities = set(lease_identities)
        self.dummy_rows = set(dummy_rows)
        self.helper_ids = set(helper_ids)
        self.pins = dict(pins or {})
        self.installed_definitions = None

    # -- pools -----------------------------------------------------------
    def low_row_free(self, n: int) -> bool:
        if not 10 <= n <= 999:
            return False
        if n in self.vanilla_ids and n not in self.dummy_rows:
            return False
        if n in self.installed_char_ids or n in self.helper_ids:
            return False
        if {n + k for k in BASE_SLOT_OFFSETS} & self.used_art:
            return False
        if {n, n + 10000} & self.face_anims or n in self.banner_anims:
            return False
        return True

    def free_low_rows(self):
        """Kit allocation order: free dummy rows first, then ascending free ids."""
        free = [i for i in range(10, 1000) if self.low_row_free(i)]
        return sorted(free, key=lambda i: (0 if i in self.dummy_rows else 1, i))

    def costume_class_free(self, n: int) -> bool:
        if not COSTUME_CLASS_BAND[0] <= n <= COSTUME_CLASS_BAND[1] or n % 10:
            return False
        if OVERLORD_BAND[0] <= n <= OVERLORD_BAND[1]:
            return False
        if n in self.vanilla_ids or n in self.installed_char_ids:
            return False
        return n not in self.lease_identities

    def free_costume_class_ids(self):
        return [n for n in range(COSTUME_CLASS_BAND[0], COSTUME_CLASS_BAND[1] + 1, 10)
                if self.costume_class_free(n)]

    def art_group_free(self, n: int, taken=()) -> bool:
        if not ART_BAND[0] <= n <= ART_BAND[1] or n % 10:
            return False
        if n + RESIDENT_SPAN - 1 > 32767:
            return False
        files = {n, n + 1, n + 2} | set(range(n + 10000, n + 10000 + RESIDENT_SPAN))
        residents = (set(range(n, n + RESIDENT_SPAN))
                     | set(range(n + 10000, n + 10000 + RESIDENT_SPAN)))
        if (files | residents) & (self.used_art | set(taken)):
            return False
        if residents & self.face_anims or set(range(n, n + RESIDENT_SPAN)) & self.banner_anims:
            return False
        return True

    def free_art_groups(self, count):
        out = []
        for n in range(ART_BAND[0], ART_BAND[1] + 1, 10):
            if len(out) == count:
                break
            if self.art_group_free(n, self._art_taken(out)):
                out.append(n)
        return out

    @staticmethod
    def _art_taken(groups):
        taken = set()
        for n in groups:
            taken |= {n, n + 1, n + 2} | set(range(n + 10000, n + 10000 + RESIDENT_SPAN))
            taken |= set(range(n, n + RESIDENT_SPAN))
        return taken


def roster(grouping):
    """[(base dict, [costume look dicts])] in ascending source-base order."""
    characters = grouping.get("characters") or []
    if grouping.get("schema") != "drpg-grouping-decisions/1":
        raise ValueError("unsupported DRPG grouping schema")
    out = []
    for group in sorted(characters, key=lambda g: g["base_id"]):
        by_id = {int(l["id"]): l for l in group["looks"]}
        costumes = [by_id[int(c)] for c in group.get("costume_ids") or []]
        if len(costumes) != len(group.get("costume_ids") or []):
            raise ValueError(f"character {group['base_id']} names an unassigned costume")
        out.append((group, costumes))
    return out


def base_claims(n, art):
    return {
        "row": n,
        "slot_files": [n + 2, n + 10000],
        "art_group": [art, art + 1, art + 2] + list(range(art + 10000, art + 10000 + RESIDENT_SPAN)),
        "face_anims": [n, n + 10000],
        "banner_anims": [n],
    }


def costume_claims(n):
    return {
        "art": [n + k for k in COSTUME_FILE_OFFSETS],
        "portrait_cutin": list(range(n + 10000, n + 10000 + RESIDENT_SPAN)),
        "resident_face": (list(range(n, n + RESIDENT_SPAN))
                          + list(range(n + 10000, n + 10000 + RESIDENT_SPAN))),
        "banner": list(range(n, n + RESIDENT_SPAN)),
        # K2 assigns an explicit texture cell; not derivable at N >= 14560.
        "icon": None,
    }


def build(grouping, inventory, *, generated):
    """Assign every base a free low row, every look a high class id (+ base) and art N."""
    rows = inventory.free_low_rows()
    groups = roster(grouping)
    looks = sum(1 + len(cs) for _, cs in groups)
    if len(rows) < 146:
        raise ValueError(f"only {len(rows)} free low rows; 146 bases need a lease")
    classes = inventory.free_costume_class_ids()
    costumes = [(g, c) for g, cs in groups for c in cs]
    if len(classes) < len(costumes):
        raise ValueError(f"only {len(classes)} free high class ids for {len(costumes)} costumes")
    art = inventory.free_art_groups(looks)
    if len(art) < looks:
        raise ValueError(f"only {len(art)} free high art groups for {looks} looks")

    bases, cost = {}, {}
    pos = 0
    for i, (group, cs) in enumerate(groups):
        n, a = rows[i], art[pos]
        pos += 1
        bases[group["base_id"]] = {
            "lease": f"drpg:{group['base_id']}",
            "name": group.get("name") or "",
            "kind": group.get("kind") or "",
            "class_id": n,
            "art": a,
            "sprite_id": a,
            "color_id": a,
            "claims": base_claims(n, a),
        }
        for look in cs:
            a = art[pos]
            pos += 1
            cost[str(look["id"])] = {
                "lease": f"drpg:{look['id']}",
                "name": look.get("en") or "",
                "owner": f"drpg:{group['base_id']}",
                "owner_class_id": n,
                "body_kind": look.get("type") or "",
                "class_id": classes[len(cost)],
                "art": a,
                "sprite_id": a,
                "color_id": a,
                "claims": costume_claims(a),
            }
    leased_rows = {b["class_id"] for b in bases.values()}
    return {
        "schema": SCHEMA,
        "status": STATUS,
        "generated": generated,
        "route": ("costume-only: 146 low unique bases + 89 high-class costume rows, every look "
                  "with its own high art group N (%d..%d step 10, sprite=color=N)"
                  % (ART_BAND[0], ART_BAND[1])),
        "pins": dict(inventory.pins),
        "counts": {"bases": len(bases), "costumes": len(cost),
                   "looks": len(bases) + len(cost),
                   "costume_class_ids": len({c["class_id"] for c in cost.values()}),
                   "art_groups": len({b["art"] for b in bases.values()}
                                     | {c["art"] for c in cost.values()})},
        "reserved": {
            "sample_zed_rows": [r for r in SAMPLE_ZED_ROWS if r not in leased_rows],
            "spare_low_rows": [r for r in rows if r not in leased_rows],
        },
        "bases": [bases[g["base_id"]] for g, _ in groups],
        "costumes": [cost[str(l["id"])] for _, l in costumes],
    }


def check(manifest, inventory, *, pins_expected=None):
    """Return a list of problems; empty means the manifest is valid and collision-free."""
    problems = []
    if manifest.get("schema") != SCHEMA:
        problems.append(f"schema {manifest.get('schema')!r} != {SCHEMA!r}")
    if manifest.get("status") != STATUS:
        problems.append(f"status {manifest.get('status')!r} is not the v2 lease status")
    expected = dict(pins_expected if pins_expected is not None else inventory.pins)
    recorded = manifest.get("pins") or {}
    for key, value in expected.items():
        if recorded.get(key) != value:
            problems.append(f"pin {key}: manifest {recorded.get(key)!r} != input {value!r} "
                            "(moved kit or revised proposal; rebuild the manifest)")
    bases = manifest.get("bases") or []
    costumes = manifest.get("costumes") or []
    if len(bases) != 146:
        problems.append(f"{len(bases)} base leases, expected 146")
    if len(costumes) != 89:
        problems.append(f"{len(costumes)} costume leases, expected 89")

    seen_rows, seen_ids, seen_art = {}, {}, {}
    face_taken, banner_taken = set(), set()

    seen = {"row": seen_rows, "id": seen_ids, "art": seen_art}

    def claim(kind, key, owner):
        table = seen[kind]
        if key in table:
            problems.append(f"{kind} {key} claimed by both {table[key]} and {owner}")
        else:
            table[key] = owner

    def art_claims(owner, files, residents, banner):
        for key in files:
            if key in inventory.used_art:
                problems.append(f"{owner}: file key {key} is already used ({_who_art(inventory, key)})")
            if key in seen_art:
                problems.append(f"art key {key} claimed by both {seen_art[key]} and {owner}")
            else:
                seen_art[key] = owner
        for key in residents:
            if key in inventory.face_anims or key in face_taken:
                problems.append(f"{owner}: resident face anim {key} is taken")
            face_taken.add(key)
        for key in banner:
            if key in inventory.banner_anims or key in banner_taken:
                problems.append(f"{owner}: banner anim {key} is taken")
            banner_taken.add(key)

    for b in bases:
        owner = b.get("lease")
        n, a = b.get("class_id"), b.get("art")
        if not isinstance(n, int):
            problems.append(f"{owner}: base class id {n!r} is not an integer")
            continue
        if b.get("sprite_id") != a or b.get("color_id") != a:
            problems.append(f"{owner}: base sprite/color must equal its art group {a}")
        claim("row", n, owner)
        if not inventory.low_row_free(n):
            problems.append(f"{owner}: low row {n} is not free in the audited inventory")
        claims = b.get("claims") or {}
        if claims.get("row") != n or claims.get("slot_files") != [n + 2, n + 10000]:
            problems.append(f"{owner}: slot claim block does not match row {n}")
        for key in claims.get("slot_files") or []:
            if key in inventory.used_art:
                problems.append(f"{owner}: slot file {key} is already used ({_who_art(inventory, key)})")
        if claims.get("face_anims") != [n, n + 10000] or claims.get("banner_anims") != [n]:
            problems.append(f"{owner}: resident claim block does not match row {n}")
        files = claims.get("art_group") or []
        if files[:3] != [a, a + 1, a + 2]:
            problems.append(f"{owner}: art group block does not match N={a}")
        art_claims(owner, files, [], [])
        for key in claims.get("face_anims") or []:
            if key in inventory.face_anims or key in face_taken:
                problems.append(f"{owner}: resident face anim {key} is taken")
            face_taken.add(key)
        for key in claims.get("banner_anims") or []:
            if key in inventory.banner_anims or key in banner_taken:
                problems.append(f"{owner}: banner anim {key} is taken")
            banner_taken.add(key)

    owner_leases = {b.get("lease") for b in bases}
    for c in costumes:
        owner, cid, art = c.get("lease"), c.get("class_id"), c.get("art")
        if c.get("owner") not in owner_leases:
            problems.append(f"{owner}: owning base {c.get('owner')!r} is not leased")
        if c.get("sprite_id") != art or c.get("color_id") != art:
            problems.append(f"{owner}: costume must carry sprite=color=art N")
        if isinstance(cid, int):
            claim("id", cid, owner)
            if not inventory.costume_class_free(cid):
                problems.append(f"{owner}: high class id {cid} is outside the free band")
        if isinstance(art, int):
            claims = c.get("claims") or {}
            if claims.get("art") != [art, art + 1, art + 2]:
                problems.append(f"{owner}: art claim block does not match N={art}")
            files = (claims.get("art") or []) + (claims.get("portrait_cutin") or [])
            art_claims(owner, files, claims.get("resident_face") or [],
                       claims.get("banner") or [])
    return problems


def rebase(manifest, inventory, *, generated):
    """Minimal re-lease: every base whose low row (or the row's slot/face/banner keys) is no longer free moves to
    the next free row in Kit order; every other lease, every art group and every costume stays byte-identical.
    Returns (new manifest, {lease: (old row, new row)})."""
    new = json.loads(json.dumps(manifest))
    kept = {b["class_id"] for b in new["bases"] if inventory.low_row_free(b["class_id"])}
    moved = {}
    pool = [r for r in inventory.free_low_rows() if r not in kept and r not in SAMPLE_ZED_ROWS]
    for b in new["bases"]:
        n = b["class_id"]
        if n in kept:
            continue
        if not pool:
            raise ValueError("no free low row left to re-lease %s" % b["lease"])
        m = pool.pop(0)
        moved[b["lease"]] = (n, m)
        b["class_id"] = m
        b["claims"] = base_claims(m, b["art"])
        for c in new["costumes"]:
            if c.get("owner") == b["lease"]:
                c["owner_class_id"] = m
        kept.add(m)
    leased = {b["class_id"] for b in new["bases"]}
    new["generated"] = generated
    new["pins"] = dict(inventory.pins)
    new["reserved"] = {"sample_zed_rows": [r for r in SAMPLE_ZED_ROWS if r not in leased],
                       "spare_low_rows": [r for r in inventory.free_low_rows()
                                           if r not in leased and r not in SAMPLE_ZED_ROWS]}
    new["rebased"] = {k: list(v) for k, v in sorted(moved.items())}
    return new, moved


# the gate's view of what a DRPG lease claims (importcore.lease_claims): every number below counts as an ANM number,
# the resident face/banner animation ids included, so a re-lease must keep clear of all of them.
def base_gate_anm(n, art):
    return {n, n + 2, n + 10000, *range(art, art + RESIDENT_SPAN), *range(art + 10000, art + 10000 + RESIDENT_SPAN)}


def costume_gate_anm(art):
    return {*range(art, art + RESIDENT_SPAN), *range(art + 10000, art + 10000 + RESIDENT_SPAN)}


def release(manifest, inventory, claimed, *, keep=("drpg:94",), generated=None):
    """Re-lease against the cross-importer union: `claimed` = {kind: {ids}} that OTHER owners hold (the used-id gate's
    index without the DRPG manifest: kinds 'char.dat', 'anm', ...).  A lease that still clears vanilla, installed,
    every other importer's lease/pack and the other DRPG leases is left byte-identical; the rest move to the next free
    row / art group / costume class.  `keep` leases (Zed: save slot 04 wears costume 30170) must not move: a collision
    on them raises instead of moving.  Returns (new manifest, {lease: {field: (old, new)}})."""
    new = json.loads(json.dumps(manifest))
    ch, anm = claimed.get("char.dat", set()), claimed.get("anm", set())
    rows_used, anm_used, cls_used = set(), set(), set()
    moved = {}
    order = sorted(new["bases"], key=lambda b: b["lease"] not in keep)
    rowpool = [r for r in inventory.free_low_rows() if r not in SAMPLE_ZED_ROWS]
    artpool = [n for n in range(ART_BAND[0], ART_BAND[1] + 1, 10)]
    clspool = list(range(COSTUME_CLASS_BAND[0], COSTUME_CLASS_BAND[1] + 1, 10))

    def take(pool, ok):
        for x in pool:
            if ok(x):
                return x
        raise ValueError("pool exhausted")

    costumes_of = {}
    for c in new["costumes"]:
        costumes_of.setdefault(c["owner"], []).append(c)

    def row_fine(r):
        return (inventory.low_row_free(r) and r not in ch and not ({r, r + 2, r + 10000} & anm))

    def art_fine(a):
        return inventory.art_group_free(a) and not (costume_gate_anm(a) & anm)

    def cls_fine(c):
        return inventory.costume_class_free(c) and c not in ch

    # pass 1: whatever already clears everyone else stays and is reserved before anything moves (a mover must
    # not take a row a later, still-fine lease owns, or the moves cascade)
    for b in order:
        if row_fine(b["class_id"]):
            rows_used.add(b["class_id"])
            anm_used |= {b["class_id"], b["class_id"] + 2, b["class_id"] + 10000}
        if art_fine(b["art"]):
            anm_used |= costume_gate_anm(b["art"])
        for c in costumes_of.get(b["lease"], []):
            if art_fine(c["art"]):
                anm_used |= costume_gate_anm(c["art"])
            if cls_fine(c["class_id"]):
                cls_used.add(c["class_id"])
    for b in order:
        lease, moves = b["lease"], {}
        a, r = b["art"], b["class_id"]
        if not art_fine(a):
            if lease in keep:
                raise ValueError(f"{lease} is pinned but its art {a} collides")
            a2 = take(artpool, lambda x: art_fine(x) and not (costume_gate_anm(x) & anm_used))
            moves["art"] = (a, a2)
            b["art"] = b["sprite_id"] = b["color_id"] = a2
            a = a2
            anm_used |= costume_gate_anm(a)
        if not row_fine(r):
            if lease in keep:
                raise ValueError(f"{lease} is pinned but its row {r} collides")
            r2 = take(rowpool, lambda x: row_fine(x) and x not in rows_used and not ({x, x + 2, x + 10000} & anm_used))
            moves["class_id"] = (r, r2)
            b["class_id"] = r2
            r = r2
            rows_used.add(r)
            anm_used |= {r, r + 2, r + 10000}
        b["claims"] = base_claims(r, a)
        for c in costumes_of.get(lease, []):
            cm = {}
            ca, cc = c["art"], c["class_id"]
            if not art_fine(ca):
                if lease in keep:
                    raise ValueError(f"{c['lease']} is pinned but its art {ca} collides")
                ca2 = take(artpool, lambda x: art_fine(x) and not (costume_gate_anm(x) & anm_used))
                cm["art"] = (ca, ca2)
                c["art"] = c["sprite_id"] = c["color_id"] = ca2
                ca = ca2
                anm_used |= costume_gate_anm(ca)
            if not cls_fine(cc):
                if lease in keep:
                    raise ValueError(f"{c['lease']} is pinned but its class id {cc} collides")
                cc2 = take(clspool, lambda x: cls_fine(x) and x not in cls_used)
                cm["class_id"] = (cc, cc2)
                c["class_id"] = cc2
                cc = cc2
                cls_used.add(cc)
            c["owner_class_id"] = r
            c["claims"] = costume_claims(ca)
            if cm:
                moved[c["lease"]] = cm
        if moves:
            moved[lease] = moves
    leased = {b["class_id"] for b in new["bases"]}
    new["reserved"] = {"sample_zed_rows": [r for r in SAMPLE_ZED_ROWS if r not in leased],
                       "spare_low_rows": [r for r in rowpool if r not in leased
                                          and base_gate_anm(r, 0) & (anm | anm_used) == set()]}
    new["pins"] = dict(inventory.pins)
    if generated:
        new["generated"] = generated
    new["released"] = {k: {f: list(v) for f, v in m.items()} for k, m in sorted(moved.items())}
    return new, moved


HELP_RANGE = (4000, 65536)      # charhelp ids >= 4000 (Kit rule)
QUEST_ID_RANGE = (1, 1490)      # recruitment quest ids below the hidden quest rows (dbpatch.PLACEHOLDER_FIRST)
QUEST_SLOT_RANGE = (0, 1024)    # progress slots below the save's 1024 bytes (dbpatch.QUEST_SLOTS)


def pin_namespaces(manifest, current, help_ids, quest_ids, slots, *, generated=None, first=("drpg:94",), dirty_slots=None):
    """Pin each base's recruit-quest id, quest progress slot and charhelp id into the manifest.

    The importer used to hand these out per run (first free, in run order, against whatever was installed that day):
    a partial or later run gave two packs the same slot, and a pack built before D1C was installed collided with D1C.
    `current` {lease: {help_id, quest_id, quest_slot}} is what the packs carry now; a base keeps it unless a value is
    taken (vanilla, installed, candidate builds, an earlier pinned base) and then moves to the next free value.
    dirty_slots (DRPG-SAVESLOT1): {"generated", "source", "slots": [...]}, the quest progress slots a known save already
    marks completed/accepted/seen (tools/save_quest_slots.py).  They count as taken, so a recruit quest never inherits
    another quest's state in a save; only the bases that collide move.  Recorded in the manifest as `dirty_slots`.
    Returns (new manifest, {lease: {field: (old, new)}})."""
    new = json.loads(json.dumps(manifest))
    dirty = {int(x) for x in (dirty_slots or {}).get("slots", [])}
    if dirty_slots:
        new["dirty_slots"] = {"generated": dirty_slots.get("generated"), "source": dirty_slots.get("source"),
                              "slots": sorted(dirty)}
        dirty |= {int(x) for x in new["dirty_slots"]["slots"]}
    elif manifest.get("dirty_slots"):
        dirty = {int(x) for x in manifest["dirty_slots"].get("slots", [])}
    taken = {"help_id": set(help_ids), "quest_id": set(quest_ids), "quest_slot": set(slots) | dirty}
    # a base whose slot is free keeps it: reserve every such slot first so a mover never takes a neighbour's
    keep = {}
    for b in new["bases"]:
        v = (current.get(b["lease"]) or {}).get("quest_slot")
        if isinstance(v, int) and v not in taken["quest_slot"] and QUEST_SLOT_RANGE[0] <= v < QUEST_SLOT_RANGE[1] \
                and v not in keep.values():
            keep[b["lease"]] = v
    held = set(keep.values())
    span = {"help_id": HELP_RANGE, "quest_id": QUEST_ID_RANGE, "quest_slot": QUEST_SLOT_RANGE}
    moved = {}
    for b in sorted(new["bases"], key=lambda b: b["lease"] not in first):   # Zed (save slot 04) allocates first
        cur = current.get(b["lease"]) or {}
        pin = {}
        for field in ("help_id", "quest_id", "quest_slot"):
            v = cur.get(field)
            if field == "quest_slot" and b["lease"] in keep:
                taken[field].add(v)
                pin[field] = v
                continue
            if not isinstance(v, int) or v in taken[field] or not span[field][0] <= v < span[field][1]:
                lo, hi = span[field]
                n = next((x for x in range(lo, hi) if x not in taken[field]
                          and not (field == "quest_slot" and x in held)), None)
                if n is None:
                    raise ValueError(f"no free {field} left for {b['lease']}")
                moved.setdefault(b["lease"], {})[field] = (v, n)
                v = n
            taken[field].add(v)
            pin[field] = v
        b["namespaces"] = pin
    if generated:
        new["generated"] = generated
    return new, moved


def _who_art(inventory, key):
    who = getattr(inventory, "art_sources", {}).get(key)
    return who or "installed/lease claim"


# -- live read-only collection -------------------------------------------------
class _Claims:
    """Sets plus, per key, the labels that claimed it (so a collision names its claimant)."""

    def __init__(self):
        self.used, self.face, self.banner, self.installed = set(), set(), set(), set()
        self.who = {"art": {}, "face": {}, "banner": {}, "row": {}}

    def add(self, kind, keys, label):
        target = {"art": self.used, "face": self.face, "banner": self.banner, "row": self.installed}[kind]
        for k in keys:
            target.add(k)
            self.who[kind].setdefault(k, set()).add(label)


def scan_mod_root(root: Path, char, claims, label, _rows, files=None):
    """Add every id a pack folder under `root` claims (anm files, char rows, outfit pairs, uniques).
    `label` prefixes the claimant name (e.g. 'installed', 'Builds/D4CAND2-20261109')."""
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not (d / "mod.json").is_file():
            continue
        who = f"{label}:{d.name}"
        for p in d.rglob("anm*.lzs"):
            if p.name[3:8].isdigit():
                n = int(p.name[3:8])
                claims.add("art", [n], who)
                if files is not None:
                    files.append((p, n, root))
        p = d / "patches/db/char.dat.json"
        if p.is_file():
            for r in _rows(char, json.loads(p.read_text())):
                if "id" not in r:
                    continue
                cid = int(r["id"])
                claims.add("row", [cid], who)
                color = int(r.get("color_id", 0))
                key = cid if cid < 1000 else color
                if 0 < key <= 32767:
                    claims.add("art", (key + 2, key + 10000), who)
                    claims.add("face", (key, key + 10000), who)
                    claims.add("banner", [key], who)
        for name in ("patches/outfits/outfits.json", "patches/characters/unique.json"):
            p = d / name
            if not p.is_file():
                continue
            doc = json.loads(p.read_text())
            if name.endswith("outfits.json"):
                for a, b in doc.get("pairs", []):
                    if int(b) < 1000:
                        b = int(b)
                        claims.add("art", (b + 2, 10000 + b), who)
                        claims.add("face", (b, 10000 + b), who)
                        claims.add("banner", [b], who)
                claims.add("art", [int(x) for x in doc.get("own_sprites", [])], who)
            else:
                for decl in doc.get("uniques") or [doc]:
                    if not isinstance(decl, dict) or "physical" not in decl:
                        continue
                    n = int(decl["physical"])
                    claims.add("art", (n, n + 1, n + 2, n + 10000, n + 10001), who)
                    claims.add("face", (n, n + 10000), who)
                    claims.add("banner", [n], who)


def collect(base: Path, game: Path, *, extra_mod_roots=(), lease_files=None):
    """Read the installed kit read-only and return (Inventory, pins).

    extra_mod_roots: further `<...>/mods` folders (candidate builds about to be installed) whose packs count as
    claimed exactly like installed ones.  lease_files: explicit lease json files; default is every
    `*-leases.json` in every worktree plus the D1C batch lease files."""
    import sys
    sys.dont_write_bytecode = True
    from d5lib import database, gamefs, modsys, sprites
    from d5lib.importers._drpg_namespaces import _rows

    state = game / "D5ModKit/state/games/Disgaea_5_Complete-d8040a88"
    root = game / "D5ModKit/mods"
    inst = object.__new__(modsys.Installer)
    inst.backup_dir = str(state / "backups")
    inst.index = json.loads((state / "backups.json").read_text())
    fs = gamefs.GameFS(str(game), backup_resolver=inst.backup_resolver)
    char = database.load_table("char.dat", fs.read("Database/Database_0.dat/char.dat"))
    vanilla = {r["id"] for r in char.rows}
    claims = _Claims()
    claims.add("art", sprites.used_sprite_numbers(fs), "vanilla game")
    roots = [(root, "installed")] + [(Path(r), f"extra:{Path(r).parent.parent.name}/{Path(r).parent.name}")
                                      for r in extra_mod_roots]
    nmods = 0
    for r, label in roots:
        nmods += sum(1 for d in r.iterdir() if d.is_dir() and (d / "mod.json").is_file())
        scan_mod_root(r, char, claims, label, _rows)
    used, installed, face, banner = claims.used, claims.installed, claims.face, claims.banner

    leases, lease_ids = [], set()
    if lease_files is None:
        lease_files = sorted((base / "Local/Worktrees").glob("*/d5lib/**/*-leases.json"))
        lease_files += [base / "Local/Worktrees/core-d1c-b/d5lib/data/unique_art_leases.json",
                        base / "Research/source-packs/d1c/batches/unique-leases.json",
                        base / "Research/source-packs/d1c/batches/unique-leases-b.json"]
    for p in lease_files:
        p = Path(p)
        if p.is_file():
            _walk_leases(p, used, lease_ids, leases, claims, p.name)
    for n in (643, 646, 653):  # published pending corrections (CORED4C/CORED1CC)
        claims.add("art", [n, n + 1, n + 2, 10000 + n, 10001 + n], "published pending lease")
        leases.append({"file": "published pending lease", "physical": n})

    from d5lib import anm
    res = anm.parse(fs.read("Anime/ANM_HI_JP.dat/anm_resident.lzs"))
    vface = {a.id for b in res.blocks if b.id == 9017 for a in b.animations}
    vbanner = {a.id for b in res.blocks if b.id == 9018 for a in b.animations}
    claims.add("face", vface, "vanilla game")
    claims.add("banner", vbanner, "vanilla game")

    # The pin is the union of claims, not file mtimes: installing a candidate that was already an extra root
    # leaves it unchanged, anything that adds or drops a claim moves it (rebuild or re-check the manifest).
    inventory_sha = _sha256_bytes(json.dumps(
        {"art": sorted(used), "face": sorted(face), "banner": sorted(banner), "rows": sorted(installed),
         "vanilla_rows": sorted(vanilla), "lease_identities": sorted(lease_ids)}, sort_keys=True).encode())

    sprites.CACHE_DIR  # keep import used even when the cache is absent
    inv = Inventory(
        vanilla_ids=vanilla, installed_char_ids=installed, used_art=used,
        face_anims=face, banner_anims=banner, lease_identities=lease_ids,
        helper_ids=set(sprites.script_spawn_ids()),
        pins={
            "inventory_sha256": inventory_sha,
            "grouping_sha256": _sha256_file(base / "Research/source-packs/drpg/grouping-decisions.json"),
            "allocation_sha256": _sha256_file(
                base / "Builds/CORERPG2-20261105/id-space/proposed-allocation.json"),
            "audit_sha256": _sha256_file(base / "Builds/CORERPG2-20261105/id-space/audit.json"),
            "ownership_manifest_sha256": _sha256_file(
                base / "Subprojects/Engine-Extensions/ownership/manifest.json"),
        },
    )
    inv.installed_definitions = nmods
    inv.claimants = claims.who
    inv.art_sources = {k: "; ".join(sorted(v)) for k, v in claims.who["art"].items()}
    fs.reset()
    return inv, inv.pins


def _walk_leases(path, used, lease_ids, out, claims=None, label=None):
    doc = json.loads(path.read_text())

    def walk(x, key):
        if isinstance(x, dict):
            if isinstance(x.get("physical"), int):
                n = x["physical"]
                if claims is not None:
                    claims.add("art", [n, n + 1, n + 2, 10000 + n, 10001 + n], f"lease {label}")
                else:
                    used.update([n, n + 1, n + 2, 10000 + n, 10001 + n])
                ident = x.get("identity", x.get("target"))
                if isinstance(ident, int):
                    lease_ids.add(ident)
                    if claims is not None:
                        claims.add("row", [ident], f"lease {label}")
                out.append({"file": str(path), "key": key, "physical": n})
            for k, v in x.items():
                walk(v, key + "/" + str(k))
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, key + "/" + str(i))

    walk(doc, "")


def _dirty(args):
    return json.loads(Path(args.dirty_slots).read_text()) if getattr(args, "dirty_slots", None) else None


def main(argv=None):
    import argparse
    import datetime
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("action", choices=("build", "check", "rebase", "pin-ns", "release"))
    ap.add_argument("--manifest", default=str(Path(__file__).with_name("drpg-leases.json")))
    ap.add_argument("--base", required=True, help="the project folder (maintainer step; no machine default)")
    ap.add_argument("--game", required=True, help="the Disgaea 5 Complete folder")
    ap.add_argument("--extra-mods", action="append", default=[],
                    help="a candidate <build>/<game>/mods folder whose packs count as claimed (repeatable)")
    ap.add_argument("--leases-from", action="append", default=None,
                    help="restrict recorded leases to these files (default: every worktree's *-leases.json)")
    ap.add_argument("--receipts", action="append", default=[],
                    help="pin-ns: an importer output dir (results.json + mods/) whose packs hold the current ids; later wins")
    ap.add_argument("--out", help="rebase: where to write the new manifest (default: --manifest)")
    ap.add_argument("--dirty-slots", help="pin-ns/release: JSON from tools/save_quest_slots.py; those quest slots count as taken")
    args = ap.parse_args(argv)
    base, game = Path(args.base), Path(args.game)
    inv, pins = collect(base, game, extra_mod_roots=args.extra_mods, lease_files=args.leases_from)
    if args.action == "release":
        from d5lib import importcore
        state = game / "D5ModKit/state/games/Disgaea_5_Complete-d8040a88"
        roots = importcore.default_extra_roots(args.extra_mods)
        used = importcore.UsedIds(game, state, roots)
        idx = used.index()
        claimed = {}
        for (kind, i), owners in idx.items():
            if any(not label.startswith("lease drpg:") for label, _ in owners):
                claimed.setdefault(kind, set()).add(i)
        old = load(args.manifest)
        manifest, moved = release(old, inv, claimed, generated=datetime.date.today().isoformat())
        taken = {}
        for kind, vkind in (("help_id", "charhelp.dat"), ("quest_id", "Quest.dat"), ("quest_slot", importcore.QUEST_SLOT)):
            taken[kind] = set(claimed.get(vkind, set())) | {i for i in used.vanilla_ids(vkind)}
        cur = {b["lease"]: b.get("namespaces") or {} for b in manifest["bases"]}
        manifest, nmoved = pin_namespaces(manifest, cur, taken["help_id"], taken["quest_id"], taken["quest_slot"],
                                          generated=manifest.get("generated"), dirty_slots=_dirty(args))
        # verification, the gate's own way: this manifest's claims against everyone else's
        mine = {(k, i) for src, owner, c in importcore.lease_claims(manifest) if src == "drpg" for k, ids in c.items() for i in ids}
        clash = sorted((k, i) for (k, i) in mine if any(not label.startswith("lease drpg:") for label, _ in idx.get((k, i), ())))
        _drpg_text.dump(Path(args.out or args.manifest), manifest)
        problems = check(manifest, inv) + [f"gate clash {k} {i}" for k, i in clash]
        print(json.dumps({"moved": len(moved), "ns_moved": len(nmoved), "moved_detail": moved,
                          "problems": problems}, indent=1, default=list))
        return 1 if problems else 0
    if args.action == "pin-ns":
        from d5lib import gamefs, modsys
        from d5lib.importers._drpg_namespaces import taken_namespaces
        state = game / "D5ModKit/state/games/Disgaea_5_Complete-d8040a88"
        inst = object.__new__(modsys.Installer)
        inst.backup_dir = str(state / "backups")
        inst.index = json.loads((state / "backups.json").read_text())
        fs = gamefs.GameFS(str(game), backup_resolver=inst.backup_resolver)
        try:
            h, q, sl = taken_namespaces(fs, game / "D5ModKit/mods", args.extra_mods)
        finally:
            fs.reset()
        current = {}
        for d in args.receipts:
            d = Path(d)
            for r in json.loads((d / "results.json").read_text())["results"]:
                rec = json.loads((d / "mods" / r["mod_folder"] / "CORERPG1-receipt.json").read_text())["leased_ids"]
                current[r["id"]] = {k: rec[k] for k in ("help_id", "quest_id", "quest_slot")}
        old = load(args.manifest)
        manifest, moved = pin_namespaces(old, current, h, q, sl,
                                         generated=datetime.date.today().isoformat(), dirty_slots=_dirty(args))
        _drpg_text.dump(Path(args.out or args.manifest), manifest)
        print(json.dumps({"bases": len(manifest["bases"]), "moved": len(moved), "moved_detail": moved}, indent=1))
        return 0
    if args.action == "rebase":
        old = load(args.manifest)
        manifest, moved = rebase(old, inv, generated=datetime.date.today().isoformat())
        _drpg_text.dump(Path(args.out or args.manifest), manifest)
        problems = check(manifest, inv)
        print(json.dumps({"moved": {k: list(v) for k, v in moved.items()}, "problems": problems}, indent=1))
        return 1 if problems else 0
    if args.action == "build":
        grouping = json.loads((base / "Research/source-packs/drpg/grouping-decisions.json").read_text())
        manifest = build(grouping, inv, generated=datetime.date.today().isoformat())
        _drpg_text.dump(Path(args.manifest), manifest)
        problems = check(manifest, inv)
    else:
        manifest = load(args.manifest)
        problems = check(manifest, inv)
    print(json.dumps({"bases": len(manifest.get("bases", [])),
                      "costumes": len(manifest.get("costumes", [])),
                      "spare_low_rows": len((manifest.get("reserved") or {}).get("spare_low_rows", [])),
                      "problems": problems}, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
