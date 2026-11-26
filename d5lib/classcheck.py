"""Source-pack identity rules: what a built class / unique mod must carry before it can be installed.

Every rule here was learned from a live failure, and each one is *refused at build time* rather
than reported after an install:

  R1  personalities  A generic class family needs at least three charPersonal.dat rows whose
                     voice_group equals family // 10.  The Recruiter's personality page
                     (FUN_140659070) lists the rows whose u16 +0x04 equals the class id / 10 and
                     its confirm handler (FUN_140658cf0) reads
                     `rows[selected.index * 0x15c + 6]` with no bounds check: with no row the
                     index is whatever the empty list left behind and the read is wild.  Cryswar's
                     Overlord patches that page for exactly this reason (d5_custom_classes.c:
                     "the page needs 3").  Live evidence: all 13 D1C families and DD2 22680 wedge
                     the command loop, all 16 D4 families (which do write the rows) create fine.
  R2  ranks          A generic class that builds N rank rows declares N unlocked ranks.  Declaring
                     one leaves five built rows unreachable in the Recruiter and the rank switch.
  R3  face           A class patch set ships at least face_<family>.png (colour 0 is the fallback
                     face for every colour without one of its own).
  R4  quest reward   A Quest.dat row a mod adds with reward_type 5 (recruit a character) must reward
                     one of the mod's own char.dat rows.  Two shipped quests pointed at other
                     characters' rows (Stella 9503 -> 470, Xenolith 300 -> 470, Shark King 341 -> 45).
  R5  row ownership  An added char.dat row may not be a vanilla character row, and may not be a row
                     another pack already claims.  Repurposing a vanilla character silently loses
                     the patch (row 45 stayed vanilla Pleinair on the live install).
  R7  text bytes     A pack's own text goes into three tables with a fixed, byte-oriented encoding:
                     charhelp's 92-byte line slots, char.dat's 92-byte name/title slots and
                     StringListDataBase (string ids 41000+n, written by database._write_pool with a
                     *character* count next to a UTF-8 byte pool).  A character outside ASCII in a
                     Latin slot is written as 2-3 UTF-8 bytes while every length the game reads is a
                     character count, so the drawn line and the stored bytes disagree.  Every
                     shipped working pack is pure ASCII; all 13 D1C class packs carried U+2014.
  R8  help link      charhelp.dat is looked up by the char.dat row's `help_id` and matched against
                     the charhelp `char_id` field (0x14008eee0); "a help_id that matches no row makes
                     UNIT INFO crash".  A pack that renumbers its char rows without renumbering
                     `help_id` ships a dangling description link - the defect that confounded the
                     D1CWEDGE2 A/B probes (both wedging builds pointed at a charhelp row the same
                     build had moved away, and the working D4 pack did not).
  R9  desc length    The class's one-line description (the StringListDataBase text the Kit's desc hook
                     returns for the wheel) is copied into a fixed 0x100-byte field of the menu object
                     with no bound at all: `0x140663200 movzx eax,[rcx] / 0x140663203 mov
                     [rcx+rdx+0x1c2c],al / ... / jne` (the same copy at 0x14065feb0's panel draw), and
                     the dirty byte is written at +0x1d2c, i.e. exactly one byte past the 256-byte
                     field.  +0x1d30/+0x1d34 hold 17.0f/16.0f (0x1403ea680) and +0x1d38 is the list
                     pane the s28to33 screens call through (vt+0xa8, e.g. 0x1407af960),
                     so a description of 256+ bytes overwrites live pointers.  D1C's 13 descriptions
                     were 247-280 bytes; 11390 (273) is the class LIVE10 froze on.
  R10 control code   D5 reads a control node's code from the LOW byte of the key's flags u16
                     (`0x1402f5002 movsx ecx, byte ptr [rdx+2]`, then 2 loop back / 3 conditional /
                     4 wait / 5 hold, and the loop-marker back-scan `0x1402f5150 cmp byte [rdx+2],1`);
                     code 0 takes no control action.  A bank whose animation roots carry the code in
                     the HIGH byte leaves every preview with no marker: it never holds or loops.
                     All nine DD2 class packs built 2026-10-30 shipped that way - the only packs of
                     the 174 in TEST18B that fail this rule, and the ones the Recruiter wheel draws
                     first.  Fix: `d5lib.dd2source.normalize_control_flags`.

This module is pure file inspection of a *built mod folder*: no game, no exe, no installer state.
`d5lib.d4expansion.preflight` calls `check()` for every selected mod, so all importers
(`nativeimports.build_entry`, `sourceimports.build_d4_pilot`) refuse a defective pack, and the
source-pack batch validators call the same function so the rule cannot drift between them.
"""
from __future__ import annotations

