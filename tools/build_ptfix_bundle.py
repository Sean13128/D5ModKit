#!/usr/bin/env python3
"""Assemble the PTFIX bundle: LIVE5_TEST's 80 enabled mods, with our fixed folders and tonight's data fixes.

  python tools/build_ptfix_bundle.py <out dir>            # e.g. Builds/LIVE5_TEST2-20261027

Sources (read-only):
  * Builds/LIVE4_SAFE2-20261027/mods  - DEDUP2's re-leased packs (our folders, when present)
  * Builds/LIVE5-20261027b/mods       - what LIVE5_TEST installed (everything else)
  * <kit>/profiles/LIVE5_TEST/load_order.json - the enabled set, unchanged
Fixes applied to the copied folders (never to the sources):
  C1  every Skill.dat description becomes a valid printf format (d5lib/textfmt, tools/fix_evility_formats)
  C3  the four class families that fell back to a vanilla voice of the wrong gender get a male one
  C6  Noel's two leader skills get their RPG names and English descriptions (no Japanese left)
  C7  Citri Smart's class title shortened to fit the box
Writes a per-mod tree_sha256 inventory, LEASES.json, the profile directory and INSTALL.md. Nothing is installed.
"""
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from d5lib import textfmt                    # noqa: E402

PROJECT = "/Volumes/Data/Projects/D5"
# Sean's own mods (AGENTS.md): never edited, not even in a bundle copy.  Their own malformed evility
# descriptions stay as they are and are reported instead (PTFIX-REPORT §C1).
SEAN_MODS = {"Outfit_System", "Girl_Laharl_Outfits", "Zed", "Thunderlady", "My_Mod"}


def is_seans(name):
    return name in SEAN_MODS or name.startswith("DRPG_Outfits_")
KIT = os.path.join(PROJECT, "Local", "Installed D5ModKit")
SAFE2 = os.path.join(PROJECT, "Builds", "LIVE4_SAFE2-20261027", "mods")
LIVE5B = os.path.join(PROJECT, "Builds", "LIVE5-20261027b", "mods")
PROFILE_SRC = os.path.join(KIT, "profiles", "LIVE5_TEST")
DROP_FROM_PROFILE = {"D4_ArmorKnight_1080_PILOT"}   # C2: installed, not enabled
NEW_PROFILE = "LIVE5_TEST2"

# C3: (class name prefix, wrong voice, right voice, why).  The voice packs we ship cover most D4 classes
# (9000+); these four families have no D4 voice set, so the importer fell back to a vanilla voice by sound
# family without checking gender, and landed on a female one.
VOICE_FIX = [
    ("Armor Knight (D4)", 1150, 1220, "1150 is vanilla Armor Knight, a female class; 1220 is Dark Knight (male, armoured)"),
    ("Mystic Beast (D4)", 2190, 2170, "2190 is vanilla Nine-Tails, a female class; 2170 is Bear (male beast)"),
    ("Rifle Demon (D4)", 2130, 2080, "2130 is vanilla Sea Angel, a female class; 2080 is Winged Warrior (male)"),
    ("Death Saber (D4)", 2070, 2150, "2070 is vanilla Slumber Cat, a female class; 2150 is Chimera (male)"),
]
# C7: the Recruiter class box holds 20 characters (vanilla's longest title is 'Generic Human Dummy' = 19);
# PTFIX-REPORT §C7 has the measurement.
TITLE_FIX = [("Apothecary of House Smart", "Smart Apothecary")]
# C6: Noel's RPG leader skills (Research/source-packs/drpg/mapping.json, characters[Noel].leader_skills)
NOEL_CHAR_ID = 267           # the rebuilt DRPG sample's char row (LIVE4_SAFE2)
NOEL_SKILL_ORDER = [
    ("Holy Field",
     "Heals own HP each round. (RPG: Holy Field - party HP regen at turn start)"),
    ("Astral Protect",
     "Reduces damage taken by nearby allies. (RPG: Astral Protect - party takes less normal-attack damage)"),
]


