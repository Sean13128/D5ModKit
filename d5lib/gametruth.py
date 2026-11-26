"""GAMETRUTH1 (second implementation, branch gametruth1b): "what will the GAME do with this pack?", offline.

For every installed mod folder that adds char rows, follow the path a player meets (recruit -> status screen ->
battle body -> actions -> voice -> stats) through the files the game will read (installed Database_0.dat,
ANM_HI_JP.dat, Sound_Voice tables and the installed, Kit-patched disgaea5.exe) and say per check
PASS / FAIL / NOT MODELLED / N/A, the decompiled function it rests on and how:

    executed        the function runs under Unicorn on the installed exe (tools/stat_oracle.Emu rig)
    re-implemented  the function's rule, read in the decomp, replayed in Python on the installed data
    kit gate        an existing importcore/readback gate is called
    linked          proven elsewhere (named proof), not re-run here

NOT MODELLED names where the path stopped.  Read-only.
"""
from __future__ import annotations

import json
import struct
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
ANIME = "Anime/ANM_HI_JP.dat"
FACE_BLOCK = 9017                     # resident block holding status-panel face animations (SMALLFIX1 sweep)
HUMAN_MOTIONS = 1                     # resident block 1: shared humanoid motion set (docs/ANM.md sec. 5)
BODY_MOTIONS = {"idle front": 1001, "idle back": 1007, "walk front": 11, "walk back": 17,
                "hurt front": 1061, "hurt back": 1067}   # stand/walk/hit ids read live (MOTIONPROBE1, LIVE42)
PLACEHOLDER_NAMES = {"", "Disgaea RPG", "Unique Dummy", "DLC Dummy", "Human Dummy", "Monster Dummy", "???", "Dummy"}
BOARD_END = 0x1407ECA32               # first menu call after the scan + request append

F = {
    "board": (0x1407EC450, "FUN_1407ec450 Quest Shop board builder (QBOARD1)"),
    "quest_load": (0x1400C2A40, "db_quest_load_fixed (qsort by id)"),
    "gfx": (0x14021F4A0, "anm_id_for_variant"),
    "evil": (0x140218C90, "unit_stats_evil_rebuild_list"),
    "name": (0x140217EB0, "database_table_character_name / class_title_read_21090 0x140221090"),
    "appearance": (0x14014EA10, "unit_set_appearance -> ui_sprite_set_anm 0x14014e7e0 -> anm_find_loaded_record 0x1403020c0"),
    "select": (0x1402F4BA0, "anm_actor_select_motion"),
    "render": (0x1402F5450, "anm_actor_build_render_root"),
    "texture": (0x14030FFF0, "model_decode_texture (byte-order marker)"),
    "voice": (0x1400AEF60, "sound_voice_table_lookup"),
    "init": (0x140218590, "unit_init_stats + unit_recalc 0x14021bfb0"),
}


def fn(key):
    a, n = F[key]
    return f"{n} 0x{a:X}"


@dataclass
class Check:
    name: str
    status: str
    why: str
    rests_on: str
    mode: str


@dataclass
class PackResult:
    pack: str
    game: str
    enabled: bool
    rows: list = field(default_factory=list)
    checks: list = field(default_factory=list)
    folder_rows: dict = field(default_factory=dict)

    def add(self, *a):
        self.checks.append(Check(*a))

    def worst(self):
        s = {c.status for c in self.checks}
        return "FAIL" if "FAIL" in s else "NOT MODELLED" if "NOT MODELLED" in s else "PASS"


def game_of(name):
    p = name.split("_")[0]
    return p if p in ("D4", "D1C", "DD2", "DRPG") else "other"


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None


def added_rows(folder, member):
    d = _json(Path(folder) / "patches" / "db" / f"{member}.json") or {}
    return d.get("added") or []


def objects(image):
    """Upload objects one image costs: 1, or 256 when its byte-order marker is not 1 (DD2WHEEL6)."""
    return 1 if image.unk == 1 else 256


