"""SPECIALS2 post-pass: source special attacks with the source's numbers, for D4 / D1C / DD2 packs.

`plan(game, mod)` reads a built (or installed) pack folder and the source tables and decides, per source
learn-list entry, E / A / H (d5lib/srcskills.py).  `apply(mod, plan)` writes table files only:
patches/db/magic.dat.json (rows at leased ids), patches/skills/skills.json (the stand-in's choreography),
the learn fields of patches/db/char.dat.json and a `specials2` block in mod.json that labels every
adaptation.  Ids come from specials2-leases.json and are never recomputed; an id an installed pack already
teaches for the same source skill is kept (a save stores learned skills by magic.dat id: unit record
+0xCC0, 16-byte entries, id at +4, count at +0x2CC0; decomp unit_stats_skills_remove 0x14015C830).

Not the DRPG importer's: importers/_drpg_* and drpg-leases.json are read (id collisions) and never written.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .. import srcskills

HERE = Path(__file__).resolve().parent
LEASES = HERE / "specials2-leases.json"
BLOCK = (29000, 29999)          # measured free in vanilla, every installed mod and every lease file (tools/specials2.py)
LANGS = ("JP", "EN", "FR", "CHN", "KOR")
_LOCK = threading.Lock()
_CTX = {}


def context(game):
    """Source table + D5 reference + concordance, built once per process."""
    with _LOCK:
        if "d5" not in _CTX:
            _CTX["d5"] = srcskills.D5()
        if game not in _CTX:
            table, maps, handle = {"d4": srcskills.d4_table, "dd2": srcskills.dd2_table,
                                   "d1c": srcskills.d1c_table}[game]()
            _CTX[game] = dict(table=table, maps=maps, handle=handle,
                              conc=srcskills.Concordance(table, _CTX["d5"]))
        return _CTX["d5"], _CTX[game]


def source_ids(game, mod):
    """(source character id of the first rank, is_class)."""
    meta = json.loads((Path(mod) / "mod.json").read_text())
    si = meta.get("source_import") or {}
    cid = si.get("source_id") or (si.get("identity") or {}).get("character_id")
    if cid is None:
        raise ValueError(f"{Path(mod).name}: mod.json names no source character")
    return int(cid), "_Class_" in Path(mod).name


def learnset(game, src, cid):
    if game == "d4":
        c = src["handle"].chars.get(cid)
        return list(c["learnset"]) if c else None
    if game == "dd2":
        try:
            return list(src["handle"].learn_list(cid))
        except KeyError:
            return None
    from .. import d1skill
    try:
        got = d1skill.learnset(src["handle"].member(43), cid, "d1hd")["learn"]
    except (KeyError, ValueError):
        return None
    return [(int(e["skill"]), int(e["level"])) for e in got]


def _json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text()) if path.is_file() else default


def installed_state(mod):
    mod = Path(mod)
    char = _json(mod / "patches/db/char.dat.json", {})
    rows = char.get("added") or []
    magic = {int(r["id"]): r for r in (_json(mod / "patches/db/magic.dat.json", {}) or {}).get("added") or []}
    learn = []
    if rows:
        r = rows[0]
        learn = [(int(r.get(f"learn{i}_skill") or 0), int(r.get(f"learn{i}_level") or 0)) for i in range(1, 17)]
        learn = [x for x in learn if x[0]]
    return dict(rows=rows, magic=magic, learn=learn)


def plan(game, mod, leases=None, standins=None):
    """Per source learn entry: dict(src, level, label E/A/H, d5_id, standin, fields, notes, carried)."""
    d5, src = context(game)
    mod = Path(mod)
    cid, is_class = source_ids(game, mod)
    cid = (standins or {}).get("variant_of", {}).get(cid, cid)
    state = installed_state(mod)
    out = dict(mod=mod.name, game=game, source_character=cid, entries=[], kept=[])
    learn = learnset(game, src, cid)
    if learn is None or not state["rows"]:
        out["note"] = "no source character row" if learn is None else "no char.dat row in the pack"
        return out
    body = int(state["rows"][0].get("body_type") or 0)
    sprite = int(state["rows"][0].get("sprite_id") or 0)
    bank = d5.survey.bank_ids(mod, sprite + (1 if sprite > 2000 else 0)) or set()
    names = {}
    for sid, _ in state["learn"]:
        row = state["magic"].get(sid) or d5.rows.get(sid)
        if row is not None:
            names.setdefault(srcskills.norm(row["name_EN"]), sid)
    for sid, row in state["magic"].items():
        names.setdefault(srcskills.norm(row["name_EN"]), sid)
    used, tier, seen_names = set(), 0, {}
    leases = leases if leases is not None else load_leases()
    for sid, level in learn:
        s = src["table"].get(sid)
        if s is None:
            out["entries"].append(dict(src=sid, level=level, label="N", name=None, carried="missing",
                                       notes=["source learn id has no magic.dat row: the source gives the unit no such "
                                              "skill, nothing to import (D4SPEC1)"]))
            continue
        e = dict(src=sid, name=s["name"], level=level, notes=[],
                 source=dict(sp=s["sp"], power=s["power_raw"], element=srcskills.ELEMENTS.get(s["element"], s["element"]),
                             range=s["range"], attack_map=s["attack_map"], up=s["up"], down=s["down"],
                             effects=s["effects"]))
        have = names.get(srcskills.norm(s["name"]))
        old_standin = (standins or {}).get("by_skill", {}).get(sid)
        e["carried"] = _carried(have, state, d5, s, old_standin)
        e["installed_id"] = have if have else old_standin
        if s.get("group") == srcskills.MAGICHANGE_GROUP or (game in ("d4", "dd2") and sid >= 20000):
            e.update(label="H", notes=["Magichange move: held (DECISIONS 2026-10-29)" if game == "d4" else
                                       "DD2 mounted-attack row (id 20000+): needs the mount mode, held"])
            if have:
                e["d5_id"] = have
            out["entries"].append(e)
            continue
        key_name = srcskills.norm(s["name"])
        if key_name in seen_names:
            e.update(label="D", notes=[f"same special as source row {seen_names[key_name]} (the source lists it twice)"])
            out["entries"].append(e)
            continue
        seen_names[key_name] = sid
        twin, basis = d5.twin(s)
        if twin is not None and int(d5.rows[twin]["skill_group"]) != srcskills.MAGICHANGE_GROUP:
            copy = have if have in state["magic"] else None
            e.update(label="E", d5_id=copy or twin, twin=twin, basis=basis)
            if copy:
                e["notes"].append(f"installed copy {copy} of D5 {twin} kept (a save may hold it)")
            e["motion"] = d5.survey._status(mod, state["rows"][0], twin)["status"]
            used.add(twin)
            out["entries"].append(e)
            tier += 1
            continue
        fields, notes = _fields(s, src, d5)
        if fields is None and game == "d4" and notes == [NO_EFFECT] and _stub(src, sid):
            e.update(label="N", notes=[f"{NO_EFFECT} and its attack script holds no animation or damage "
                                       "step (2 opcodes): an empty stub in the source, nothing to import (D4SPEC1)"])
            out["entries"].append(e)
            continue
        if fields is None:
            e.update(label="H", notes=notes)
            if e["installed_id"]:
                e["d5_id"] = e["installed_id"]
                e["notes"].append(f"installed stand-in {e['installed_id']} kept as it is")
            out["entries"].append(e)
            continue
        prefer = old_standin
        own = None
        if game == "d4":                                 # SPECIALS2c: the body's own attack tracks
            if "script" not in src:
                src["script"] = srcskills.d4_script_motions(src["handle"])
            held = {a // 10 for a in bank if 4000 <= a < 4100 and a % 10 == 1}
            want = src["script"](sid)
            own = dict(bank=held, want=(want or frozenset()) & held)
            e["source"]["script_motions"] = sorted(want) if want is not None else None
        best = srcskills.pick_standin(s, body, mod, d5, fields.get("attack_map"), used, prefer, min(tier, 3), own)
        if best is None:
            e.update(label="H", notes=notes + ["no D5 skill whose caster motions this bank can play"])
            out["entries"].append(e)
            continue
        _, standin, status, geom = best[:4]
        if len(best) > 4:
            notes.append("own track: the stand-in calls motion(s) " + ", ".join(map(str, best[4]["calls"]))
                         + " of this body's bank (" + ("the numbers D4's own script names" if best[4]["match"] == 0 else
                                                        "shares a motion with D4's script" if best[4]["match"] == 1 else
                                                        "D4's script names none the bank holds") + ")")
            e["own_track"] = best[4]
        elif own is not None and own["bank"]:
            notes.append("generic animation: no D5 skill of matching reach, element and weight calls this body's own motions 400+")
        used.add(standin)
        q = d5.rows[standin]
        if fields.get("attack_map") is None:            # D1C spell-style row or a shape D5 lacks: the stand-in's
            for k in ("attack_map", "range", "area_flag", "range_flag"):
                fields[k] = int(q[k])
            notes.append("range and area: the stand-in's" + ("" if s.get("attack_map") else
                                                              " (the source stores no shape for this row)"))
        elif geom:
            notes.append("animation was authored for another range/area "
                         f"(stand-in range {int(q['range'])}, shape {int(q['attack_map'])})")
            fields["flag_468"] = 1 if fields["range"] else 0
        if status != "ok":
            notes.append("caster motion absent from the bank; vanilla-precedented fallback pose")
        key = f"{game}:{mod.name}:{sid}"
        new_id = have if have in state["magic"] else leases.get(key)
        if old_standin and old_standin in d5.rows:
            notes.append(f"earlier reviewed twin {old_standin} {d5.rows[old_standin]['name_EN'].strip()}: "
                         + ("kept as the animation" if old_standin == standin else f"replaced by {standin}"))
        e.update(label="A", d5_id=new_id, lease_key=key, tier=min(tier, 3), standin=standin, standin_name=q["name_EN"].strip(),
                 motion=status, fields=fields, notes=notes)
        out["entries"].append(e)
        tier += 1
    mapped = {e.get("d5_id") for e in out["entries"]} | {e.get("installed_id") for e in out["entries"]}
    has_source = any(e["label"] in "EA" for e in out["entries"])
    for sid, level in state["learn"]:
        if sid in mapped:
            continue
        row = state["magic"].get(sid) or d5.rows.get(sid)
        nm = row["name_EN"].strip() if row is not None else "?"
        if not has_source or (row is not None and int(row["skill_group"]) == srcskills.MAGICHANGE_GROUP):
            out["kept"].append(dict(d5_id=sid, level=level, name=nm,
                                    why="Magichange row" if has_source else "donor line (source has no mappable skill)"))
        else:
            out["kept"].append(dict(d5_id=sid, level=level, name=nm, dropped=True,
                                    why="earlier by-reference stand-in, replaced by the source's own rows"))
    return out


def _carried(have, state, d5, s, old_standin):
    if have is None:
        if old_standin and any(old_standin == sid for sid, _ in state["learn"]):
            return "donor (D5 skill under D5's name)"
        return "missing"
    if have in d5.rows:
        return "exact (D5's own row)"
    row = state["magic"][have]
    twin = d5.by_en.get(srcskills.norm(s["name"]))
    if twin and all(int(row[k]) == int(d5.rows[twin][k]) for k in ("sp_cost", "range", "attack_map", "effect1_value")):
        return "exact (copy of D5's row)"
    if s["sp"] is not None and int(row["sp_cost"]) == s["sp"] and int(row["element"]) == s["element"] \
            and (s["range"] is None or int(row["range"]) == s["range"]):
        return "adapted (source numbers)"
    return "adapted (stand-in's numbers under the source name)"


NO_EFFECT = "no effect stored in the source row"


def _stub(src, sid):
    """True when D4's attack script for `sid` is the empty two-opcode wrapper (no animation, no damage step)."""
    if "script_ops" not in src:
        src["script_ops"] = srcskills.d4_script_ops(src["handle"])
    n = src["script_ops"](sid)
    return n is not None and n <= 2