def tree(root):
    h = hashlib.sha256()
    n = files = 0
    for base, dirs, names in os.walk(root):
        dirs.sort()
        for f in sorted(names):
            p = os.path.join(base, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            data = open(p, "rb").read()
            h.update(rel.encode())
            h.update(b"\0")
            h.update(hashlib.sha256(data).hexdigest().encode())
            h.update(b"\n")
            n += len(data)
            files += 1
    return h.hexdigest(), files, n


def patch_file(mod_dir, member):
    p = os.path.join(mod_dir, "patches", "db", member)
    if not os.path.isfile(p):
        return None, None
    with open(p, encoding="utf-8-sig") as fh:
        return p, json.load(fh)


def db_rows(patch):
    return list(patch.get("added") or []) + list((patch.get("rows") or {}).values())


def rellease_sample_leaderskills(mods_out, order, mod_name, changes, taken=None):
    """Move a DRPG sample's leader-skill rows off ids a D4 class pack also appends.

    DEDUP2 re-leased the samples' char rows, outfit slots and personality ids but not these Skill.dat rows:
    Noel's 7120/7121, Citri's 7110 and Melodia's 7100 are also appended by D4_Class_2020/1050/1010, so one
    of the two rows is lost and a D4 unit can show the sample's aura.  This re-leases them at the bundle
    source with the same tool DEDUP2 used (`d5lib/rellease`) and repoints the sample's own references.
    """
    from d5lib import modclaims, ownership, rellease, database

    pack = os.path.join(mods_out, mod_name)
    others = modclaims.scan_mods(mods_out, only=[m for m in order if m != mod_name])
    vanilla = database.load_table(
        "Skill.dat",
        open(os.path.join(PROJECT, "Private", "Overlord and Sorrow research", "community", "sorrow",
                          "research-20261014", "database", "files", "Skill.dat"), "rb").read())
    van = {"Skill.dat": {int(r["id"]) for r in vanilla.rows} | set(taken or ())}
    plan_ = rellease.plan(pack, others, van, ownership.load())
    if not plan_.ok:
        raise SystemExit(f"{mod_name}: unfixable ids: {plan_.as_dict()['unfixable']}")
    if not plan_.leases:
        return
    tmp = pack + ".rellease"
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    rellease.apply(pack, tmp, plan_)
    # the extension table (.d5el) is keyed by evility id: follow the re-lease or the behaviour stays behind
    evp = os.path.join(tmp, "patches", "evilities", "evilities.json")
    mapping = plan_.map_for("Skill.dat")
    if os.path.isfile(evp) and mapping:
        ev = json.load(open(evp, encoding="utf-8"))
        table = ev.get("evilities") or {}
        moved = {}
        for key, val in table.items():
            moved[str(mapping.get(int(key), int(key)))] = val
        ev["evilities"] = moved
        with open(evp, "w", encoding="utf-8") as fh:
            json.dump(ev, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    inner = os.path.join(tmp, os.path.basename(pack))     # apply() treats `tmp` as the mods root
    shutil.rmtree(pack)
    os.replace(inner, pack)
    shutil.rmtree(tmp, ignore_errors=True)
    for lease in plan_.leases:
        changes.append(dict(mod=mod_name, kind="rellease", id=lease.old, new=lease.new,
                            why=f"{lease.reason} (evility_id band)"))
        if taken is not None:
            taken.add(lease.new)


def rellease_remaining_duplicates(mods_out, order, changes):
    """Last pass: any id two of our folders still append goes to the later one in the load order."""
    from d5lib import modclaims, ownership, rellease

    for _round in range(10):
        scan = modclaims.scan_mods(mods_out, only=order)
        findings = modclaims.duplicate_findings(scan)
        rows = [(f.table if hasattr(f, "table") else f.kind, f) for f in findings]
        if not findings:
            return
        by_pack = {}
        for f in findings:
            member = f.table if hasattr(f, "table") else f.__dict__.get("table")
            holders = list(f.holders) if hasattr(f, "holders") else []
            if not member or not holders:
                raise SystemExit(f"cannot read finding {f!r}")
            keeper = next((h for h in order if h in holders), None)
            later = [h for h in holders if h != keeper and h in order]
            if not later:
                raise SystemExit(f"{member}[{f.rid}]: no later holder to re-lease: {holders}")
            yield_from = later[-1] if len(later) > 1 else later[0]
            by_pack.setdefault(yield_from, {}).setdefault(member, set()).add(int(f.rid))
        if not by_pack:
            raise SystemExit(f"duplicates with no pack to re-lease: {[str(f) for f in findings]}")
        for pack_name, only in sorted(by_pack.items()):
            pack = os.path.join(mods_out, pack_name)
            others = modclaims.scan_mods(mods_out, only=[m for m in order if m != pack_name])
            plan_ = rellease.plan(pack, others, {}, ownership.load(), only_ids=only)
            if not plan_.ok or not plan_.leases:
                raise SystemExit(f"{pack_name}: could not re-lease {only}: {plan_.as_dict()}")
            tmp = pack + ".rellease"
            if os.path.exists(tmp):
                shutil.rmtree(tmp)
            rellease.apply(pack, tmp, plan_)
            inner = os.path.join(tmp, os.path.basename(pack))
            shutil.rmtree(pack)
            os.replace(inner, pack)
            shutil.rmtree(tmp, ignore_errors=True)
            for lease in plan_.leases:
                changes.append(dict(mod=pack_name, kind="rellease", id=lease.old, new=lease.new,
                                    why=f"{lease.reason} (bundle duplicate pass)"))


def fix_char(mod_dir, changes):
    p, patch = patch_file(mod_dir, "char.dat.json")
    if not patch:
        return
    touched = False
    for r in db_rows(patch):
        name = str(r.get("name_EN") or "")
        for prefix, wrong, right, why in VOICE_FIX:
            if name.startswith(prefix) and int(r.get("voice_id") or 0) == wrong:
                r["voice_id"] = right
                changes.append(dict(mod=os.path.basename(mod_dir), kind="voice", id=r.get("id"),
                                    old=wrong, new=right, why=why))
                touched = True
        title = r.get("title_EN")
        for old, new in TITLE_FIX:
            if title == old:
                for lang in ("JP", "EN", "FR", "CHN", "KOR"):
                    r["title_" + lang] = new
                changes.append(dict(mod=os.path.basename(mod_dir), kind="title", id=r.get("id"),
                                    old=old, new=new, why="class title overruns the Recruiter box"))
                touched = True
    if touched:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(patch, fh, indent=1, ensure_ascii=False)
            fh.write("\n")


def fix_skill(mod_dir, changes):
    """C6: Noel's two leader skills get their RPG names and English descriptions."""
    p, patch = patch_file(mod_dir, "Skill.dat.json")
    if not patch or os.path.basename(mod_dir) != "DRPG_Sample_Noel":
        return
    touched = False
    mine = sorted((r for r in patch.get("added") or [] if int(r.get("owner") or 0) == NOEL_CHAR_ID),
                  key=lambda r: int(r.get("id") or 0))
    for idx, r in enumerate(mine):
        rid = int(r.get("id") or 0)
        if idx < len(NOEL_SKILL_ORDER):
            name, desc = NOEL_SKILL_ORDER[idx]
            for lang in ("JP", "EN", "FR", "CHN", "KOR"):
                r["name_" + lang] = name
                r["desc_" + lang] = textfmt.format_text(desc)
            old = r.get("name_EN")
            changes.append(dict(mod=os.path.basename(mod_dir), kind="skill-name", id=rid,
                                old=old, new=name, why="RPG source name (mapping.json leader_skills)"))
            touched = old != name or True
    if touched:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(patch, fh, indent=1, ensure_ascii=False)
            fh.write("\n")


def fix_descs(mod_dir, changes):
    """C1: every Skill.dat description must be a valid printf format."""
    p, patch = patch_file(mod_dir, "Skill.dat.json")
    if not patch:
        return 0
    n = 0
    for r in db_rows(patch):
        for field in textfmt.fix_row(r):
            n += 1
    if n:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(patch, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        changes.append(dict(mod=os.path.basename(mod_dir), kind="desc-format", count=n,
                            why="desc is the game's printf format; a bare % is invalid"))
    return n


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__.splitlines()[0])
    out = os.path.abspath(sys.argv[1])
    if os.path.exists(out):
        sys.exit(f"{out} exists; give a new directory")
    order = json.load(open(os.path.join(PROFILE_SRC, "load_order.json"), encoding="utf-8-sig"))
    # C2: the pilot is installed but not enabled.  Proven live (PTFIX live run): no unit of the save is on
    # class 1350-1355 any more (the armour-knight unit at roster 58 is class 14085 = D4_Class_1080), so the
    # pilot's rows are no longer needed, and dropping it removes the second male Armor Knight at the
    # Recruiter.  If a save ever has a class-135x unit again, re-enable the folder (it stays installed).
    dropped = [m for m in order if m in DROP_FROM_PROFILE]
    order = [m for m in order if m not in DROP_FROM_PROFILE]
    meta = json.load(open(os.path.join(PROFILE_SRC, "profile.json"), encoding="utf-8-sig"))
    mods_out = os.path.join(out, "mods")
    os.makedirs(mods_out)
    install_all = list(order) + dropped          # every folder is copied; only `order` is enabled
    changes, missing, origin = [], [], {}
    for name in install_all:
        src = os.path.join(SAFE2, name)
        origin[name] = "LIVE4_SAFE2 (DEDUP2 re-lease)"
        if not os.path.isdir(src):
            src = os.path.join(LIVE5B, name)
            origin[name] = "LIVE5-20261027b (installed copy)"
        if not os.path.isdir(src):
            missing.append(name)
            continue
        shutil.copytree(src, os.path.join(mods_out, name))
    if missing:
        sys.exit(f"missing source folders: {missing}")

    taken = set()
    for name in ("DRPG_Sample_Melodia", "DRPG_Sample_Citri", "DRPG_Sample_Noel"):
        if name in order:
            rellease_sample_leaderskills(mods_out, order, name, changes, taken)
    rellease_remaining_duplicates(mods_out, order, changes)

    for name in install_all:
        d = os.path.join(mods_out, name)
        if is_seans(name):
            if os.path.isfile(os.path.join(d, "patches", "db", "Skill.dat.json")):
                changes.append(dict(mod=name, kind="skipped", why="Sean's own mod: not edited, malformed "
                                    "descriptions reported instead"))
            continue
        fix_char(d, changes)
        fix_skill(d, changes)
        fix_descs(d, changes)

    # inventory
    lines = ["# PTFIX bundle (LIVE5_TEST2) — mod inventory",
             "# tree_sha256 = sha256 over 'relpath\\0sha256(file)' for every file, in sorted path order",
             "# mod\tfiles\tbytes\ttree_sha256\torigin"]
    inv = {}
    for name in install_all:
        d = os.path.join(mods_out, name)
        sha, files, nbytes = tree(d)
        inv[name] = dict(files=files, bytes=nbytes, tree_sha256=sha, origin=origin[name],
                         enabled=name in order)
        lines.append(f"{name}\t{files}\t{nbytes}\t{sha}\t{origin[name]}"
                     f"{'' if name in order else '\tdisabled'}")
    with open(os.path.join(out, "INVENTORY.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(out, "INVENTORY.json"), "w") as fh:
        json.dump(dict(mods=inv, enabled=order, count=len(order)), fh, indent=1)

    # leases: every id the bundle's enabled folders append
    from d5lib import modclaims
    scan = modclaims.scan_mods(mods_out, only=order)
    leases = scan.as_dict()
    with open(os.path.join(out, "LEASES.json"), "w") as fh:
        json.dump(leases, fh, indent=1)

    # the profile to install
    prof = os.path.join(out, "profile", NEW_PROFILE)
    os.makedirs(prof)
    json.dump(order, open(os.path.join(prof, "load_order.json"), "w"), indent=1)
    meta2 = dict(meta)
    meta2["name"] = NEW_PROFILE
    meta2["description"] = ("PTFIX 2026-10-27: LIVE5_TEST's mods with the C1-C7 playtest fixes "
                            "(evility description formats, D4 voice genders, Noel's RPG names, Citri's title); "
                            "the D4 Armor Knight pilot is installed but off (C2).")
    if dropped:
        changes.append(dict(mod=", ".join(dropped), kind="profile", old="enabled", new="installed-not-enabled",
                            why="C2: no unit of the save is on class 135x any more; the folder stays installed"))
    json.dump(meta2, open(os.path.join(prof, "profile.json"), "w"), indent=1)

    with open(os.path.join(out, "CHANGES.json"), "w") as fh:
        json.dump(changes, fh, indent=1)

    print(f"{out}: {len(order)} mods, {len(changes)} change records")
    for c in changes:
        print("  ", c["mod"], c.get("kind"), c.get("id"), c.get("old"), "->", c.get("new"), c.get("count", ""))


if __name__ == "__main__":
    main()
