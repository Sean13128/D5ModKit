"""Skill caster motions vs the animation bank a unit binds in battle (UNIQUESKILLS1, after the D1C hurt-pose lesson).

For every skill in a built unit's learn list: the caster motion ids the kit's simulator (``choreo.py``) says the
skill puts on the caster, mapped to animation ids the way the game does (motion m -> m*10+1 front / m*10+7 back,
109 -> 1051/1057, 151 -> 7011/7017; ``d5gui/skilledit/render.MOTION_BASE``), checked against the animation ids in:

* monster (body_type 1): the unit's own bank ``anm{sprite_id (+1 when sprite_id > 2000)}`` only;
* humanoid (body_type 0): that bank plus the shared resident humanoid block 1 (docs/ANM.md sec. 5).

Result per (unit, skill): ``ok``, ``fallback`` (absent, but vanilla runs the same absent animation for the same body type), ``missing`` (absent and
vanilla never does that) or ``unknown`` (choreo cannot resolve the skill).
Reads the clean Disgaea 5 copy in ``Disgaea Source/`` (vanilla script, banks, resident); no game is touched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CLEAN_GAME = Path(os.environ.get("D5_CLEAN_GAME", "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)"))
MOTION_BASE = {109: 1050, 151: 7010}
BANK = Path("files/Anime/ANM_HI_JP.dat")


def anims_of(motion):
    base = MOTION_BASE.get(motion, motion * 10)
    return (base + 1, base + 7)


class Survey:
    def __init__(self, game=None, skill_roots=()):
        from d5lib import anm, script, scriptpatch, skills
        from d5lib.gamefs import GameFS
        self.anm, self.script, self.scriptpatch = anm, script, scriptpatch
        self.fs = GameFS(str(game or CLEAN_GAME))
        self.raw = self.fs.read(scriptpatch.SCRIPT)
        self.vanilla = {e.id: e for e in script.ScriptFile.from_bytes(self.raw).events}
        self.sc = skills.with_mods(self.fs, [])
        self.resident1 = None
        self.cache, self.vbank, self.evcache, self.mskills = {}, {}, {}, {}
        for r in skill_roots:                          # other mods' skill rows (a learn list may name one)
            self._load_skills(Path(r))

    # ---------------------------------------------------------------- data
    def _load_skills(self, mod):
        p = mod / "patches/skills/skills.json"
        if p.is_file():
            d = json.loads(p.read_text())
            for sid, v in (d.get("skills") or {}).items():
                self.mskills.setdefault(int(sid), (mod, v.get("choreography"), d.get("events") or {}))

    def resident_ids(self):
        if self.resident1 is None:
            res = self.anm.parse(self.fs.read("Anime/ANM_HI_JP.dat/anm_resident.lzs"))
            blk = next(b for b in res.blocks if b.id == 1)
            self.resident1 = {a.id for a in blk.animations}
        return self.resident1

    def bank_ids(self, mod, body):
        p = Path(mod) / BANK / f"anm{body:05d}.lzs"
        key = str(p) if p.is_file() else body
        if key not in self.vbank:
            try:
                data = p.read_bytes() if p.is_file() else self.fs.read(f"Anime/ANM_HI_JP.dat/anm{body:05d}.lzs")
                self.vbank[key] = {a.id for a in self.anm.load(data).blocks[0].animations}
            except Exception:                              # noqa: BLE001 - no such bank
                self.vbank[key] = None
        return self.vbank[key]

    def events(self, mod, text):
        if not text:
            return self.vanilla
        key = str(mod)
        if key not in self.evcache:
            sf = self.script.ScriptFile.from_bytes(self.raw)
            self.scriptpatch.apply(sf, {"events": text})
            self.evcache[key] = {e.id: e for e in sf.events}
        return self.evcache[key]

    def caster(self, sid):
        """sorted motion ids of the skill's caster, or None (unknown)."""
        from d5lib import choreo
        if sid in self.cache:
            return self.cache[sid]
        ev, root = self.vanilla, None
        try:
            root = self.sc.root_of(sid)
        except Exception:                                  # noqa: BLE001
            root = None
        if sid in self.mskills:                            # a mod's own row: its choreography (and events)
            mod, root, text = self.mskills[sid]
            ev = self.events(mod, text)
        out = None
        if root is not None and int(root) in ev:
            ctx = choreo.Context(loading=True, in_battle=(1, 2010))
            ctx.vars[60201], ctx.vars[64000] = 0, 1
            try:
                tl = choreo.simulate(ev, int(root), ctx)
                out = sorted({m for _, _, m, _ in tl.motions(choreo.CASTER) if isinstance(m, int)})
            except Exception:                              # noqa: BLE001
                out = None
        self.cache[sid] = out
        return out

    def precedent(self):
        """{(body_type, animation id)} the vanilla game itself runs with the animation absent from the unit's bank.

        Measured on the clean char.dat (every vanilla row with a learn list and a bank): 41% of its learn-list skills
        put a caster motion on a unit whose bank lacks the animation, and the game plays on (it falls back to a stand
        pose; render.SpriteCache.anim_for mirrors that).  So absent != frozen; a pair vanilla never has is the risk."""
        if getattr(self, "_precedent", None) is None:
            from d5lib import database
            t = database.load_table("char.dat", self.fs.read("Database/Database_0.dat/char.dat"))
            out = set()
            for r in t.rows:
                n, sp = min(int(r["learn_count"] or 0), 16), int(r["sprite_id"] or 0)
                if not n or not sp:
                    continue
                kind = int(r["body_type"] or 0)
                ids = self.bank_ids("/nonexistent", sp + (1 if sp > 2000 else 0))
                if ids is None:
                    continue
                if kind == 0:
                    ids = ids | self.resident_ids()
                for i in range(1, n + 1):
                    for x in self.caster(int(r[f"learn{i}_skill"] or 0)) or []:
                        out |= {(kind, a) for a in anims_of(x) if x and a not in ids}
            self._precedent = out
        return self._precedent

    # ---------------------------------------------------------------- check
    def status_of(self, mod, sid):
        """ok / fallback / missing / unknown for one skill on the (first) char row of a built mod folder."""
        row = (json.loads((Path(mod) / "patches/db/char.dat.json").read_text()).get("added") or [{}])[0]
        return self._status(Path(mod), row, int(sid))["status"]

    def check_mod(self, mod):
        """[{unit, skill, status, missing:[(motion, anim ids absent)]}] for every learn-list skill of the mod's char rows."""
        mod = Path(mod)
        p = mod / "patches/db/char.dat.json"
        if not p.is_file():
            return []
        self._load_skills(mod)
        out = []
        for row in json.loads(p.read_text()).get("added") or []:
            n = min(int(row.get("learn_count") or 0), 16)
            sids = [int(row.get(f"learn{i}_skill") or 0) for i in range(1, n + 1)]
            sids = [s for s in sids if s]
            if not sids:
                continue
            for sid in sids:
                out.append(self._status(mod, row, sid))
        return out

    def _status(self, mod, row, sid):
        sprite = int(row.get("sprite_id") or 0)
        body = sprite + (1 if sprite > 2000 else 0)
        kind = int(row.get("body_type") or 0)
        ids = self.bank_ids(mod, body)
        if ids is not None and kind == 0:
            ids = ids | self.resident_ids()
        m = self.caster(sid)
        rec = dict(unit=int(row.get("id", 0)), mod=mod.name, sprite=body, skill=sid)
        if m is None:
            rec["status"] = "unknown"
        elif ids is None:
            rec.update(status="unknown", note="no bank anm%05d in the mod or the game" % body)
        else:
            miss = [(x, [a for a in anims_of(x) if a not in ids]) for x in m if x and any(a not in ids for a in anims_of(x))]
            prec = self.precedent()
            hard = [(x, a) for x, a in miss if any((kind, i) not in prec for i in a)]
            rec.update(status="missing" if hard else "fallback" if miss else "ok", missing=hard or miss)
        return rec
