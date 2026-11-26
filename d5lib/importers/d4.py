"""Disgaea 4 Complete+ (PC) importer for the shared import runner (SOURCEPREP4-D4).

Every game input comes from the user's prepared source folder (`_d4_source`, SOURCEPREP2), verified
against the prep manifest; ids and rules come from the checked-in `d4-*.json` data files; game text
in those files is a SHA-256 reference resolved from the same source and the user's own Disgaea 5
tables at build time.  The importer contains no machine path and, on its default path, reads no
installed pack: an installed comparison is the explicit `--installed-reference` / `--compare-installed`.

* classes — every D4 class family the reviewed allocation lists (`d4-allocation.json`: source family,
  registry family, name reference, sprite lease, template, kind).
* uniques — every leased `D4_Unique_*` pack, plus a **source census** of D4's named characters read
  from `char.dat` (id < 1000, written to `unique-census.json` beside results.json).  Which census rows
  are in scope follows the lease file (DECISIONS 2026-11-03).

Builders wrapped (nothing is reimplemented):

* classes — `tools/build_source_pack.py` → `d5lib.sourceimports.build_d4_pilot`, with the later passes
  the installed packs carry: packed class-mastery declaration (`--mastery --mastery-mode packed`) and
  the reviewed exact-evility emission (`--engine-exact` → `d5lib.d4exact`).
* uniques — `tools/build_d4_unique.py` → `d5lib.d4unique.build_import`, replayed from the recorded
  command data (`d4-unique-commands.json`; latest lane wins: d4uniq3 > d4uniq2 > d4uniq > breadth).
* voices — the VOICES2 recipe: `d4voices.import_d4_voice` for EN and JP with its evidence-bound
  D4-category → D5-situation role map.
* prepared art — regenerated on every build from the verified `ANM_HI.dat` by `_d4_source` (Character
  Forge art code resolved through `D5_D4_FORGE`), into the build scratch.  Face and cut-in PNGs are
  the character's own D4 screen art, extracted from the same source by `d5lib.d4screenart`.

Everything is offline: the D5 game and the prepared source copy are read-only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from .. import d4screenart, gamefs
from ..importcore import Entry, Result
from . import _d4_source, _d4_specials

WORKTREE = Path(__file__).resolve().parents[2]
# The child builders run with the interpreter that runs this importer (no machine-specific path).
PY = Path(sys.executable)
LEASE_FILE = Path(__file__).with_name("d4-leases.json")
SCOPE_FILE = Path(__file__).with_name("d4-scope.json")
# MODORG1 / DECISIONS 2026-11-03: 510 Rutile and 520 Stella are parked - Overlord's versions win.
# Their mod ids still exist on disk (the installed copy stays), so the importer must not rebuild them
# and must not let them claim art rows 393/396 that u350/u360 own.
PARKED = {"D4_Unique_510": "parked: Overlord's Rutile wins (MODORG1, DECISIONS 2026-11-03)",
          "D4_Unique_520": "parked: Overlord's Stella wins (MODORG1, DECISIONS 2026-11-03)"}

# tools/build_voices2_pack.py ROLE_MAP: D4 source category -> D5 (kind, situations), evidence in
# docs/VOICES2.md.  Kept here so the runner does not import a tools/ script.
VOICE_ROLES = {
    0: [dict(kind=0, cats=[0])], 2: [dict(kind=0, cats=[4])], 4: [dict(kind=0, cats=[9])],
    5: [dict(kind=0, cats=[10])], 6: [dict(kind=0, cats=[11])], 7: [dict(kind=0, cats=[13])],
    1: [dict(kind=0, cats=[1, 2])], 3: [dict(kind=0, cats=[6])],
}
VOICE_ID = 9000

# D4GAP1: the checkpoint's sprite lease for 2190 Rifle Demon (2620) is on vanilla ground: the game's own archive
# has anm02622 (used_ids gate: "vanilla: anm 2622").  Moved to the first monster family free against vanilla, every
# lease, the live kit, the holding folder and today's builds (tools/d4gap1_leases.py; free: 2840-2890).
SPRITE_FAMILY_OVERRIDE = {2190: 2840}

CLASS_NAMES_FALLBACK = {}                          # filled from the checkpoint
# Classes whose D4 row carries more than the default three personality variants; the recorded
# breadth command chose the first three explicitly (`d4-breadth/scripts/build_batch.py` PERSONALITY).
PERSONALITY_VARIANTS = {1220: (0, 1, 2)}            # Prism Ranger: six source variants


def _clean_env():
    return {k: v for k, v in os.environ.items()
            if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX")}


def _run(cmd, log_path, cwd=None, files=None):
    """Run a child builder.  With a verified prepared set, the child gets the set's description in
    ``D5_D4_VERIFIED_SET`` so its own D4 reads go through the same manifest-checked file list."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = _clean_env()
    if files is not None and files.prepared:
        files.verify()
        config = log_path.parent / "verified-d4-set.json"
        config.write_text(json.dumps(files.to_config(), indent=1) + "\n")
        env["D5_D4_VERIFIED_SET"] = str(config)
    with log_path.open("w") as f:
        f.write(json.dumps([str(c) for c in cmd], indent=1) + "\n\n")
        f.flush()
        proc = subprocess.run([str(c) for c in cmd], cwd=str(cwd or WORKTREE), stdout=f,
                              stderr=subprocess.STDOUT, env=env)
    return proc.returncode


def _sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# D4 own animation tracks (ANIM / ANIMALL / ANIMALL2, 2026-10-29) and PT1030ANIM's bank rules
# (2026-10-30) were applied to the shipped packs *after* their build, so every held D4 class and
# unique bank carries D4's own body textures and tracks, not the donor-track build (D4-FIX2:
# 2 vs 9 textures, 4 vs 5).  The importer now runs that pass itself.  Two packs keep donor tracks on
# purpose: D4's own files for Toro and Kuro hold 7 motions, 58 of the donor's 65 have no source
# (playtest/ANIMALL2-REPORT.md section 4).  D4-TRACKS1: the rule is the source body's own motion
# count, not a list.  Monster bodies (body_type 1) carry their whole set: 62-83 motions for every
# full figure (God's Part 62, Pringer X 65, Prinny Kurtis 83), 7 for Toro/Kuro, 3 for Politan
# (stand front/back only).  Nothing lies between 7 and 62, so any count under 20 is a cut-down
# figure and keeps the donor's tracks.  Humanoid bodies hold 3-11 motions because D4's shared block
# (anm00001) supplies the rest; the merge covers them, so the rule never applies to them.
DONOR_TRACK_MOTIONS = 20
# D4-PAL1: shipped uniques whose D4 colour bank is not 0 (d4unique.d4_bank: color_id % 10), for the
# compare reason only; the build itself reads the bank from the source.
PALETTE_SWAPS = {180: 4, 220: 4, 230: 8}
# held palette-header shape of the donor-track packs: Toro/Kuro 10 (see _trim_palettes)
HELD_DONOR_BANKS = {"D4_Unique_240", "D4_Unique_250"}


def donor_tracks(data, sid):
    """True when the D4 unique `sid` keeps the donor's tracks (a monster body under 20 motions)."""
    row = data.chars[sid]
    return (row["body_type"] == 1 and
            len(data.anm(row["sprite"]).blocks[0].animations) < DONOR_TRACK_MOTIONS)
# PT1030ANIM item 4: the D4 three-part composed figure (Death) paints body -> weapon -> hands.
PART_ORDER = {"D4_Class_2120", "D4_Unique_170"}
# D4IDLE1: DEATH2's duplicate rule keeps a part whose removal changes the finished picture by more than
# this fraction of its opaque pixels (measured: Death's hands strip 706 px of ~20k changes the shaft).
DUPLICATE_COMPOSITE_TOL = 0.002


def load_leases():
    """The recorded allocation: {mod_id: {...}} plus the parked list (read, never recomputed)."""
    doc = json.loads(LEASE_FILE.read_text())
    by_mod = {c["mod"]: dict(c, parked=False) for c in doc["characters"].values()}
    for mod_id, why in (doc.get("parked") or {}).items():
        by_mod[mod_id] = dict(mod=mod_id, parked=True, why=why)
    return doc, by_mod


def load_scope():
    """D4-ROSTER1: {source_family: {in_scope, why_not, ...}} built by tools/build_d4_scope.py."""
    return {k: v for k, v in json.loads(SCOPE_FILE.read_text()).items() if not k.startswith("_")}


def load_npc_rows():
    """D4-NPC1 rows (TARGET-ROSTER characters with no lease): listed, out of scope."""
    return json.loads(SCOPE_FILE.read_text())["_npcs"]


ART_MARKER = ".d5-d4-screen-art-cache"
_ART = {"dir": None, "owned": False}
_ART_LOCK = threading.Lock()