def rows_to_table(member, vanilla_raw, rows):
    from d5lib import database
    t = database.load_table(member, vanilla_raw)
    proto = t.rows[0].copy()
    while len(t):
        t.delete_row(len(t) - 1)
    for r in rows:
        t.rows.append(proto.copy())
        nr = t.rows[-1]
        for k, v in r.items():
            if k in nr and not k.startswith("pad_"):        # padding keeps the prototype's bytes
                nr.set(k, v, truncate=True)
    return t.to_bytes()


# ============================================================================================ the world
class World:
    """The files the game will read.  folder_mode: banks from the mod folder first and the installer replayed
    for resident blocks (pre-fix folders kept in Local/kit-backups)."""

    def __init__(self, game=GAME, mods=None, save=None, quest_rows=None, folder_mode=False, exe=None,
                 load_order=None):
        from d5lib import database, gamefs, anm
        self.anm = anm
        self.game = Path(game)
        self.mods = Path(mods) if mods else self.game / "D5ModKit" / "mods"
        self.folder_mode = folder_mode
        self.db = database.load_database(str(self.game / "Data/Database/Database_0.dat"))
        if quest_rows is not None:
            self.db.raw["Quest.dat"] = rows_to_table("Quest.dat", self.db.raw["Quest.dat"], quest_rows)
        T = lambda n: database.load_table(n, self.db.raw[n]).rows      # noqa: E731
        self.chars = {int(r["id"]): r for r in T("char.dat")}
        self.quests = sorted(T("Quest.dat"), key=lambda r: int(r["id"]))
        self.magic = {int(r["id"]) for r in T("magic.dat")}
        self.skill = {int(r["id"]): r["name_EN"] for r in T("Skill.dat")}
        self.fs = gamefs.GameFS(str(self.game))
        res = anm.parse(self.fs.read(f"{ANIME}/anm_resident.lzs"))
        self.resident = {b.id for b in res.blocks}
        blocks = {b.id: b for b in res.blocks}
        self.faces = {a.id for a in blocks[FACE_BLOCK].animations} if FACE_BLOCK in blocks else set()
        self.human = {a.id for a in blocks[HUMAN_MOTIONS].animations}
        self.exe = Path(exe) if exe else self.game / "disgaea5.exe"
        self.save = Path(save) if save else None
        self._emu = self._board = None
        lo = Path(load_order or (self.mods.parent / "profiles" / "MAIN" / "load_order.json"))
        self.enabled = set(_json(lo) or []) if lo.is_file() else None
        self._banks = {}
        self.voice_sets = {}
        self.voice_loaded = False          # load_voice() sets it; an unloaded table is NOT MODELLED, never a pass

    @property
    def emu(self):
        if self._emu is None:
            sys.path.insert(0, str(KIT / "tools"))
            import stat_oracle as so
            self.so = so
            e = so.Emu(exe_path=self.exe, db=self.db)
            raw, self.char_index, _ = so.char_table_with(self.db, [])   # char_find_by_id is a binary search
            e.set_chars(raw)
            self._emu = e
        return self._emu

    def gfx_id(self, cid, palette):
        v = self.emu.call(F["gfx"][0], [cid, palette]) & 0xFFFFFFFF
        return v - (1 << 32) if v >= 1 << 31 else v

    def evil_list(self, row):
        """Run unit_stats_evil_rebuild_list 0x140218C90 on a freshly created unit of this row -> (innate ids, active
        list).  The copy of the row's ids into the unit's innate slots (+0x2EEE, count +0x2EF8) is unit_construct's
        job and is re-implemented here; the rebuild itself is executed (port of gametruth1 ebf56fb Rig.unit)."""
        e, so = self.emu, self.so
        cid = int(row["id"])
        e.fresh(bytes(row.raw), self.char_index.get(cid), 1, 0x1234)
        n = min(int(row["evility_count"] or 0), 4)
        ev = [int(row[f"evility{k}"]) for k in range(1, n + 1)]
        for k, v in enumerate(ev):
            e.put(so.ROSTER + 0x2EEE + 2 * k, v & 0xFFFF, "<H")
        e.put(so.ROSTER + 0x2EF8, len(ev), "<H")
        e.put(so.ROSTER + 0x2F2C, 0, "<I")
        e.put(so.ROSTER + 0x4348, 0xFFFF, "<I")
        e.call(F["evil"][0], [so.ROSTER])
        cnt = struct.unpack("<i", e.read(so.ROSTER + 0x3030, 4))[0]
        active = list(struct.unpack(f"<{cnt}i", e.read(so.ROSTER + 0x2F30, 4 * cnt))) if 0 <= cnt <= 64 else None
        return ev, active

    def voice_row(self, lang, line_id):
        """sound_voice_table_lookup 0x1400AEF60 executed on the installed EN/JP voice table -> row index or None."""
        from d5lib import voices
        e = self.emu
        if not hasattr(self, "_vtab"):
            self._vtab = {}
            for lg, path in voices.TABLES.items():
                v = self.db.raw[path.rsplit("/", 1)[1]]
                n = struct.unpack_from("<I", v)[0]
                self._vtab[lg] = (e.alloc(v[4:4 + 48 * n]), n)
        base, n = self._vtab[lang]
        e.put(0x140A03CB8, base)
        e.put(0x140A03CC0, n, "<I")
        p = e.call(F["voice"][0], [0, line_id])
        return (p - base) // 48 if p else None

    def board(self):
        """FUN_1407ec450 executed on the installed Quest.dat (sorted as db_quest_load_fixed does) and the save."""
        if self._board is None and self.save:
            from d5lib import savegame
            e, so = self.emu, self.so
            st = savegame.Save(str(self.save)).state
            e.mu.mem_write(so.BLOCK, bytes(st[:so.BLOCK_SIZE]))
            e._plain("Quest.dat", 0x140A03B50, 0x140A03B58, 0x1604, 0)
            obj = e.alloc(bytes(0x90000))
            X = e.X
            rsp = so.STACK + 0x100000 - 8
            e.mu.mem_write(rsp, struct.pack("<Q", so.RET))
            e.mu.reg_write(X.UC_X86_REG_RSP, rsp)
            e.mu.reg_write(X.UC_X86_REG_RCX, obj)
            e.mu.emu_start(F["board"][0], BOARD_END, count=50_000_000)
            n = struct.unpack("<i", e.read(obj + 0x5C158, 4))[0]
            ptrs = struct.unpack(f"<{n}Q", e.read(obj + 0x85C50, 8 * n))
            self._board = dict(listed=[struct.unpack("<I", e.read(p, 4))[0] for p in ptrs], state=st)
        return self._board

    def bank(self, folder, n):
        key = (str(folder) if self.folder_mode else "", n)
        if key not in self._banks:
            p = Path(folder) / "files" / ANIME / f"anm{n:05d}.lzs"
            try:
                if self.folder_mode and p.is_file():
                    from d5lib import gamefs
                    data = gamefs.decode_member(p.read_bytes())
                else:
                    data = self.fs.read(f"{ANIME}/anm{n:05d}.lzs")
            except Exception:                                      # noqa: BLE001  no such member
                data = None
            self._banks[key] = self.anm.parse(data) if data else None
        return self._banks[key]


