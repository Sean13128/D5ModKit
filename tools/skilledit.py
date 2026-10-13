"""skilledit -- edit what a skill looks like: its choreography (script.dat) and its effect pictures (Effect.dat).
See docs/SKILL_ANIMATIONS.md.  MOD = a mod folder name in mods/.  SKILL = a magic.dat skill id.

  python tools/skilledit.py info SKILL                      choreography, its events and effects (+ geometry, textures)
  python tools/skilledit.py assign MOD SKILL FROM           play the choreography of skill FROM (or event id 15xxxxxx)
  python tools/skilledit.py copy MOD SKILL [FROM]           editable copy (of FROM, default the skill's own)
  python tools/skilledit.py export MOD SKILL DIR            the copy's events -> DIR/<event>.txt (annotated)
  python tools/skilledit.py import MOD DIR                  DIR/*.txt -> the mod (checked by assembling)
  python tools/skilledit.py textures EFFECT DIR             an effect model's textures -> PNG
  python tools/skilledit.py picture MOD SKILL EFFECT INDEX PNG [--fit contain|cover|stretch] [--scale 1]
                                [--rotate 0] [--tile 1] [--brightness auto]
                                                            show PNG as texture INDEX of EFFECT in this skill
  python tools/skilledit.py preview [--solo SKILL:SLOT,SLOT]  send the enabled mods' scripts to the running game
                                                            (runtime live_reload; restart-free for choreography)
  python tools/skilledit.py commands                        the command reference
Effects (new or changed pictures) need Install + a game restart; choreography edits only need `preview`.
"""
import argparse
import os
import sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KIT)
from d5lib import paths  # noqa: E402
from d5lib import database, modsys, skills  # noqa: E402
from d5lib.gamefs import GameFS  # noqa: E402

GAME = paths.require_game_dir()


def fs():
    return GameFS(GAME, backup_resolver=modsys.Installer(GAME, KIT, log=lambda *x: None).backup_resolver)


def mod(name):
    p = os.path.join(KIT, "mods", name)
    if not os.path.isdir(p):
        sys.exit(f"no mod folder {p}")
    return modsys.Mod(p)


def skill_names(f):
    t = database.load_table("magic.dat", f.read(skills.MAGIC))
    return {r["id"]: r.get("name") or r.get("name_en") or "" for r in t.rows}


def cmd_info(a):
    f = fs()
    mods = modsys.ModManager(KIT).enabled_mods()
    sc = skills.with_mods(f, mods)
    sid = int(a.skill)
    root = sc.root_of(sid)
    owner = next((m.name for m in mods if str(sid) in (m.load_patch(skills.FOLDER, skills.DATA_FILE) or {})
                  .get("skills", {})), None)
    print(f"skill {sid}: choreography {root or 'default sequence ' + str(skills.DEFAULT_SCRIPT)}"
          + (f"  (set by mod {owner})" if owner else ""))
    if not root:
        return
    tree = sc.tree(root)
    print(f"  events: {', '.join(map(str, tree))}")
    members = skills.effect_members(f.read)
    for line in "\n".join(sc.text(e) for e in tree).splitlines():
        m = skills.EFFECT_RE.match(line)
        if not m:
            continue
        eid = int(m.group(2))
        info = skills.effect_info(f.read, eid, members, mods)
        slot = line.split()[1].rstrip(",")
        if info is None:
            print(f"  slot {slot:>3}: effect {eid} (missing!)")
            continue
        tex = ", ".join(f"#{t[0]} {t[2]}x{t[3]} {t[4]}" + (f"x{t[5]}" if t[5] > 1 else "") + (" additive" if t[6] else "")
                        for t in info["textures"])
        print(f"  slot {slot:>3}: effect {eid:4d} {info['geometry']:5s} {tex}"
              + (f"   (new: copy of {info['from']})" if info["from"] else ""))


def cmd_assign(a):
    f = fs()
    src = int(a.src)
    root = src if src >= skills.CHOREO_MIN else skills.with_mods(f, modsys.ModManager(KIT).enabled_mods()).root_of(src)
    if not root:
        sys.exit(f"skill {src} has no choreography of its own")
    skills.assign(mod(a.mod), a.skill, root)
    print(f"skill {a.skill} -> choreography {root}")