import json
import os

DB = "Database/Database_0.dat/"
PERSONAL = "charPersonal.dat"
CHAR = "char.dat"
QUEST = "Quest.dat"
MIN_PERSONALITIES = 3
RANK_DIGITS = range(0, 6)
REWARD_RECRUIT = 5                      # Quest.dat reward_type that adds a character
DESC_MAX = 255                          # bytes that fit in the menu's 0x100 description field (R9)


def personality_group(family):
    """charPersonal.dat voice_group the game matches for a class family (class id / 10)."""
    return int(family) // 10


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return None


def _patch(mod_dir, table):
    return _load(os.path.join(str(mod_dir), "patches", "db", table + ".json")) or {}


def _added(mod_dir, table):
    return [r for r in (_patch(mod_dir, table).get("added") or []) if isinstance(r, dict)]


def class_specs(mod_dir):
    """Every patches/classes/class_<family>.json descriptor, sorted by family."""
    folder = os.path.join(str(mod_dir), "patches", "classes")
    out = []
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not (name.startswith("class_") and name.endswith(".json")):
            continue
        spec = _load(os.path.join(folder, name))
        if isinstance(spec, dict) and "family" in spec:
            out.append(spec)
    return sorted(out, key=lambda s: int(s["family"]))


def face_colours(mod_dir, family):
    """Colour indices that ship a face picture (0 is the fallback for every other colour)."""
    folder = os.path.join(str(mod_dir), "patches", "classes")
    out = []
    if not os.path.isdir(folder):
        return out
    base = "face_%d" % int(family)
    for name in os.listdir(folder):
        if not name.endswith(".png"):
            continue
        stem = name[:-4]
        if stem == base:
            out.append(0)
        elif stem.startswith(base + "_"):
            try:
                out.append(int(stem[len(base) + 1:]))
            except ValueError:
                pass
    return sorted(out)


def char_rows(mod_dir):
    """{row id: row dict} for every char.dat row the mod adds."""
    return {int(r["id"]): r for r in _added(mod_dir, CHAR) if r.get("id") is not None}


def personality_counts(mod_dir):
    """{voice_group: row count} for the charPersonal.dat rows the mod adds."""
    out = {}
    for r in _added(mod_dir, PERSONAL):
        if r.get("voice_group") is None:
            continue
        g = int(r["voice_group"])
        out[g] = out.get(g, 0) + 1
    return out


def quests(mod_dir):
    """Every Quest.dat row the mod adds."""
    return _added(mod_dir, QUEST)


def registry_uniques(mod_dir):
    """Declarations of uniques on registry identities: [{identity, physical, template, ...}]."""
    data = _load(os.path.join(str(mod_dir), "patches", "characters", "unique.json")) or {}
    docs = data.get("uniques") or ([data] if data.get("identity") else [])
    return [d for d in docs if isinstance(d, dict) and d.get("identity") is not None]


def describe(mod_dir):
    """A comparable description of a built mod, field by field.

    Two built class mods of different sources are compared with `diff()`; the fields are the ones
    that differ between a pack that installs and one that wedges the Recruiter.
    """
    fams = class_specs(mod_dir)
    files = os.path.join(str(mod_dir), "files", "Anime", "ANM_HI_JP.dat")
    anm = sorted(n for n in (os.listdir(files) if os.path.isdir(files) else []) if n.endswith(".lzs"))
    faces = {int(s["family"]): face_colours(mod_dir, s["family"]) for s in fams}
    return dict(
        path=str(mod_dir),
        classes=[dict(family=int(s["family"]), name=s.get("name"), kind=s.get("kind"),
                      sprite_family=s.get("sprite_family", s["family"]),
                      unlocked=s.get("unlocked"), unlocked_ranks=s.get("unlocked_ranks"),
                      faces=faces.get(int(s["family"]), [])) for s in fams],
        tables={t: dict(added=len(_added(mod_dir, t)), changed=len(_patch(mod_dir, t).get("rows") or {}))
                for t in (CHAR, PERSONAL, "JobRank.dat", "charhelp.dat", QUEST)},
        char_rows=sorted(char_rows(mod_dir)),
        personality=personality_counts(mod_dir),
        quests=[dict(id=int(q["id"]), reward_type=int(q.get("reward_type", -1)),
                     reward_value=int(q.get("reward_value", -1)),
                     reward_count=int(q.get("reward_count", 0)),
                     client_EN=q.get("client_EN"), name_EN=q.get("name_EN")) for q in quests(mod_dir)],
        anm=anm,
    )