# ============================================================================================ checks
def check_pack(w: World, folder, survey=None, voice_problems=None, resident_override=None):
    folder = Path(folder)
    meta = _json(folder / "mod.json") or {}
    enabled = w.enabled is None or folder.name in w.enabled
    res = PackResult(folder.name, game_of(folder.name), enabled)
    frows = added_rows(folder, "char.dat")
    res.rows = [int(r["id"]) for r in frows]
    if not enabled:
        res.add("installed", "N/A", "not in the MAIN load order: the game never reads it", "", "none")
        return res
    if not frows:
        res.add("char rows", "N/A", "pack adds no char row", "", "none")
        return res
    res.folder_rows = {int(r["id"]): r for r in frows}
    missing = [c for c in res.folder_rows if c not in w.chars]
    if missing:
        res.add("installed rows", "FAIL", f"char rows {missing[:6]} are not in the installed char.dat", "", "re-implemented")
    rows = []
    for cid, fr in res.folder_rows.items():
        ir = w.chars.get(cid)
        if ir is None:
            continue
        if w.folder_mode:                       # a pre-fix folder: its own row values over the installed row
            ir = ir.copy()
            for k, v in fr.items():
                if k in ir and not k.startswith("pad_") and k != "voice_id":
                    ir.set(k, v, truncate=True)
        rows.append(ir)
    if not rows:
        return res
    _recruit(w, folder, meta, rows, res)
    _status(w, folder, rows, res)
    _body(w, folder, rows, res, resident_override)
    _actions(folder, res, survey)
    _voice(w, folder, meta, rows, res, voice_problems)
    _stats(w, rows, res)
    return res


