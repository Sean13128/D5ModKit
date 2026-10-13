"""Make a player installer: one .exe that installs the chosen mods into anyone's Disgaea 5 Complete (no Python, no
kit) and uninstalls them again byte-exact.  See docs/SHARING.md.

    python tools/export_pack.py OUT.exe --title "My Disgaea 5 mods" [--desc "..." | --desc-file notes.txt]
                                [--mods Outfit_System,DRPG_Outfits_Etna,...] [--keep-installed]

--mods: the mods to put in the package (default: the enabled ones, in load order).  When they differ from the
enabled set, the kit installs exactly them first, exports, and installs your usual set again afterwards (unless
--keep-installed).  The game must be closed.
"""
import argparse
import os
import sys
import time

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
from d5lib import modsys, package              # noqa: E402
from d5lib.gamefs import GameFS                 # noqa: E402

GAME = paths.require_game_dir()


def install(mods, log):
    inst = modsys.Installer(GAME, KIT, log=lambda *a: None)
    fs = GameFS(GAME, backup_resolver=inst.backup_resolver)
    ctx = modsys.build(fs, mods, log=lambda *a: None)
    inst.install(fs, ctx)
    log(f"installed {len(mods)} mod(s): " + ", ".join(m.id for m in mods))
    return modsys.Installer(GAME, KIT, log=lambda *a: None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--title", required=True)
    ap.add_argument("--desc", default="")
    ap.add_argument("--desc-file")
    ap.add_argument("--mods")
    ap.add_argument("--keep-installed", action="store_true")
    a = ap.parse_args()
    mm = modsys.ModManager(KIT)
    enabled = mm.enabled_mods()
    if a.mods:
        want = [x.strip() for x in a.mods.split(",") if x.strip()]
        order = {m.id: i for i, m in enumerate(enabled)}
        mods = [mm.get(x) for x in want]
        if any(m is None for m in mods):
            raise SystemExit("unknown mod: " + ", ".join(x for x, m in zip(want, mods) if m is None))
        mods.sort(key=lambda m: order.get(m.id, len(order)))
    else:
        mods = enabled
    missing = modsys.missing_requirements(mods)
    if missing:
        raise SystemExit("missing required mods: " + ", ".join(f"{m.id} needs {r}" for m, r in missing))
    desc = open(a.desc_file, encoding="utf-8").read() if a.desc_file else a.desc
    if not desc:
        desc = "Mods:\r\n" + "\r\n".join(f"  - {m.name}" + (f": {m.meta.get('description')}" if m.meta.get("description") else "")
                                          for m in mods)
    desc = desc.replace("\r\n", "\n").replace("\n", "\r\n")
    t = time.time()
    inst = install(mods, print)
    payload = os.path.splitext(a.out)[0] + ".payload"
    package.build_payload(inst, a.title, desc, "+".join(m.id for m in mods)[:120], payload, log=print)
    bad = package.verify_against(payload, GAME, log=None, sources=package.vanilla_sources(inst))
    if bad:
        raise SystemExit(f"{bad} file(s) did not rebuild from the package -- not written")
    package.write_installer(payload, a.out)
    os.remove(payload)
    print(f"-> {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB) in {time.time() - t:.0f}s")
    if [m.id for m in mods] != [m.id for m in enabled] and not a.keep_installed:
        install(enabled, print)


if __name__ == "__main__":
    main()
