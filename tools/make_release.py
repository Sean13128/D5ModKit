"""Make a shareable copy of the kit: the D5 Mod Kit, the mods of a release profile, a private Python with everything
the kit needs, the guide -- one folder (and a .zip) that works on another PC.

    python tools/make_release.py OUT_DIR [--zip] [--profile outfits|all] [--mods A,B,...] [--drpg] [--no-runtime]
                                 [--previous OLD_RELEASE_FOLDER or its manifest.json]

Every release gets manifest.json (every file with its SHA-1 and the version; d5lib.updater).  The GitHub release carries
only D5ModKit.zip: kits update themselves from it in place (d5lib.updater.apply writes the files that differ), and
players can copy it over their kit.  --previous also writes OUT_DIR/D5ModKit-update-<old>-to-<new>.zip (only what
changed since that release); it isn't attached any more.

OUT_DIR/D5ModKit is (re)made from scratch; --zip also writes OUT_DIR/D5ModKit.zip.

Profiles (which mods go in; --mods adds more by folder name):
    outfits (default)   the Outfit System and every outfit mod (Girl Laharl, DRPG Outfits *)
    all                 every mod in the kit
The Item World auto-battle is personal: never shared, whatever the profile (its mod, page, docs, Python and native
sources stay here; the shared runtime DLL is built without it, see d5lib/runtime.py).  The guide and README carry
edition markers: <!--mod:ID,ID-->...<!--/mod--> (kept only when one of those mods is in), a line ending in
<!--mod-line:ID--> (the same for one line), <!--full-->...<!--/full--> (this PC's copy only) and
<!--share: TEXT --> (shown only in a release; {OUTFIT_SUMMARY} becomes "N outfits for M characters").

Left out on purpose: state/ (this PC's backups of its own game), cache/ (rebuilt from the other player's game; only
the compiled runtime DLLs are kept so nobody needs a compiler), _research/ and _extracted/ (research), the Disgaea RPG
asset folders (the mods are already built from them; only the command-line builders of new DRPG outfits, classes and
monsters read them, and the guide tells the other player where to put their own copy.  --drpg copies the sprites,
faces and cut-ins the builders read, ~1 GB), the underscore test scripts, settings.json (the other PC chooses its own
game folder).
"""
import argparse
import fnmatch
import importlib.metadata as md
import json
import os
import re
import shutil
import sys
import time
import zipfile

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, KIT)

KIT_DIRS = ["d5lib", "d5gui", "tools", "docs", "mods", "partmaps", "SpriteSheet"]
KIT_FILES = ["D5ModKit.pyw", "README.md", "CHANGELOG.md", "START HERE - Guide.html"]
SKIP_DIRS = {"__pycache__", ".git", ".idea"}
SKIP_TOOLS = {"unlock_all_classes.py", "make_release.py.bak"}
SKIP_EXT = {".pyc", ".pdb", ".tmp", ".log"}
PACKAGES = ["PyQt6", "PyQt6-Qt6", "PyQt6_sip", "numpy", "pillow", "scipy", "pefile", "keystone-engine", "capstone",
            "soundfile", "cffi", "pycparser", "pip"]
PY_SKIP_LIB = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "ensurepip", "__pycache__", "lib2to3",
               }
DRPG_UPDATED = "DRPG Assets (Updated)"
DRPG_PARTS = [("Characters", "Sprites"), ("Characters", "Icons"), ("Characters", "Cut-Ins")]
PREVIOUS_UNKNOWN = "previous"         # the version of a release folder without manifest.json
NO_DEFLATE = {".png", ".jpg", ".jpeg", ".webp", ".zip", ".mp3", ".ogg"}

# which mods a release carries (folder names, * patterns)
PROFILES = {
    "outfits": ("the Outfit System, the outfit mods and Thunderlady",
                ["Outfit_System", "Girl_Laharl_Outfits", "DRPG_Outfits_*", "Thunderlady"]),
    "all": ("every mod", ["*"]),
}
# personal features: never shared (the mod, and the kit files only it uses)
PERSONAL_MODS = {"Item_World_Auto-Battle"}
PERSONAL_FILES = {
    "d5lib/autobattle.py", "d5lib/demonic.py", "d5gui/pages/autobattle.py", "docs/AUTOBATTLE.md",
    "docs/guide/autobattle.png", "tools/d5dev.py",
    "d5lib/native/d5pilot.inc.c", "d5lib/native/d5di.inc.c", "d5lib/native/d5menu.inc.c",
}
EDITION_DOCS = ["README.md", "CHANGELOG.md", "START HERE - Guide.html"]

