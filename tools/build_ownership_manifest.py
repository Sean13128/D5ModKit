"""Build d5lib/data/ownership_manifest.json -- the allocation manifest (see d5lib/ownership.py).

Every number that the kit itself decides (class families, flag block, mastery slots, voice band,
choreography blocks) is read from the module that owns it, so the manifest cannot drift from the code
without this script failing.  The bands that belong to someone else (vanilla, Overlord) are written
out here with the file and line/row they were taken from, because no code in this repo owns them.

  python tools/build_ownership_manifest.py            # write the manifest
  python tools/build_ownership_manifest.py --check     # fail if the committed manifest is stale

Offline only: nothing here launches the game or reads kit/game state.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from d5lib import masteryext, newclasses, skills, voices      # noqa: E402  (path first)

BASE = "063b240"
GENERATED = "2026-10-27"

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "d5lib", "data", "ownership_manifest.json")

OVERLORD_SRC = "Private/Overlord and Sorrow research/class-support/overlord-source"
ROSTER = "Research/ASSESSMENT-20261026/p2-overlord-v3/ROSTER-DEDUPE.md"

# A unique character's graphics are keyed to its char.dat row: the sprite set is row .. row + 2
# (body, +1 companion, +2 standing picture) and its cut-in / status portrait is 10000 + row
# (d5lib/d4unique.py:479 `keyed = {id, id+1, id+2, 10000+id, 10001+id}`; d5lib/newchars.py:7-8;
# d5lib/newclasses.py:399-419 states the same window for a class family).  10-wide portrait sets
# (10000 + id + 0..9) belong to class *families*, not to uniques.
UNIQUE_SPRITE_SPAN = 3
UNIQUE_PORTRAIT_OFFSET = 10000
UNIQUE_PORTRAIT_SPAN = 2

# Unique on a registry identity (decision 2026-10-27, DECISIONS.md; Overlord ships the same shape for
# Stella 20300 -- d5_custom_classes.c, The Unlicense, credit Cryswar).  The identity is a class id whose
# char.dat row id equals it (the game finds a class's row by id: char_find_by_id 0x140061f80), one rank
# only, and the graphics stay keyed to a low *physical* row leased for the character -- so no low char row
# is consumed and the art keys stay in the free low run rather than in Overlord's 30000+ anm bands.
UNIQUE_IDENTITY_FIRST, UNIQUE_IDENTITY_LAST = 10000, 10990
# The free low run measured on the pinned char.dat and every installed mod file: 853..999 has no file at
# n, n+1, n+2, 10000+n or 10001+n (the 47-number run 453..499 is the only other one; see lease-capacity).
UNIQUE_SPRITE_FIRST, UNIQUE_SPRITE_LAST = 853, 999

# ---- third lease run (D1C2, DECISIONS 2026-10-29 [taste, coordinator]) -------------------------------
# 404..852 is *not* empty ground the way 853..999 and 223..403 are: it carries 45 vanilla character rows at
# stride 10 (410 Dark Bit, 420 Alfonzo ...), the live outfit rows 470-497, and 220 picture numbers in use.
# Only the individual three-number windows that measure free are leased, so the band cannot be re-labelled
# wholesale -- every window is carved out of the vanilla band here, from a recorded lease file, and the
# rest of the band stays vanilla.  The record is what makes the manifest reproducible offline; the proof
# that each window is free (archive as installed, pristine archive, no char row, no installed mod claim)
# is evidence in the bundle that recorded it (Subprojects/Engine-Extensions/D1C2-REPORT.md).
ART_LEASE_RECORD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "d5lib", "data", "unique_art_leases.json")
THIRD_RUN = (404, 852)
# The portrait keys 10000 + p and 10001 + p land in 10404..10853; 10404 is already the kit's (223-403 run)
# band end and 10853 the start of the 853-999 portrait band, so only 10405..10852 has to be carved.
THIRD_RUN_PORTRAITS = (10000 + THIRD_RUN[0] + 1, 10000 + THIRD_RUN[1])


def third_run_leases():
    """{mod_id: physical} for every art window carved out of the vanilla third run."""
    if not os.path.exists(ART_LEASE_RECORD):
        return {}
    with open(ART_LEASE_RECORD, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    out = {}
    for mod_id, lease in sorted((doc.get("leases") or {}).items()):
        physical = int(lease["physical"])
        lo, hi = THIRD_RUN
        if not lo <= physical <= hi:
            raise SystemExit(f"{ART_LEASE_RECORD}: {mod_id} leases {physical}, outside the third run "
                             f"{lo}..{hi}; the first two runs are whole-band reservations and need no carve")
        out[mod_id] = physical
    keys = {}
    for mod_id, physical in out.items():
        for n in (physical, physical + 1, physical + 2, 10000 + physical, 10001 + physical):
            if n in keys:
                raise SystemExit(f"{ART_LEASE_RECORD}: {mod_id} and {keys[n]} share the art key {n}")
            keys[n] = mod_id
    return out


def _contiguous(numbers):
    runs = []
    for n in sorted(numbers):
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return [tuple(r) for r in runs]


def _carve(start, end, keys, label_kit, label_vanilla, evidence):
    """Split [start, end] into vanilla bands and kit bands, one per contiguous run of leased keys."""
    bands, pos = [], start
    for lo, hi in _contiguous(keys):
        if lo > pos:
            bands.append(band(pos, lo - 1, "vanilla", "vanilla", label_vanilla, evidence))
        who = sorted({keys[n] for n in range(lo, hi + 1)})
        bands.append(band(lo, hi, "kit", "in_use",
                          f"{label_kit}: {' '.join(who)}",
                          f"[code] d5lib/data/unique_art_leases.json; d5lib/slots.SPRITE_LEASE_RUNS; "
                          f"{evidence}"))
        pos = hi + 1
    if pos <= end:
        bands.append(band(pos, end, "vanilla", "vanilla", label_vanilla, evidence))
    return bands


def band(start, end, owner, status, label, evidence, claimants=None, rule=None):
    d = {"start": int(start), "end": int(end), "owner": owner, "status": status}
    if claimants:
        d["claimants"] = list(claimants)
    if rule:
        d["rule"] = rule
    d["label"] = label
    d["evidence"] = evidence
    return d


def member(name, owner, status, writers, note):
    return {"name": name, "owner": owner, "status": status, "writers": list(writers), "note": note}


def row_span(family, ranks=6):
    return family, family + ranks - 1


def _family_groups():
    """(first family, last family) of each contiguous run of families with the same role, from the code."""
    groups = []
    for label, fams in (("human dummy", newclasses.HUMAN_DUMMIES),
                        ("monster dummy", newclasses.MONSTER_DUMMIES),
                        ("new humanoid", [f for f in newclasses.NEW_HUMAN]),
                        ("new monster", [f for f in newclasses.NEW_MONSTER])):
        fams = sorted(fams)
        groups.append((label, fams[0], fams[-1], len(fams)))
    return groups


def build():
    # ---- self-checks against the code that allocates these ids -------------------------------------
    assert len(newclasses.ALL_FAMILIES) == 119, len(newclasses.ALL_FAMILIES)
    assert newclasses.FLAG_BASE == 17283
    flag_last = newclasses.FLAG_BASE + 6 * len(newclasses.ALL_FAMILIES) - 1
    assert flag_last == 17996, flag_last
    assert newclasses.FLAG_LAST == 17999
    assert (masteryext.SLOT_FIRST, masteryext.SLOT_COUNT) == (47, 6)
    assert masteryext.RANK_SLOTS == 53
    assert (voices.CUSTOM_FIRST, voices.CUSTOM_LAST) == (6000, 9999)
    assert skills.MOD_CHOREO_BASE == 15900000 and skills.CHOREO_MIN == 15000000

    kits = _family_groups()
    dummy_h, new_h, dummy_m, new_m = kits[0][1], kits[2][1], kits[1][1], kits[3][1]
    human_dummy_last = max(f for f in newclasses.HUMAN_DUMMIES if f != 1350) + 5
    row_end = {g[0]: row_span(g[2])[1] for g in kits}

    namespaces = {}
    # Every art window the third lease run hands out (404-852).  Empty until a bundle records one.
    _third = third_run_leases()

    # ---- char.dat rows ---------------------------------------------------------------------------
    namespaces["char_dat_row"] = {
        "kind": "range",
        "description": "char.dat row ids. A row is one class rank (family + rank 0..5), one unique "
                       "character or one of the game's dummy rows; unique skills refer back to the row id.",
        "bands": [
            band(1, 89, "vanilla", "vanilla", "vanilla unique characters / NPC rows",
                 "[code] char.dat, ROSTER-DEDUPE.md §4; 80 is the vanilla 'Usalia (Awakening)' row, "
                 "which Xenolith no longer repurposes (FIXCONTENT 2026-10-27: it moved to 941)"),
            band(90, 90, "overlord", "in_use", "Berserk Usalia - repurposed vanilla row",
                 f"[code] {ROSTER} §1"),
            band(91, 169, "vanilla", "vanilla", "vanilla unique characters / NPC rows", "[code] char.dat"),
            band(170, 170, "overlord", "in_use", "Liezerota Dark - existing NPC row, aptitudes retuned",
                 f"[code] {ROSTER} §1"),
            band(171, 222, "vanilla", "vanilla", "vanilla unique characters / NPC rows", "[code] char.dat"),
            band(223, 403, "kit", "reserved", "superseded D4 unique low-row band: the D4 uniques now build on "
                                            "registry identities (D4UNIQ, 2026-10-29) and claim no low row; held "
                                            "reserved so no later import takes a row the old shape used",
                 f"[code] {ROSTER} §2; DECISIONS.md 2026-10-27; Subprojects/Engine-Extensions/D4UNIQ-REPORT.md"),
            band(404, 429, "vanilla", "vanilla", "vanilla rows", "[code] char.dat"),
            band(430, 430, "overlord", "in_use", "Prinny Overlord - existing vanilla row, evility retuned",
                 f"[code] {ROSTER} §1"),
            band(431, 769, "vanilla", "vanilla", "vanilla rows", "[code] char.dat"),
            band(770, 770, "overlord", "in_use", "Baal - existing vanilla boss row",
                 f"[code] {ROSTER} §1"),
            band(771, 819, "vanilla", "vanilla", "vanilla rows", "[code] char.dat"),
            band(820, 850, "overlord", "in_use", "Baal Bit x4 - vanilla 'Ball Bit' rows renamed",
                 f"[code] {ROSTER} §1"),
            band(851, 930, "vanilla", "vanilla", "vanilla rows (incl. 'Unique Dummy' / 'DLC Dummy' "
                                                 "rows the kit fills in place)", "[code] dbpatch.RESERVED_NAMES"),
            band(931, 931, "kit", "in_use", "Shark King (D1 Complete unique), re-leased 2026-10-27: "
                                           "row 45 belongs to the DRPG Pleinair pack",
                 "[code] Research/source-packs/d1c/batches/unique-leases.json; HUB2-REPORT.md §7"),
            band(932, 940, "vanilla", "vanilla", "vanilla rows", "[code] char.dat"),
            band(941, 941, "kit", "in_use", "Xenolith (DD2 unique), re-leased 2026-10-27: row 470 is "
                                           "the live game's Girl Laharl row",
                 "[code] Research/source-packs/dd2/slice/build/make_configs.py RELEASES; HUB2-REPORT.md §7"),
            band(942, 1269, "vanilla", "vanilla", "vanilla rows", "[code] char.dat"),
            band(dummy_h, human_dummy_last, "kit", "in_use",
                 "Human Dummy class families 1270-1340 (8 slots x 6 ranks), filled in place "
                 "(family 1350 is listed separately: contested)",
                 "[code] d5lib/newclasses.py HUMAN_DUMMIES"),
            band(1350, 1355, "contested", "contested",
                 "D4 Armor Knight pilot (ours) vs Overlord v3 'Human Dummy' rewrite: same six rows, "
                 "opposite intent", f"[code] {ROSTER} §4; d5lib/newclasses.py:1270-1355",
                 claimants=["kit", "overlord"]),
            band(1356, 1359, "unallocated", "unallocated", "no owner recorded (family stride 10, "
                                                          "so these rows have no family base)", ""),
            band(new_h, row_end["new humanoid"], "kit", "in_use",
                 "new humanoid class families 1360-1990 (64 slots x 6 ranks, rows appended)",
                 "[code] d5lib/newclasses.py NEW_HUMAN"),
            band(1996, 2219, "vanilla", "vanilla", "vanilla rows / unused", "[code] char.dat"),
            band(dummy_m, max(newclasses.MONSTER_DUMMIES) + 5, "kit", "in_use",
                 "Monster Dummy class families 2220-2330 (12 slots x 6 ranks), filled in place",
                 "[code] d5lib/newclasses.py MONSTER_DUMMIES"),
            band(2336, 2339, "unallocated", "unallocated", "no owner recorded", ""),
            band(new_m, 2395, "kit", "in_use", "new monster class families 2340-2390 (6 slots x 6 ranks)",
                 "[code] d5lib/newclasses.py NEW_MONSTER"),
            band(2396, 2609, "vanilla", "vanilla", "vanilla rows", "[code] char.dat"),
            band(2610, 2615, "overlord", "in_use", "Proto Darkdeath - existing Item World boss rows",
                 f"[code] {ROSTER} §1"),
            band(2616, 2619, "unallocated", "unallocated", "no owner recorded", ""),
            band(2620, row_end["new monster"], "kit", "in_use",
                 "new monster class families 2620-2890 (28 slots x 6 ranks)",
                 "[code] d5lib/newclasses.py NEW_MONSTER"),
            band(2896, 9999, "unallocated", "unallocated",
                 "no mod allocates a physical char.dat row here", "[code] d5lib/newclasses.validate_specs"),
            band(UNIQUE_IDENTITY_FIRST, UNIQUE_IDENTITY_LAST, "kit", "in_use",
                 "unique registry identity rows: one rank per unique, row id = class id (the game finds a "
                 "class's row by id, char_find_by_id 0x140061f80); the art is keyed to the low physical row "
                 "each unique leases, not to this row",
                 "[code] d5lib/nativeimports.unique_identity; d5lib/slots.unique_sprite_pool"),
            band(UNIQUE_IDENTITY_LAST + 1, 18099, "unallocated", "unallocated",
                 "no owner recorded here (a registry class lands at 11000+ and its rank rows sit at the "
                 "identity itself)", "[code] d5lib/newclasses.py"),
            band(18100, 18199, "kit", "in_use",
                 "D4UNIQ3: ten D4 unique registry rows 18100-18190 (stride 10), one row per character; "
                 "the rows sit here because every lower registry identity and the 22700 block are taken "
                 "and an identity above 22770 would push its 10000 + identity portraits into the kit's "
                 "next portrait band", "[code] d5lib/data/unique_art_leases.json; D4UNIQ3-REPORT.md"),
            band(18200, 19999, "unallocated", "unallocated",
                 "no owner recorded here (a registry class lands at 11000+ and its rank rows sit at the "
                 "identity itself)", "[code] d5lib/newclasses.py"),
            band(20000, 20505, "overlord", "in_use",
                 "Overlord v3 class rows 20000-20005/20010-20015/20300-20305/20310-20315/20500-20505 "
                 "(Battle Suit, Android, Stella, Rutile, Majin)", f"[code] {ROSTER} §1, §4"),
            band(20506, 21999, "overlord", "reserved",
                 "Overlord class-row band, reserved (v4 adds ~20 classes; v3 uses the front of it)",
                 f"[doc] NORTH-STAR.md, {ROSTER} §6"),
            band(22000, 32760, "unallocated", "unallocated", "no owner recorded", ""),
        ],
        "rules": {
            "unique_row_lease":
                "A unique character is one row, and that row id is also its class id (job_class_id), the "
                "base of its sprite ids (anm_id: row .. row + 2) and, 10000 higher, its cut-in / status "
                "portrait. The kit's unique band is 223-403 (26 D4 named characters) plus the two "
                "re-leased single rows 931 (Shark King) and 941 (Xenolith, moved off vanilla row 80 and "
                "off the live game's 470). Non-unique kit families are separate bands.",
        },
    }

    # ---- job / class ids -------------------------------------------------------------------------
    namespaces["job_class_id"] = {
        "kind": "range",
        "description": "Class and rank ids as the game, the menus and the saves see them: a family base "
                       "plus rank 0..5. Registry identities (10000+) lease a physical row of their own "
                       "(char_dat_row) and keep their identity in saves.",
        "bands": [
            band(1, 79, "vanilla", "vanilla", "vanilla character class ids (vanilla unique rows 1-79)",
                 "[code] char.dat"),
            band(80, 80, "vanilla", "vanilla",
                 "vanilla character class ids (80 stays vanilla: Xenolith moved to 941)", "[code] char.dat"),
            band(81, 222, "vanilla", "vanilla", "vanilla character class ids", "[code] char.dat"),
            band(223, 403, "kit", "reserved",
                 "superseded D4 unique class ids: a unique is one rank on a registry identity (>= 10000) now, "
                 "so no pack claims a low class id for a D4 character",
                 f"[code] {ROSTER} §2; DECISIONS.md 2026-10-27; Subprojects/Engine-Extensions/D4UNIQ-REPORT.md"),
            band(404, 930, "vanilla", "vanilla",
                 "vanilla character class ids (incl. the vanilla rows Overlord repurposes at 430/770/"
                 "820-850: class ids stay vanilla, see char_dat_row)", "[code] char.dat"),
            band(931, 931, "kit", "in_use", "Shark King class id = its char row 931",
                 "[code] d1c unique leases; see char_dat_row 931"),
            band(932, 940, "vanilla", "vanilla", "vanilla character class ids", "[code] char.dat"),
            band(941, 941, "kit", "in_use", "Xenolith class id = its char row 941",
                 "[code] Research/source-packs/dd2 RELEASES; see char_dat_row 941"),
            band(942, 1009, "vanilla", "vanilla", "vanilla character class ids", "[code] char.dat"),
            band(1010, 1269, "vanilla", "vanilla", "vanilla generic class families (26, base + ranks)",
                 "[code] d5lib/masteryext.py NATIVE_FAMILIES"),
            band(1270, 1349, "kit", "in_use", "kit Human Dummy families 1270-1340 (identity = row)",
                 "[code] d5lib/newclasses.py"),
            band(1350, 1355, "contested", "contested", "Armor Knight pilot vs Overlord 'Human Dummy'",
                 f"[code] {ROSTER} §4", claimants=["kit", "overlord"]),
            band(1356, 1359, "unallocated", "unallocated", "no owner recorded", ""),
            band(1360, 1995, "kit", "in_use", "kit families of their own 1360-1990", "[code] d5lib/newclasses.py"),
            band(1996, 2009, "unallocated", "unallocated", "no owner recorded", ""),
            band(2010, 2219, "vanilla", "vanilla", "vanilla monster class families (21, base + ranks)",
                 "[code] d5lib/masteryext.py NATIVE_FAMILIES"),
            band(2220, 2335, "kit", "in_use", "kit Monster Dummy families 2220-2330", "[code] d5lib/newclasses.py"),
            band(2336, 2339, "unallocated", "unallocated", "no owner recorded", ""),
            band(2340, 2395, "kit", "in_use", "kit monster families 2340-2390", "[code] d5lib/newclasses.py"),
            band(2396, 2609, "vanilla", "vanilla", "vanilla monster rows / bosses", "[code] char.dat"),
            band(2610, 2619, "vanilla", "vanilla", "vanilla Item World boss rows (Overlord repurposes "
                                                   "rows 2610-2615; see char_dat_row)", "[code] char.dat"),
            band(2620, 2895, "kit", "in_use", "kit monster families 2620-2890", "[code] d5lib/newclasses.py"),
            band(2896, 9999, "vanilla", "vanilla", "vanilla NPC / boss class ids", "[code] char.dat"),
            band(10000, UNIQUE_IDENTITY_LAST, "kit", "in_use",
                 "unique registry identities (decision 2026-10-27): one rank (digit 0; 1-5 unused) per "
                 "unique character, art leased to a low physical row. Overlord ships the same shape for "
                 "Stella 20300 / Battle Suit 20000",
                 "[code] d5lib/nativeimports.unique_identity; "
                 f"[code] {OVERLORD_SRC}/d5_custom_classes.c:76,103 (The Unlicense, Cryswar); DECISIONS.md 2026-10-27",
                 rule="unique_registry_lease"),
            band(UNIQUE_IDENTITY_LAST + 1, 18099, "kit", "reserved", "registry class identities, leased to a physical row "
                                                 "(stride 10, ranks +0..+5, digits 6-9 unused)",
                 "[code] d5lib/newclasses.validate_specs"),
            band(18100, 18199, "kit", "in_use",
                 "D4UNIQ3: ten D4 unique registry identities 18100-18190 (stride 10, rank 0 only)",
                 "[code] d5lib/data/unique_art_leases.json; D4UNIQ3-REPORT.md"),
            band(18200, 19999, "kit", "reserved", "registry class identities, leased to a physical row "
                                                 "(stride 10, ranks +0..+5, digits 6-9 unused)",
                 "[code] d5lib/newclasses.validate_specs"),
            band(20000, 21999, "overlord", "reserved",
                 "Overlord class ids (v3 ships 20000/20010/20300/20310/20500; v3.5 accepts any id >= 10000)",
                 f"[code] {ROSTER} §4; {OVERLORD_SRC}/d5_custom_classes.c:76,103"),
            band(22000, 32760, "kit", "reserved", "registry class identities (upper part of the range "
                                                  "the kit accepts)", "[code] d5lib/newclasses.py:96,101"),
        ],
        "rules": {
            "registry_lease": {
                "first": 10000,
                "last": 32760,
                "step": 10,
                "max_ranks": 6,
                "rank_digits_reserved": [6, 9],
                "excluded": [[20000, 21999]],
            },
            "unique_registry_lease": {
                "first": UNIQUE_IDENTITY_FIRST,
                "last": UNIQUE_IDENTITY_LAST,
                "step": 10,
                "ranks": 1,
                "note": "A unique character's class id is a registry identity, one rank only (digit 0; 1-5 "
                        "unused). Its char.dat row id equals the identity because the game finds a class's "
                        "row by id (char_find_by_id 0x140061f80). Its graphics are keyed to the low physical "
                        "row it leases (anm band unique_sprite), so it derives no 10000 + id portraits and "
                        "the class-derived check does not apply. Adding a rank (digit 1-5) turns it into a "
                        "class family and needs its own band here.",
            },
            "unique_row_lease": {
                "first": 223,
                "last": 403,
                "note": "A unique character carries no family and no registry identity: its class id "
                        "IS its char.dat row id (d5lib/newchars.py, d5lib/d4unique.check_conflicts), so "
                        "the unique row band owns the matching class ids. A unique placed outside "
                        "223-403 or the re-leased rows 931/941 needs its own band here before a build "
                        "may claim it.",
            },
        },
    }

    # ---- unlock flags ----------------------------------------------------------------------------
    namespaces["unlock_flag"] = {
        "kind": "range",
        "description": "FlagList indices. The game keeps one flag per class rank (17001..17282 named, "
                       "FLAG_CHARAMAKE_*); the kit continues the block for its own families.",
        "bands": [
            band(17001, 17282, "vanilla", "vanilla", "vanilla class-rank unlock flags (FLAG_CHARAMAKE_*)",
                 "[code] d5lib/newclasses.py:14"),
            band(newclasses.FLAG_BASE, flag_last, "kit", "in_use",
                 "119 kit families x 6 ranks: 17283 + 6 * family index + rank",
                 "[code] d5lib/newclasses.py:17,111"),
            band(flag_last + 1, newclasses.FLAG_LAST, "kit", "reserved",
                 "tail of the class unlock block, not assigned (4 flags)",
                 "[code] d5lib/newclasses.py:40 FLAG_LAST"),
        ],
        "rules": {
            "overlord_claim": "Overlord packs 239 unlock slots, three bits each, over the whole "
                              "17283..17999 block (a different encoding of the same bits). The kit owns "
                              "the block: an Overlord class converted into a kit mod leases a kit family "
                              "and uses the kit's flags. A separately installed Overlord is not co-resident.",
        },
    }

    # ---- mastery slots ---------------------------------------------------------------------------
    namespaces["mastery_slot"] = {
        "kind": "range",
        "description": "Per-unit class-mastery array index (unit + 0x30A4 + 24 * slot + 4 * rank). The game "
                       "keeps 53 slots; the kit leases the six spare ones to imported families.",
        "bands": [
            band(0, masteryext.SLOT_FIRST - 1, "vanilla", "vanilla",
                 "vanilla class-mastery slots 0-46 (one per native family)", "[code] d5lib/masteryext.py:59"),
            band(masteryext.SLOT_FIRST, masteryext.SLOT_FIRST + masteryext.SLOT_COUNT - 1, "kit", "in_use",
                 "kit leases: mastery_slots.json maps one imported family per spare slot, permanently",
                 "[code] d5lib/masteryext.py:122-215,448-498"),
        ],
        "rules": {
            "overlord_claim": "Overlord treats slots 47-51 as one 120-byte packed table and 52 as working "
                              "state for its own class pool (d5_custom_classes.c:43,106,283). The kit owns "
                              "all six slots; Overlord's packed pool is not co-resident.",
            "index_range": "an index >= 53 is out of range: the game's reader bound is 0x35 (53).",
        },
    }

    # ---- evility ids (Skill.dat) ------------------------------------------------------------------
    namespaces["evility_id"] = {
        "kind": "range",
        "description": "Skill.dat row ids: evilities (the game's own and every mod's). A new evility row "
                       "names an existing effect (alias), so ids are a naming space, not logic.",
        "bands": [
            band(1, 6306, "vanilla", "vanilla", "vanilla evilities",
                 "[inferred] no custom allocation below 6307 in either system"),
            band(6307, 6314, "overlord", "in_use", "Overlord v3 evilities (8 rows)",
                 f"[code] {ROSTER} §4"),
            band(6315, 6999, "vanilla", "vanilla", "vanilla evilities", "[code] Skill.dat"),
            band(7000, 7999, "kit", "in_use", "kit: class/unique evility aliases (7048-7050 in the installed "
                                              "D4 packs) and the allocator's fallback band (7000+)",
                 "[code] d5lib/charstudio.free_evility_id; d5lib/newclasses.py alias hook"),
            # SPECIALS (2026-10-29): the game's own Skill.dat stops at 6306 (read on the pristine
            # original-state archive), so 8000+ is not a vanilla band.  Since D4REV2 every D4 evility
            # that needed its own compiled rule ships as "8000 + the D4 evility id" (8023, 8026, 8037,
            # 8068, 8096, 8109, 8178-8186, 8347, 8368, 8614, 8625, 8643, 8694, 8815, 8845, 8846,
            # 8861), and the D4 converter's exact-ID scheme is that same formula (d5lib/d4exact.py).
            # 8000..8999 is therefore the kit's exact-row block; everything above it stays as recorded.
            band(8000, 8999, "kit", "in_use",
                 "kit: D4 exact extension rows, id = 8000 + the D4 evility id (D4REV2 onward)",
                 "[code] d5lib/d4exact.py; d5lib/evility.py; D4REV2/D4UNIQ2/SPECIALS reports"),
            band(9000, 9999, "vanilla", "vanilla", "vanilla evilities (no row above 6306 in the "
                                              "pristine Skill.dat)", "[code] Skill.dat"),
            # SPECIALS (2026-10-29): the same idea for DD2, whose evility ids overlap D4's (DD2 30
            # Sadistic and D4 30 would both be 8030), so DD2 exact rows live one place higher.
            band(10000, 10999, "kit", "in_use",
                 "kit: DD2 exact extension rows, id = 10000 + the DD2 evility id",
                 "[code] d5lib/evility.py; SPECIALS report"),
            band(11000, 19999, "vanilla", "vanilla", "vanilla evilities (no row above 6306 in the "
                                                    "pristine Skill.dat)", "[code] Skill.dat"),
            band(20000, 20503, "overlord", "in_use",
                 "Overlord v3 evilities (20000-20016 Android/Majin, 20300-20303 Stella/Rutile)",
                 f"[code] {ROSTER} §1, §4"),
            band(20504, 21999, "overlord", "reserved", "Overlord evility band, reserved for v4",
                 f"[doc] {ROSTER} §6"),
            band(22000, 26199, "unallocated", "unallocated", "no owner recorded (the installed DD2 packs use "
                                                            "24000-26182; not carved here)", ""),
            band(26200, 26299, "kit", "in_use",
                 "kit: DD2 rows by the installed convention 24000 + the DD2 evility id, continued above the highest "
                 "installed id (26200 Wind Dominance, EVILFX3)", "[code] d5lib/importers/dd2-innate-evilities.json"),
            # EVILFX2b (coordinator, 2026-11-10): SAVE SAFETY.  Learned evilities are one bit per Skill.dat row
            # POSITION, so a row added today must not sort before an installed learnable row (highest: 26182).
            # New D4 / DD2 rows that would do so go into these LATE bands, below the Disgaea RPG block (innate
            # only).  The mapping is recorded per row (D4: d4-evility-additions.json `late_ids`); installed rows
            # keep their ids.  Gate: d5lib.learned.moved / tools/check_skill_budget.py --installed.
            band(26300, 26999, "kit", "in_use",
                 "kit: DD2 late rows (new rows that would sort before an installed learnable row), allocated "
                 "one by one and recorded per row (26300-26304, EVILFX3/PLUME1)",
                 "[code] d5lib/importers/dd2-innate-evilities.json; d5lib/learned.py"),
            band(27000, 27999, "kit", "in_use",
                 "kit: D4 late rows, id = 27000 + the D4 evility id, for rows added from 2026-11-10 on that would "
                 "sort before an installed learnable row (first: 27844 Beryl's Servant 1)",
                 "[code] d5lib/importers/d4-evility-additions.json late_ids; d5lib/learned.py"),
            # DRPGEVIL1 (2026-11-10): Disgaea RPG leader-skill ids are character id * 10 + n (up to 600289), so
            # they cannot be offset into a band the way D4/DD2 ids are.  Each of the 146 base characters gets
            # four fixed ids, 28000 + 4 * its position in drpg-leases.json + slot (main, sub 1-3) = 28000..28583,
            # recorded per row in d5lib/importers/drpg-evility-overlay.json.  The block sits ABOVE every evility
            # id in use (installed and built packs stop at 26182) on purpose: the game records learned evilities
            # as one bit per Skill.dat row POSITION for the first 1000 rows (d5lib/learned.py), the installed
            # table has 951 rows, and a block below the DD2 rows would move their bit positions in every save.
            band(28000, 28999, "kit", "in_use",
                 "kit: Disgaea RPG own evility rows, id = 28000 + 4 * lease position + slot (DRPGEVIL1)",
                 "[code] d5lib/importers/drpg_evilities.py; drpg-evility-overlay.json; d5lib/learned.py"),
            # OLCONV2 (2026-11-19): the converted Overlord characters keep their evilities out of Overlord's
            # reserved 20000-21999 band and ABOVE every in-use id (same save-safety reason as the bands above).
            band(29000, 29099, "kit", "in_use",
                 "kit: converted Overlord character evility rows (Stella/Rutile/Majin), allocated first-free and "
                 "recorded per character in d5lib/importers/overlord-leases.json (OLCONV2)",
                 "[code] d5lib/importers/overlord-leases.json; d5lib/learned.py"),
            band(29100, 65535, "unallocated", "unallocated", "no owner recorded", ""),
        ],
        "rules": {
            "band_name": "Overlord's 6307-6314 is the low evility band (a second config file); both "
                         "Overlord bands are reserved so a converted evility keeps its numbers.",
        },
    }

    # ---- magic.dat ids (skills / specials) --------------------------------------------------------
    namespaces["special_id"] = {
        "kind": "range",
        "description": "magic.dat row ids: the game's skills and every mod's own skills/specials. A unique "
                       "character's own skills are 10000 + class id + n; classes without a unique id use the "
                       "13000+ fallback.",
        "bands": [
            band(1, 9999, "vanilla", "vanilla", "vanilla skills (incl. the 1001-1005 / 1401-1405 ladders)",
                 "[code] magic.dat; d5lib/charstudio.free_skill_id"),
            band(10000, 16999, "kit", "in_use",
                 "kit own skills: 10000 + class id + n, and the 13000+ fallback",
                 "[code] d5lib/charstudio.free_skill_id"),
            # DRPGSKILL1 (2026-11-10): the Disgaea RPG importer gives each of its 146 bases up to four fixed ids,
            # 17000 + 4 * its position in drpg-leases.json + n (the skill's place among the base's own source
            # skills) = 17000..17583.  No char id 7000-7599 exists, so `10000 + class id + n` never lands here, and
            # no vanilla skill-script wrapper (12000000 / 12100000 / 12200000 + id) does either.  Learned skills
            # are stored by id in the unit record and found by binary search, so the band's position is free.
            band(17000, 17599, "kit", "in_use",
                 "kit: Disgaea RPG own skill rows, id = 17000 + 4 * lease position + n (DRPGSKILL1)",
                 "[code] d5lib/importers/drpg_skills.py; tools/build_drpg_skill_overlay.py"),
            band(17600, 28999, "kit", "in_use",
                 "kit own skills: 10000 + class id + n (the game's Magichange 2xxxx range included)",
                 "[code] d5lib/charstudio.free_skill_id"),
            band(29000, 29999, "kit", "in_use",
                 "SPECIALS2: source special attacks of the D4 / D1C / DD2 packs (explicit append-only leases)",
                 "[code] d5lib/importers/specials2-leases.json; d5lib/importers/specials2.BLOCK"),
            band(30000, 39999, "kit", "in_use",
                 "kit own skills: 10000 + class id + n (the game's combo 3xxxx range included)",
                 "[code] d5lib/charstudio.free_skill_id"),
            band(40000, 40312, "overlord", "in_use", "Overlord v3 specials (13: Battle Suit 40000-40003, "
                                                     "Android 40010-40012, Stella/Rutile ladders)",
                 f"[code] {ROSTER} §4"),
            band(40313, 42769, "kit", "in_use", "kit own skills for registry classes 30313-32760 "
                                                "(10000 + class id + n)", "[code] d5lib/charstudio.py"),
            band(42770, 65535, "unallocated", "unallocated", "no owner recorded", ""),
        ],
        "rules": {
            "allocation_not_reservation": "These ids are allocated first-free from the loaded table "
                                          "(unique characters: 10000 + char id // 10 * 10 + n; classes "
                                          "without one: 13000+), not reserved in advance. A collision is "
                                          "caught when the table is loaded at build time, so this "
                                          "manifest does not model them as derived bands.",
            "overlord_specials": "40000-40312 is Overlord's; any builder that allocates a skill id in it "
                                 "is refused by the claims check.",
        },
    }

    # ---- personality rows (charPersonal.dat) ------------------------------------------------------
    # The kit's class importer gives every imported class three personality rows ("Honest / Extravagant /
    # Overwhelming"), one per creation-screen choice.  The game finds them by `voice_group`, not by id
    # (d5lib/newclasses.personality_names groups on voice_group), but the id is the table key the loader
    # sorts on, so two packs using one id is the same ambiguity as a duplicate char.dat row.  DUPFIX found
    # 17 mods appending 132-134 because each build computed `max(id) + 1` against its own pack only.
    namespaces["personality_id"] = {
        "kind": "range",
        "description": "charPersonal.dat row ids. Three rows per imported class family (variant 0..2), found "
                       "at creation time by voice_group = 100 + (family - 1000) // 10; the id is the table "
                       "key (the loader sorts on it), so it must be unique across every installed mod.",
        "bands": [
            band(1, 131, "vanilla", "vanilla",
                 "vanilla personality rows (129-131 appear four times each in vanilla itself: one set per "
                 "base voice group)", "[code] charPersonal.dat; d5lib/newclasses.py:296-324"),
            band(132, 65535, "kit", "in_use",
                 "kit personality rows for imported classes; allocate first-free above the vanilla max "
                 "(135-263 are already leased by the first D4/D1C/D2 packs)",
                 "[code] d5lib/rellease.py; tools/build_ownership_manifest.py"),
        ],
        "rules": {
            "lookup_key": "the game looks a personality row up by voice_group + variant; the id only has to "
                          "be unique, so re-leasing an id never changes which class a row belongs to",
        },
    }

    # ---- wishes ----------------------------------------------------------------------------------
    namespaces["wish_id"] = {
        "kind": "range",
        "description": "WishDataBase row ids (the Dark Assembly bills; Overlord ships its recruits as bills).",
        "bands": [
            band(1, 1048, "vanilla", "vanilla", "vanilla bills", "[inferred] Overlord's lowest custom bill is 1049"),
            band(1049, 1057, "overlord", "in_use", "Overlord v3 bills (Berserk Usalia, Liezerota, Prinny "
                                                   "Overlord, Baal, Baal Bits x4, Proto Darkdeath)",
                 f"[code] {ROSTER} §1, §4"),
            band(1058, 19999, "vanilla", "vanilla", "vanilla bills", "[code] WishDataBase.dat"),
            band(20000, 20500, "overlord", "in_use", "Overlord v3 recruit bills for its five classes",
                 f"[code] {ROSTER} §4"),
            band(20501, 21999, "overlord", "reserved", "Overlord bill band, reserved for v4",
                 f"[doc] {ROSTER} §6"),
            band(22000, 22099, "kit", "in_use",
                 "kit: recruit bills of the converted Overlord characters (WishDataBase rows read by "
                 "d5lib/wishrecruit.py), recorded in d5lib/importers/overlord-leases.json (OLCONV2)",
                 "[code] d5lib/importers/overlord-leases.json; d5lib/wishrecruit.py"),
            band(22100, 65535, "unallocated", "unallocated", "no owner recorded; D5ModKit recruit quests "
                                                            "use Quest.dat slots, not wishes", ""),
        ],
    }

    # ---- ANM ids (sprites, portraits, cut-ins) ----------------------------------------------------
    namespaces["anm_id"] = {
        "kind": "range",
        "description": "ANM archive image / animation-set ids: a class sprite set (family .. family + 2), "
                       "portraits and list icons (10000 + family + 0..9), the face bank (9017) and cut-ins. "
                       "A unique character uses the same shape keyed to its char row instead of a family "
                       "(sprite row .. row + 2, cut-in / status portrait 10000 + row .. +1).",
        "bands": [
            band(1, 222, "vanilla", "vanilla",
                 "vanilla sprites, faces bank (9017), standing pictures, portraits of vanilla unique rows "
                 "(row 80's sprite keys stay vanilla: Xenolith moved to 941)",
                 "[code] d5lib/newclasses.py:35; d5lib/outfits.py"),

            band(223, 403, "kit", "reserved",
                 "unique graphics lease pool, second measured run: the superseded low-row D4 unique band "
                 "(sprite = row, +1 companion, +2 standing picture) is no longer used as char rows, and no "
                 "game file and no installed mod file sits at n, n+1, n+2, 10000+n or 10001+n for the "
                 "windows still free in it (measured: d5lib/slots.unique_sprite_pool), so a registry "
                 "unique may key its art to a lease from here (both portrait keys stay in 10223-10404). "
                 "Handed out after 853-999 so earlier leases keep their numbers",
                 "[code] d5lib/slots.py SPRITE_LEASE_RUNS; d5lib/d4unique.py unique_shape; "
                 "Subprojects/Engine-Extensions/D4UNIQ2-REPORT.md"),
            *_carve(404, 852, {n: m for m, p in _third.items()
                               for n in (p, p + 1, p + 2)},
                    "unique art lease window (third run, carved out of the vanilla band)",
                    "vanilla sprites, faces bank (9017), standing pictures (rows at stride 10 and the live "
                    "outfit rows 470-497; a lease only takes the windows that measure free)",
                    "Subprojects/Engine-Extensions/D1C2-REPORT.md"),
            band(UNIQUE_SPRITE_FIRST, UNIQUE_SPRITE_LAST, "kit", "reserved",
                 "unique graphics lease pool: no game file and no installed mod file sits at n or 10000+n "
                 "anywhere in 853..999 (measured: d5lib/slots.unique_sprite_pool), so a unique leases three "
                 "consecutive numbers here -- sprite, +1 companion, +2 standing picture -- and its cut-in / "
                 "status portrait at 10000+n. Leased today: Shark King 931-933, Xenolith 941-943, and every "
                 "registry unique in the D1C batch (leases recorded per pack)",
                 "[code] d5lib/slots.unique_sprite_pool; d5lib/nativeimports.unique_identity; "
                 "Research/source-packs/d1c/batches/unique-leases.json"),
            band(1000, 10079, "vanilla", "vanilla", "vanilla sprites, faces bank (9017), standing pictures",
                 "[code] d5lib/newclasses.py:35; d5lib/outfits.py"),
            band(10080, 10081, "vanilla", "vanilla",
                 "vanilla portraits (Xenolith's old 80 keys stay vanilla)", "[code] ANM_HI_JP.dat"),
            band(10082, 10222, "vanilla", "vanilla", "vanilla portraits / cut-ins", "[code] ANM_HI_JP.dat"),

            band(10223, 10404, "kit", "reserved",
                 "cut-in / status portraits of unique leases taken from the second measured run 223-403 "
                 "(10000 + n and +1); the band is the same one the superseded low-row D4 unique rows used",
                 "[code] d5lib/slots.py SPRITE_LEASE_RUNS; d5lib/d4unique.py unique_shape"),
            *_carve(THIRD_RUN_PORTRAITS[0], THIRD_RUN_PORTRAITS[1],
                    {n: m for m, p in _third.items() for n in (10000 + p, 10001 + p)},
                    "cut-in / status portrait of a third-run lease (10000 + n and +1)",
                    "vanilla portraits / cut-ins",
                    "Subprojects/Engine-Extensions/D1C2-REPORT.md"),
            band(10853, 10999, "kit", "reserved",
                 "cut-in / status portraits of every unique in the 853..999 lease pool (10000 + n and +1; "
                 "Shark King 10931-10932, Xenolith 10941-10942, the registry uniques' own leases)",
                 "[code] d5lib/nativeimports.unique_identity; d5lib/newchars.py:7-8"),
            band(11000, 11269, "vanilla", "vanilla", "vanilla portraits / cut-ins", "[code] ANM_HI_JP.dat"),
            band(11270, 12905, "kit", "in_use", "kit portraits and list icons for physical families "
                                                "1270-2895 (10000 + family + 0..9, family .. family + 9)",
                 "[code] d5lib/newclasses.py:35"),
            band(12906, 13172, "vanilla", "vanilla", "vanilla ids", "[code] ANM_HI_JP.dat"),
            band(13173, 13186, "overlord", "in_use", "Overlord legacy save alias for its portrait bases",
                 f"[code] {ROSTER} §4"),
            band(13187, 19999, "vanilla", "vanilla", "vanilla ids", "[code] ANM_HI_JP.dat"),
            band(20000, 20506, "overlord", "in_use", "Overlord v3 animation sets 20000/20010/20300/20310/"
                                                     "20500 (+1 companion each)", f"[code] {ROSTER} §1"),
            band(20507, 21999, "overlord", "reserved", "Overlord animation-set band, reserved for v4",
                 f"[doc] {ROSTER} §6"),
            band(22000, 29999, "kit", "in_use", "kit portraits/list icons for registry classes 12000-19999",
                 "[code] d5lib/newclasses.py:35 (10000 + family + 0..9)"),
            band(30000, 30506, "overlord", "in_use", "Overlord v3 cut-ins 30000-30019, 30300, 30310, "
                                                     "30500-30506", f"[code] {ROSTER} §1"),
            band(30507, 32769, "overlord", "reserved", "Overlord portrait logical bases 31000/31010/31020/"
                                                       "32000/32001 and the gap before kit's derived ids",
                 f"[code] {ROSTER} §4"),
            band(32770, 42769, "kit", "in_use", "kit portraits/list icons for registry classes 22770-32760",
                 "[code] d5lib/newclasses.py:35"),
            band(42770, 65535, "unallocated", "unallocated", "no owner recorded", ""),
        ],
        "rules": {
            "unique_keyed_graphics": {
                "rows": [223, 403],
                "sprite_span": UNIQUE_SPRITE_SPAN,
                "portrait_offset": UNIQUE_PORTRAIT_OFFSET,
                "portrait_span": UNIQUE_PORTRAIT_SPAN,
                "note": "A unique character's sprite ids are its char.dat row .. row + 2 and its cut-in / "
                        "status portrait 10000 + row .. +1 (d5lib/d4unique.py:479, d5lib/newchars.py:7-8). "
                        "The bands 223-403 and 10223-10404 encode that for the unique row band. A unique on "
                        "a row whose derived ids leave the band -- rows 402 and 403 derive 404/405, vanilla "
                        "rows -- is refused by the claims check instead of being silently allocated; move "
                        "the unique or extend the band deliberately.",
            },
            "family_portraits": "A class family's portrait / list-icon set is 10000 + family + 0..9 "
                                "(ten colours, d5lib/newclasses.py:399-419). That wider window applies "
                                "to families, not to uniques, so it is modelled by the 11270-12905 band.",
        },
    }

    # ---- voices ----------------------------------------------------------------------------------
    namespaces["voice_id"] = {
        "kind": "range",
        "description": "Voice ids (voice set = kind * 100000 + voice id * 10 + personality). The game's own "
                       "ids end at 5321; the kit allocates new ids from 9000 downwards inside 6000-9999.",
        "bands": [
            band(0, 4199, "vanilla", "vanilla", "vanilla voices", "[code] d5lib/voices.py:48"),
            band(4200, 4205, "overlord", "in_use", "Overlord v3 voice groups 42000/42001/42030/42031/42050 "
                                                   "(= voice ids 4200-4205, inside the vanilla id range: the "
                                                   "mapping to a line table is Overlord's own)",
                 f"[code] {ROSTER} §4"),
            band(4206, 5321, "vanilla", "vanilla", "vanilla voices (the game's highest id is 5321)",
                 "[code] d5lib/voices.py:48"),
            band(5322, 5999, "unallocated", "unallocated", "no owner recorded", ""),
            band(voices.CUSTOM_FIRST, voices.CUSTOM_LAST, "kit", "in_use",
                 "kit custom voices (6000-9999; handed out from 9000 first)",
                 "[code] d5lib/voices.py:48-50"),
        ],
    }

    # ---- script event ids ------------------------------------------------------------------------
    namespaces["script_event_id"] = {
        "kind": "range",
        "description": "Script/script.dat event ids: a skill's choreography and its call_event targets. "
                       "An event id is stored in three bytes, so it must stay below 16777216.",
        "bands": [
            band(1, 4999999, "unallocated", "unallocated", "no owner recorded", ""),
            band(skills.MOD_CHOREO_EXT[1][0], skills.MOD_CHOREO_EXT[1][1] - 1, "kit", "reserved",
                 "second kit choreography range 5000000-10999999 (100 blocks of 1000, used after the "
                 "first range is full)", "[code] d5lib/skills.py:37-38"),
            band(skills.DEFAULT_SCRIPT, skills.DEFAULT_SCRIPT, "kit", "in_use",
                 "default skill script event (DEFAULT_SCRIPT)", "[code] d5lib/skills.py:33"),
            band(skills.DEFAULT_SCRIPT + 1, skills.SKILL_SCRIPT - 1, "unallocated", "unallocated",
                 "no owner recorded (SKILL_SCRIPT + skill id starts at 12000000; skill ids stay below "
                 "100000 in the manifest's tables)", ""),
            band(skills.SKILL_SCRIPT, skills.SKILL_SCRIPT + 99999, "kit", "in_use",
                 "per-skill wrapper: SKILL_SCRIPT + skill id (skill ids < 100000)",
                 "[code] d5lib/skills.py:32,665"),
            band(skills.SKILL_SCRIPT + 100000, skills.OVL_WRAPPER - 1, "unallocated", "unallocated",
                 "no owner recorded", ""),
            band(skills.OVL_WRAPPER, skills.OVL_WRAPPER + 109999, "kit", "in_use",
                 "Overload wrapper (OVL_WRAPPER + id) and its short variant (+100000)",
                 "[code] d5lib/skills.py:42-43"),
            band(skills.OVL_WRAPPER + 110000, skills.MOD_CHOREO_EXT[0][0] - 1, "unallocated", "unallocated",
                 "no owner recorded", ""),
            band(skills.MOD_CHOREO_EXT[0][0], skills.MOD_CHOREO_EXT[0][1] - 1, "kit", "in_use",
                 "first kit choreography range 14000000-14999999",
                 "[code] d5lib/skills.py:36-38"),
            band(skills.CHOREO_MIN, skills.CHOREO_MAX - 1, "kit", "in_use",
                 "custom choreography blocks (15900000 .. 15999999) and the game's own 15xxxxxx ones",
                 "[code] d5lib/skills.py:36,44"),
            band(16000000, 16777215, "vanilla", "vanilla",
                 "the game's own choreographies above 15xxxxxx (Macrocosm 16133700)",
                 "[code] d5lib/skills.py:39 GAME_CHOREO_HIGH"),
        ],
    }

    # ---- Database_0 members ----------------------------------------------------------------------
    namespaces["database_member"] = {
        "kind": "list",
        "description": "Data/Database/Database_0.dat members. The kit's finalizer writes the archive; "
                       "Overlord replaces a whole member from mods/<Mod>/Database/Database_0/<member> and "
                       "row-merges only char.dat. One owner per member: the kit, with converted mods "
                       "writing rows through it.",
        "members": [
            member("char.dat", "kit", "in_use", ["kit", "overlord:merge"],
                   "class rows, uniques, dummy rows; the only member Overlord row-merges"),
            member("JobRank.dat", "kit", "in_use", ["kit"], "class rank table"),
            member("charhelp.dat", "kit", "in_use", ["kit"], "class help text"),
            member("charPersonal.dat", "kit", "in_use", ["kit"], "character personality / voice rows"),
            member("comb.dat", "kit", "in_use", ["kit"], "class combo slots"),
            member("magic.dat", "kit", "in_use", ["kit"], "skills and specials (special_id)"),
            member("Skill.dat", "kit", "in_use", ["kit"], "evilities (evility_id)"),
            member("OverlordSkill.dat", "kit", "in_use", ["kit"], "Overload rows and their script ids"),
            member("EffectTableDataBase.dat", "kit", "in_use", ["kit"], "skill effect table"),
            member("StringListDataBase.dat", "kit", "in_use", ["kit"], "UI strings"),
            member("Quest.dat", "kit", "in_use", ["kit"], "quests; kit recruit quests take slots here"),
            member("item.dat", "kit", "in_use", ["kit"], "items (weapons reference it)"),
            member("dungeon.dat", "kit", "in_use", ["kit"], "stage list / base panels"),
        ],
        "rules": {
            "new_member": "a member not listed here is refused: add it to the manifest first, so a new "
                          "shape (and its owner) is a deliberate decision",
        },
    }

    # bands must be written in ascending order: the manifest is read at a glance, and the checker
    # reports overlaps by looking at neighbours.
    for name, ns in namespaces.items():
        if ns.get("kind") == "range":
            ns["bands"].sort(key=lambda b: b["start"])

    # A third-run lease is only legitimate while each of its five keys is a kit band of its own: the carve
    # above is what makes the claims pass, so a drift here would surface as "not_owned" per build instead.
    for mod_id, physical in _third.items():
        for n in (physical, physical + 1, physical + 2, 10000 + physical, 10001 + physical):
            hits = [b for b in namespaces["anm_id"]["bands"] if b["start"] <= n <= b["end"]]
            assert len(hits) == 1 and hits[0]["owner"] == "kit", (mod_id, n, hits)

    return {
        "version": 1,
        "base": BASE,
        "generated": GENERATED,
        "source": "generated by tools/build_ownership_manifest.py from d5lib constants + the named "
                  "Overlord/v1 records; do not hand-edit (the tests fail if it drifts)",
        "notes": [
            "One owner per band. 'contested' names two claimants and nothing may be allocated there.",
            "'unallocated' is not free: a claim in an unallocated band is refused, so an unrecorded "
            "range cannot be taken by accident.",
            "Overlord bands are reserved for Overlord's content. Under NORTH-STAR.md that content is "
            "converted into kit mods, so the numbers are kept free for the conversion rather than for a "
            "co-installed Overlord.",
            "Scope: offline. Every band cites a file, a report section or a module constant; nothing "
            "here was verified by launching the game.",
        ],
        "rules": {
            "grandfather": "Existing installed packs keep the ids they already have. The manifest "
                           "records them; it does not move them (see OWNERSHIP-REPORT.md, migration).",
            "not_co_resident": "A separately installed Overlord and the kit are not co-resident: unlock "
                               "flags, mastery slots 47-52 and the 20000-21999 ids are single-owner.",
        },
        "namespaces": namespaces,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the committed manifest differs")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)
    data = build()
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not os.path.exists(args.out):
            print(f"missing {args.out}")
            return 1
        with open(args.out, "r", encoding="utf-8") as fh:
            current = fh.read()
        if current != text:
            print(f"{args.out} is stale: run tools/build_ownership_manifest.py")
            return 1
        print(f"{args.out} is up to date")
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