def _fields(s, src, d5):
    """Source numbers as D5 magic.dat fields, or (None, why) when the main effect has no D5 code."""
    notes = []
    if not s["effects"] and s["power_raw"] is None and s["game"] != "d1c":
        return None, [NO_EFFECT]
    if s["game"] != "d1c" and (not s["effects"] or s["effects"][0][0] != 1):
        return None, [f"main effect code {s['effects'][0][0] if s['effects'] else 0} is not damage: needs its own logic"]
    if s["formula"] not in (2, 3):
        return None, [f"formula class {s['formula']} (heal / support) has no stand-in rule"]
    f = dict(sp_cost=int(s["sp"]), element=int(s["element"]), height_up=int(s["up"]), height_down=int(s["down"]))
    val, basis = src["conc"].convert_power(s["formula"], s["power_raw"])
    if val is None:
        notes.append(f"power: the stand-in's (source power {s['power_raw']} recorded only; {basis})")
    else:
        f["effect1_value"] = val
        notes.append(f"power: source {s['power_raw']} -> D5 modifier {val} ({basis})")
    extra = []
    for code, value in (() if s["game"] == "d1c" else s["effects"][1:]):
        to = code if s["game"] == "dd2" else src["conc"].effect.get(code)
        if to is None:
            notes.append(f"secondary effect code {code} (value {value}) not carried: no shared skill maps it")
        else:
            extra.append((to, int(value)))
    f["effects"] = extra
    if s["attack_map"] is not None:
        shape, label = srcskills.shape_for(s, src["maps"], d5)
        if shape is None and s["game"] == "d1c":        # D1 shape D5 has no AttackMap for: keep the stand-in's
            notes.append(f"area: D1 pattern {s['d1_pattern']} (range {s['range']}) has no identical D5 shape")
            return f, notes
        if shape is None:
            return None, [f"area: {label}"]
        f.update(attack_map=shape, range=int(s["range"]), area_flag=int(s["area_flag"]),
                 range_flag=None if s["range_flag"] is None else int(s["range_flag"]))
        if s["game"] == "d1c":
            notes.append(f"range {s['range']} and area: the source's (D1 pattern {s['d1_pattern']} = D5 shape {shape})")
            if any(c[2] == 2 for c in s["d1_cells"]):
                notes.append("D1's caster-landing cell not carried (the stand-in animation does not move the caster)")
        elif label != "exact":
            notes.append(f"area: {label}")
    return f, notes


