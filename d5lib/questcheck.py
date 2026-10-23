"""What a quest asks for (its objective) and whether the stages it points at exist.

A recruit quest the kit makes copies 'Combat Lecture' (quest 1), whose objective is to clear Dried Up Wasteland
(cond_type 4, cond_target1 = map 101).  The objective can instead be any stage -- one of the game's or a stage of
a mod -- or defeating enemies of a class.  A quest that asks for a stage of a mod that is switched off can never be
finished (the game's quest board would show "Clear ???"): `problems` finds those before an install.
"""
from . import database, dbpatch

QUEST = "Database/Database_0.dat/Quest.dat"
CHAR = "Database/Database_0.dat/char.dat"
DUNGEON = "Database/Database_0.dat/dungeon.dat"
CLEAR_STAGE, DEFEAT = 4, 0                 # Quest.dat cond_type


def set_objective(row, cond):
    """cond: {"type": 4, "target": map id} (clear that stage) or {"type": 0, "target": class id, "count": n}
    (defeat n of that class; -1 = any enemy).  None leaves the row as it is."""
    if not cond:
        return
    t = int(cond.get("type", CLEAR_STAGE))
    row.set("cond_type", t)
    row.set("cond_target1", int(cond.get("target", 101)))
    row.set("cond_count1", max(1, int(cond.get("count", 1))))
    for k in (2, 3):
        row.set(f"cond_target{k}", 0)
        row.set(f"cond_count{k}", 0)
    row.set("cond_option", 0)
    row.set("cond_option_value", 0)
    for f in row.keys():
        if f.startswith("cond_label"):
            row.set(f, "")


def objective_of(row):
    """the objective of a quest row as a cond dict (see set_objective)"""
    return {"type": int(row["cond_type"]), "target": int(row["cond_target1"]), "count": int(row["cond_count1"])}


# ------------------------------------------------------------------------------------------------ stages to pick from
def stage_choices(dungeon_table, vanilla_rows, dungeon_cls):
    """[(label, map id, is a mod's)] of the stages a quest can ask to clear: the listed ones (a story flag), the
    game's first; dungeon_cls = mapfile.DungeonRecord (not imported here: mapfile pulls numpy in)"""
    out = []
    for i, row in enumerate(dungeon_table.rows):
        rec = dungeon_cls(bytes(row.raw))
        mine = i >= vanilla_rows
        if not rec.title_id and not mine:
            continue
        if rec.map_id < 100 or rec.map_id >= 10000 and not mine:
            continue
        name = rec.name() or f"map{rec.map_id:05d}"
        if "(Demo)" in name:
            continue
        out.append((f"{name}  (map{rec.map_id:05d})" + ("  · your stage" if mine else ""), rec.map_id, mine))
    return out


# ------------------------------------------------------------------------------------------------ the check
def layered(fs, mods, name):
    t = database.load_table(name, fs.read(f"Database/Database_0.dat/{name}"))
    for m in mods:
        patch = m.load_patch("db", f"{name}.json")
        if patch:
            try:
                dbpatch.apply_patch(t, patch)
            except Exception:
                pass
    return t


def _map_files(fs):
    out = set()
    for arch in ("Map/Map_JP.dat", "Map/Map_EN.dat"):
        try:
            out |= {n.lower() for n in fs.list_members(arch)}
        except Exception:
            pass
    return out


def _mods_with_map(mods, name):
    name = "/" + name.lower()
    return [m for m in mods if any(f.lower().endswith(name) for f in m.list_files())]


def problems(fs, enabled, all_mods):
    """[{quest, title, who, map, stage, mod, quest_mod, text}] for quests of the enabled mods whose stage is not
    there: the stage's map is in no enabled mod and not in the game (mod: the switched-off mod that has it, or
    None), or the stage has no stage-list row any more.  `who` names the character / class the quest gives."""
    out = []
    try:
        q = layered(fs, enabled, "Quest.dat")
        c = layered(fs, enabled, "char.dat")
        from . import mapfile
        d = mapfile.DungeonTable(_final_dungeon(fs, enabled))
    except Exception:
        return out
    names = {}
    for r in c.rows:
        names.setdefault(int(r["id"]), r["name_EN"])
    maps = _map_files(fs)
    stage_rows = {rec.map_id: rec for rec in d.records}
    by_quest = _quest_owners(enabled)
    for r in q.rows:
        if dbpatch.is_placeholder_quest(r) or int(r["cond_type"]) != CLEAR_STAGE:
            continue
        qid = int(r["id"])
        mid = int(r["cond_target1"])
        if mid < 100:
            continue                                  # -1: any stage (the game's own training quests)
        name = f"map{mid:05d}.lzs"
        have = name in maps or bool(_mods_with_map(enabled, name))
        rec = stage_rows.get(mid)
        if have and rec is not None:
            continue
        if qid not in by_quest and have:
            continue                                  # a game quest about a game stage the game builds itself
        off = _mods_with_map([m for m in all_mods if all(m.id != e.id for e in enabled)], name)
        who = None
        if int(r["reward_type"]) in (5, 6):
            who = names.get(int(r["reward_value"]))
        stage = rec.name() if rec is not None else None
        text = (f"Quest “{r['name_EN']}”" + (f" (it gives {who})" if who else "") +
                f" asks to clear {stage or f'map{mid:05d}'}, ")
        if off:
            text += f"a stage of the mod “{off[0].name}”, which is switched off: the quest can't be finished."
        elif rec is None and have:
            text += "which is not in the stage list any more."
        else:
            text += "whose map no mod has any more: the quest can't be finished."
        out.append(dict(quest=qid, title=r["name_EN"], who=who, map=mid, stage=stage,
                        mod=off[0] if off else None, quest_mod=by_quest.get(qid), text=text))
    return out


def _quest_owners(mods):
    """{quest id: mod} for quests the mods add"""
    out = {}
    for m in mods:
        p = m.load_patch("db", "Quest.dat.json") or {}
        for r in p.get("added") or []:
            if "id" in r:
                out[int(r["id"])] = m
    return out


def _final_dungeon(fs, mods):
    """dungeon.dat as the mods leave it (its rows aren't schema rows: the kit edits them through mapfile)"""
    data = fs.read(DUNGEON)
    try:
        t = database.load_table("dungeon.dat", data)
        for m in mods:
            patch = m.load_patch("db", "dungeon.dat.json")
            if patch:
                dbpatch.apply_patch(t, patch)
        return t.to_bytes()
    except Exception:
        return data


def problem_texts(fs, enabled, all_mods):
    return [p["text"] for p in problems(fs, enabled, all_mods)]