def _recruit(w, folder, meta, rows, res):
    quests = [q for q in added_rows(folder, "Quest.dat") if int(q.get("reward_type") or 0) == 5]
    classes = sorted((folder / "patches" / "classes").glob("class_*.json"))
    if classes:
        from d5lib import wheelmeta
        try:
            wheel = wheelmeta.class_wheel({**meta, "category": "classes"})
            res.add("recruit: class page", "PASS", f"{len(classes)} class descriptor(s) on the '{wheel}' page",
                    "Kit runtime wheel table (d5lib.wheelmeta, compiled into d5auto); the page builder is Kit code",
                    "re-implemented")
        except Exception as exc:                                  # noqa: BLE001
            res.add("recruit: class page", "FAIL", f"wheel metadata unusable: {exc}", "d5lib.wheelmeta", "re-implemented")
    if not quests:
        if not classes:
            res.add("recruit: quest", "N/A", "no character-reward quest (costume/outfit rows)", "", "none")
        return
    ids = set(res.folder_rows)
    byid = {int(q["id"]): q for q in w.quests}
    qcount = len(w.quests) & 0xFFFF
    b = w.board()
    from d5lib import savegame as sg
    for q in quests:
        qid = int(q["id"])
        iq = byid.get(qid)
        if iq is None:
            res.add("recruit: board", "FAIL", f"quest {qid} not in the installed Quest.dat", fn("quest_load"), "re-implemented")
            continue
        slot, val = int(iq["sort_order"]), int(iq["reward_value"])
        res.add("recruit: reward", "PASS" if val in ids and int(iq["reward_type"]) == 5 else "FAIL",
                f"quest {qid} reward type {iq['reward_type']} -> char {val}" + ("" if val in ids else " (not this pack's row)"),
                "Quest.dat reward_type 5 = character (as vanilla recruit rows); reward handler not traced", "re-implemented")
        if b is None:
            res.add("recruit: board", "FAIL" if slot >= qcount else "NOT MODELLED",
                    f"quest {qid} slot {slot}, {qcount} rows" + (": never scanned" if slot >= qcount else "; no save given"),
                    fn("board"), "re-implemented")
            continue
        st = b["state"]
        if qid in b["listed"]:
            res.add("recruit: board", "PASS", f"quest {qid} (slot {slot}) listed (position {b['listed'].index(qid) + 1})",
                    fn("board"), "executed")
        elif st[sg.QUEST_COMPLETED + slot]:
            res.add("recruit: board", "PASS", f"quest {qid} (slot {slot}) completed on this save (recruited already)",
                    fn("board"), "executed")
        else:
            shadow = next((int(x["id"]) for x in w.quests if int(x["sort_order"]) == slot and int(x["id"]) < qid), None)
            why = ("slot >= row count %d: never scanned" % qcount if slot >= qcount else
                   "id >= 2000: the scan stops there" if qid >= 2000 else
                   f"shadowed by quest {shadow} on the same slot" if shadow is not None else
                   "prerequisite / story flag / min level / accepted on this save")
            res.add("recruit: board", "FAIL", f"quest {qid} (slot {slot}) NOT listed: {why}", fn("board"), "executed")