LAUNCHER = r"""@echo off
rem Starts the D5 Mod Kit with its own Python (runtime folder); falls back to an installed Python.
cd /d "%~dp0"
if exist "runtime\pythonw.exe" (
    start "" "runtime\pythonw.exe" -s -E D5ModKit.pyw
) else (
    start "" pythonw D5ModKit.pyw
)
"""
CONSOLE = r"""@echo off
rem A command prompt for the kit's command-line tools (python = the kit's own Python).
cd /d "%~dp0"
if exist "runtime\python.exe" set "PATH=%~dp0runtime;%PATH%"
title D5 Mod Kit console
echo.
echo  D5 Mod Kit command line.  Examples (see the guide, "Command-line tools"):
echo.
echo    python tools\install_mods.py                       install the enabled mods
echo    python tools\drpg_outfits.py build 10              build Killia's Disgaea RPG outfits
echo    python tools\export_pack.py Pack.exe --title "My mods"   make a player installer
echo    python tools\new_drpg_class.py --help              new class from a Disgaea RPG unit
echo.
cmd /k
"""
PTH = "python310.zip\nDLLs\nLib\nLib\\site-packages\n..\nimport site\n"


def log(*a):
    print(*a, flush=True)


def copy_tree(src, dst, skip_file=None):
    n = 0
    for dp, dns, fns in os.walk(src):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        rel = os.path.relpath(dp, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for f in fns:
            if os.path.splitext(f)[1].lower() in SKIP_EXT:
                continue
            if skip_file and skip_file(f if rel == "." else os.path.join(rel, f)):
                continue
            shutil.copy2(os.path.join(dp, f), os.path.join(dst, rel, f))
            n += 1
    return n


def release_mods(profile, extra=()):
    """the mod folders a release carries: the profile's patterns + extra, never a personal mod; in load order"""
    mods_dir = os.path.join(KIT, "mods")
    have = sorted(d for d in os.listdir(mods_dir) if os.path.isfile(os.path.join(mods_dir, d, "mod.json")))
    pats = list(PROFILES[profile][1]) + list(extra)
    unknown = [x for x in extra if x not in have]
    if unknown:
        raise SystemExit(f"no such mod: {', '.join(unknown)}")
    picked = [m for m in have if any(fnmatch.fnmatchcase(m, p) for p in pats) and m not in PERSONAL_MODS]
    from d5lib.profiles import Profiles
    order = Profiles(KIT).active().load_order()          # the order of this kit's active profile
    first = [m for m in order if m in picked]
    picked = first + [m for m in picked if m not in first]
    # every mod a picked one needs must come along
    for m in picked:
        with open(os.path.join(mods_dir, m, "mod.json"), encoding="utf-8") as f:
            for req in json.load(f).get("requires") or []:
                if req not in picked:
                    raise SystemExit(f"{m} needs {req}: add it (--mods {req})")
    return picked


def outfit_summary(mods):
    """"N outfits for M characters" of the given mods (their outfits.json pairs: [character class, outfit class])"""
    pairs, hidden = set(), set()
    for m in mods:
        p = os.path.join(KIT, "mods", m, "patches", "outfits", "outfits.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            pairs |= {tuple(x) for x in d.get("pairs") or []}
            hidden |= set(d.get("hide") or [])          # taken off a character's list by a mod (e.g. Thunderlady)
    pairs = {(c, o) for c, o in pairs if o not in hidden}
    chars = {c for c, _ in pairs}
    return f"{len(pairs)} outfits for {len(chars)} characters"


def edition_text(text, mods, summary=""):
    """a release's copy of a guide / README: see the module doc for the markers"""
    def keep(ids):
        return any(i.strip() in mods for i in ids.split(","))
    # one line ending in <!--mod-line:ID-->
    lines = []
    for line in text.split("\n"):
        m = re.search(r"\s*<!--mod-line:([^>]*?)-->\s*$", line)
        if m:
            if not keep(m.group(1)):
                continue
            line = line[:m.start()]
        lines.append(line)
    text = "\n".join(lines)
    # blocks (innermost first: no nesting is used, but be safe)
    block = re.compile(r"<!--mod:([^>]*?)-->(.*?)<!--/mod-->\n?", re.S)
    while True:
        new = block.sub(lambda m: (m.group(2) + ("\n" if m.group(0).endswith("\n") else "")) if keep(m.group(1))
                        else "", text)
        if new == text:
            break
        text = new
    text = re.sub(r"<!--full-->.*?<!--/full-->\n?", "", text, flags=re.S)
    text = re.sub(r"<!--share:\s?(.*?)\s?-->", lambda m: m.group(1).replace("{OUTFIT_SUMMARY}", summary), text,
                  flags=re.S)
    return text


def stage_kit(out, mods):
    def personal(d, rel):
        return (d + "/" + rel.replace(os.sep, "/")) in PERSONAL_FILES

    for d in KIT_DIRS:
        src = os.path.join(KIT, d)
        if not os.path.isdir(src):
            continue
        if d == "tools":
            skip = lambda rel, d=d: (os.path.basename(rel).startswith("_") or os.path.basename(rel) in SKIP_TOOLS  # noqa
                                     or personal(d, rel))
        elif d == "d5lib":
            skip = lambda rel, d=d: (rel.startswith(os.path.join("bin", "")) and rel.endswith(".pdb")  # noqa
                                     or personal(d, rel))
        elif d == "mods":
            skip = lambda rel: (os.path.dirname(rel) == "" or rel.split(os.sep)[0] not in mods)  # noqa
        else:
            skip = lambda rel, d=d: personal(d, rel)  # noqa
        n = copy_tree(src, os.path.join(out, d), skip)
        log(f"  {d}: {n} files")
    # the release's mods, in load order (enabled = listed; the first start makes it the profile Default)
    with open(os.path.join(out, "mods", "load_order.json"), "w", encoding="utf-8") as f:
        json.dump(mods, f, indent=2)
    for dp, _, _ in os.walk(out, topdown=False):            # folders left empty by the skips (deepest first)
        if dp != out and not os.listdir(dp):
            os.rmdir(dp)
    summary = outfit_summary(mods)
    for f in KIT_FILES:
        if not os.path.exists(os.path.join(KIT, f)):
            continue
        if f in EDITION_DOCS:
            with open(os.path.join(KIT, f), encoding="utf-8") as fi:
                txt = edition_text(fi.read(), set(mods), summary)
            with open(os.path.join(out, f), "w", encoding="utf-8", newline="") as fo:
                fo.write(txt)
        else:
            shutil.copy2(os.path.join(KIT, f), os.path.join(out, f))
    with open(os.path.join(out, "Start D5 Mod Kit.bat"), "w", newline="\r\n") as f:
        f.write(LAUNCHER)
    with open(os.path.join(out, "D5 Mod Kit Console.bat"), "w", newline="\r\n") as f:
        f.write(CONSOLE)
    with open(os.path.join(out, "settings.json"), "w", encoding="utf-8") as f:
        json.dump({"language": "EN", "active_mod": None}, f, indent=2)
    filter_exe_data(out)
    # the compiled runtime DLLs, built from the release's own native sources (no auto-battle) and named by their
    # hash: a copy of the kit finds them in cache/ and needs no compiler
    from d5lib import runtime
    native = os.path.join(out, "d5lib", "native")
    cache = os.path.join(out, "cache")
    if runtime.has_autobattle(native):
        raise SystemExit("the release's native sources still hold the auto-battle")
    from d5lib import exemap
    for t in [exemap.Translator(exemap.KNOWN_SHA1)] + [exemap.translator_from_map(p) for p in exemap.shipped_maps()]:
        exemap.use(t)                                   # every checked build of the game: its own addresses
        runtime.build_core(log=lambda *a: None, native=native, cache=cache)
        runtime.build_loader(log=lambda *a: None, native=native, cache=cache)
    exemap.use(exemap.Translator(exemap.KNOWN_SHA1))
    for f in os.listdir(cache):                         # the compiler's side files (.pdb, .lib)
        if not f.endswith(".dll"):
            os.remove(os.path.join(cache, f))
    log(f"  cache: {', '.join(sorted(os.listdir(cache)))}")
    # the native LZS codec must look newer than its source (else a copy without a compiler skips it)
    now = time.time()
    os.utime(os.path.join(out, "d5lib", "bin", "d5lzs.dll"), (now, now))
    for d in ("state",):
        os.makedirs(os.path.join(out, d), exist_ok=True)


def filter_exe_data(out):
    """the game-address reference and the build maps keep only the addresses the release's own files use (none of
    the personal features')"""
    import glob
    from d5lib import exemap
    keep = {hex(a) for a in exemap.kit_addresses(out)}
    ref_path = os.path.join(out, "d5lib", "data", os.path.basename(exemap.REF_PATH))
    ref = exemap.load_reference(ref_path)
    n = len(ref["sites"])
    ref["sites"] = {k: v for k, v in ref["sites"].items() if k in keep}
    exemap.save_reference(ref, ref_path)
    for p in glob.glob(os.path.join(out, "d5lib", "data", "exe_map_*.json")):
        with open(p) as f:
            d = json.load(f)
        for k in ("map", "how", "manual", "manual_notes"):
            if k in d:
                d[k] = {a: v for a, v in d[k].items() if a in keep}
        d["missing"] = [a for a in d.get("missing", []) if a in keep]
        with open(p, "w") as f:
            json.dump(d, f, indent=0)
    log(f"  game addresses: {len(ref['sites'])} of {n} (the release's files)")


def stage_drpg(out):
    src_root = os.path.join(KIT, DRPG_UPDATED)
    n = 0
    for parts in DRPG_PARTS:
        src = os.path.join(src_root, *parts)
        if os.path.isdir(src):
            n += copy_tree(src, os.path.join(out, DRPG_UPDATED, *parts))
    ids = os.path.join(src_root, "Units IDs.txt")
    if os.path.exists(ids):
        shutil.copy2(ids, os.path.join(out, DRPG_UPDATED, "Units IDs.txt"))
    # faces / cut-ins only the older folder has
    old = os.path.join(KIT, "DRPG Assets")
    for sub_old, sub_new in ((("Chara Icons",), ("Characters", "Icons")), (("Cutins",), ("Characters", "Cut-Ins"))):
        d = os.path.join(old, *sub_old)
        if not os.path.isdir(d):
            continue
        have = set(os.listdir(os.path.join(src_root, *sub_new)))
        for f in os.listdir(d):
            if f.lower().endswith(".png") and f not in have:
                os.makedirs(os.path.join(out, "DRPG Assets", *sub_old), exist_ok=True)
                shutil.copy2(os.path.join(d, f), os.path.join(out, "DRPG Assets", *sub_old, f))
                n += 1
    log(f"  Disgaea RPG sprites / faces / cut-ins: {n} files")


def stage_runtime(out):
    rt = os.path.join(out, "runtime")
    base = sys.base_prefix
    for f in os.listdir(base):
        p = os.path.join(base, f)
        if os.path.isfile(p) and (f.lower().endswith((".exe", ".dll")) or f.upper().startswith("LICENSE")):
            if f.lower().startswith(("python", "vcruntime", "license")) or f.lower() in ("pythonw.exe",):
                os.makedirs(rt, exist_ok=True)
                shutil.copy2(p, os.path.join(rt, f))
    copy_tree(os.path.join(base, "DLLs"), os.path.join(rt, "DLLs"),
              lambda rel: os.path.basename(rel).lower().startswith(("_tkinter", "tcl", "tk", "_test")))
    lib = os.path.join(base, "Lib")
    os.makedirs(os.path.join(rt, "Lib"), exist_ok=True)
    for name in os.listdir(lib):
        if name in PY_SKIP_LIB:
            continue
        p = os.path.join(lib, name)
        if os.path.isdir(p):
            copy_tree(p, os.path.join(rt, "Lib", name), lambda rel: os.sep + "tests" + os.sep in os.sep + rel)
        elif not name.endswith(".pyc"):
            shutil.copy2(p, os.path.join(rt, "Lib", name))
    sp = os.path.join(rt, "Lib", "site-packages")
    os.makedirs(sp, exist_ok=True)
    total = 0
    for name in PACKAGES:
        dist = md.distribution(name)
        n = 0
        for f in dist.files or []:
            src = str(dist.locate_file(f))
            if not os.path.isfile(src) or src.endswith(".pyc") or "__pycache__" in str(f):
                continue
            rel = str(f)
            if rel.startswith(".."):                 # scripts outside site-packages (pip entry points): not needed
                continue
            dst = os.path.join(sp, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
        total += n
        log(f"  runtime: {name} {dist.version} ({n} files)")
    with open(os.path.join(rt, "python310._pth"), "w") as f:
        f.write(PTH)
    log(f"  runtime: Python {sys.version.split()[0]} + {total} package files")


def write_zip(out_dir, folder):
    zpath = os.path.join(out_dir, "D5ModKit.zip")
    tmp = zpath + ".part"
    n = 0
    with zipfile.ZipFile(tmp, "w", allowZip64=True) as z:
        for dp, dns, fns in os.walk(folder):
            dns.sort()
            for f in sorted(fns):
                p = os.path.join(dp, f)
                arc = os.path.relpath(p, out_dir)
                ext = os.path.splitext(f)[1].lower()
                z.write(p, arc, compress_type=zipfile.ZIP_STORED if ext in NO_DEFLATE else zipfile.ZIP_DEFLATED,
                        compresslevel=6)
                n += 1
    os.replace(tmp, zpath)
    log(f"-> {zpath}: {n} files, {os.path.getsize(zpath) / 1e9:.2f} GB")
    return zpath


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--zip", action="store_true")
    ap.add_argument("--drpg", action="store_true", help="also copy the Disgaea RPG sprites the builders read")
    ap.add_argument("--no-runtime", action="store_true")
    ap.add_argument("--runtime-only", action="store_true", help="(re)make only the runtime folder of OUT_DIR")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="outfits")
    ap.add_argument("--mods", default="", help="more mods (folder names, comma separated)")
    ap.add_argument("--previous", default="", help="the previous release (folder or manifest.json): update zip")
    a = ap.parse_args()
    out_dir = os.path.abspath(a.out)
    folder = os.path.join(out_dir, "D5ModKit")
    try:
        inside = os.path.commonpath([folder, KIT]) == KIT
    except ValueError:                      # another drive
        inside = False
    if inside:
        raise SystemExit("choose an output folder outside the kit")
    if a.runtime_only:
        shutil.rmtree(os.path.join(folder, "runtime"), ignore_errors=True)
        stage_runtime(folder)
        return
    if os.path.exists(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    t = time.time()
    mods = release_mods(a.profile, [m.strip() for m in a.mods.split(",") if m.strip()])
    log(f"profile {a.profile} ({PROFILES[a.profile][0]}): {len(mods)} mods -- {', '.join(mods)}")
    log("kit and mods ...")
    stage_kit(folder, mods)
    if a.drpg:
        log("Disgaea RPG assets ...")
        stage_drpg(folder)
    if not a.no_runtime:
        log("Python runtime ...")
        stage_runtime(folder)
    from d5lib import updater
    from d5lib.version import VERSION
    manifest = updater.make_manifest(folder, VERSION)
    with open(os.path.join(folder, updater.MANIFEST), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=0)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(folder) for f in fs)
    log(f"staged {folder}: {size / 1e9:.2f} GB in {time.time() - t:.0f}s ({len(manifest['files'])} files in the manifest)")
    if a.previous:
        prev = a.previous
        if os.path.isdir(prev):
            mp = os.path.join(prev, updater.MANIFEST)
            if not os.path.exists(mp) and os.path.isdir(os.path.join(prev, "D5ModKit")):
                prev = os.path.join(prev, "D5ModKit")
                mp = os.path.join(prev, updater.MANIFEST)
            if os.path.exists(mp):
                with open(mp, encoding="utf-8") as f:
                    old = json.load(f)
            else:                                       # a release from before manifests: made from its files
                old = updater.make_manifest(prev, PREVIOUS_UNKNOWN)
        else:
            with open(prev, encoding="utf-8") as f:
                old = json.load(f)
        up = os.path.join(out_dir, updater.update_name(old["version"], VERSION))
        changed, removed = updater.make_update(folder, manifest, old, up)
        log(f"-> {up}: {len(changed)} changed / new file(s), {len(removed)} removed, "
            f"{os.path.getsize(up) / 1e6:.1f} MB")
    if a.zip:
        write_zip(out_dir, folder)


if __name__ == "__main__":
    main()
