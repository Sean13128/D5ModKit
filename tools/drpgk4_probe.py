"""DRPG-K4 probe: choreography of a built mixed-body look (offline; reads only).

    python tools/drpgk4_probe.py MODDIR SPRITE [SKILL] [GAMEDIR]

Simulates the normal-attack root the engine starts for a unit of `SPRITE` (12010000 + sprite, and the effects-skipped
12110000 + sprite) and one skill, and prints the caster/target motion timeline each one produces.  The events are the
ones the build wrote (the mod's patches/script/script.json applied to the vanilla script), so this is the same table
the game would run with the mod enabled.  Nothing is written.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib import choreo, modsys, paths, script, scriptpatch, skills  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

NORMAL = (12010000, 12110000, 12210000)


def events(fs, mod):
    """vanilla script events + every event the mod writes (exactly what scriptpatch applies at build time)."""
    sf = script.ScriptFile.from_bytes(fs.read(scriptpatch.SCRIPT))
    patch = mod.load_patch("script", "script.json") or {}
    text = patch.get("events") or {}
    if text:
        scriptpatch.apply(sf, {"events": text})
    return {e.id: e for e in sf.events}


def context(sprites):
    ctx = choreo.Context(loading=True, in_battle=tuple(s for s in sprites if s))
    ctx.vars[60201] = 0
    ctx.vars[64000] = 1
    return ctx


def trace(tl, actor):
    return [[start, end, motion] for start, end, motion, _op in tl.motions(actor)][:12]


def main():
    mod, sprite = Path(sys.argv[1]), int(sys.argv[2])
    skill = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] else None
    game = sys.argv[4] if len(sys.argv) > 4 else paths.require_game_dir()
    fs = GameFS(game, backup_resolver=modsys.Installer(game, str(ROOT), log=lambda *a: None).backup_resolver)
    ev = events(fs, modsys.Mod(str(mod)))
    out = {"sprite": sprite, "roots": {}, "skill": None}
    for p in NORMAL:
        root = p + sprite
        if root not in ev:
            continue
        tl = choreo.simulate(ev, root, context((sprite, 2010)))
        out["roots"][root] = {"frames": tl.length, "caster": trace(tl, choreo.CASTER),
                              "target": trace(tl, choreo.TARGET)}
    if skill is not None:
        sc = skills.with_mods(fs, [])
        root = None
        try:
            root = sc.root_of(skill)
        except Exception:
            root = None
        if root is None and skill >= skills.CHOREO_MIN:
            root = skill if skill in ev else None
        if root is not None and root in ev:
            tl = choreo.simulate(ev, root, context((sprite, 2010)))
            out["skill"] = {"id": skill, "root": root, "frames": tl.length,
                            "caster": trace(tl, choreo.CASTER), "target": trace(tl, choreo.TARGET)}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