def reviewed_twins(game):
    """Earlier by-reference stand-ins per source skill, from the reviewed maps (named, then kept or replaced)."""
    out = dict(by_mod={}, variant_of={}, all={})
    if game == "d1c":
        doc = _json(HERE.parent / "sourcemaps/d1c.json", {})
        for lid, c in (doc.get("characters") or {}).items():
            out["by_mod"][f"D1C_Unique_{lid}"] = {int(s["d1_id"]): int(s["d5_id"]) for s in c.get("skills", [])
                                                  if s.get("d1_id") and s.get("d5_id")}
            if int(c.get("source_character", lid)) != int(lid):
                out["variant_of"][int(lid)] = int(c["source_character"])
    if game == "dd2":
        doc = _json(srcskills.BASE / "Research/source-packs/dd2/coverage.json", {})
        out["all"] = {int(k): int(v["copy_of"]) for k, v in (doc.get("skills") or {}).items()
                      if isinstance(v.get("copy_of"), int)}
    return out


def plan_mod(game, mod, twins=None):
    twins = twins or reviewed_twins(game)
    name = Path(mod).name
    return plan(game, mod, standins=dict(by_skill=twins["by_mod"].get(name) or twins["all"],
                                         variant_of=twins["variant_of"]))


def run(game, mod, roots):
    """The importer's step (`import_game.py --source-specials`): plan, lease, write, gate one built pack.
    Returns (label, ok, why) in the tracker's vocabulary."""
    p = plan_mod(game, mod)
    if not any(e["label"] in "EA" for e in p["entries"]):
        return "n/a (no mappable source special)", True, ""
    lease([p], roots)
    apply(mod, p)
    problems = gate(mod, context(game)[0])
    n = {k: sum(e["label"] == k for e in p["entries"]) for k in "EAH"}
    label = "own rows, stand-in animation" if n["A"] else "exact (D5's own rows)"
    return f"{label} (E {n['E']}, A {n['A']}, held {n['H']})", not problems, "; ".join(problems)