def _status(w, folder, rows, res):
    from d5lib import importcore
    bad = []
    for r in rows:
        cid = int(r["id"])
        face = 10000 + w.gfx_id(cid, int(r["tier"]))
        if face not in w.faces:
            bad.append(f"{cid}: face anim {face} (10000 + graphics id) not in resident block {FACE_BLOCK}")
    ok_t, why_t = importcore.face_template_gate(folder)
    if not ok_t:
        bad.append("next install: " + why_t)
    res.add("status: portrait", "FAIL" if bad else "PASS",
            "; ".join(bad[:4]) or f"{len(rows)} row(s): face anim 10000+graphics id in installed block {FACE_BLOCK}",
            fn("gfx") + f" (executed) -> face 10000+id in installed anm_resident block {FACE_BLOCK} (SMALLFIX1 rule; the "
            "panel's draw call not traced) + face_template_gate (installer)", "executed")
    bad = []
    titles = _json(KIT / "d5lib/importers/drpg-titles.json") or {}
    kept = any(folder.name.endswith("_" + k) for k in titles.get("no_source_title") or {})
    for r in rows:
        for k in ("name_EN", "title_EN"):
            v = (r.get(k) or "").strip()
            if v in PLACEHOLDER_NAMES and not (kept and k == "title_EN" and v == titles.get("placeholder")):
                bad.append(f"{r['id']} {k}={v!r}")
    res.add("status: name/title", "FAIL" if bad else "PASS", "; ".join(bad[:6]) or (
            "title keeps the group label: no source title (drpg-titles.json)" if kept else "names and titles are real text"),
            fn("name") + " (reads the row's text fields)", "re-implemented")
    bad, note, mode = [], [], "executed"
    for r in rows:
        try:
            ev, active = w.evil_list(r)
        except Exception as exc:                                  # noqa: BLE001
            bad.append(f"{r['id']}: emulation stopped ({exc})")
            mode = "re-implemented"
            ev, active = [int(r[f"evility{i}"]) for i in range(1, min(int(r["evility_count"] or 0), 4) + 1)], None
        if active is not None and sorted(x for x in ev if x) != sorted(x for x in active if x in ev):
            bad.append(f"{r['id']}: innate {ev} but the game's active list is {active}")
        if not [x for x in ev if x]:
            bad.append(f"{r['id']} links no innate evility (status page 3 blank)")
        for e in (x for x in ev if x):
            if not (w.skill.get(e) or "").strip():
                bad.append(f"{r['id']} evility {e} has no named row in installed Skill.dat")
            else:
                note.append(w.skill[e])
    # EVILFX3: a unit whose SOURCE has no innate evility (reviewed data: sourcemaps/d4.json uniques.<id>.no_source_innate,
    # with the source evidence) is N/A when it links none: a blank page 3 is what the source game shows too
    src = ((_json(KIT / "d5lib/sourcemaps/d4.json") or {}).get("uniques") or {}).get(folder.name.rsplit("_", 1)[-1]) or {}
    if folder.name.startswith("D4_Unique_") and src.get("no_source_innate") and bad and all("links no innate" in b for b in bad):
        res.add("status: innate evility", "N/A", "the source unit has no innate evility: " + src.get("innate_source", ""),
                "reviewed data d5lib/sourcemaps/d4.json", "re-implemented")
        bad = None
    if bad is not None:
      res.add("status: innate evility", "FAIL" if bad else "PASS", "; ".join(bad[:6]) or ", ".join(sorted(set(note))[:4]),
            fn("evil") + " executed on the created unit (the row -> innate-slot copy of unit_construct 0x14021B510 "
            "re-implemented); names looked up in installed Skill.dat", mode)
    bad = []
    for r in rows:
        for i in range(1, min(int(r["learn_count"] or 0), 16) + 1):
            s = int(r[f"learn{i}_skill"] or 0)
            if s and s not in w.magic:
                bad.append(f"{r['id']} learn{i} {s}")
    res.add("status: learn list", "FAIL" if bad else "PASS", "; ".join(bad[:6]) or "every learn id in installed magic.dat",
            "magic.dat lookup by id (learn_skill_gate rule on the installed table)", "re-implemented")