def diff(left, right):
    """Field-by-field differences between two `describe()` results (left: working, right: suspect)."""
    out = []

    def add(field, a, b):
        if a != b:
            out.append(dict(field=field, left=a, right=b))

    add("classes", left["classes"], right["classes"])
    add("tables", left["tables"], right["tables"])
    add("char_rows", left["char_rows"], right["char_rows"])
    add("personality", left["personality"], right["personality"])
    add("quests", left["quests"], right["quests"])
    add("anm", sorted(set(left["anm"]) ^ set(right["anm"])), sorted(set(right["anm"]) ^ set(left["anm"])))
    return out


def vanilla_rows(fs):
    """(char row ids, {voice_group: count}) read from the pristine table through a GameFS."""
    from . import database
    char = database.load_table(CHAR, fs.read(DB + CHAR))
    counts = {}
    personal = database.load_table(PERSONAL, fs.read(DB + PERSONAL))
    for r in personal.rows:
        counts[int(r["voice_group"])] = counts.get(int(r["voice_group"]), 0) + 1
    return {int(r["id"]) for r in char.rows}, counts


def vanilla_help_ids(fs):
    """charhelp.dat char_id (and id) values of the pristine table, for rule R8."""
    from . import database
    help_rows = database.load_table("charhelp.dat", fs.read(DB + "charhelp.dat"))
    out = set()
    for r in help_rows.rows:
        out.add(int(r["char_id"]))
        out.add(int(r["id"]))
    return out


def foreign_rows(mods, vanilla_ids=()):
    """{char row id: mod id} for rows other mods add (a unique row is one character's identity)."""
    out = {}
    for mod in mods:
        for cid in char_rows(mod.folder if hasattr(mod, "folder") else mod):
            if int(cid) not in vanilla_ids:
                out[int(cid)] = mod.id if hasattr(mod, "id") else str(mod)
    return out


def finding(rule, message, severity="error", **detail):
    return dict(rule=rule, severity=severity, message=message, **detail)


# char rows a pack may add above 10000 outside the Kit's registry scheme: only a pack that declares
# itself part of Overlord's package, and only inside the band the ownership manifest gives him.
OVERLORD_ROW_BAND = (20000, 20500)