def cmd_copy(a):
    f = fs()
    sc = skills.with_mods(f, modsys.ModManager(KIT).enabled_mods())
    src = int(a.src) if a.src else int(a.skill)
    root = src if src >= skills.CHOREO_MIN else sc.root_of(src) or skills.DEFAULT_SCRIPT
    new = skills.make_custom(f, mod(a.mod), a.skill, root, sc)
    print(f"skill {a.skill} -> editable copy {new} (of {root}): {skills.custom_events(mod(a.mod), new)}")


def cmd_export(a):
    m = mod(a.mod)
    d = skills.load(m)
    root = d["skills"].get(str(int(a.skill)), {}).get("choreography")
    if not root or not skills.is_custom_choreo(root):
        sys.exit("the skill has no editable copy in this mod (use: copy)")
    os.makedirs(a.dir, exist_ok=True)
    for e in skills.custom_events(m, root):
        with open(os.path.join(a.dir, f"{e}.txt"), "w", encoding="utf-8") as fh:
            fh.write(skills.annotate(d["events"][str(e)]))
    print(f"{len(skills.custom_events(m, root))} event(s) -> {a.dir}")


def cmd_import(a):
    m = mod(a.mod)
    n = 0
    for fn in sorted(os.listdir(a.dir)):
        if fn.endswith(".txt") and fn[:-4].isdigit():
            with open(os.path.join(a.dir, fn), encoding="utf-8") as fh:
                skills.set_event(m, int(fn[:-4]), fh.read())
            n += 1
    print(f"{n} event(s) imported into {m.name}")


def cmd_textures(a):
    info = skills.effect_info(fs().read, int(a.effect))
    if not info:
        sys.exit("no such effect")
    os.makedirs(a.dir, exist_ok=True)
    for i, img, w, h, fmt, layers, add in info["textures"]:
        if img is not None:
            img.save(os.path.join(a.dir, f"effect{a.effect}_{i}_{w}x{h}{'_x%d' % layers if layers > 1 else ''}.png"))
    print(f"effect {a.effect} ({info['geometry']}): {len(info['textures'])} texture(s) -> {a.dir}")


def cmd_picture(a):
    prep = {"fit": a.fit, "scale": a.scale, "rotate": a.rotate, "tile": a.tile,
            "brightness": None if a.brightness == "auto" else float(a.brightness)}
    nid = skills.set_picture(fs(), mod(a.mod), a.skill, a.effect, a.index, a.png, **prep)
    print(f"skill {a.skill}: effect {a.effect} texture {a.index} -> effect {nid} (install + restart the game)")


def cmd_preview(a):
    solo = {}
    for s in a.solo or []:
        sid, _, slots = s.partition(":")
        solo[int(sid)] = [int(x) for x in slots.split(",") if x]
    data = skills.live_script(fs(), modsys.ModManager(KIT).enabled_mods(), solo)
    print("->", skills.send_live(GAME, data), f"({len(data)} bytes; the game loads it within half a second)")


def cmd_commands(a):
    for name, r in skills.reference().items():
        print(f"{name:16s} {', '.join(r['args']):60s} [{r['sure']}]\n{'':16s} {r['desc']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("info"); s.add_argument("skill")
    s = sub.add_parser("assign"); s.add_argument("mod"); s.add_argument("skill"); s.add_argument("src")
    s = sub.add_parser("copy"); s.add_argument("mod"); s.add_argument("skill"); s.add_argument("src", nargs="?")
    s = sub.add_parser("export"); s.add_argument("mod"); s.add_argument("skill"); s.add_argument("dir")
    s = sub.add_parser("import"); s.add_argument("mod"); s.add_argument("dir")
    s = sub.add_parser("textures"); s.add_argument("effect"); s.add_argument("dir")
    s = sub.add_parser("picture")
    for n in ("mod", "skill", "effect", "index", "png"):
        s.add_argument(n)
    s.add_argument("--fit", default="contain", choices=["contain", "cover", "stretch"])
    s.add_argument("--scale", type=float, default=1.0)
    s.add_argument("--rotate", type=float, default=0.0)
    s.add_argument("--tile", type=int, default=1)
    s.add_argument("--brightness", default="auto")
    s = sub.add_parser("preview"); s.add_argument("--solo", action="append")
    sub.add_parser("commands")
    a = p.parse_args()
    globals()["cmd_" + a.cmd](a)


if __name__ == "__main__":
    main()
