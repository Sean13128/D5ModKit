"""The recorded specials / evility / ability-note post-pass for the D4 unique packs (SOURCEPREP4-D4).

This is the kit's copy of the two lane scripts the importer used to load from ``Research/``:

* ``Research/source-packs/specials/patch_specials.py`` (22 packs): a magic.dat row per D4 special (a
  copy of its reviewed D5 donor, with D4's own name and description), the donor's choreography, and --
  for Fenrich -- the one exact evility row (D4 861 Moonlight Fang -> 8861);
* ``Research/source-packs/d4uniq3/specials.py`` (ten packs): the same shape for the D4UNIQ3 set plus
  the two exact evility rows (874 -> 8874, 884 -> 8884) and the D4UNIQ3 ability notes.

Nothing here invents content: the reviewed skill/donor/relation table is the lane's (ids and
authored reasons only), every skill id comes from ``d4-leases.json`` (write what the installed pack
records), the per-character skill rows and text come from the checked-in rule data with their game
text as references, and the D4 names/descriptions are read from the verified source at build time.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from . import _d4_source

TEN = (70, 220, 410, 420, 430, 440, 450, 460, 470, 610)
D4UNIQ = (60, 170, 180, 190, 210, 230, 240, 250, 490)
D4UNIQ2 = (10, 20, 30, 40, 50, 80, 300, 310, 320, 340, 350, 360, 500)

# D4 skill id -> (D5 donor, relation, why).  D4UNIQ3's reviewed table (verbatim from the lane script).
SKILLS = {
    10071: (12024, 'adapted', "D4's single high-tier malice attack takes the top of D5's monster ladder "
                              "(Dark Illuminati, sp120, dark); Nemo is a monster-layout body, so a "
                              "monster-ladder donor keeps the choreography on its own layout"),
    12121: (10621, 'adapted', 'light tier, reaping flavour (Soul Reaper, sp10)'),
    12122: (10622, 'adapted', 'medium tier, the same reaper ladder (Grim Specter, sp30)'),
    12123: (10623, 'adapted', 'heavy tier, the same ladder (Delta of Death, sp72)'),
    12124: (10514, 'adapted', "top tier (sp160) takes D5's top humanoid tier (Overlord Dimension) -- the "
                              'same donor and reason D4_Unique_170 (the other Hugo) records'),
    22121: (0, 'omit', 'Magichange skill: the Magichange mode it belongs to is not built'),
    22122: (0, 'omit', 'Magichange skill: the Magichange mode it belongs to is not built'),
    10181: (10611, 'adapted', "the builder already emits the reviewed completed-mapping's copy of D5's "
                              "Desco-line row of the same name (10611)"),
    10182: (10612, 'adapted', "the builder already emits the reviewed completed-mapping's copy of 10612"),
    20431: (0, 'omit', 'Magichange skill: the Magichange mode it belongs to is not built'),
    20432: (0, 'omit', 'Magichange skill: the Magichange mode it belongs to is not built'),
    10441: (10631, 'adapted', 'light tier, the "justice" line (Justice Knife, sp10)'),
    10442: (10702, 'adapted', 'medium tier, fire of battle (Soaring Fire, sp30, fire)'),
    10443: (10543, 'adapted', 'heavy tier, "phantoms aid me" reads as a summoned delivery (Sicily '
                              'Delivery, sp72)'),
    10451: (10681, 'adapted', 'light tier of one D5 sword ladder (Virgin Innocence, sp10, ice)'),
    10452: (10682, 'adapted', 'medium tier of the same ladder (Shunpu Moondance, sp30)'),
    10453: (10683, 'adapted', 'heavy tier of the same ladder (Legend White, sp72)'),
    10461: (10531, 'adapted', "the Love ladder's own fist move (Love Knuckle, sp10); D4's row is a single "
                              'mid-level fist attack, D5 has no matching tier'),
    10471: (10681, 'adapted', 'light tier, the ice flavour (Virgin Innocence, sp10, ice); D5 has no ice fist'),
    10472: (10662, 'adapted', '"elegant combo" reads as the gun ladder (The Great Gun King, sp30)'),
    10473: (10703, 'adapted', 'heavy tier, fire (Vulcan Blaze, sp72, fire)'),
}
# D4 evility id -> the exact row the pack carries.  value1 is D4's stored value (mskill.dat +13); the
# description is the kit's D5-vocabulary adaptation (authored), the name is D4's own (read at build time).
EVILITIES = {
    874: dict(row=8874, value1=40,
              desc='ATK increases by %d％ while Fuka or Desco stands on an adjacent panel.',
              rows=[dict(family='stats', effects=[dict(stat='atk', value=40)],
                         condition=dict(kind='near_char', id=ch, of=1, radius=1))
                    for ch in (600, 610, 10340, 10350)],
              note='D4 stores one value (40) and prints it once; four rows so either Fuka or either Desco '
                   'satisfies it, whichever copy of them is in the roster (native 600/610 or the D4 '
                   'identities 10340/10350).'),
    884: dict(row=8884, preexisting=True,
              desc='Damage of Specials is increased by %d％.', value1=50,
              rows=[dict(family='power', effects=[dict(value=50)],
                         condition=dict(kind='attack_skill'))],
              note="'Specials' is D5's own vocabulary for a skill action; the power family is the attack-"
                   'power percentage pass (P3), gated on attack_skill.'),
}

_LOCK = threading.Lock()


def lease_by_mod(lease_doc):
    return {c["mod"]: c for c in lease_doc["characters"].values()}


def builder_mappings(receipts):
    """{mod_id: {d4_id: d5_id}} - the skills a build emitted from the reviewed completed mapping."""
    out = {}
    for sid, doc in receipts.items():
        mod = f"D4_Unique_{sid}"
        out[mod] = {int(m["d4_id"]): int(m["d5_id"]) for m in doc.get("mappings", [])
                    if m.get("kind") == "skill" and m.get("d5_id")}
    return out


def d4_skill_names(files):
    """{id: {name, desc}} from the verified magic.dat, decoded as the lane script did (UTF-8)."""
    import struct
    from .. import d4source
    raw = files.data("EN").db.read('magic.dat')
    out = {}
    for row in d4source._rows(raw, d4source.SKILL_STRIDE):
        sid = struct.unpack_from('<I', row, 40)[0]
        out[sid] = dict(name=row[184:248].split(b'\0', 1)[0].decode('utf-8', 'replace'),
                        desc=row[56:184].split(b'\0', 1)[0].decode('utf-8', 'replace'))
    return out


def _has_skill(mod_dir, skill_id):
    path = Path(mod_dir) / "patches/db/magic.dat.json"
    if not path.is_file():
        return False
    return any(int(r["id"]) == int(skill_id) for r in json.loads(path.read_text()).get("added") or [])


def _drop_skill(mod_dir, skill_id):
    path = Path(mod_dir) / 'patches/db/magic.dat.json'
    doc = json.loads(path.read_text())
    doc['added'] = [r for r in doc.get('added') or [] if int(r['id']) != int(skill_id)]
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    rules = Path(mod_dir) / 'patches/skills/skills.json'
    if rules.is_file():
        doc = json.loads(rules.read_text())
        doc.get('skills', {}).pop(str(skill_id), None)
        rules.write_text(json.dumps(doc, indent=1, ensure_ascii=False))


def add_skill_row(fs, mod, new_id, copy_of, name, desc):
    """`newclasses.add_skill`, but the magic.dat patch is written explicitly.

    The kit's add_skill diffs its edited table against whatever `fs.read` returned on the first call;
    in a checkout that is the LIVE (modded) Database_0.dat while a later call sees the same table, so
    the diff re-shipped every installed pack's skill rows (the lane measured 137 rows for one skill).
    Copying the donor row and appending it under `added` is the shape the installed packs carry and
    cannot pick up another pack's rows.
    """
    from .. import database, dbpatch, modsys
    import d5lib.newclasses as newclasses
    table = database.load_table("magic.dat", fs.read("Database/Database_0.dat/magic.dat"))
    donor = table.find(int(copy_of))
    if donor is None:
        raise ValueError(f"magic.dat donor {copy_of} is not in the table")
    row = donor.copy()
    row.set("id", int(new_id))
    newclasses.set_langs(row, "name", name)
    if desc is not None:
        newclasses.set_langs(row, "desc", desc)
    doc = mod.load_patch("db", "magic.dat.json") or {"table": "magic.dat"}
    doc.setdefault("added", [])
    doc["added"] = [r for r in doc["added"] if int(r.get("id") or 0) != int(new_id)]
    doc["added"].append(dbpatch._row_values(row))
    mod.save_patch("db", "magic.dat.json", doc)
    from .. import skills
    skills.inherit(fs, mod, new_id, copy_of)


def _add_evility(mod_dir, identity, spec, name, fs):
    from .. import evility
    rows, conds, fx = evility.table({str(spec['row']): spec['rows']})
    skill = Path(mod_dir) / 'patches/db/Skill.dat.json'
    doc = json.loads(skill.read_text()) if skill.is_file() else {'table': 'Skill.dat', 'added': []}
    if any(int(r['id']) == spec['row'] for r in doc['added']):
        return                              # already owned by the pack (rebuild path)
    doc['added'].append(dict(
        id=spec['row'], kind=1, name_EN=name, name_JP=name, name_FR=name,
        name_CHN=name, name_KOR=name, slot_cost=0,
        **{f'desc_{lang}': spec['desc'] for lang in ('EN', 'JP', 'FR', 'CHN', 'KOR')},
        effect_group=0, value1=spec['value1'], value2=0, source=4, category=0, subcategory=0,
        mana_cost=0, shop_rank=0, owner=identity, class_order=0, version_group=100))
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    ev = Path(mod_dir) / 'patches/evilities/evilities.json'
    edoc = json.loads(ev.read_text()) if ev.is_file() else {'evilities': {}}
    edoc['evilities'][str(spec['row'])] = spec['rows']
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps(edoc, indent=1, ensure_ascii=False))
    cp = Path(mod_dir) / 'patches/db/char.dat.json'
    doc = json.loads(cp.read_text())
    row = doc['added'][0]
    if int(row.get('evility1') or 0):
        if int(row['evility1']) == int(spec['row']):
            return
        raise ValueError(f'{cp}: the row already carries innate evility {row["evility1"]}')
    row['evility1'] = spec['row']
    row['evility_count'] = 1
    cp.write_text(json.dumps(doc, indent=1, ensure_ascii=False))


def _notes(mod_id, learnset, learn, emitted, names):
    import textwrap
    have = dict(learn)
    lines = [f'{mod_id}: specials and evilities, the SPECIALS way.', '']
    for d4_id, level in learnset:
        spec = SKILLS.get(d4_id)
        name = f'D4 skill {d4_id}'
        if d4_id in have:
            if d4_id in emitted:
                kind = 'copied from the reviewed completed-mapping'
            else:
                kind = 'exact D5 move' if spec and spec[1] == 'exact' else 'closest D5 move'
            lines.append(f'  {name}: learned at level {level}, {kind}.')
        else:
            why = spec[2] if spec else 'no reviewed D5 equivalent'
            lines.append(f'  {name}: not shipped -- {why}.')
    for line in textwrap.wrap('D5 numbers, SP cost, reach, area, choreography and the donor actor '
                              'metadata apply to any borrowed move; D4 stores no formula, element or power '
                              'for its unique skills, so nothing of D4\'s numbers could be carried.', 100):
        lines.append(line)
    return '\n'.join(lines) + '\n'


def _patch_specials(lease, targets, files, fs, pool):
    data = _d4_source.specials()
    mapping = data['mapping']
    from .. import modsys
    for group, ids in (("d4uniq", D4UNIQ), ("d4uniq2", D4UNIQ2)):
        for sid in ids:
            ch = data['characters'][str(sid)]
            mod_id = ch["mod"]
            if mod_id not in targets:
                continue
            out = Path(targets[mod_id])
            leased = {int(s["d4_id"]): s for s in (lease.get(mod_id) or {}).get("specials", [])}
            for skill in ch.get('skills') or []:
                m = mapping.get(str(skill['id']))
                if not m or not m.get("copy_of"):
                    continue
                entry = leased.get(int(skill['id']))
                if entry is None:
                    raise ValueError(f"{mod_id}: no lease row for D4 skill {skill['id']} "
                                     f"({pool.resolve(skill.get('name'))}); record it in d4-leases.json")
                new_id = int(entry["d5_id"])
                if not _has_skill(out, new_id):
                    add_skill_row(fs, modsys.Mod(str(out)), new_id, int(entry["copy_of"]),
                                  pool.resolve(skill.get('name')), pool.resolve(skill.get('desc')))
            if int(ch["identity"]) == 10320:
                _add_evility_8861(modsys.Mod(str(out)), out, pool)


def _add_evility_8861(mod, out, pool):
    """The one new exact evility row Fenrich carries (D4 861 -> 8861), from the reviewed overlay."""
    overlay = pool.resolve_doc(_d4_source._json(_d4_source.OVERLAY))["mods"]["D4_Unique_20"]
    row = next(r for r in overlay["skill_rows"] if int(r["id"]) == 8861)
    path = Path(out) / "patches/db/Skill.dat.json"
    doc = json.loads(path.read_text())
    if any(int(r["id"]) == 8861 for r in doc["added"]):
        return
    doc["added"].append(row)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
    ep = Path(out) / "patches/evilities/evilities.json"
    edoc = json.loads(ep.read_text()) if ep.is_file() else {"evilities": {}}
    edoc["evilities"]["8861"] = overlay["behaviors"]["evilities"]["8861"]
    ep.parent.mkdir(parents=True, exist_ok=True)
    ep.write_text(json.dumps(edoc, indent=1, ensure_ascii=False))


def _d4uniq3(lease, targets, receipts, files, fs, pool):
    data = files.data("EN")
    names = d4_skill_names(files)
    from .. import modsys
    for sid in TEN:
        mod_id = f'D4_Unique_{sid}'
        if mod_id not in targets:
            continue
        leased = {int(s['d4_id']): s for s in (lease.get(mod_id) or {}).get('specials', [])}
        identity = int((lease.get(mod_id) or {}).get('identity'))
        dst = Path(targets[mod_id])
        mod = modsys.Mod(str(dst))
        char = data.chars[sid]
        build_receipt = (receipts or {}).get(sid)
        emitted = {m['d4_id']: m['d5_id'] for m in (build_receipt or {}).get('mappings', [])
                   if m.get('kind') == 'skill' and m.get('d5_id')}
        learn = []
        for order, (d4_id, level) in enumerate(char['learnset'], 1):
            spec = SKILLS.get(d4_id)
            name = names.get(d4_id, {}).get('name') or f'D4 skill {d4_id}'
            if spec is None or spec[1] == 'omit':
                continue
            entry = leased.get(d4_id)
            if entry is None:
                raise ValueError(f'{mod_id}: no lease row for D4 skill {d4_id} ({name}); '
                                 f'record it in d4-leases.json')
            if d4_id in emitted:
                _drop_skill(dst, emitted[d4_id])
            donor, _relation, _why = spec
            new_id = int(entry['d5_id'])
            text = names[d4_id]['desc'].replace('Unique:%s', '').replace('Unique:ε', '').strip()
            add_skill_row(fs, mod, new_id, donor, name, text)
            learn.append((new_id, level))
        path = dst / 'patches/db/char.dat.json'
        doc = json.loads(path.read_text())
        if len(doc['added']) != 1:
            raise ValueError(f'{mod_id}: char.dat patch does not hold exactly one row')
        row = doc['added'][0]
        for n in range(16):
            row[f'learn{n + 1}_skill'] = learn[n][0] if n < len(learn) else 0
            row[f'learn{n + 1}_level'] = learn[n][1] if n < len(learn) else 0
        row['learn_count'] = len(learn)
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))

        innate = data.class_profile(sid, 1)[0]['innate_evility']
        spec = EVILITIES.get(int(innate.get('id') or 0))
        if spec and spec.get('preexisting'):
            spec = None
        if spec:
            ev_name = data.evilities[int(innate['id'])]['name']
            _add_evility(dst, identity, spec, ev_name, fs)
        notes = _notes(mod_id, char['learnset'], learn, emitted, names)
        (dst / 'D4UNIQ3-ABILITY-NOTES.txt').write_text(notes)


def apply(catalog, lease_doc, receipts, files, fs, pool):
    """Run both recorded passes over the rebuilt unique folders; returns a per-mod note dict."""
    lease = lease_by_mod(lease_doc)
    targets = {mod: Path(folder) for mod, folder in catalog.items() if not lease.get(mod, {}).get('parked')}
    if not targets:
        return {}
    import d5lib.newclasses as newclasses
    with _LOCK:
        original = newclasses.add_skill
        newclasses.add_skill = add_skill_row
        try:
            _patch_specials(lease, targets, files, fs, pool)
            _d4uniq3(lease, targets, receipts, files, fs, pool)
            notes = {"specials": "recorded specials pass (d4-specials.json)",
                     "d4uniq3": "recorded D4UNIQ3 pass (specials, evilities, notes)"}
            notes["learn"] = write_learn_lists(targets, lease, builder_mappings(receipts), files)
        finally:
            newclasses.add_skill = original
    if fs is not None:
        fs.reset()
    return notes


def _has_learn_row(mod, skill_id):
    path = Path(mod) / "patches/db/char.dat.json"
    if not path.is_file():
        return False
    return any(int(r.get(f"learn{i}_skill") or 0) == int(skill_id)
               for r in json.loads(path.read_text()).get("added") or [] for i in range(1, 17))


def _donor_learn(sid):
    """Reviewed fallback rows for a D4 unique whose source learnset is empty (sourcemaps/d4.json "uniques")."""
    doc = json.loads((Path(__file__).resolve().parents[1] / "sourcemaps/d4.json").read_text())
    return (doc.get("uniques") or {}).get(str(sid), {}).get("skills", [])


def write_learn_lists(catalog, lease, emitted, files):
    """D4's learn order, level for level, with the leased (or builder's) D5 id for each row."""
    data = files.data("EN")
    report = {}
    for mod_id, folder in catalog.items():
        entry = lease.get(mod_id)
        if not entry or entry.get("parked"):
            continue
        sid = int(entry["mod"].rsplit("_", 1)[-1])
        char = data.chars.get(sid)
        if not char:
            report[mod_id] = "no D4 char row"
            continue
        leased = {int(s["d4_id"]): int(s["d5_id"]) for s in entry.get("specials", [])}
        builder = emitted.get(mod_id, {})
        learn = []
        for d4_id, level in char["learnset"]:
            d5_id = leased.get(d4_id) or builder.get(d4_id)
            if d5_id:
                learn.append((d5_id, level))
        if not learn:
            learn = [(int(r["d5_id"]), int(r["level"])) for r in _donor_learn(sid)]
        path = Path(folder) / "patches/db/char.dat.json"
        if not path.is_file():
            report[mod_id] = "no char.dat patch"
            continue
        doc = json.loads(path.read_text())
        if len(doc.get("added") or []) != 1:
            report[mod_id] = "char.dat patch is not a single row"
            continue
        row = doc["added"][0]
        changed = 0
        for n in range(16):
            value = learn[n][0] if n < len(learn) else 0
            level_i = learn[n][1] if n < len(learn) else 0
            if int(row.get(f"learn{n + 1}_skill") or 0) != value:
                changed += 1
            row[f"learn{n + 1}_skill"] = value
            row[f"learn{n + 1}_level"] = level_i
        row["learn_count"] = len(learn)
        path.write_text(json.dumps(doc, indent=1, ensure_ascii=False))
        report[mod_id] = dict(rows=len(learn), changed=changed)
    return report