def claim_art_dir(output_root):
    """Choose the face / cut-in folder of this run and make sure the importer may write into it.

    A folder the user names (``D5_D4_SCREEN_ART`` / the ``d4_screen_art`` setting) is theirs and is used as
    given.  Otherwise the importer owns ``<output>/screen-art``: it is created here with a marker, it is never
    inside the prepared source folder (a file that merely sits there must not win), a symlink or a non-empty
    folder without our marker is refused, nothing in it is ever deleted, and every PNG is used only when this
    folder's receipt records its SHA-256 (``d4screenart.ensure(verified=True)``)."""
    with _ART_LOCK:
        chosen = d4screenart.explicit_art_dir()
        if chosen is not None:
            _ART.update(dir=chosen, owned=False)
            return chosen
        folder = Path(output_root) / "screen-art"
        if folder.is_symlink():
            raise _d4_source.D4SourceError(f"D4 screen-art folder {folder} is a symlink; refusing to use it")
        if folder.exists():
            if not folder.is_dir():
                raise _d4_source.D4SourceError(f"D4 screen-art path {folder} is not a folder")
            if not (folder / ART_MARKER).is_file() and any(folder.iterdir()):
                raise _d4_source.D4SourceError(
                    f"D4 screen-art folder {folder} is not empty and is not an importer cache; refusing to "
                    "write into it (remove it or choose another output folder)")
        folder.mkdir(parents=True, exist_ok=True)
        marker = folder / ART_MARKER
        if not marker.is_file():
            marker.write_text("d5 D4 importer screen-art cache; written by the build, never read unverified\n")
        _ART.update(dir=folder, owned=True)
        return folder


def art_dir():
    """The extracted D4 face / cut-in folder in use (the folder `claim_art_dir` chose for this run)."""
    return _ART["dir"] or d4screenart.screen_art_dir()


def screen_art(sid):
    """`(face, cut-in)` PNGs of resource id `sid` in the active art folder; names from `d4screenart`.

    Both id widths use the same zero padding (`swf0070.png` for cast 70, `swf1220.png` for class 1220)."""
    face, cutin = d4screenart.art_paths(sid, art_dir())
    missing = [str(p) for p in (face, cutin) if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            "D4 face/cut-in art missing: " + ", ".join(missing) + ". Extract it from your own D4 files with "
            f"`python tools/d4_extract_screen_art.py <Disgaea 4 Complete+ folder> {art_dir()}`.")
    return face, cutin


def ensure_art(face_ids, cutin_ids, source, label="face/cut-in"):
    """Extract the requested ids the art folder lacks, from the same D4 source copy the build reads.

    The class builder reads the face run `swf<sid> .. swf<sid+9>` (`sourceimports.colour_variants`); the extractor
    only writes the ids it is given, so a partially extracted folder would silently lose the recoloured faces.
    The face and cut-in requests stay separate all the way through `d4screenart.ensure`: filling a class's
    colour-variant faces must not ask for cut-ins the class never reads.  The FULL requests are handed over,
    never a pre-pruned list: `ensure` also owns the receipt check, so a retry after a failed manifest publish
    finds the PNGs present, records them in the merged receipt, and does not extract them again.  Returns a
    note for the build result, or None when nothing had to be done."""
    folder = art_dir()
    if d4screenart.is_legacy(folder):
        return None                       # never write into the October extraction; it is an archive
    face_ids = [int(i) for i in face_ids or []]
    cutin_ids = [int(i) for i in cutin_ids or []]
    need = sorted(set(face_ids) | set(cutin_ids))
    try:
        written = d4screenart.ensure(game=source, folder=folder, face_ids=face_ids, cutin_ids=cutin_ids,
                                     verified=_ART["owned"] and folder == _ART["dir"])
    except (FileNotFoundError, OSError, ValueError) as exc:
        return (f"{label} art {need} missing from {folder} and not extracted "
                f"({type(exc).__name__}: {exc})")
    if written:
        return f"extracted {label} art {written} into {folder}"
    return None