def _body(w, folder, rows, res, resident_override=None):
    from d5lib import importcore
    import numpy as np
    anm = w.anm
    bad = []
    for r in rows:
        cid, colour = int(r["id"]), int(r["color_id"])
        g = w.gfx_id(cid, int(r["tier"]))
        if g != colour:
            who = w.chars.get(g)
            bad.append(f"{cid}: graphics id {g} != colour {colour}" + (f" ({who['name_EN']})" if who else ""))
    res.add("body: graphics id", "FAIL" if bad else "PASS", "; ".join(bad[:4]) or "graphics id = colour id on every row",
            fn("gfx") + " (installed, Kit-patched exe)", "executed")
    draw_bad, motion_bad, root_bad, amplified, nobank, nopair, budget = [], [], [], [], [], [], 0
    sprites = sorted({(int(r["sprite_id"]), int(r["body_type"])) for r in rows if int(r["sprite_id"])})
    for n, kind in sprites:
        banks = [(b, w.bank(folder, b)) for b in (n, n + 1)]
        banks = [(b, a) for b, a in banks if a is not None]
        # FIXUP1: vanilla pairs every bank N with N+1 (loose, or resident for 6 body_type 2 rows: 0 exceptions in the
        # clean char.dat), so N present with N+1 resolved nowhere is an unresolved prerequisite, not a pass
        if banks and banks[0][0] == n and n + 1 not in {b for b, _ in banks} and n + 1 not in w.resident:
            nopair.append(n + 1)
        if not banks:
            if n not in w.resident:
                nobank.append(n)
            continue
        for b, a in banks:
            imgs = a.textures + a.palettes
            budget += sum(objects(i) for i in imgs)
            amp = sum(1 for i in imgs if i.unk != 1)
            if amp:
                amplified.append(f"anm{b:05d}: {amp} image(s) with a swapped byte-order marker (x256 objects each)")
            ids = {x.id for bl in a.blocks for x in bl.animations}
            have = ids | (w.human if kind == 0 else set())
            miss = [m for m, v in BODY_MOTIONS.items() if v not in have]
            if miss:
                motion_bad.append(f"anm{b:05d} ({'monster' if kind else 'humanoid'}): no {', '.join(miss)}")
            for m in (1001, 1007):
                if m not in ids:
                    continue
                items = anm.evaluate(a, ("id", m), 0, nested=True, game=True)
                px = 0
                if items:
                    img, _ = anm.render_items(a, items, 0)
                    px = int((np.asarray(img)[..., 3] > 16).sum())
                if not px:
                    draw_bad.append(f"anm{b:05d} {m}: the game's render root draws nothing")
            mm = anm.render_root_mismatches(a)
            if mm:
                root_bad.append(f"anm{b:05d}: {len({x[1] for x in mm})} animation(s) draw other parts in game (e.g. {mm[0][1]})")
    if nobank or nopair:
        res.add("body: bank", "FAIL", (f"no bank anm{nobank[0]:05d}/+1 in the archive or resident" if nobank else
                f"bank N is there but its pair anm{nopair[0]:05d} (N+1) is in neither the pack, the archive nor resident"),
                "anm_acquire_lzs 0x1403ffcb0 (archive member by number); vanilla ships N with N+1", "re-implemented")
    res.add("body: idle draws (front/back)", "FAIL" if draw_bad else "PASS",
            "; ".join(draw_bad[:4]) or f"{len(sprites)} body sprite(s): 1001 and 1007 draw at the game's render root",
            fn("select") + " + " + fn("render") + " (anm.evaluate(game=True))", "re-implemented")
    res.add("body: render root", "FAIL" if root_bad else "PASS", "; ".join(root_bad[:3]) or "game picture = kit picture",
            fn("render") + " (anm.render_root_mismatches)", "re-implemented")
    res.add("body: motions idle/walk/hurt", "FAIL" if motion_bad else "PASS",
            "; ".join(motion_bad[:3]) or "all six motions resolve (own bank, + resident block 1 for humanoids)",
            fn("select") + " (missing id -> first animation 0); vanilla monster banks hold all six (222/222)",
            "re-implemented")
    if resident_override is not None:
        ok, why = importcore.resident_placeholder_gate(folder, resident_ids=resident_override)
        how = "given resident block set"
    elif w.folder_mode:
        ok, why = importcore.resident_placeholder_gate(folder)
        how = "installer replay"
    else:
        ok, why = importcore.resident_placeholder_gate(folder, resident_ids=w.resident)
        how = "installed anm_resident blocks"
    res.add("body: monster placeholder", "PASS" if ok else "FAIL", why or "every monster row's N+2 is resident",
            fn("appearance") + f"; {how}", "re-implemented")
    res.budget = budget
    res.add("body: texture objects", "FAIL" if amplified else "PASS",
            "; ".join(amplified[:3]) or f"{budget} upload objects for this pack's banks", fn("texture"), "re-implemented")