# ------------------------------------------------------------------ leases
def load_leases():
    return (_json(LEASES, {}) or {}).get("leases", {})


def taken_ids(roots, d5):
    """Every magic.dat id in vanilla, every mod folder under `roots`, and every lease file beside this one."""
    ids = set(d5.rows)
    for root in roots:
        for f in Path(root).glob("*/patches/db/magic.dat.json"):
            doc = json.loads(f.read_text())
            ids.update(int(r["id"]) for r in doc.get("added") or [])
            ids.update(int(k) for k in (doc.get("rows") or {}))
    for f in HERE.glob("*leases*.json"):
        ids.update(_ints(json.loads(f.read_text())))
    return ids


def _ints(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and k.isdigit():
                yield int(k)
            yield from _ints(v)
    elif isinstance(node, list):
        for v in node:
            yield from _ints(v)
    elif isinstance(node, int) and not isinstance(node, bool):
        yield node


def lease(plans, roots):
    """Give every A entry without an id the next free id of BLOCK; persist; returns the number added."""
    d5, _ = context(plans[0]["game"])
    doc = _json(LEASES, None) or dict(schema="specials2-leases/1", block=list(BLOCK), leases={},
                                      about="magic.dat ids of source specials built by SPECIALS2. Append-only: "
                                            "an id is never moved or reused (a save stores learned skills by id).")
    taken = taken_ids(roots, d5) | set(doc["leases"].values())
    nxt, added = BLOCK[0], 0
    for p in plans:
        for e in p["entries"]:
            if e["label"] != "A" or e.get("d5_id"):
                continue
            if e["lease_key"] not in doc["leases"]:
                while nxt in taken:
                    nxt += 1
                if nxt > BLOCK[1]:
                    raise ValueError("SPECIALS2 lease block is full")
                doc["leases"][e["lease_key"]] = nxt
                taken.add(nxt)
                added += 1
            e["d5_id"] = doc["leases"][e["lease_key"]]
    LEASES.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    return added


# ------------------------------------------------------------------ write
def apply(mod, p):
    """Write the plan into the pack's table files.  Returns the list of files written."""
    from .. import dbpatch
    d5, _ = context(p["game"])
    mod = Path(mod)
    todo = [e for e in p["entries"] if e["label"] == "A"]
    body = int((installed_state(mod)["rows"] or [{}])[0].get("body_type") or 0)
    if not any(e["label"] in "EA" for e in p["entries"]):
        return []
    written = []
    magic_path = mod / "patches/db/magic.dat.json"
    doc = _json(magic_path, None) or {"table": "magic.dat"}
    doc.setdefault("added", [])
    skills_path = mod / "patches/skills/skills.json"
    sk = _json(skills_path, None) or {"skills": {}}
    sk.setdefault("skills", {})
    for e in todo:
        if not e.get("d5_id"):
            raise ValueError(f"{mod.name}: source skill {e['src']} has no leased id")
        row = dbpatch._row_values(d5.rows[e["standin"]].copy())
        row["id"] = e["d5_id"]
        for lang in LANGS:                               # the source's name and text (the installed row's when present)
            row[f"name_{lang}"] = e["name"]
            row[f"desc_{lang}"] = _desc(p, e)
        f = e["fields"]
        for k in ("sp_cost", "element", "height_up", "height_down", "effect1_value", "attack_map", "range",
                  "area_flag", "range_flag", "flag_468"):
            if f.get(k) is not None:
                row[k] = f[k]
        for i in range(2, 7):                            # D5's own convention: a single-effect row repeats its value
            if "effect1_value" not in f and not f["effects"]:
                break                                    # power and ailments are the stand-in's: leave its slots alone
            code, value = f["effects"][i - 2] if i - 2 < len(f["effects"]) else \
                (0, 0 if f["effects"] else row["effect1_value"])
            row[f"effect{i}_type"], row[f"effect{i}_value"] = code, value
        row["rank"] = e["tier"]
        row["skill_group"] = 7 if "_Unique_" in mod.name else 9 if body == 1 else 8
        doc["added"] = [r for r in doc["added"] if int(r["id"]) != e["d5_id"]] + [row]
        sk["skills"][str(e["d5_id"])] = {"choreography": int(d5.survey.sc.root_of(e["standin"]))}
    if todo:
        doc["added"].sort(key=lambda r: int(r["id"]))
        magic_path.parent.mkdir(parents=True, exist_ok=True)
        magic_path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        skills_path.parent.mkdir(parents=True, exist_ok=True)
        skills_path.write_text(json.dumps(sk, indent=1, ensure_ascii=False))
        written += [magic_path, skills_path]
    learn, seen = [], set()
    for e in p["entries"]:
        if e.get("d5_id") and e["d5_id"] not in seen:
            learn.append((e["d5_id"], e["level"]))
            seen.add(e["d5_id"])
    for k in p["kept"]:
        if not k.get("dropped") and k["d5_id"] not in seen:
            learn.append((k["d5_id"], k["level"]))
            seen.add(k["d5_id"])
    if len(learn) > 16:
        raise ValueError(f"{mod.name}: {len(learn)} learn entries exceed the 16 native slots")
    char_path = mod / "patches/db/char.dat.json"
    char = json.loads(char_path.read_text())
    for row in char.get("added") or []:
        for n in range(16):
            row[f"learn{n + 1}_skill"] = learn[n][0] if n < len(learn) else 0
            row[f"learn{n + 1}_level"] = learn[n][1] if n < len(learn) else 0
        row["learn_count"] = len(learn)
    char_path.write_text(json.dumps(char, indent=1, ensure_ascii=False))
    meta_path = mod / "mod.json"
    meta = json.loads(meta_path.read_text())
    meta["specials2"] = dict(
        about="Source special attacks. E = D5's own row of the same special; A = the source's SP, element, range, "
              "area, heights and converted power on a labelled D5 stand-in animation; H = held.",
        native_tested=False,
        entries=[{k: e.get(k) for k in ("src", "name", "level", "label", "d5_id", "twin", "basis", "standin",
                                        "standin_name", "motion", "own_track", "source", "fields", "notes")
                  if e.get(k) is not None} for e in p["entries"] if e["label"] != "N"],
        source_absent=_absent(p),
        kept=p["kept"])
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    return written + [char_path, meta_path]


def _absent(p):
    """Learn entries the source gives no usable skill for (label N): recorded, never counted as held."""
    return [dict(src=e["src"], level=e["level"], name=e.get("name"), why=e["notes"][0])
            for e in p["entries"] if e["label"] == "N"]


def relabel(mod, p):
    """D4SPEC1: rewrite ONLY the `specials2` block of mod.json from plan `p` (no table row, learn list or art
    touched): label-N entries leave `entries` for `source_absent`; a unit whose source learn list is empty gets
    `source_has_none`.  Returns True when the file changed."""
    meta_path = Path(mod) / "mod.json"
    meta = json.loads(meta_path.read_text())
    before = json.dumps(meta, sort_keys=True)
    block = meta.get("specials2")
    absent = _absent(p)
    if block is None:
        if p["entries"] or not p.get("source_character"):
            return False
        block = meta["specials2"] = dict(
            about="Source special attacks. This unit's source learn list is empty: the source game gives it none.",
            native_tested=False, entries=[], source_has_none=True, kept=p["kept"])
    else:
        gone = {e["src"] for e in p["entries"] if e["label"] == "N"}
        block["entries"] = [e for e in block.get("entries") or [] if e.get("src") not in gone]
        if absent:
            block["source_absent"] = absent
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    return json.dumps(meta, sort_keys=True) != before


def _desc(p, e):
    """The source description; D1/D4/DD2 rows open with 'Unique:%s' style text the D5 drawer also fills."""
    _, src = context(p["game"])
    text = src["table"][e["src"]]["desc"].strip()
    if not text:                                         # D1 Complete's skill table stores no description
        return f"Unique:%sA Disgaea 1 special. Animation: D5's {e['standin_name']}."
    if text.count("%") == 1 and "%s" in text:
        return text
    body = text.split(":", 1)[-1].replace("%s", "").replace("%", "\uff05").replace("\u3000", " ").strip()
    return "Unique:%s" + body                            # the drawer passes exactly one string argument


# ------------------------------------------------------------------ gate
def gate(mod, d5=None, magic_ids=None):
    """SPECIALS2 skill gate for one built pack (a new function: importcore.learn_skill_gate and
    skill_motion_gate are untouched).  Returns a list of problems; [] = pass.

    Every learn-list id resolves; every pack-owned row is inside D5's field ranges, below 32768, points at
    an existing AttackMap shape and has a choreography; no caster motion is 'missing' on the pack's bank."""
    d5 = d5 or context("d4")[0]
    mod = Path(mod)
    state = installed_state(mod)
    sk = (_json(mod / "patches/skills/skills.json", {}) or {}).get("skills", {})
    problems = []
    known = set(d5.rows) | set(state["magic"]) | set(magic_ids or ())
    for row in state["rows"]:
        n = int(row.get("learn_count") or 0)
        ids = [int(row.get(f"learn{i}_skill") or 0) for i in range(1, 17)]
        if n > 16 or any(ids[n:]) or not all(ids[:n]) or len(set(ids[:n])) != n:
            problems.append(f"char {row.get('id')}: learn list is not {n} distinct leading entries")
        for sid in ids[:n]:
            if sid not in known:
                problems.append(f"char {row.get('id')}: learn id {sid} resolves to no magic.dat row")
    for sid, row in state["magic"].items():
        if not 10000 <= sid < 32768:
            problems.append(f"row {sid}: id outside 10000..32767")
        if not 0 <= int(row["sp_cost"]) <= 65535 or not 0 <= int(row["element"]) <= 4 \
                or not 0 <= int(row["range"]) <= 99 or not -32768 <= int(row["effect1_value"]) <= 32767 \
                or not 0 <= int(row["height_up"]) <= 255 or not 0 <= int(row["height_down"]) <= 255:
            problems.append(f"row {sid}: a field is out of range")
        if int(row["attack_map"]) and int(row["attack_map"]) not in d5.maps:
            problems.append(f"row {sid}: AttackMap {row['attack_map']} does not exist in D5")
        if str(sid) not in sk and not d5.has_root(int(row.get("base_skill") or 0)) and int(row["skill_group"]) != 10:
            problems.append(f"row {sid}: no choreography")
    for rec in d5.survey.check_mod(mod):
        if rec["status"] == "missing":
            problems.append(f"skill {rec['skill']}: caster motion missing from bank {rec['sprite']}: {rec['missing']}")
    return problems