class Importer:
    game = "d4"

    # ------------------------------------------------------------------ verified source
    def source(self, source_root=None):
        """The verified D4 source set, resolved once per importer instance.

        ``source_root`` is the explicit diagnostic route (the D4 install folder, unverified);
        without it the SOURCEPREP2 prepared folder and its manifest are used."""
        key = str(source_root) if source_root else None
        cache = getattr(self, "_source_cache", None)
        if cache is None or cache[0] != key:
            cache = (key, _d4_source.data_dir(source_root))
            self._source_cache = cache
            self._pool = None
            self._fs_cache = None
        return cache[1]

    def pool(self, files, fs=None):
        """The game-text pool for this run (D4 source tables, plus D5 tables when ``fs`` is given)."""
        cached = getattr(self, "_pool", None)
        if cached is None or (fs is not None and cached[0] is not fs):
            cached = (fs, _d4_source.text_pool(files, fs))
            self._pool = cached
            self._resolved_cache = {}
            self._overlay_cache = None
        return cached[1]

    def resolved(self, key, factory, pool):
        """A rule document with its game-text references resolved (once per run)."""
        cache = getattr(self, "_resolved_cache", None)
        if cache is None:
            cache = self._resolved_cache = {}
        if key not in cache:
            cache[key] = pool.resolve_doc(factory())
        return cache[key]

    def _rule_file(self, name, factory, out_dir, pool):
        """Write a resolved rule document to the build scratch and return its path.

        The child builders read plain JSON paths; the refs are resolved here, so no game text is in
        the kit and the scratch file is the one input they see."""
        doc = self.resolved(name, factory, pool)
        path = Path(out_dir) / f"{name}.json"
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding='utf-8')   # never reuse a stale file
        return path

    @staticmethod
    def _fs(ctx):
        """The D5 base tables through the kit's own backup index (read-only, no Installer)."""
        fs = ctx.get("_fs") if ctx else None
        if fs is None:
            from .dd2 import original_fs
            fs = original_fs(ctx)
            if ctx is not None:
                ctx["_fs"] = fs
        return fs

    # ------------------------------------------------------------------ roster
    def roster(self, source_root=None):
        cached = getattr(self, "_roster_cache", None)
        if cached is not None:
            return list(cached)
        files = self.source(source_root)
        pool = self.pool(files)
        plan = _d4_source.allocation()
        rows = [f for f in plan["families"] if f.get("registry_family")]
        scope = load_scope()
        entries = []
        sha = _sha(files.path(_d4_source.DATABASE_EN))
        for f in rows:
            sid = int(f["source_family"])
            folder = f"D4_Class_{sid}"
            sc = scope[str(sid)]
            entries.append(Entry(
                id=f"d4:{sid}", kind="class", name=pool.resolve(f["name"]), mod_folder=folder,
                source_ref=dict(file=_d4_source.DATABASE_EN, row=sid,
                                registry="D5-Classes-by-Game.xlsx#Disgaea 4",
                                registry_family=f["registry_family"],
                                sprite_family=SPRITE_FAMILY_OVERRIDE.get(sid, f["sprite_family"]),
                                template=f["template"], kind=f["kind"], sha256=sha),
                in_scope=sc["in_scope"], why_not=sc["why_not"],
                detail=dict(scope_note=sc["note"], id_status=sc["id_status"])))
        # D4-ROSTER1: membership is the lease file (every leased character, plus the parked pair),
        # never the installed folders; `shipped` is a compare-only flag in detail.
        census = {row["id"]: row for row in self.unique_census(source_root)}
        _doc, leases = load_leases()
        for mod_id, lease in sorted(leases.items(), key=lambda kv: int(kv[0].rsplit("_", 1)[1])):
            uid = int(mod_id.rsplit("_", 1)[1])
            row = census.get(uid) or {}
            entries.append(Entry(
                id=f"d4:u{uid}", kind="unique", name=row.get("name") or pool.resolve(lease.get("name")) or mod_id,
                mod_folder=mod_id,
                source_ref=dict(file=_d4_source.DATABASE_EN, row=uid,
                                sha256=row.get("sha256") or sha,
                                kind_gender=row.get("kind_gender")),
                in_scope=not lease.get("parked"),
                why_not=lease.get("why") or "",
                detail=dict(shipped=bool(row.get("shipped")))))
        for mod_id, npc in load_npc_rows().items():
            if mod_id in leases:                      # D4GAP1: leased NPCs are built (the loop above)
                continue
            entries.append(Entry(
                id=f"d4:u{mod_id.rsplit('_', 1)[1]}", kind="unique", name=pool.resolve(npc["name"]), mod_folder=mod_id,
                source_ref=dict(file=_d4_source.DATABASE_EN, row=int(npc["row"]), sha256=sha),
                in_scope=False, why_not=self.npc_twin(source_root, int(npc["row"]), mod_id) or npc["why_not"],
                detail=dict(shipped=False)))
        self._roster_cache = list(entries)
        return entries

    def npc_twin(self, source, cid, mod_id=""):
        """D4GAP1 rule: why an NPC row adds no appearance, or "" when it does (-> it needs its own lease).

        The look of a D4 character is its body (`sprite`) in one of the body's colour banks
        (`color_id % 10`).  A row that wears (a) the body and bank of a leased unique, or (b) a class body
        in that class's own bank, is the same picture as a character or class the Kit already carries;
        a new art window would hold a copy.  Rows in another bank (Psylos, the Guardians) are new looks."""
        data = self.source(source).data("EN")
        row = data.chars[cid]
        look = (row["sprite"], row["color_id"] % 10)
        _doc, leases = load_leases()
        for other, lease in sorted(leases.items()):
            oid = int(other.rsplit("_", 1)[1])
            orow = data.chars.get(oid)
            if other == mod_id or lease.get("parked") or not orow:
                continue
            if (orow["sprite"], orow["color_id"] % 10) == look:
                return (f"same look as {other} ({(orow.get('name') or '').strip()}): body {look[0]}, colour bank "
                        f"{look[1]} (D4-KG1 appearance rule; no new art window for a copy)")
        scope = load_scope().get(str(row["sprite"]))
        crow = data.chars.get(row["sprite"])
        if scope and scope.get("status_vs_d5") == "In D5ModKit" and scope.get("in_scope") is False:
            # D4-NPC1: an owner the Kit reserves but ships no art pack for is no look to share either;
            # the row's own `why_not` says so instead of claiming a twin that does not exist.
            return ""
        if scope and crow and crow["color_id"] % 10 == look[1]:
            who = (f"built as D4_Class_{row['sprite']}" if scope["in_scope"]
                   else f"the D5-native class ({scope['why_not']})")
            return (f"same look as class {self.pool(self.source(source)).resolve(scope['name'])}: body {look[0]}, its own colour bank {look[1]} - {who} "
                    "(D4-KG1 appearance rule; no new art window for a copy)")
        return ""

    def unique_census(self, source):
        """Every D4 named character row (id < 1000) from char.dat, with our shipped set marked."""
        files = self.source(source)
        data = files.data("EN")
        digest = _sha(files.path(_d4_source.DATABASE_EN))
        _doc, leases = load_leases()
        # The shipped set is the recorded lease file (D4-ROSTER1): never a listing of installed packs.
        shipped = {int(mod.rsplit("_", 1)[1]) for mod in leases}
        out = []
        for cid in sorted(data.chars):
            if cid >= 1000 or cid <= 0:
                continue
            row = data.chars[cid]
            name = (row.get("name") or "").strip()
            if not name or name.startswith("ダミー") or name == "Dummy":
                continue
            story = self._story_form(data, cid)
            out.append(dict(id=cid, name=name, title=row.get("title", ""),
                            kind_gender=row.get("kind_gender"), body=row.get("body"),
                            voice_group_base=row.get("voice_group_base"),
                            sha256=digest, shipped=cid in shipped, story_form=bool(story),
                            in_scope=(f"D4_Unique_{cid}" in leases and not leases[f"D4_Unique_{cid}"].get("parked")),
                            why_not=(PARKED.get(f"D4_Unique_{cid}", "") if f"D4_Unique_{cid}" in leases else
                                     f"story-form: {story}" if story else
                                     "not in the shipped 2026-10 selection; appearance-only "
                                     "candidate (DECISIONS 2026-11-03)")))
        try:
            target = Path(os.environ.get("D5_IMPORT_OUT", "")).resolve() if os.environ.get("D5_IMPORT_OUT") else None
            if target and target.is_dir():
                (target / "unique-census.json").write_text(json.dumps(out, indent=1) + "\n")
        except OSError:
            pass
        return out

    @staticmethod
    def _story_form(data, cid):
        """D4-KG1 (review F7): why a named row is a story-only form, or "" for a real candidate.

        930-980 are the WF forms (kind_gender 13, sprite 9000: no body of their own); a row that
        wears another named row's body in that row's own colour bank (990 Genjuro = Valvatorez's
        body 10) adds no appearance either."""
        row = data.chars[cid]
        if row["sprite"] >= 9000 or row.get("kind_gender") == 13:
            return f"kind_gender {row.get('kind_gender')}, sprite {row['sprite']} (no body of its own)"
        owner = data.chars.get(row["sprite"])
        if (row["sprite"] != cid and 0 < row["sprite"] < 1000 and owner is not None
                and row["color_id"] % 10 == owner["color_id"] % 10):
            return f"wears {(owner.get('name') or '').strip() or row['sprite']}'s body {row['sprite']} unchanged"
        return ""

    # ------------------------------------------------------------------ build
    def build(self, entry, out_dir, ctx):
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        files = self.source(ctx.get("source_root"))
        claim_art_dir(ctx["output_root"])
        options = dict(ctx.get("options") or {})
        if entry.kind == "class":
            result = self._build_class(entry, out_dir, files, ctx)
        else:
            result = self._build_unique(entry, out_dir, files, ctx)
        return result

    def _spec(self, entry):
        by = {int(f["source_family"]): f for f in _d4_source.allocation()["families"]
              if f.get("registry_family")}
        return by[int(entry.source_ref["row"])]

    def _hold_blank_keys(self, entry, built, options=None):
        """REPROFIX3: BLANKKEYS1's held pose on the motion banks, as a build pass.

        With an installed reference the installed pack of the same name decides which animation ids
        are held; on the default path the ids recorded in ``held-blank-keys.json`` are held instead
        (REPROFIX3 (e)), so no installed pack is read.  The rule is shared with the D1C/DD2 importers
        (``d5lib/holdblank.py``); labelled APPROXIMATION.  -> (held, source)"""
        from d5lib import holdblank
        installed = None
        if (options or {}).get("installed_reference"):
            from d5lib import offlinepaths
            path = Path(offlinepaths.installed_mods_root()) / entry.mod_folder
            installed = path if path.is_dir() else None
        info = {}
        held = holdblank.hold_pack(
            built, installed,
            holdblank.reference_ids('d4', entry.mod_folder), log=lambda _s: None, info=info)
        return held, info.get('source')

    @staticmethod
    def _hold_note(held, source):
        if not held:
            return None
        return ('blank key times held (BLANKKEYS1 rule, labelled approximation, '
                + ('installed reference' if source == 'installed'
                   else 'held-blank-keys.json: no installed pack')
                + '): ' + ', '.join(f'{b} {sorted(ids)}' for b, ids in held.items()))

    def _build_class(self, entry, out_dir, files, ctx):
        options = dict(ctx.get("options") or {})
        source = files.root
        sid = int(entry.source_ref["row"])
        spec = self._spec(entry)
        work = out_dir / "build"
        # D4-KG1 (review F9): the class path's donor kind must match every source rank row's body
        # type, as plan_import requires of a unique's donor (build_d4_pilot only checks the range).
        data = files.data("EN")
        wrong = [sid + k for k in range(6) if sid + k in data.chars and
                 data.chars[sid + k]["body_type"] != (1 if spec["kind"] == "monster" else 0)]
        if wrong:
            result = Result(id=entry.id, mod_folder=entry.mod_folder)
            result.error = (f"source body_type differs from the donor kind {spec['kind']!r} "
                            f"(template {spec['template']}) for row(s) {wrong}")
            return result
        pool = self.pool(files, self._fs(ctx))
        name = pool.resolve(spec["name"])
        mapping_path = self._rule_file('mapping', _d4_source.mapping, out_dir, pool)
        emission_path = self._rule_file('emission', lambda: _d4_source.emission(False), out_dir, pool)
        reserved = work_reserved = out_dir / "reserved-ids.json"
        work_reserved.write_text(json.dumps(_d4_source.reserved(sid), indent=1) + "\n")
        (out_dir / "no-installed-mods").mkdir(parents=True, exist_ok=True)
        # The class builder reads both runs for all ten colours: faces via `colour_variants(face_path, body)` and
        # cut-ins via `colour_variants(cutin_path, 10000 + body)` (`sourceimports.py`).  Both are requested
        # explicitly here, as two separate kinds, so neither drags along anything the class does not read.
        # D4FACE1 (``d4_face_rule``, default on): the game draws the class face (swf<sid>) for every rank row
        # (D4-FACE-02), so only that face is requested; the cut-ins stay per colour (D4-CUT-01).
        face_rule = options.get("d4_face_rule", True)
        art_note = ensure_art([sid] if face_rule else d4screenart.family_ids(sid), d4screenart.family_ids(sid), files,
                              "class face and colour-variant cut-in" if face_rule else "colour-variant face and cut-in")
        try:
            face_path, cutin_path = screen_art(sid)
        except FileNotFoundError as exc:
            result = Result(id=entry.id, mod_folder=entry.mod_folder)
            result.error = str(exc)
            return result
        try:
            prepared, library = _d4_source.class_art(files, sid, name, out_dir / "art")
        except _d4_source.D4SourceError as exc:
            result = Result(id=entry.id, mod_folder=entry.mod_folder)
            result.error = str(exc)
            return result
        cmd = [PY, WORKTREE / "tools/build_source_pack.py",
               "--prepared-root", prepared,
               "--library-root", library,
               "--source-archive", files.path(_d4_source.DATABASE_EN),
               "--game-path", ctx["game_path"], "--original-state", ctx["state_root"],
               "--face-path", face_path, "--cutin-path", cutin_path,
               "--family", spec["registry_family"],
               "--sprite-family", str(SPRITE_FAMILY_OVERRIDE.get(sid, spec["sprite_family"])),
               "--kind", spec["kind"], "--template", spec["template"],
               "--supported-families", spec["registry_family"],
               "--source-ids", *[str(sid + k) for k in range(6)],
               "--edition", "Disgaea 4 Complete+ PC EN", "--d4-root", source,
               "--mapping", mapping_path, "--reserved-ids", reserved,
               "--class-name", name + " (D4)",
               "--mod-id", entry.mod_folder, "--unlocked-ranks", "6",
               "--engine-exact", emission_path, "--finalize", "--approximate-palettes",
               "--exact-mods-root", (out_dir / "no-installed-mods"),
               "--mastery", "--mastery-mode", "packed",
               "--output-path", work]
        if not face_rule:
            cmd += ["--face-per-colour"]
        if sid in PERSONALITY_VARIANTS:
            cmd += ["--personality-variants", *[str(v) for v in PERSONALITY_VARIANTS[sid]]]
        rc = _run(cmd, out_dir / "build.log", files=files)
        result = Result(id=entry.id, mod_folder=entry.mod_folder)
        built = work / "native-mods" / entry.mod_folder
        if rc or not built.is_dir():
            result.built = False
            result.error = f"build_source_pack rc={rc}"
            return result
        result.built = True
        notes = [art_note] if art_note else []
        if self._fix_charhelp(built):
            notes.append("QUICKFIX1 charhelp keys renamed")
        try:
            notes.append(self._own_tracks(entry, built, sid, data, options))
        except Exception as exc:                                # noqa: BLE001
            result.error = f"own-tracks pass failed: {type(exc).__name__}: {exc}"
        if (options or {}).get("d4_hold_blank", True):
            try:
                held, hsource = self._hold_blank_keys(entry, built, options)
                if held:
                    result.extra["hold_blank"] = held
                    result.extra["hold_blank_source"] = hsource
                    notes.append(self._hold_note(held, hsource))
            except Exception as exc:                            # noqa: BLE001
                notes.append(f"hold blank keys: {type(exc).__name__}: {exc}")
        try:
            notes.append(self._reviewed_evilities(entry, built, pool))
        except Exception as exc:                                # noqa: BLE001
            result.error = f"reviewed evilities failed: {type(exc).__name__}: {exc}"
        try:
            self._voices(built, sid, class_=True, files=files)
        except Exception as exc:                                # noqa: BLE001
            notes.append(f"voices: {type(exc).__name__}: {exc}")
        result.notes = notes
        result.features = self._features(built)
        return result

    @staticmethod
    def _npc_lease(sid):
        """The lease of a D4GAP1 NPC unique (`"npc": true`), else None."""
        _doc, leases = load_leases()
        lease = leases.get(f"D4_Unique_{sid}") or {}
        return lease if lease.get("npc") else None

    def _unique_command(self, sid):
        """The recorded semantic arguments of a unique (d4uniq3 > d4uniq2 > d4uniq > breadth)."""
        return _d4_source.command(sid)

    def _reserved_root(self, entry, out_dir, options):
        """Packs the builder must respect.

        Everything this run has already rebuilt is always included (those packs carry the renamed
        charhelp keys).  Installed packs are included only under an explicit installed reference: the
        default build reads none, and the recorded ids/leases pin what this pack writes."""
        root = Path(out_dir) / "reserved" / entry.mod_folder
        if root.is_dir():
            return root
        root.mkdir(parents=True, exist_ok=True)
        if (options or {}).get("installed_reference"):
            from d5lib import offlinepaths
            installed = Path(offlinepaths.installed_mods_root())
            built_dir = Path(out_dir).parents[1] / "mods"
            rebuilt = {x.name for x in built_dir.iterdir()} if built_dir.is_dir() else set()
            for src in sorted(installed.iterdir()):
                if src.name == entry.mod_folder or src.name in rebuilt or not (src / "mod.json").is_file():
                    continue
                if src.name in PARKED:
                    # The parked packs (510 Rutile, 520 Stella) are retired in favour of Overlord's
                    # versions, so their claims on rows 393/396 are released to u350/u360 (DECISIONS
                    # 2026-11-03 MODORG1).
                    continue
                try:
                    broken = "help1_" in (src / "patches/db/charhelp.dat.json").read_text()
                except OSError:
                    broken = False
                if broken:
                    continue
                os.symlink(src, root / src.name)
        built = Path(out_dir).parents[1] / "mods"
        if built.is_dir():
            for src in sorted(built.iterdir()):
                if src.name != entry.mod_folder and (src / "mod.json").is_file():
                    os.symlink(src, root / ("run-" + src.name))
        return root

    def overlay(self, pool):
        """The reviewed evility overlay with its game-text references resolved (once per run)."""
        cached = getattr(self, "_overlay_cache", None)
        if cached is None:
            cached = pool.resolve_doc(_d4_source.overlay())
            self._overlay_cache = cached
        return cached

    def _art_ids(self, sid, options=None):
        """The face / cut-in resource ids a unique reads (its recorded ones, else its row; NPCs: colour key).

        D4FACE1 (``d4_face_rule``, default on): an NPC row's FACE is the game's own face number for the row
        (D4-FACE-02: the colour key rounded down to tens, Chief 1154 -> swf1150), while its cut-in keeps the colour
        key (D4-CUT-01: 10000 + sprite + colour byte).  ``--no-d4-face-rule`` keeps the old key for both."""
        if self._npc_lease(sid):
            key = int(self.source().data("EN").chars[sid]["color_id"])
            face = (d4screenart.game_face_number(sid, key)
                    if (options or {}).get("d4_face_rule", True) else key)
            return [face], [key]
        row = _d4_source.commands().get(str(sid)) or {}
        return list(row.get("face_ids") or [sid]), list(row.get("cutin_ids") or [sid])

    @staticmethod
    def _fix_charhelp(mod):
        """QUICKFIX1: `help{1,2,3}_*` -> `line{1,2,3}_*` in a built mod's charhelp patch."""
        path = Path(mod) / "patches/db/charhelp.dat.json"
        if not path.is_file():
            return 0
        text = path.read_text()
        if "help1_" not in text:
            return 0
        fixed = re.sub(r'"help([123])_', r'"line\1_', text)
        path.write_text(fixed)
        return len(re.findall(r'"help[123]_', text))

    @staticmethod
    def _source_help_line3(built, data, sid):
        """D4-TEXT1: line 3 is D4's own player text (Weapon Forte / Magichange Type / a quip); the builder's
        "D4 skills/Evilities pending; see GAPS." overlay (d4unique) is replaced by the source line, as
        `sourceimports._d4_class_help` does for classes.  Returns the number of rows changed."""
        path = Path(built) / "patches/db/charhelp.dat.json"
        if not path.is_file():
            return 0
        sys.path.insert(0, str(WORKTREE))
        from d5lib import textfmt
        lines = list(data.help_lines(data.chars[sid]["help_id"]))   # the source's own line 3, not re-wrapped
        if len(lines) < 3 or not lines[2]:
            return 0
        doc = json.loads(path.read_text())
        n = 0
        for row in doc.get("added") or []:
            for key in [k for k in row if k.startswith("line3_")]:
                new = textfmt.prose(lines[2])
                if row[key] != new:
                    row[key], n = new, n + 1
        if n:
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        return n

    def _build_unique(self, entry, out_dir, files, ctx):
        options = dict(ctx.get("options") or {})
        data = files.data("EN")
        pool = self.pool(files, self._fs(ctx))
        sid = int(entry.source_ref["row"])
        mapping_path = self._rule_file('mapping', _d4_source.mapping, out_dir, pool)
        emission_path = self._rule_file('emission-cast', lambda: _d4_source.emission(True), out_dir, pool)
        _doc, leases = load_leases()
        lease = leases.get(entry.mod_folder) or {}
        result = Result(id=entry.id, mod_folder=entry.mod_folder)
        npc = self._npc_lease(sid)
        recorded = None
        art_note = None
        prepared = library = None
        work = out_dir / "build"
        if lease.get("share_art_with"):
            # D4-NPC1: a shared-art pack ships no art at all.
            args = ["--source-id", str(sid),
                    "--identity", str(lease["identity"]),
                    "--template-id", str(lease["template"]),
                    "--share-art-owner", lease["share_art_with"],
                    "--share-sprite", str(lease["share_sprite"]),
                    "--share-color", str(lease["share_color"])]
        else:
            if npc:
                identity, physical = npc["identity"], npc["physical"]
                template = npc["template"]
            else:
                recorded = self._unique_command(sid)
                if recorded is None:
                    result.error = f"no recorded build command for unique {sid}"
                    return result
                identity = lease.get("identity") or recorded.get("identity")
                physical = lease.get("physical") or recorded.get("physical")
                template = recorded.get("template_id")
            try:
                prepared, library = _d4_source.unique_art(
                    files, sid, out_dir / "art", v3=(recorded or {}).get("style") == "v3")
            except _d4_source.D4SourceError as exc:
                result.error = str(exc)
                return result
            face_ids, cutin_ids = self._art_ids(sid, options)
            frame = (recorded or {}).get("cutin_packet_frame")
            art_note = ensure_art(face_ids, [] if frame else cutin_ids, files, "face and cut-in")
            face_path = d4screenart.art_paths(face_ids[0], art_dir())[0]
            cutin_path = d4screenart.art_paths(cutin_ids[0] if cutin_ids else face_ids[0], art_dir())[1]
            if frame:
                # The lane recorded its own prepared packet's stand frame as this pack's cut-in (610).
                cutin_path = Path(prepared) / frame
            missing = [str(p) for p in (face_path, cutin_path) if not p.is_file()]
            if missing:
                result.error = ("D4 face/cut-in art missing: " + ", ".join(missing)
                                + ". Extract it from the prepared source with `python tools/d4_extract_screen_art.py`.")
                return result
            args = ["--source-id", str(sid)]
            if identity is not None:
                args += ["--identity", str(identity)]
            if physical is not None:
                args += ["--physical", str(physical)]
            if recorded and recorded.get("target_id") is not None:
                args += ["--target-id", str(recorded["target_id"])]
            args += ["--template-id", str(template),
                     "--prepared-root", str(prepared), "--library-root", str(library),
                     "--face-path", str(face_path), "--cutin-path", str(cutin_path)]
            for value in (recorded or {}).get("exclude_source_ids") or []:
                args += ["--exclude-source-id", str(value)]
            for value in (recorded or {}).get("supersede_prefix") or []:
                args += ["--supersede-prefix", str(value)]
        (out_dir / "no-installed-mods").mkdir(parents=True, exist_ok=True)
        args += ["--d4-root", str(files.root), "--game-path", str(ctx["game_path"]),
                 "--original-state", str(ctx["state_root"]), "--output-path", str(work),
                 "--mapping", str(mapping_path), "--engine-exact", str(emission_path),
                 "--mods-root", str(self._reserved_root(entry, out_dir, options)),
                 # recorded quest/slot/help ids (D4-FIX4): reproduce what a save was played with
                 "--storage-lease", str(LEASE_FILE)]
        cmd = [PY, WORKTREE / "tools/build_d4_unique.py"] + args
        rc = _run(cmd, out_dir / "build.log", files=files)
        result = Result(id=entry.id, mod_folder=entry.mod_folder)
        built = work / "native-mods" / entry.mod_folder
        if not built.is_dir():
            cands = list(work.glob("native-mods/*")) if work.is_dir() else []
            built = cands[0] if cands else built
        if rc or not built.is_dir():
            result.error = f"build_d4_unique rc={rc}"
            result.built = False
            return result
        result.built = True
        notes = [art_note] if art_note else []
        if self._fix_charhelp(built):
            notes.append("QUICKFIX1 charhelp keys renamed")
        try:
            if self._source_help_line3(built, data, int(sid)):
                notes.append("charhelp line 3 = D4's own help line (D4-TEXT1)")
        except Exception as exc:                                # noqa: BLE001
            result.error = f"charhelp line 3: {type(exc).__name__}: {exc}"
        # The recorded specials/voice/notes passes: the kit's copy of the lane scripts, ids from the lease.
        try:
            notes.extend(self._specials_pass(entry, built, work, sid, files, ctx, pool))
        except Exception as exc:                                # noqa: BLE001
            notes.append(f"specials pass: {type(exc).__name__}: {exc}")
            result.error = f"specials pass failed: {type(exc).__name__}: {exc}"
        try:
            notes.extend(self._magichange_pass(entry, built, ctx, pool=pool))
        except Exception as exc:                                # noqa: BLE001
            notes.append(f"magichange pass: {type(exc).__name__}: {exc}")
            result.error = f"magichange pass failed: {type(exc).__name__}: {exc}"
        try:
            notes.append(self._reviewed_evilities(entry, built, pool))
        except Exception as exc:                                # noqa: BLE001
            result.error = f"reviewed evilities failed: {type(exc).__name__}: {exc}"
        keep_donor = donor_tracks(data, sid)
        if lease.get("share_art_with"):
            notes.append("shared art: no bank, face, icon or portrait written (owned by "
                         + lease["share_art_with"] + ")")
        elif not self._trim_palettes(entry, built, sid, data, options or {}):
            notes.append("palette slots trimmed to D4's own bank count (D4 source header count)")
        if lease.get("share_art_with"):
            pass                                              # no bank to carry D4 tracks or palettes
        elif keep_donor and not options.get("d4_source_tracks", True):
            notes.append("donor tracks kept: the D4 body has fewer than "
                         f"{DONOR_TRACK_MOTIONS} motions (D4-TRACKS1)")
        else:
            try:
                notes.append(self._own_tracks(entry, built, sid, data, options, donor=keep_donor))
            except Exception as exc:                            # noqa: BLE001
                result.error = f"own-tracks pass failed: {type(exc).__name__}: {exc}"
        if not lease.get("share_art_with"):
            try:
                ok, why = self._palette_slot0(entry, built, sid, data)
            except Exception as exc:                            # noqa: BLE001
                ok, why = False, f"{type(exc).__name__}: {exc}"
            result.gates["palette_slot0"] = ok
            notes.append("palette slot 0: " + why)
        if not lease.get("share_art_with") and (options or {}).get("d4_hold_blank", True):
            # REPROFIX3: BLANKKEYS1's held pose after the own tracks (Politan 2077/3077/4017)
            try:
                held, hsource = self._hold_blank_keys(entry, built, options)
                if held:
                    result.extra["hold_blank"] = held
                    result.extra["hold_blank_source"] = hsource
                    notes.append(self._hold_note(held, hsource))
            except Exception as exc:                            # noqa: BLE001
                notes.append(f"hold blank keys: {type(exc).__name__}: {exc}")
        try:
            self._voices(built, sid, class_=False, files=files, lease=lease)
        except Exception as exc:                                # noqa: BLE001
            notes.append(f"voices: {type(exc).__name__}: {exc}")
        result.notes = notes
        result.features = self._features(built)
        return result

    # -------------------------------------------------------------- recorded passes
    def _reviewed_evilities(self, entry, built, pool):
        """The reviewed evility state (D4REV1-4 + PT1030DATA + CARRIERS2), recorded in
        `d4-evility-overlay.json` by `tools/build_d4_evility_overlay.py`: Skill rows, behaviors, alias
        maps and the char rows' evility links replace the builder's own emission (D4-FIX4).  The game
        text in the record is a SHA-256 reference resolved from the user's own tables."""
        st = self.overlay(pool)["mods"].get(entry.mod_folder)
        if not st:
            return "no reviewed evility record for " + entry.mod_folder
        built = Path(built)

        def put(rel, doc):
            path = built / rel
            if doc is None:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

        skill = built / "patches/db/Skill.dat.json"
        base = json.loads(skill.read_text()) if skill.is_file() else {"table": "Skill.dat"}
        if "skill_rows" in st:
            base["added"] = st["skill_rows"]
            put("patches/db/Skill.dat.json", base)
        else:
            put("patches/db/Skill.dat.json", None)
        put("patches/evilities/evilities.json", st.get("behaviors"))
        put("patches/evilities/aliases.json", st.get("aliases"))
        classes = sorted((built / "patches/classes").glob("class_*.json"))
        if classes and "class_alias" in st:
            cj = json.loads(classes[0].read_text())
            cj["evility_alias"] = st["class_alias"]
            classes[0].write_text(json.dumps(cj, indent=1, ensure_ascii=False) + "\n")
        chf = built / "patches/db/char.dat.json"
        links = st.get("char_links") or {}
        if chf.is_file() and links:
            ch = json.loads(chf.read_text())
            rows = {str(r["id"]): r for r in ch["added"]}
            if set(rows) != set(links):
                raise ValueError(f"char rows {sorted(rows)} != reviewed link rows {sorted(links)}")
            for cid, fields in links.items():
                rows[cid].update(fields)
            chf.write_text(json.dumps(ch, indent=1, ensure_ascii=False) + "\n")
        if st.get("requires"):          # EVILGAP1b: a referenced row's owner must load first
            mj = built / "mod.json"
            meta = json.loads(mj.read_text())
            meta["requires"] = list(st["requires"])
            mj.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
        if st.get("adaptations"):       # EVILGAP1: every adapted / D5-equivalent row is labelled in the pack
            mj = built / "mod.json"
            meta = json.loads(mj.read_text())
            lst = meta.setdefault("source_import", {}).setdefault("adaptations", [])
            # EVILCAP1: a reviewed label replaces an earlier line about the same evility ("evility <name> (<id>):"),
            # so a pack re-staged over an older build does not keep a superseded label next to the new one
            keys = {a.split(":", 1)[0] for a in st["adaptations"] if a.startswith("evility ")}
            lst[:] = [a for a in lst if a in st["adaptations"] or a.split(":", 1)[0] not in keys]
            lst += [a for a in st["adaptations"] if a not in lst]
            mj.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
        ids = sorted(int(r["id"]) for r in st.get("skill_rows", []))
        moved = Importer._pin_magic_ids(built, st.get("magic_ids") or [])
        return f"reviewed evility state applied: Skill rows {ids}" + (f"; magic ids {moved}" if moved else "")

    @staticmethod
    def _pin_magic_ids(built, held_ids):
        """Give the builder's adaptation magic rows (ids < 20000, first free id at build time) the held
        pack's ids: two builds that each took the lowest free id collided (u180/u190 13000, D4-FIX4)."""
        import re
        mg = Path(built) / "patches/db/magic.dat.json"
        if not held_ids or not mg.is_file():
            return {}
        have = sorted(int(r["id"]) for r in json.loads(mg.read_text()).get("added") or [] if int(r["id"]) < 20000)
        if len(have) != len(held_ids) or have == held_ids:
            return {}
        mapping = dict(zip(have, held_ids))
        pat = re.compile(r"(?<!\d)(%s)(?!\d)" % "|".join(str(k) for k in mapping))
        for rel in ("patches/db/magic.dat.json", "patches/skills/skills.json", "patches/db/char.dat.json"):
            path = Path(built) / rel
            if path.is_file():
                path.write_text(pat.sub(lambda m: str(mapping[int(m.group(1))]), path.read_text()))
        return mapping

    @staticmethod
    def _magichange_pass(entry, built, ctx=None, lease=None, pool=None):
        """The MAGICHANGE lane's rows (D4 monsters' Magichange attacks, D4-FIX5): `tools/magichange_rows.py`
        is the only writer and `magichange/magichange-content.json` the only content; the lease
        (`d4-leases.json` "magichange") pins which ids/names/levels the pack must come out with, and the
        pass refuses a drift instead of shipping different ids than a save was played with."""
        _doc, leases = load_leases()
        want = (lease if lease is not None else leases.get(entry.mod_folder) or {}).get("magichange")
        if not want:
            return []
        if _d4_source.has_refs(want):         # the lease names the pinned rows as game-text references
            pool = pool if pool is not None else _d4_source.text_pool_for_tools()
            want = pool.resolve_doc(want)
        import tempfile
        sys.path.insert(0, str(WORKTREE))
        from tools import magichange_rows
        built = Path(built)
        magic = None
        if ctx is not None:
            from d5lib import database, newclasses
            magic = database.load_table("magic.dat", Importer._fs(ctx).read(newclasses.MAGIC))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / entry.mod_folder).symlink_to(built)
            problems, report = magichange_rows.apply(tmp, magic_table=magic, write=True,
                                                     only={entry.mod_folder}, adaptation=False)
        if problems or len(report) != 1:
            raise ValueError(f"magichange writer: {problems or 'no content entry for ' + entry.mod_folder}")
        mg = {int(r["id"]): r for r in json.loads((built / "patches/db/magic.dat.json").read_text())["added"]}
        ch = json.loads((built / "patches/db/char.dat.json").read_text())["added"][0]
        learn = {int(ch[f"learn{k}_skill"]): int(ch[f"learn{k}_level"]) for k in range(1, 17) if ch[f"learn{k}_skill"]}
        for row in want:
            sid = int(row["d5_id"])
            got = (mg[sid]["name_EN"] if sid in mg else None, learn.get(sid))
            if got != (row["name"], row["level"]):      # reuse rows (name None) must not be emitted
                raise ValueError(f"magichange lease drift {entry.mod_folder} {sid}: lease "
                                 f"({row['name']!r}, lv {row['level']}) != build {got}")
        return [f"Magichange rows {[int(r['d5_id']) for r in want]} from the MAGICHANGE writer, pinned by the lease"]

    def _specials_pass(self, entry, built, work, sid, files, ctx, pool):
        """Specials, evilities, learn list and ability notes from the recorded passes."""
        doc, _leases = load_leases()
        receipt = work / "unique-receipt.json"
        receipts = {sid: json.loads(receipt.read_text())} if receipt.is_file() else {}
        notes = _d4_specials.apply({entry.mod_folder: built}, doc, receipts, files,
                                   self._fs(ctx), pool)
        out = ["specials/learn list restored from the recorded lease"]
        learn = (notes.get("learn") or {}).get(entry.mod_folder)
        if isinstance(learn, dict) and learn.get("rows"):
            out.append(f"learn list {learn['rows']} row(s)")
        if (Path(built) / "D4UNIQ3-ABILITY-NOTES.txt").is_file():
            out.append("D4UNIQ3 ability notes written")
        return out

    def _own_tracks(self, entry, built, sid, data, options=None, donor=False):
        """D4's own animation tracks on the two main banks (ANIMALL2 + PT1030ANIM), in place.

        Wraps the lanes' code, nothing reimplemented: `tools/animall2_convert.convert_new` merges
        the D4 body (and, for humanoids, D4's shared block), fills donor-only motion ids from its
        documented table, proves every source-authored motion pixel-identical to D4 and re-roots the
        wheel; `ownanim.duplicate_items` (DEATH2) blanks a part that paints no new ink;
        `tools/pt1030_bankfix.fix_bank` then puts 1001/1007 back to the native zero-length
        stub and, for Death, orders the composed parts.  Byte-identical to 10 of the 11 held class
        banks D4-BUILD1 rebuilt (1190 differs only by PT1029's orphaned copy of its idle tree).

        D4IDLE1 options (defaults on; ``--no-d4-...`` selects the old path):
        D4MESH1 option ``d4_mesh_nodes`` (default on, ``--no-d4-mesh-nodes`` = old path): D4's mesh nodes (node +4 = 1:
        Death, Hugo, Des X, Prinny Kurtis) keep their stored vertices (D5 node ``mesh`` = 1, D4-ANM-08) instead of
        being placed as pivoted rectangles.

        ``d4_stub_xform`` keeps D4's own idle stub 1001/1007 (it names 6001/6007 with D4's placement
        transform) instead of re-rooting it and rebuilding it at (0, 0); ``d4_death_game_view`` runs
        DEATH2's duplicate-part rule on the picture the game draws (render roots fixed, part order
        applied, removal must leave the finished picture unchanged), so Death/Hugo keep the scythe shaft
        between the hands; ``donor`` (``d4_source_tracks``, Toro/Kuro/Politan) takes D4's own stand, walk and
        hurt and holds the source stand picture for the states D4 never drew, keeping the palette header
        count.
        """
        opts = options or {}
        stub = opts.get("d4_stub_xform", True)
        game_view = opts.get("d4_death_game_view", True)
        sys.path.insert(0, str(WORKTREE))
        from d5lib import anm, d4source, ownanim
        from tools import animall2_convert, pt1030_bankfix
        built = Path(built)
        tmp = built.parent.parent / "own-tracks"
        if tmp.exists():
            shutil.rmtree(tmp)
        kind = "class" if entry.kind == "class" else "unique"
        receipt = animall2_convert.convert_new(built.name, kind, sid, built.parent, tmp, data, {},
                                               reroot=not stub, pad_palettes=True if donor else None,
                                               mesh_nodes=opts.get("d4_mesh_nodes", True))
        anime = Path("files/Anime/ANM_HI_JP.dat")
        bank = int(receipt["bank"])
        for number in (bank, bank + 1):
            # DEATH2 (2026-10-30) ran between ANIMALL2 and PT1030ANIM: blank a part item that paints
            # no new ink (Death/Hugo hands strip, Lady Samurai/Asuka/Vulcanus back views).
            sprite = anm.load(tmp / built.name / anime / f"anm{number:05d}.lzs")
            if game_view:
                # PART_ORDER is not applied: D4's own chain order already draws the scythe shaft in front of the
                # body and under the fists (Sean's 10-30 request); the reorder only made up for DEATH2 having
                # blanked the hands strip that carries that shaft (D4IDLE1 report, section 2)
                fixed, _log = pt1030_bankfix.fix_bank(sprite.to_bytes(), True, False, entry.mod_folder, "D4_", 2)
                ownanim.duplicate_items(fixed, game=True, composite_tol=DUPLICATE_COMPOSITE_TOL)
                (built / anime / f"anm{number:05d}.lzs").write_bytes(fixed.to_bytes())
                continue
            ownanim.duplicate_items(sprite)
            raw = sprite.to_bytes()
            fixed, _log = pt1030_bankfix.fix_bank(raw, True, entry.mod_folder in PART_ORDER,
                                                  entry.mod_folder, "D4_", 2)
            (built / anime / f"anm{number:05d}.lzs").write_bytes(fixed.to_bytes())
        shutil.rmtree(tmp)
        if donor:
            self._record_motion_origin(built, receipt)
        (built.parent.parent / "own-tracks-receipt.json").write_text(
            json.dumps(receipt, indent=1, default=str) + "\n")
        return (f"D4 own tracks on anm{bank:05d}/{bank + 1:05d}: {receipt['source_anm']}, "
                f"{len(receipt['aliases'])} donor-only id(s) aliased, {receipt['pixel_checks']} pixel checks")

    @staticmethod
    def _record_motion_origin(built, receipt):
        """D4IDLE1: per motion id, where the picture comes from, in mod.json ``source_import.motion_origin``.

        source = D4's own motion (pictures, timing, ground line); held = a D5 state D4 never drew, played as
        the source motion named here (the stand); d5-only = an empty attachment with no source picture."""
        path = Path(built) / "mod.json"
        if not path.is_file():
            return
        held, only = {}, []
        for aid, al in sorted(receipt["aliases"].items()):
            if al["rule"] in ("blank-attachment", "empty-attachment"):
                only.append(int(aid))
            else:
                held[str(aid)] = int(al["source"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.setdefault("source_import", {})["motion_origin"] = dict(
            source_motions=int(receipt["source_motions"]), held=held, d5_only=only,
            note="held = D4 never drew this state; it plays the named source motion (labelled held)")
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _trim_palettes(self, entry, built, sid, data, options):
        """Default: reproduce the installed palette-header count (D4's own bank count per sprite).

        `--d4-faithful-palettes` keeps the CORED4B output (every palette slot recoloured from the
        D4 banks).  That variant is a FOLLOW-UP: the engine's palette-wheel capacity for a unique
        with more banks than the installed copy has never been soaked live, so it does not ship by
        default (DECISIONS 2026-11-03, CORED4C).
        """
        if options.get("d4_faithful_palettes") or entry.mod_folder in HELD_DONOR_BANKS:
            # Toro/Kuro keep the donor-track bank and its 10 palette headers (held: 10/1); trimming
            # them to D4's single bank changed the bank shape and failed the wheel gate (D4-FIX2).
            # Politan also keeps donor tracks now (D4-TRACKS1) but is held with D4's 1 bank, so he
            # is trimmed like every other unique: the wheel gate holds the installed header count.
            return True
        sys.path.insert(0, str(WORKTREE))
        from d5lib import anm, gamefs
        _doc, leases = load_leases()
        lease = leases.get(entry.mod_folder) or {}
        physical = int(lease.get("physical") or sid)
        banks = data.body_palettes(data.chars[sid]["sprite"])
        wanted = len(banks)
        anime = Path(built) / "files/Anime/ANM_HI_JP.dat"
        if not anime.is_dir():
            return True
        for number in (physical, physical + 1):
            path = anime / f"anm{number:05d}.lzs"
            if not path.is_file():
                continue
            doc = anm.parse(gamefs.decode_member(path.read_bytes()))
            while len(doc.palettes) > wanted and len(doc.blocks[0].palette_infos) > 1:
                anm.remove_palette(doc, doc.blocks[0].pal_base + len(doc.blocks[0].palette_infos) - 1, 0)
            path.write_bytes(doc.to_bytes())
        return False

    def _palette_slot0(self, entry, built, sid, data):
        """D4-PAL1 (review F1): slot 0 of both main banks shows the D4 colour bank the row wears.

        The own-tracks pass ships the D4 body's palettes in D4's order (slot k = bank k), so a
        palette-swap unique (Des X 180 = Desco + bank 4, Nemo 220 = body 70 + bank 4) showed the base
        character.  Rotate the wanted bank to slot 0 (the rest keep D4's order, bank count kept),
        then gate: slot 0 must be that bank (nearest-colour distance 0).  -> (ok, why)"""
        sys.path.insert(0, str(WORKTREE))
        from d5lib import anm, d4unique, gamefs
        import numpy as np
        banks = data.body_palettes(data.chars[sid]["sprite"])
        wanted = d4unique.d4_bank(data, sid)
        _doc, leases = load_leases()
        physical = int((leases.get(entry.mod_folder) or {}).get("physical") or sid)
        anime = Path(built) / "files/Anime/ANM_HI_JP.dat"
        whys = []
        for number in (physical, physical + 1):
            path = anime / f"anm{number:05d}.lzs"
            if not path.is_file():
                continue
            doc = anm.parse(gamefs.decode_member(path.read_bytes()))
            pals = [anm.get_palette(doc, k) for k in range(len(doc.palettes))]
            if wanted and len(pals) == len(banks) and all(np.array_equal(p, b) for p, b in zip(pals, banks)):
                for k, pal in enumerate(d4unique.rotate_banks(pals, wanted)):
                    anm.set_palette(doc, k, pal)
                path.write_bytes(doc.to_bytes())
                whys.append(f"anm{number:05d} rotated D4 bank {wanted} to slot 0")
            ok, why = d4unique.slot0_gate(doc, banks, wanted)
            if not ok:
                return False, f"anm{number:05d}: {why}"
        return True, "; ".join(whys) or f"slot 0 = D4 bank {wanted}"

    # ------------------------------------------------------------------ voices
    def _voice_id(self, source_id, class_, lease=None):
        """Custom voice lease: 9000+ordinal for classes; uniques read the recorded set id.

        The installed unique packs did not use one ordinal series (9100-9121 for the first batch,
        9130-9138 for D4UNIQ3, 9068/9069 for the parked pair), so a unique's voice set is a
        recorded lease (`d5lib/importers/d4-leases.json`), never `9100 + ordinal`.
        """
        if not class_:
            if lease is None:
                _doc, leases = load_leases()
                lease = leases.get(f"D4_Unique_{source_id}") or {}
            if lease.get("voice_id"):
                return int(lease["voice_id"])
        roster = [e for e in self.roster() if e.kind == ("class" if class_ else "unique")]
        ids = [int(e.source_ref["row"]) for e in roster]
        return (9000 if class_ else 9100) + sorted(ids).index(int(source_id))

    def _voices(self, mod, source_id, *, class_, files=None, source=None, lease=None):
        """VOICES2 recipe: EN then JP, merged; every char row speaks the custom voice.

        ``source`` (an explicit D4 root) is the diagnostic/test route; production passes the verified
        ``files`` set."""
        sys.path.insert(0, str(WORKTREE))
        from d5lib import d4voices, modsys
        if files is None:
            files = _d4_source.D4Files(Path(source), {}, prepared=False)
        data = files.data("EN")
        source = files.root
        row = data.chars[source_id]
        base = row["voice_group_base"]
        groups = [base, base + 1, base + 2] if class_ else [base]
        voices_dir = mod / "patches/voices"
        if voices_dir.is_dir():
            shutil.rmtree(voices_dir)
        # REPROFIX4: a character the source game does not voice (Pringer X 210, Politan 610) is silent, as in the
        # installed packs (VOICESILENT1): char rows on SILENT_VOICE_ID and the mod.json note, no donor voice 2020.
        facts = None if class_ else d4voices.source_voice_facts(source, source_id, locate=files.path)
        if not class_ and not d4voices.source_has_voice(facts):
            from d5lib import drpgvoice
            drpgvoice.link_silent(mod, d4voices.silent_why(facts), keep_layout=True)
            return
        event_map = {str(k): v for k, v in VOICE_ROLES.items()}
        obj = modsys.Mod(str(mod))
        voice_id = self._voice_id(source_id, class_, lease)
        for lang in ("EN", "JP"):
            d4voices.import_d4_voice(obj, data, voice_id=voice_id, groups=groups,
                                     event_map=event_map, source_language=lang,
                                     destination_language=lang)
        path = mod / "patches/db/char.dat.json"
        if path.is_file():
            doc = json.loads(path.read_text())
            for r in doc.get("added", []):
                r["voice_id"] = voice_id
            for r in (doc.get("rows") or {}).values():
                r["voice_id"] = VOICE_ID
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ gates
    @staticmethod
    def wheel_reference(folder):
        """Recorded ANM header shapes of the shipped pack, so the default build freezes the wheel
        against the same counts without reading an installed pack (SOURCEPREP4-D4)."""
        return _d4_source.wheel_reference(folder)

    # ------------------------------------------------------------------ features
    def _features(self, mod):
        f = {k: "n/a" for k in ("stand", "walk", "attack", "hurt", "carried", "face", "cutin",
                                "stats", "skills", "evilities", "voice", "specials", "ranks")}
        f["recruit"] = "own"
        try:
            receipt = json.loads((mod.parent.parent / "pilot-receipt.json").read_text())
        except Exception:                                      # noqa: BLE001
            receipt = {}
        plan = receipt.get("d4_plan") or {}
        f["stats"] = "done" if len(plan.get("ranks", [])) >= 6 or (mod / "patches/db/char.dat.json").is_file() else "missing"
        f["skills"] = "done" if any(True for _ in (plan.get("skills") or [])) else (
            "done" if (mod / "patches/db/magic.dat.json").is_file() or (mod / "patches/db/Skill.dat.json").is_file() else "missing")
        f["evilities"] = "done" if (mod / "patches/evilities/evilities.json").is_file() else (
            "partial" if (mod / "patches/db/Skill.dat.json").is_file() else "missing")
        f["voice"] = "own" if (mod / "patches/voices/voices.json").is_file() else "missing"
        try:
            silent = str((json.loads((mod / "mod.json").read_text()).get("source_import") or {}).get("voice", "")).startswith("silent")
        except Exception:                                      # noqa: BLE001
            silent = False
        if silent and f["voice"] == "missing":
            f["voice"] = "silent"                              # REPROFIX4: the source game has no voice for it
        f["face"] = "done" if list((mod / "patches/classes").glob("face_*.png")) else "missing"
        f["cutin"] = "done" if receipt.get("source_import", {}).get("cutin") or (mod / "files/Anime").is_dir() else "done"
        for k in ("stand", "walk", "attack"):
            f[k] = "done" if (mod / "files/Anime").is_dir() else "missing"
        f["hurt"] = f["carried"] = "adapted"
        f["ranks"] = "done" if (mod / "patches/db/char.dat.json").is_file() else "missing"
        skills = plan.get("report") or []
        spec = [x for x in skills if x.get("kind") == "skill"]
        if spec:
            done = sum(1 for x in spec if x.get("status") in ("exact", "adapted", "exact-extension"))
            f["specials"] = "done" if done == len(spec) else ("partial" if done else "missing")
        else:
            f["specials"] = "adapted"
        return f

    # ------------------------------------------------------------------ compare
    def explained_missing(self, entry, path):
        """An installed file the rebuild does not carry because a recorded lease moved its id."""
        if entry.kind == "class" and int(entry.source_ref["row"]) in SPRITE_FAMILY_OVERRIDE:
            # D4GAP1: the checkpoint's family moved off vanilla ground; its files move with it
            old = int(self._spec(entry)["sprite_family"])
            return any(path.endswith(f"anm{n:05d}.lzs") for n in
                       [old + k for k in range(3)] + [10000 + old + k for k in range(10)])   # banks + rank portraits
        _doc, leases = load_leases()
        lease = leases.get(entry.mod_folder) or {}
        old = lease.get("physical_supersedes")
        if not old:
            return False
        old = int(old)
        return any(path.endswith(name) for name in (
            f"anm{old:05d}.lzs", f"anm{old + 1:05d}.lzs", f"anm{old + 2:05d}.lzs",
            f"anm{10000 + old:05d}.lzs", f"face_{old}.png", f"icon_{old}.png"))

    @staticmethod
    def _magichange_lost(entry, dirs):
        """A leased Magichange row (magic.dat) or learn slot the rebuild lacks, for the MAGICHANGE lane's
        seven mods: a regression, never an expected difference (D4-FIX5)."""
        _doc, leases = load_leases()
        want = (leases.get(entry.mod_folder) or {}).get("magichange")
        if not want:
            return ""
        built = Path(dirs[0])

        def load(rel):
            try:
                return json.loads((built / rel).read_text())
            except (OSError, ValueError):
                return {}
        rows = {int(r["id"]) for r in load("patches/db/magic.dat.json").get("added", [])}
        ch = (load("patches/db/char.dat.json").get("added") or [{}])[0]
        learns = {int(ch.get(f"learn{k}_skill") or 0) for k in range(1, 17)}
        gone = sorted(int(r["d5_id"]) for r in want
                      if int(r["d5_id"]) not in learns or (r["name"] and int(r["d5_id"]) not in rows))
        return ("Magichange rows/learn slots missing from the rebuild: " + str(gone)) if gone else ""

    def compare_reason(self, entry, diff, dirs=None):
        added, missing, changed = diff
        names = set(changed) | set(added)
        reasons = []
        lost = self._magichange_lost(entry, dirs) if dirs else ""
        if lost:
            return "regression: " + lost
        if any(n.endswith("mastery.json") for n in added):
            reasons.append("packed class-mastery declaration (INTEG6 fix) now in the command")
        if any(n.startswith("patches/voices/") for n in names):
            reasons.append("VOICES2 bilingual bank (EN+JP, merged role map) rebuilds the installed voice pass")
        if any(n.startswith("patches/evilities/") or n.startswith("patches/db/Skill.dat.json") for n in names):
            from d5lib.importcore import evility_row_diff
            ids = evility_row_diff(*dirs) if dirs else ""
            reasons.append("evility state: " + (ids or "files differ in formatting only") +
                           " (the rebuild applies the reviewed overlay, d4-evility-overlay.json)")
        sid = int(entry.source_ref.get("row") or 0) if entry.kind == "unique" else 0
        if sid in PALETTE_SWAPS and any(n.startswith("files/Anime/") for n in names):
            reasons.append(f"main bank palette slot order: D4 bank {PALETTE_SWAPS[sid]} rotated to slot 0 "
                           "(D4-PAL1; the held copy showed the base character's bank 0)")
        if sid and any(n.startswith("files/Anime/") for n in names):
            try:
                data = self.source().data("EN")
            except _d4_source.D4SourceError:
                data = None
            if data is not None and donor_tracks(data, sid):
                reasons.append(f"main banks on the donor's tracks (D4-TRACKS1: the D4 body has under "
                               f"{DONOR_TRACK_MOTIONS} motions; the held copy froze it on its stand picture)")
        if any(n.startswith("files/Anime/") for n in names):
            reasons.append("sprite/animation bytes differ from the installed build (same prepared art, "
                           "current kit finalizer)")
        if any(n.endswith("charPersonal.dat.json") for n in names):
            reasons.append("personality row ids shifted to the current free range")
        if any(n.endswith("mod.json") for n in names):
            reasons.append("mod.json provenance/adaptation text reflects this command")
        if any(n.startswith("patches/db/magic.dat.json") or n.startswith("patches/skills/")
               for n in names):
            reasons.append("specials: magic.dat rows + choreography rules rebuilt from the lanes' "
                           "reviewed tables at the leased ids (no new rows)")
        if any(n == "D4UNIQ3-ABILITY-NOTES.txt" for n in added + changed):
            reasons.append("D4UNIQ3 ability notes regenerated by the wrapped lane pass")
        if any(n.startswith("patches/voices/") and "leased" not in " ".join(reasons)
               for n in names):
            reasons.append("voice clips rebuilt at the lease's recorded voice set id")
        _doc, leases = load_leases()
        lease = leases.get(entry.mod_folder) or {}
        if entry.mod_folder in ("D4_Unique_350", "D4_Unique_360"):
            reasons.append("art row 393/396 was shared with the now-parked D4_Unique_510/520 "
                           "(MODORG1: Overlord's versions win), so the installed copy under this "
                           "name carried a different character; this rebuild owns the row")
        if entry.kind == "class" and int(entry.source_ref["row"]) in SPRITE_FAMILY_OVERRIDE:
            reasons.append(f"sprite family re-leased {self._spec(entry)['sprite_family']} -> "
                           f"{SPRITE_FAMILY_OVERRIDE[int(entry.source_ref['row'])]}: the old family holds vanilla anm02622 "
                           "(used_ids gate); the files move with it")
        if lease.get("physical_supersedes"):
            reasons.append(f"art row re-leased {lease['physical_supersedes']} -> "
                           f"{lease['physical']} (the old anm/face files move with it, none is lost): "
                           f"{lease.get('physical_why', '')}")
        return "; ".join(reasons) or ""