def overlord_row_band(mod_dir):
    """(lo, hi) when this pack is part of an Overlord package, else None"""
    try:
        with open(os.path.join(str(mod_dir), "mod.json"), encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    pkg = meta.get("overlord_package")
    return OVERLORD_ROW_BAND if isinstance(pkg, dict) else None


# ---------------------------------------------------------------- R7 / R8: text bytes and help links
LATIN_SUFFIXES = ("_EN", "_FR")           # the two Latin slots: ASCII in every shipped working pack
CJK_SUFFIXES = ("_JP", "_CHN", "_KOR")    # these slots are UTF-8 in the vanilla table
TEXT_TABLES = (CHAR, "charhelp.dat")


def non_ascii(text):
    """[(index, codepoint)] for every character a Latin slot must not carry."""
    return [(i, ord(c)) for i, c in enumerate(str(text)) if ord(c) > 0x7E or ord(c) < 0x20]


def text_findings(mod_dir):
    """R7: text a pack writes into a byte-oriented slot must be representable in that slot."""
    out = []
    for table in TEXT_TABLES:
        for row in _added(mod_dir, table):
            for field, value in sorted(row.items()):
                if not isinstance(value, str):
                    continue
                bad = non_ascii(value)
                if not bad:
                    continue
                cjk = field.endswith(CJK_SUFFIXES)
                out.append(finding(
                    "R7-text-bytes",
                    "%s row %s field %s carries U+%04X at %d of %d: %d UTF-8 byte(s) where the game "
                    "reads a character count (write ASCII, e.g. ' - ')"
                    % (table, row.get("id"), field, bad[0][1], bad[0][0], len(value),
                       len(str(value).encode("utf-8")) - len(str(value))),
                    severity="warning" if cjk else "error",
                    table=table, row=row.get("id"), field=field,
                    codepoints=[hex(c) for _, c in bad[:6]]))
    for spec in class_specs(mod_dir):
        for field in ("name", "hire_desc"):
            value = spec.get(field)
            if isinstance(value, str) and non_ascii(value):
                out.append(finding(
                    "R7-text-bytes",
                    "class %s field %s carries U+%04X (StringListDataBase 41000+n is a byte pool with a "
                    "character count; hire_desc is also copied into the charhelp lines)"
                    % (spec.get("family"), field, non_ascii(value)[0][1]),
                    severity="error", family=int(spec["family"]), field=field))
    return out


def help_link_findings(mod_dir, vanilla_help_ids=None):
    """R8: every char.dat row's help_id must resolve to a charhelp row (own, or vanilla)."""
    out = []
    have = {int(r["char_id"]) for r in _added(mod_dir, "charhelp.dat")
            if r.get("char_id") is not None}
    have |= {int(r["id"]) for r in _added(mod_dir, "charhelp.dat") if r.get("id") is not None}
    have |= {int(x) for x in (vanilla_help_ids or ())}
    for row in _added(mod_dir, CHAR):
        if row.get("help_id") is None:
            continue
        help_id = int(row["help_id"])
        # the game rounds help ids below 4000 down to a multiple of 10 before matching char_id
        key = help_id if help_id >= 4000 else help_id // 10 * 10
        if key in have or help_id in have:
            continue
        out.append(finding(
            "R8-help-link",
            "char.dat row %s carries help_id %d but this pack has no charhelp row with char_id %d "
            "(and none was supplied as vanilla): the description lookup has no row to return"
            % (row.get("id"), help_id, key),
            row=int(row["id"]), help_id=help_id, charhelp_row_ids=sorted(have)[:12]))
    return out


def control_flag_findings(mod_dir, limit=12):
    """R10: every animation's control root must carry a non-zero control code in its low byte.

    Read-only over the pack's own `files/Anime/*.dat/anm*.lzs` members.  A code above 5 is a
    warning (it takes no control action either, but it is a source value, not a layout error).
    """
    from . import anm as _anm
    out = []
    root = os.path.join(mod_dir, "files")
    if not os.path.isdir(root):
        return out
    coders = {}
    for base, _dirs, files in os.walk(root):
        for name in sorted(files):
            if not (name.startswith("anm") and name.endswith(".lzs")):
                continue
            path = os.path.join(base, name)
            try:
                parsed = _anm.load(path)
            except Exception as exc:  # noqa: BLE001 - a member that will not parse is a finding
                out.append(finding("R10-control-code",
                                   "%s: does not decode (%s); the loader would never publish it"
                                   % (name, exc), severity="error"))
                continue
            for block in parsed.blocks:
                roots = {a.root for a in block.animations if 0 <= a.root < len(block.nodes)}
                for index in roots:
                    keys = block.node_keys(block.nodes[index])
                    if not keys:
                        continue
                    low = [k.flags & 0xFF for k in keys]
                    if not any(low):
                        out.append(finding("R10-control-code",
                                           "%s: an animation root has keys %s - no control code in the "
                                           "low byte, so the preview never holds or loops"
                                           % (name, ", ".join("%#06x" % k.flags for k in keys[:4])),
                                           severity="error"))
                    for code in sorted(set(low)):
                        if code > 5:
                            coders.setdefault(code, []).append(name)
    for code, names in sorted(coders.items()):
        out.append(finding("R10-control-code",
                           "control code %d (not 1-5: takes no control action) on %d root key(s) in %s"
                           % (code, len(names), ", ".join(sorted(set(names))[:3])),
                           severity="warning"))
    return out[:limit] if len(out) > limit else out



def check(mod_dir, vanilla_char_ids=None, vanilla_personality_groups=None, foreign=None,
          dummy_rows=(), owner=None, vanilla_help_ids=None, control_codes=False):
    """Every identity rule, as a list of findings.  `error` means: do not ship this pack.

    mod_dir:            a built mod folder (patches/, files/).
    vanilla_char_ids:   char.dat row ids of the pristine game table (None: rule R5's vanilla half is skipped).
    foreign:            {row id: owning mod id} for rows another pack adds (None: skipped).
    dummy_rows:         row ids the Kit is allowed to fill in place (slots.DUMMY_ROWS).
    vanilla_help_ids:   charhelp char_id values of the pristine table (None: R8 only knows this pack's rows).
    """
    foreign = foreign or {}
    own_rows = set(char_rows(mod_dir))
    counts = personality_counts(mod_dir)
    out = []
    if control_codes:
        out.extend(control_flag_findings(mod_dir))
    for spec in class_specs(mod_dir):
        family = int(spec["family"])
        ranks = [d for d in RANK_DIGITS]
        generic = len(ranks) == 6
        group = personality_group(family)
        have = counts.get(group, 0) + int((vanilla_personality_groups or {}).get(group, 0))
        # a generic family reuses the donor's rows only if the donor's group is the family's group,
        # which it never is for a registry family; so the count is the mod's own rows
        if generic and counts.get(group, 0) < MIN_PERSONALITIES:
            out.append(finding("R1-personalities",
                               "%s (family %d): %d charPersonal rows for group %d; the personality page "
                               "needs %d" % (spec.get("name", "?"), family, counts.get(group, 0), group,
                                             MIN_PERSONALITIES),
                               family=family, group=group, rows=counts.get(group, 0), vanilla_rows=have))
        declared = spec.get("unlocked_ranks")
        # A registry family (>= 10000) has no mastery chain in the receiver, so every rank it builds
        # must be offered or the built rows are unreachable (D1C declared 1 of 6).  A Kit family
        # (a dummy slot like 1270-1350) unlocks its ranks by playing, so its declaration stays a
        # deliberate design choice.
        if generic and family >= 10000 and declared is not None and int(declared) != 6:
            out.append(finding("R2-ranks",
                               "%s (family %d) declares unlocked_ranks %s but builds 6 rank rows"
                               % (spec.get("name", "?"), family, declared),
                               family=family, unlocked_ranks=declared))
        if not face_colours(mod_dir, family):
            # a warning, not an error: a class without a face picture cannot crash the Recruiter
            # (colour 0 is the documented fallback); the source-pack validators gate on it anyway.
            out.append(finding("R3-face", "%s (family %d) ships no face_%d.png"
                               % (spec.get("name", "?"), family, family), severity="warning",
                               family=family))
        # R9: the description the wheel shows is copied into a 0x100-byte field with no bound (see the
        # module docstring).  255 bytes is the room; the writer also truncates, this refuses the pack.
        desc = spec.get("hire_desc") or ""
        n = len(desc.encode("utf-8"))
        if n > DESC_MAX:
            out.append(finding("R9-desc-length",
                               "%s (family %d): the one-line description is %d bytes; the menu copies it "
                               "into a 0x100-byte field with no bound, so %d bytes would land on the "
                               "fields after it (+0x1d2c dirty byte, +0x1d30/0x1d34, +0x1d38 list pane)"
                               % (spec.get("name", "?"), family, n, n - DESC_MAX),
                               family=family, bytes=n, max=DESC_MAX))
    # R4 / R5: quest rewards and row ownership
    for q in quests(mod_dir):
        if int(q.get("reward_type", -1)) != REWARD_RECRUIT:
            continue
        value = int(q.get("reward_value", -1))
        if value not in own_rows:
            out.append(finding("R4-quest-reward",
                               "quest %s rewards character row %d, which this mod does not add (own rows: %s)"
                               % (q.get("id"), value, sorted(own_rows)[:8]),
                               quest=int(q["id"]), reward_value=value, own_rows=sorted(own_rows)))
    for cid in sorted(own_rows):
        if vanilla_char_ids is not None and cid in vanilla_char_ids and cid not in dummy_rows:
            out.append(finding("R5-vanilla-row",
                               "char row %d is a vanilla character row, not a dummy row: the patch cannot win"
                               % cid, row=cid))
        if cid in foreign and foreign[cid] != owner:
            out.append(finding("R5-foreign-row",
                               "char row %d is already added by %s" % (cid, foreign[cid]),
                               row=cid, owner=foreign[cid]))
    # R6: a registry identity is one rank whose art is keyed to a leased low physical row.  The class id is
    # also the char.dat row id (the game finds a class's row by id, char_find_by_id 0x140061f80), so both
    # must agree; ranks 1-5 of the identity must stay unused and the colour id must be the physical row or
    # the sprite/portrait/face keys of the lease would never be read.
    declared = {int(d["identity"]): d for d in registry_uniques(mod_dir)}
    rows_by_id = char_rows(mod_dir)
    for identity, doc in sorted(declared.items()):
        physical = doc.get("physical")
        row = rows_by_id.get(identity)
        if row is None:
            out.append(finding("R6-unique-row",
                               "unique identity %d is declared but the mod adds no char.dat row for it; the "
                               "game finds a class's row by its id" % identity, identity=identity))
            continue
        if doc.get("shares_art_with"):
            # D4-NPC1: a shared-art character draws with another pack's keyed art; it ships no bank,
            # face or portrait of its own, so the low-lease rule and the colour==physical rule do not apply.
            if int(row["sprite_id"]) != int(doc.get("sprite_id", row["sprite_id"])) or \
                    int(row["color_id"]) != int(doc.get("color_id", row["color_id"])):
                out.append(finding("R6-unique-lease",
                                   "unique identity %d shares art with %s but its row does not use the declared "
                                   "sprite/colour keys" % (identity, doc["shares_art_with"]), identity=identity))
            continue
        if not isinstance(physical, int) or not 10 <= physical < 1000:
            out.append(finding("R6-unique-lease",
                               "unique identity %d leases physical %r; a unique's art keys need a low row (10..999)"
                               % (identity, physical), identity=identity, physical=physical))
            continue
        if int(row["sprite_id"]) != physical or int(row["color_id"]) != physical:
            out.append(finding("R6-unique-lease",
                               "unique identity %d row has sprite %d / colour %d, not the leased physical %d"
                               % (identity, row["sprite_id"], row["color_id"], physical),
                               identity=identity, physical=physical, sprite=int(row["sprite_id"]),
                               color_id=int(row["color_id"])))
        strays = [r for r in range(identity + 1, identity + 6) if r in own_rows]
        if strays:
            out.append(finding("R6-unique-ranks",
                               "unique identity %d is one rank but the mod also adds %s"
                               % (identity, strays), identity=identity, rows=strays))
    families = {int(s["family"]) for s in class_specs(mod_dir)}
    overlord_band = overlord_row_band(mod_dir)
    for cid in sorted(rows_by_id):
        if cid < 10000 or cid in declared:
            continue
        if cid // 10 * 10 in families:          # a class family's own rank row
            continue
        if overlord_band and overlord_band[0] <= cid <= overlord_band[1]:
            # Overlord's own conversion: the row is an allocation the ownership manifest already gives
            # him (20000-20500), not one of our registry identities, and its art travels with his
            # visual pack rather than as a leased low row.  Recorded, not silently dropped.
            out.append(finding("R6-unique-row",
                               "char row %d is in the Overlord band %d-%d this pack declares "
                               "(overlord_package): his allocation, not a Kit registry identity"
                               % (cid, overlord_band[0], overlord_band[1]),
                               severity="warning", row=cid))
            continue
        out.append(finding("R6-unique-row",
                           "char row %d is >= 10000 but is neither a declared unique identity nor a class "
                           "family rank (a registry unique declares patches/characters/unique.json)" % cid,
                           row=cid))
    # R7 / R8: what the description panel is asked to draw.
    out.extend(text_findings(mod_dir))
    out.extend(help_link_findings(mod_dir, vanilla_help_ids))
    return out


def errors(findings):
    return [f for f in findings if f["severity"] == "error"]


def gate(findings):
    """What a *pack* gate refuses: every error plus a class that ships no face picture."""
    return [f for f in findings if f["severity"] == "error" or f["rule"] == "R3-face"]


def check_or_raise(mod_dir, **kwargs):
    found = errors(check(mod_dir, **kwargs))
    if found:
        raise ValueError("Class identity rules failed: " + json.dumps(found, sort_keys=True))
    return True
