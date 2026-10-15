"""Quest.dat rows in words: what a quest asks for and when the Quest Shop offers it (d5lib/schemas/Quest.json has the
field meanings).  The Characters page uses it to show how a character is recruited."""
import html

STATS = {2: "ATK", 3: "DEF", 4: "INT", 5: "RES", 6: "HIT", 7: "SPD"}
WEAPONS = {1: "Fist", 2: "Sword", 3: "Spear", 4: "Bow", 5: "Gun", 6: "Axe", 7: "Staff"}


def recruit_quests(svc, cid):
    """Quest.dat rows whose reward is this character (reward 5) or class (6)"""
    try:
        q = svc.table("Quest.dat")
    except Exception:
        return []
    base = cid - cid % 10 if 1000 <= cid < 3000 else cid
    return [r for r in q.rows if (r["reward_type"] == 5 and r["reward_value"] == cid)
            or (r["reward_type"] == 6 and r["reward_value"] in (cid, base))]


def _name(svc, member, key, value, fallback):
    try:
        for r in svc.table(member).rows:
            if r[key] == value:
                return r["name_EN"] or fallback
    except Exception:
        pass
    return fallback


def objective(svc, r):
    """the quest's objective as a sentence"""
    t, a, n = r["cond_type"], r["cond_target1"], max(1, r["cond_count1"])
    opt, ov = r["cond_option"], r["cond_option_value"]
    more = [(r[f"cond_target{k}"], r[f"cond_count{k}"]) for k in (2, 3) if r[f"cond_target{k}"]]
    char = lambda c: "any enemy" if c == -1 else _name(svc, "char.dat", "id", c, f"class {c}")   # noqa: E731
    if t == 0:
        s = f"Defeat {n} × {char(a)}" + "".join(f", {m} × {char(b)}" for b, m in more)
        if opt == 1 and ov:
            s += f" (level {ov} or higher)"
    elif t == 1:
        s = f"Defeat {char(a)}" + (f" {n} times" if n > 1 else "")
    elif t in (2, 3):
        what = (r["cond_label1_EN"] or "any item") if a == -1 else _name(svc, "item.dat", "id", a, f"item {a}")
        s = f"Bring {n} × {what}" + (f" (item level {ov}+)" if opt == 4 and ov else "")
    elif t == 4:
        s = f"Clear the stage {_name(svc, 'dungeon.dat', 'map_id', a, f'map {a}')}"
    elif t == 6:
        s = f"Get {char(a)} to level {n}"
    elif t == 7:
        s = f"{WEAPONS.get(a, f'weapon {a}')} mastery level {n}"
    elif t == 8:
        s = f"Raise {STATS.get(a, f'stat {a}')} to {n}"
    else:
        s = f"Objective type {t} (target {a}, amount {n})"
    return s


def describe(svc, r):
    """rich text: title, client, text, objective, when it shows, the reward slot"""
    e = html.escape
    lines = [f"<b>Quest Shop: “{e(r['name_EN'])}”</b> (quest {r['id']}"
             + (", a request" if r["quest_kind"] == 1 else "") + ")"]
    if r["client_EN"]:
        lines.append(f"Client: {e(r['client_EN'])}")
    text = " ".join(x for x in (r[f"desc{k}_EN"] for k in range(1, 6)) if x)
    if text:
        lines.append(f"<i>{e(text)}</i>")
    lines.append(f"Objective: {e(objective(svc, r))}")
    pre = [p for p in (r[f"prereq_quest{k}"] for k in range(1, 5)) if p]
    need = []
    if pre:
        need.append("you complete " + ", ".join(f"“{e(_name(svc, 'Quest.dat', 'id', p, f'quest {p}'))}”" for p in pre))
    flags = [f for f in (r[f"req_flag{k}"] for k in range(1, 5)) if f]
    if flags:
        labs = []
        for f in flags:
            try:
                labs.append(svc.ref_label("FlagListDataBase.dat", f) or f"flag {f}")
            except Exception:
                labs.append(f"flag {f}")
        need.append("the story reaches " + ", ".join(e(str(x)) for x in labs))
    lines.append("Shows on the board: " + ("once " + " and ".join(need) if need else "from the start"))
    lines.append(f"<span style='color:#8a90b8'>Progress slot {r['sort_order']} in the save · change the quest in "
                 "Database Editor › Quest.dat</span>")
    return "<br>".join(lines)
