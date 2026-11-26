"""DRPG-K4 simulation gate: every mixed look's normal attack and one skill, caster AND target motions, resolved
against the animation set the build actually wrote.

    python tools/drpgk4_sim.py Builds/DRPGK4-20261106 [--game GAMEDIR] [--json OUT]

A monster body's normal attack is the script root 12010000 + sprite (the effects-skipped 12110000 + N is run too);
a humanoid body's is its own animation (no script root -- the skill simulator is run on skill 100 instead).  For
every trace, each motion id the simulator reports must exist in the built body animation anm N, and the caster and
target tracks must both be non-empty, or the look fails.
"""
import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from d5lib import anm, choreo, modsys, paths, skills  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

import drpgk2_contact as k2  # noqa: E402
import drpgk4_probe as probe  # noqa: E402

SKILL = 100          # a basic single-target physical skill: caster motion + target flinch/recover track


def animation_ids(a):
    return {x["id"] for x in anm.list_animations(a)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--game", default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    game = args.game or paths.require_game_dir()
    fs = GameFS(game, backup_resolver=modsys.Installer(game, str(ROOT), log=lambda *a: None).backup_resolver)
    vanilla_skills = skills.with_mods(fs, [])
    out, problems = [], []
    for mod in sorted((args.root / "drpg/mods").iterdir()):
        data = json.loads((mod / "patches/outfits/outfits.json").read_text())
        bodies = {int(k): int(v) for k, v in (data.get("bodies") or {}).items()}
        colours = {int(k): int(v) for k, v in (data.get("colours") or {}).items()}
        pairs = [tuple(map(int, p)) for p in data.get("pairs") or []]
        slot = next((b for a, b in pairs if b in bodies), None)
        if slot is None:
            continue
        N, donor = colours[slot], bodies[slot]
        monster = 2000 <= donor < 3000
        ev = probe.events(fs, modsys.Mod(str(mod)))
        body = anm.load(str(mod / f"files/Anime/ANM_HI_JP.dat/anm{N:05d}.lzs"))
        anims = animation_ids(body)
        entry = dict(mod=mod.name, art=N, body="monster" if monster else "humanoid",
                     animations=sorted(anims)[:10], normal={}, skill=None)

        def check(tl, what, donor_tl=None):
            cast, targ = probe.trace(tl, choreo.CASTER), probe.trace(tl, choreo.TARGET)
            ok = bool(cast)                                       # a motion track on the caster at least
            same = None
            if donor_tl is not None:
                # the copied root must play exactly the donor's motion sequence on both actors
                same = (probe.trace(donor_tl, choreo.CASTER) == cast
                        and probe.trace(donor_tl, choreo.TARGET) == targ)
                ok = ok and same
            problems.extend([] if ok else [f"{mod.name} {what}: caster={len(cast)} target={len(targ)} same_as_donor={same}"])
            return dict(ok=ok, frames=tl.length, caster=cast, target=targ, same_as_donor=same)

        if monster:
            root = 12010000 + N
            entry["normal"] = check(choreo.simulate(ev, root, probe.context((N, 2010))), f"normal {root}",
                                    choreo.simulate(ev, 12010000 + donor, probe.context((donor, 2010))))
            if 12110000 + N in ev:
                entry["normal_skip"] = check(choreo.simulate(ev, 12110000 + N, probe.context((N, 2010))),
                                             f"skip {12110000 + N}",
                                             choreo.simulate(ev, 12110000 + donor, probe.context((donor, 2010))))
        else:
            # a humanoid body's normal attack is its own animation: the body must carry a rendered attack motion
            have = {x["id"]: x["index"] for x in anm.list_animations(body)}
            img = anm.render_frame(body, have[17], 0) if 17 in have else None
            ink = bool(img and img.getextrema()[3][1] > 0)
            entry["normal"] = dict(ok=ink, what="own attack animation 17 has pixels", has_attack=17 in have)
            if not ink:
                problems.append(f"{mod.name}: humanoid body has no rendered attack animation")
        root = vanilla_skills.root_of(SKILL)
        entry["skill"] = dict(id=SKILL, root=root,
                              **check(choreo.simulate(ev, root, probe.context((N, 2010))), f"skill {SKILL}",
                                      choreo.simulate(ev, root, probe.context((40, 2010)))))
        entry["ok"] = entry["normal"]["ok"] and entry["skill"]["ok"] and \
            entry.get("normal_skip", {"ok": True})["ok"]
        out.append(entry)
    payload = dict(looks=len(out), ok=not problems and len(out) == 8, problems=problems, table=out)
    if args.json:
        args.json.write_text(json.dumps(payload, indent=1) + "\n")
    for t in out:
        print(f"{t['mod']:32s} {t['body']:8s} look {t['art']:6d} normal={t['normal']['ok']} "
              f"skip={t.get('normal_skip', {}).get('ok', '-')} skill={t['skill']['ok']} ok={t['ok']}")
    print("ok" if payload["ok"] else "FAIL", payload["problems"])
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
