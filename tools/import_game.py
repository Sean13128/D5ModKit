#!/usr/bin/env python3
"""One command rebuilds every in-scope character of a source game.

    python tools/import_game.py d4 [--only ID,...] [--out DIR] [--compare-installed] [--jobs N]

Writes `<out>/<game>/mods/<ModFolder>/...` (install-ready), `results.json` and `REPORT.md`.
Exit 0 only if every entry built, passed its gates, and nothing regressed against the
installed kit.  Offline: the installed kit, the game and saves are read-only.
Contract: Subprojects/Engine-Extensions/IMPORTCORE-INTERFACE.md.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SOURCE_ROOTS = {
    # d1c resolves the prepared source folder (SOURCEPREP4-D1C, d5lib/importers/_d1c_source.py);
    # pass --source-root (a romfs folder holding data/SUBDATA.DAT) for a one-off diagnostic run.
    # drpg resolves the prepared source folder (SOURCEPREP4-DRPG, d5lib/importers/_drpg_source.py);
    # --source-root names another prepared folder (one holding manifest.json).
    # dd2 resolves the prepared source folder (SOURCEPREP4-DD2, d5lib/importers/_dd2_source.py);
    # pass --source-root to point at a dump for a one-off run.
    # d4 resolves the prepared source folder (SOURCEPREP4-D4, d5lib/importers/_d4_source.py);
    # pass --source-root (the game folder) for a one-off diagnostic run.
}
D1_VOICE_SOURCE = Path("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 1 PC (Steam 405900)")   # Ogg voice banks (other games; D1C uses the prepared d1pc folder)
GAME = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
STATE = GAME / "D5ModKit/state/games/Disgaea_5_Complete-d8040a88"


def _d1c_voice_source(args):
    """D1C: the verified prepared Disgaea 1 PC folder (optional, voices only); other games keep their option."""
    if args.game == "drpg":
        return None                  # DRPG voices come from the prepared drpg folder (SOURCEPREP4-DRPG), not this option
    if args.game != "d1c":
        return str(D1_VOICE_SOURCE)
    from d5lib.importers import _d1c_source
    return _d1c_source.voice_source()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    games = sorted(p.stem for p in (ROOT / "d5lib/importers").glob("*.py")
                   if not p.name.startswith("_")
                   and "class Importer" in p.read_text(encoding="utf-8", errors="replace"))
    ap.add_argument("game", choices=games)
    ap.add_argument("--only", help="comma-separated entry ids or mod folder names")
    ap.add_argument("--out", type=Path, default=None,
                    help="output folder (default: ~/D5ModKit-import for dd2, the shared scratch folder otherwise)")
    ap.add_argument("--compare-installed", action="store_true",
                    help="also compare every rebuild against the installed pack (read-only); implies "
                         "--installed-reference")
    ap.add_argument("--installed-reference", action="store_true",
                    help="DD2: read the installed pack for the baseline/icon/wheel/hold-blank references "
                         "(default: off, so a machine with no install builds the same packs from recorded rules)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--source-root", type=Path, help="original game copy (default: Disgaea Source)")
    ap.add_argument("--game-path", type=Path, default=None,
                    help="Disgaea 5 install (default: the folder the kit resolves; dd2 uses the same resolver)")
    ap.add_argument("--state", type=Path, default=None,
                    help="the kit's state folder for that install (default: derived from --game-path)")
    ap.add_argument("--extra-roots", type=Path, nargs="*", default=[],
                    help="more mod folders whose ids a build must not claim (default: installed mods, also the "
                         "live kit when D5_INSTALLED_MODS points elsewhere); LEASEGATE1 used-id gate")
    ap.add_argument("--keep-builds", action="store_true", help="keep intermediate build trees")
    ap.add_argument("--with-reviewed-abilities", action="store_true",
                    help="DD2: emit reviewed skills and evilities in a separate candidate build")
    ap.add_argument("--d4-faithful-palettes", action="store_true",
                    help="D4: keep every recoloured palette slot (CORED4B output) instead of trimming "
                         "to D4's own bank count; FOLLOW-UP until a live palette-wheel soak passes")
    ap.add_argument("--drpg-source-stats", type=Path, metavar="MASTER_CACHE",
                    help="DRPG: map RPG base parameters onto the donor stats (STATORACLE1, decision pending); "
                         "MASTER_CACHE = the JSON tools/stat_oracle.py --drpg-cache writes")
    ap.add_argument("--source-voices", action="store_true",
                    help="DRPG / DD2 / D1C: give each built pack its character's own source-game voice "
                         "(VOICE1; docs/SOURCE_VOICES.md) and run the voice gate")
    ap.add_argument("--source-specials", action="store_true",
                    help="D4 / D1C / DD2: the source's own special attacks with the source's numbers on leased "
                         "magic.dat rows (SPECIALS2; d5lib/importers/specials2.py) and its skill gate")
    ap.add_argument("--no-icon-pin", action="store_true",
                    help="DRPG: keep the list-icon rows the isolated build allocated instead of the installed pack's "
                         "pair (REPROFIX1; default pins them so a rebuild equals the install)")
    ap.add_argument("--no-d1c-hold-blank", dest="d1c_hold_blank", action="store_false",
                    help="D1C: leave blank key times blank instead of holding the nearest drawn pose "
                         "(REPROFIX2; default holds, which is what BLANKKEYS1 installed)")
    ap.add_argument("--no-d4-hold-blank", dest="d4_hold_blank", action="store_false",
                    help="D4: leave blank key times blank instead of holding the nearest drawn pose "
                         "(REPROFIX3; default holds, which is what BLANKKEYS1 installed)")
    ap.add_argument("--no-d4-stub-xform", dest="d4_stub_xform", action="store_false",
                    help="D4 humanoids (D4IDLE1): old path = re-root D4's idle stub 1001/1007 and rebuild it at (0, 0), "
                         "which draws the map idle 9 px low and 3 px right of D4 (default keeps D4's stub transform)")
    ap.add_argument("--no-d4-death-game-view", dest="d4_death_game_view", action="store_false",
                    help="D4 Death/Hugo (D4IDLE1): old path = DEATH2's duplicate-part rule on the kit's default walk plus "
                         "PT1030ANIM's part reorder, which lose the scythe shaft between the hands (default: the "
                         "rule judges the game's picture and D4's part order stays)")
    ap.add_argument("--no-d4-source-tracks", dest="d4_source_tracks", action="store_false",
                    help="D4 Toro/Kuro/Politan (D4IDLE1): old path = keep a D5 donor's motions (stand low, walk "
                         "retimed, hurt missing); default carries D4's own stand/walk/hurt and holds the source "
                         "stand for states D4 never drew")
    ap.add_argument("--no-d4-face-rule", dest="d4_face_rule", action="store_false",
                    help="D4 (D4FACE1): old path = a class face per colour (swf<body+k>, or one face with no rank slots) and "
                         "NPC faces keyed by the colour id; default draws the face the game draws (D4-FACE-02): the class "
                         "face on every rank slot, the colour id rounded down to tens for NPC rows")
    ap.add_argument("--no-d4-mesh-nodes", dest="d4_mesh_nodes", action="store_false",
                    help="D4 Death/Hugo/Des X/Prinny Kurtis (D4MESH1): old path = D4's mesh nodes (37 motions) are placed as "
                         "pivoted rectangles; default carries their stored vertices (D5 node mesh = 1, D4-ANM-08)")
    ap.add_argument("--no-dd2-hold-blank", dest="dd2_hold_blank", action="store_false",
                    help="DD2: leave blank key times blank instead of holding the nearest drawn pose "
                         "(REPROFIX3; default holds, which is what BLANKKEYS1 installed)")
    ap.add_argument("--no-dd2-source-fields", dest="dd2_source_fields", action="store_false",
                    help="DD2: keep the D5 donor's battle fields (MOV, JMP, throw, counter, crit, range, flying, "
                         "resistances, weapon aptitudes, kind/gender, immunity) instead of the source row's "
                         "(DD2FIELDS1; default carries the source row)")
    ap.add_argument("--no-dd2-cutin-fit", dest="dd2_cutin_fit", action="store_false",
                    help="DD2: stretch the source cut-in page (128x544) over the whole D5 cut-in texture (336x1080, "
                         "non-uniform scale) and give every class rank rank 0's strip, as before DD2CUTIN1; "
                         "default places the drawn 125x544 cell with one scale and carries each rank's own strip")
    ap.add_argument("--d1c-rig", choices=("auto", "on", "off"), default="auto",
                    help="D1C humanoids (D1CRIG1): auto (default) = a block-1 humanoid is built from its own sheets "
                         "driven by D5's resident humanoid motions (d5lib/d1crig.py) when the body fills D5's sheet "
                         "layout and every rig check passes, else the flattened path; on = rig or fail; off = the "
                         "flattened path (d1cart.poses + ownanim) for every entry, for comparison")
    ap.add_argument("--d1c-faces", choices=("hd", "hd-cutout", "installed", "opaque", "cutout"), default="hd",
                    help="D1C faces: hd (default, D1CHDFACE1) = Disgaea 1 Complete's own HD faces (SUBDATA.DAT "
                         "anmdat.fad swf####, the game's key: sprite + palette), on their white background; "
                         "hd-cutout = the same with the FACEFIX1 flood-fill cut-out; installed (REPROFIX1) = reuse "
                         "the installed pack's face pictures (the D1CFACE2 faces); opaque / cutout = the older "
                         "start.dat[73] face set (D1CFACE1B on white / FACEFIX1 cut-out)")
    args = ap.parse_args(argv)
    if args.with_reviewed_abilities and args.game != "dd2":
        ap.error("--with-reviewed-abilities is supported only by dd2")

    from d5lib import importcore
    source = args.source_root or SOURCE_ROOTS.get(args.game)
    if args.game in ("dd2", "d1c", "d4", "drpg") and args.source_root is None:
        # SOURCEPREP4: leave it unset so the importer resolves the prepared folder and its verified
        # manifest itself (a resolved path here would be treated as an unverified diagnostic root).
        source = None
    if source is None and args.game not in ("dd2", "d1c", "d4", "drpg"):
        ap.error(f"no source root for {args.game}; pass --source-root")
    if source is not None and not Path(source).is_dir():
        ap.error(f"source root {source} is not a folder")
    out = args.out
    if out is None:
        out = (Path.home() / "D5ModKit-import" if args.game in ("dd2", "d1c", "d4", "drpg")
               else Path("/Volumes/Data/ai-tmp/hermes/importcore/out"))
    # SOURCEPREP4: no machine path for the Disgaea 5 install; the kit's own resolver finds it.
    game_path = args.game_path
    state = args.state
    if args.game in ("dd2", "d1c", "d4", "drpg") and game_path is None:
        from d5lib import modsys, paths
        try:
            game_path = Path(paths.require_game_dir())
        except Exception as exc:                                   # noqa: BLE001
            ap.error(f"Disgaea 5 install not found ({exc}); pass --game-path")
        if state is None:
            state = Path(modsys.game_state_dir(str(game_path), str(ROOT)))
    game_path = game_path or GAME
    state = state or STATE
    os.environ["D5_IMPORT_OUT"] = str((out / args.game).resolve())
    previous_reviewed = os.environ.get("D5_DD2_REVIEWED_ABILITIES")
    os.environ["D5_DD2_REVIEWED_ABILITIES"] = "1" if args.with_reviewed_abilities else "0"
    from d5lib.importers._dd2_source import Dd2SourceError
    from d5lib.importers._d1c_source import D1cSourceError
    from d5lib.importers._d4_source import D4SourceError
    from d5lib.importers._drpg_source import DrpgSourceError
    from d5lib.importers._drpg_roster import DrpgRosterError
    try:
        summary = importcore.run(args.game, out_dir=out, only=args.only,
                                 compare=args.compare_installed, jobs=args.jobs,
                                 source_root=source, game_path=game_path,
                                 state_root=state, keep_builds=args.keep_builds,
                                 options=dict(installed_reference=(args.installed_reference
                                                                   or args.compare_installed
                                                                   or args.game not in ("dd2", "d1c", "d4", "drpg")),
                                              d4_faithful_palettes=args.d4_faithful_palettes,
                                              source_voices=args.source_voices,
                                              source_specials=args.source_specials,
                                              d1c_faces=args.d1c_faces,
                                              d1c_hold_blank=args.d1c_hold_blank,
                                              d1c_rig=args.d1c_rig,
                                              d4_hold_blank=args.d4_hold_blank,
                                              d4_stub_xform=args.d4_stub_xform,
                                              d4_death_game_view=args.d4_death_game_view,
                                              d4_source_tracks=args.d4_source_tracks,
                                              d4_face_rule=args.d4_face_rule,
                                              d4_mesh_nodes=args.d4_mesh_nodes,
                                              dd2_hold_blank=args.dd2_hold_blank,
                                              dd2_source_fields=args.dd2_source_fields,
                                              dd2_cutin_fit=args.dd2_cutin_fit,
                                              no_icon_pin=args.no_icon_pin,
                                              dd2_reviewed_abilities=args.with_reviewed_abilities,
                                              d1_voice_source=_d1c_voice_source(args),
                                              extra_roots=[str(p) for p in args.extra_roots],
                                              **(dict(drpg_stats="source",
                                                      drpg_master_cache=str(args.drpg_source_stats))
                                                 if args.drpg_source_stats else {})),
                                 log=lambda s: print(s, flush=True))
    except (Dd2SourceError, D1cSourceError, D4SourceError, DrpgSourceError, DrpgRosterError) as exc:
        # A missing/failed prepared-source row is a refusal, not a crash: name the files and exit 2.
        ap.error(str(exc))
    finally:
        if previous_reviewed is None:
            os.environ.pop("D5_DD2_REVIEWED_ABILITIES", None)
        else:
            os.environ["D5_DD2_REVIEWED_ABILITIES"] = previous_reviewed
    print(f"\n{summary['built']}/{summary['total']} built, {summary['gates_passed']} with all gates, "
          f"{len(summary['regressions'])} regression(s), {summary['seconds']}s")
    print(f"results: {summary['out']}/results.json")
    return summary["exit"]


if __name__ == "__main__":
    raise SystemExit(main())