def _actions(folder, res, survey):
    if survey is None:
        res.add("actions: skill caster motions", "NOT MODELLED", "skill survey not loaded", "d5lib/choreo.py", "none")
    else:
        # FIXUP1: importcore.skill_motion_gate lets "unknown" through (the importer wants that); the verifier must not.
        # missing = FAIL; a skill the simulator cannot resolve = NOT MODELLED; only ok/fallback is a PASS
        recs = survey.check_mod(folder)
        bad = [f"unit {r['unit']} skill {r['skill']} motion {r['missing']}" for r in recs if r["status"] == "missing"]
        unk = sorted({int(r["skill"]) for r in recs if r["status"] == "unknown"})
        fb = sum(1 for r in recs if r["status"] == "fallback")
        if bad:
            status, why = "FAIL", "; ".join(bad[:6])
        elif unk:
            status, why = "NOT MODELLED", f"{len(unk)} skill(s) unresolved by the simulator (ids {unk[:6]}); {fb} fallback"
        else:
            status, why = "PASS", (f"{fb} fallback (vanilla runs the same pair absent)" if fb else
                                   "every learn-list skill's caster motions present")
        res.add("actions: skill caster motions", status, why,
                "kit skill simulator d5lib/choreo.py over the game's skill scripts (skill_motion_gate rule, unknown kept visible)",
                "kit gate")
    res.add("actions: normal attack", "NOT MODELLED", "weapon-type attack motion selection not followed",
            "attack families 2001-4087 (docs/ANM.md); the weapon -> motion table was not traced", "none")


def _voice(w, folder, meta, rows, res, voice_problems):
    silent = str((meta.get("source_import") or {}).get("voice")).startswith("silent")
    has = (folder / "patches/voices/voices.json").is_file()
    probs = list((voice_problems or {}).get(folder.name, []))
    if has or silent:                           # the pack sets its own voice ids: the game must read those
        for cid, fr in res.folder_rows.items():
            got = w.chars.get(cid)
            if got is not None and int(got["voice_id"]) != int(fr["voice_id"]):
                probs.append(f"row {cid}: the game reads voice {got['voice_id']}, pack says {fr['voice_id']}")
    mode, nlook = "kit gate", 0
    if has:
        from d5lib import modsys, voices
        doc = voices.load(modsys.Mod(str(folder)))
        for vid, voice in doc["voices"].items():
            for lang in voices.TABLES:
                for line, _src in voices.custom_lines(int(vid), voice, lang=lang):
                    nlook += 1
                    if w.voice_row(lang, line.id) is None:
                        probs.append(f"voice {vid} {lang} line {line.id}: the game's lookup finds no row")
        mode = "executed"
    nolines = [int(r["id"]) for r in rows if int(r["voice_id"]) and not w.voice_sets.get(int(r["voice_id"]))]
    if nolines and not silent and not getattr(w, "voice_loaded", True):
        res.add("voice", "NOT MODELLED", "the installed voice tables were not loaded (run without voices=False)",
                fn("voice"), "none")
        return
    if silent:
        status, why = ("FAIL" if probs else "PASS"), ("; ".join(probs[:3]) or "silent by source: no line, by design")
    else:
        bad = probs + ([f"rows {nolines[:5]}: voice id has no line in the installed table"] if nolines else [])   # FIXUP1: donor ids too
        status = "FAIL" if bad else "PASS"
        why = "; ".join(bad[:3]) or (f"{sum(len(w.voice_sets.get(int(r['voice_id']), ())) for r in rows)} table lines; "
                                     "pack lines installed with the pack's clips" if has else "donor/base voice ids resolve")
    res.add("voice", status, why + (f" ({nlook} line lookups executed)" if nlook else ""),
            fn("voice") + (" executed for every pack line (EN+JP)" if nlook else "") +
            "; row voice ids vs pack; clips byte-equal: check_installed_voices", mode)


def _stats(w, rows, res):
    w.emu
    r = rows[0]
    try:
        stats, _, _, _ = w.emu.fresh(bytes(r.raw), w.char_index.get(int(r["id"])), 1, 0x1234)
        ok = all(v > 0 for v in stats[:2])
        res.add("stats: creation", "PASS" if ok else "FAIL", f"row {r['id']} level 1: {stats}", fn("init"), "executed")
    except Exception as exc:                                        # noqa: BLE001
        res.add("stats: creation", "NOT MODELLED", f"emulation stopped: {exc}", fn("init"), "executed")
    res.add("stats: evility effects", "NOT MODELLED", "effects run by the evility runtime; see the proofs",
            "evility/offline_proof_*.py (DRPGEVIL1 66/66, DRPGEVIL1b 58/58, EVILGAP1, EVILFX1)", "linked")


# ============================================================================================ run
def load_voice(w):
    from d5lib import voices
    w.voice_loaded = True
    for lang in voices.TABLES:
        for line in voices.read_table(w.db.raw[voices.TABLES[lang].rsplit("/", 1)[1]]):
            w.voice_sets.setdefault(voices.split_set(line.group)[1], []).append(line.id)


def staged_view(view, *roots):
    """EVILFX3: a mods folder as it will be after an install -- symlinks to each pack, the LAST root that has a folder
    wins (installed mods first, staged builds after).  Use with World(mods=view, folder_mode=True, load_order=...)
    and add_staged_skill(w): rows and banks then come from the staged folders."""
    view = Path(view)
    view.mkdir(parents=True, exist_ok=True)
    pick = {}
    for root in roots:
        for f in sorted(Path(root).resolve().iterdir()):
            if (f / "mod.json").is_file():
                pick[f.name] = f
    for name, f in pick.items():
        (view / name).symlink_to(f, target_is_directory=True)
    return view


def add_staged_skill(w):
    """names of the Skill.dat rows (and the magic.dat ids) the folders under w.mods add: a staged row is not in the
    installed table yet (FIXUP1: magic ids too, or a staged learn list reads as missing skills)"""
    for f in w.mods.iterdir():
        for r in added_rows(f, "Skill.dat"):
            w.skill[int(r["id"])] = r.get("name_EN") or ""
        for r in added_rows(f, "magic.dat"):
            w.magic.add(int(r["id"]))


def run(w: World, only=None, survey=True, voices=True, resident_override=None):
    folders = sorted(p for p in w.mods.iterdir() if p.is_dir() and (p / "mod.json").is_file())
    if only:
        folders = [p for p in folders if p.name in only]
    sv = None
    if survey:
        from d5lib import skillmotions
        sv = skillmotions.Survey(skill_roots=folders)
    vp = None
    if voices:
        load_voice(w)
        sys.path.insert(0, str(KIT / "tools"))
        import check_installed_voices as civ
        probs, _ = civ.check(w.game, w.mods, set(p.name for p in folders))
        vp = {}
        for p in probs:                          # row voice ids are checked on World.chars in _voice
            if "char row" not in p:
                vp.setdefault(p.split(":", 1)[0], []).append(p.split(":", 1)[1].strip())
    return [check_pack(w, f, sv, vp, resident_override) for f in folders]


def to_json(results):
    return [dict(pack=r.pack, game=r.game, enabled=r.enabled, rows=r.rows, worst=r.worst(),
                 checks=[asdict(c) for c in r.checks]) for r in results]
