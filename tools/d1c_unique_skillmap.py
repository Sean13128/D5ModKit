"""Generate d5lib/sourcemaps/d1c.json: the reviewed D1C unique-character skill map (UNIQUESKILLS1).

One row per source skill: D1C skill id/name/learn level (Disgaea Source, Switch SUBDATA start.dat[40] skills,
[43] characters), the D5 twin, a label and a reason.  Labels: exact = same ability name in the D5 table;
adapted = closest D5 skill (effect signature / element / power class; signature specials with no D5 twin carry
backlog "own special"); donor = no source skill, the donor class's own line (disclosed).  The 19 characters the
earlier batch already mapped (Research/.../unique-skills.json) keep their twins.  Re-run to regenerate.

  .venv-macos/bin/python tools/d1c_unique_skillmap.py [--check-motion D5_GAME_DIR]
"""
import json
import struct
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
ROOT = Path('/Volumes/Data/Projects/D5')
BATCHES = ROOT / 'Research/source-packs/d1c/batches'
sys.path[:0] = [str(KIT), str(ROOT / 'Research/source-packs/d1c'), str(BATCHES)]
import d1c_source  # noqa: E402
import effect_match as em  # noqa: E402
sys.path.insert(0, str(KIT))
from d5lib import d1skill  # noqa: E402

OUT = KIT / 'd5lib/sourcemaps/d1c.json'
# D1C characters whose own learn list is empty in the source and which are named variants of a character whose
# list is not (identical stat block bytes in the source table): they take that character's list.
VARIANT_OF = {5390: 3, 5590: 5}
SHOPS = (2910, 2911, 2912)


def _donors():
    """donor class per listing, from the builds' own notes ('donor 2120 (Felynn)'); newest build wins."""
    import re
    out = {}
    for b in ('D1CBUILD2', 'ROSTERGAP1', 'LEASEGATE1'):
        for x in json.load(open(ROOT / f'Builds/{b}-20261109/d1c/results.json'))['results']:
            for n in x.get('notes', []):
                m = re.match(r'donor (\d+)', n)
                if m and x['id'].startswith('unique:'):
                    out[int(x['id'][7:])] = int(m.group(1))
    return out


DONORS = _donors()


def _motion_notes(out, tables):
    mg = {r['id']: r for r in tables['magic.dat'].rows}
    am = {r['id']: r for r in tables['AttackMap.dat'].rows}
    for e in out.values():
        for r in e['skills']:
            m = mg.get(r.get('d5_id'))
            if m:
                cells = (am.get(m['attack_map']) or {}).get('cell_num', 0)
                r['d5_info'] = '%s, range %s, %s cells, SP %s' % (em.ELEM.get(m['element'], m['element']), m['range'], cells, m['sp_cost'])
    """Per twin: skillmotions status on the unit's built bank (ok / fallback / missing / unknown); see d5lib/skillmotions.py."""
    for lid, e in out.items():
        mod = BUILT / f'D1C_Unique_{lid}'
        for r in e['skills']:
            r.pop('caster_motions', None), r.pop('motions_beyond_donor_line', None)
            if SV and r.get('d5_id') and mod.is_dir():
                r['motion_check'] = SV.status_of(mod, r['d5_id'])


BUILT = ROOT / 'Builds/UNIQUESKILLS1-20261109/d1c/mods'
SV = None


def twin_rows(tables):
    return {r['id']: r for r in tables['magic.dat'].rows}


def main():
    global SV
    import importlib.util
    spec = importlib.util.spec_from_file_location('d5lib.skillmotions', KIT / 'd5lib/skillmotions.py')
    skillmotions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(skillmotions)
    SV = skillmotions.Survey() if BUILT.is_dir() else None
    m40, c43 = d1c_source.member(40), d1c_source.member(43)
    d1 = d1skill.by_id(d1skill.read_table(m40, 'd1hd'))
    tables = em.load_tables()
    d5 = twin_rows(tables)
    names = {}
    for r in tables['magic.dat'].rows:
        if (r.get('name_EN') or '').strip():
            names.setdefault(em.name_key(r['name_EN']), []).append(r)
    pools = {s: em.pool(tables, s) for s in ('humanoid', 'monster')}
    leases = json.loads((BATCHES / 'unique-leases.json').read_text())['leased']
    for k, v in json.loads((KIT / 'd5lib/importers/d1c-extra-leases.json').read_text())['leases'].items():
        leases[k] = {**leases.get(k, {}), **v}
    old = json.loads((BATCHES / 'unique-skills.json').read_text())['characters']
    rows = {r['id']: r for r in json.loads((BATCHES / 'uniques.json').read_text())['rows']}
    extra = {int(r['id']): r for r in json.loads((KIT / 'd5lib/importers/d1c-extra-leases.json').read_text())['rows']}
    rows.update(extra)
    out = {}
    todo = []
    for lid, row in sorted(rows.items()):
        lease = leases.get(str(lid))
        if row['feasibility'] not in ('ready', 'medium') or not lease:
            continue
        kind = lease['kind']
        donor = int(lease.get('donor') or DONORS[lid])
        src_id = VARIANT_OF.get(lid, lid)
        learn = d1skill.learnset(c43, src_id, 'd1hd')['learn']
        entry = dict(name=row['name'], title=row['title'], body=row['body'], kind=kind, donor=donor,
                     source_character=src_id, skills=[])
        if lid in old:                                      # the earlier batch's reviewed twins stay
            for e in old[str(lid)]['entries']:
                if not e['attach'] or e.get('collapsed_into'):
                    entry['skills'].append(dict(d1_id=e['d1_id'], d1_name=e['d1_name'], level=e['learn_level'],
                                                d5_id=None, label='none', basis='none', reason=e['reason']))
                    continue
                by_name = e['exact_basis'] == 'name'
                entry['skills'].append(dict(
                    d1_id=e['d1_id'], d1_name=e['d1_name'], level=e['learn_level'], d5_id=e['d5_id'],
                    d5_name=e['d5_name'], label='exact' if by_name else 'adapted',
                    basis='earlier-batch-name' if by_name else 'earlier-batch-mechanics',
                    reason=e['reason'] + ('' if by_name else
                                          '; same effect signature, area/animation not comparable (D1 stores none)'
                                          if e['verdict'] == 'exact' else ''),
                    **({} if by_name else {'backlog': 'own special'} if e['d1_id'] > 1000 and e['d1_id'] % 10 else {})))
            entry['source'] = 'earlier reviewed batch (unique-skills.json)'
            out[str(lid)] = entry
            continue
        todo.append((lid, row, entry, kind, donor, learn, src_id))
        continue
    return finish(todo, out, d1, names, pools, tables)


def _tier(level, sp):
    if level and level > 1:
        return em.tier_of(level)
    return 1 if sp <= 15 else 2 if sp <= 35 else 3 if sp <= 70 else 4


def _area(x):                       # D1 'up'/'down' extent 6..48 -> 0 small / 1 medium / 2 wide
    return 0 if x <= 8 else 1 if x <= 16 else 2


def _cells(n):
    return 0 if n <= 5 else 1 if n <= 13 else 2


def _info(c):
    return '%s, range %s, %s cells, SP %s' % (em.ELEM.get(c['element'], c['element']) if not isinstance(c['element'], str) else c['element'],
                                              c['range'], c['cells'], c['sp'])


def _other_maps():
    """normalised source skill name -> (D5 id, map file) from the other games' reviewed maps (rule 2).

    TEXTHASH-D1C-DD2: ``dd2.json`` stores its source names as SHA-256 references, so this reads them
    through the DD2 source pool (the prepared source folder) instead of the literal field."""
    from d5lib import textrefs
    from d5lib.importers import _dd2_source
    out = {}
    for fname, key in (('d4.json', 'd4_name'), ('dd2.json', 'dd2_name')):
        doc = json.loads((KIT / 'd5lib/sourcemaps' / fname).read_text())
        text = _dd2_source.text_pool().get if fname == 'dd2.json' and textrefs.has_refs(doc) else (lambda v: v)
        for v in doc['skills'].values():
            name = textrefs.resolve(v[key], text, f'{fname} skills') if isinstance(v.get(key), dict) else v.get(key)
            if v.get('relation') not in (None, 'omit', 'lookalike') and v.get('copy_of') and name:
                out.setdefault(em.name_key(name), (int(v['copy_of']), fname))
    return out


def finish(todo, out, d1, names, pools, tables):
    d5 = twin_rows(tables)
    other = _other_maps()
    gused = {int(r['d5_id']) for e in out.values() for r in e['skills'] if r.get('d5_id')}   # earlier batch twins
    cused = {lid: set() for lid, *_ in todo}
    rows = {lid: [] for lid, *_ in todo}
    pending = []
    # rules 1 and 2 first, for every skill of every character (so a name hit is never pre-empted by a mechanical pick)
    for lid, row, entry, kind, donor, learn, src_id in todo:
        if lid in VARIANT_OF and VARIANT_OF[lid] in cused:
            continue                                        # copied from the base character below
        for e in sorted(learn, key=lambda e: (e['level'], e['skill'])):
            src = d1.get(e['skill'])
            if src is None:
                rows[lid].append(dict(d1_id=e['skill'], d1_name=None, level=e['level'], d5_id=None, label='none', basis='none',
                                      reason='id absent from the readable 285-row D1 skill table'))
                continue
            key = em.name_key(src['name'])
            hits = [h for h in names.get(key, []) if h['id'] not in cused[lid]]
            hits.sort(key=lambda h: (h['id'] in gused, h['id']))
            base = dict(d1_id=src['id'], d1_name=src['name'], level=e['level'])
            if hits:
                h = hits[0]
                cused[lid].add(h['id']); gused.add(h['id'])
                rows[lid].append(dict(base, d5_id=h['id'], d5_name=h['name_EN'].strip(), label='exact', basis='name',
                                      reason='same ability name in the D5 skill table'))
            elif key in other and other[key][0] in d5 and other[key][0] not in cused[lid]:
                sid, f = other[key]
                cused[lid].add(sid); gused.add(sid)
                rows[lid].append(dict(base, d5_id=sid, d5_name=d5[sid]['name_EN'].strip(), label='adapted', basis='other-map',
                                      reason=f'the same skill name is already mapped to this twin in {f}'))
            else:
                pending.append((lid, kind, donor, src, e))
                rows[lid].append(None)
    # rule 3: mechanics, then rule 4: donor weapon skill of the tier
    slot = {lid: [i for i, r in enumerate(rows[lid]) if r is None] for lid in rows}
    memo = {}
    for lid, kind, donor, src, e in pending:
        i = slot[lid].pop(0)
        pool = pools['humanoid' if kind == 'humanoid' else 'monster']
        donor_line = (12000 if kind == 'monster' else 11000) + donor % 1000
        mod = BUILT / f'D1C_Unique_{lid}'
        tier = _tier(e['level'], src['sp'])
        sig1 = em.signature(em.d1_effects(src), cross_game=True)
        mod = BUILT / f'D1C_Unique_{lid}'
        prev = memo.get((src['id'], kind))
        if prev and prev['id'] not in cused[lid] and not (SV and mod.is_dir() and SV.status_of(mod, prev['id']) == 'missing'):
            cused[lid].add(prev['id'])
            rows[lid][i] = dict(d1_id=src['id'], d1_name=src['name'], level=e['level'], d5_id=prev['id'], d5_name=prev['name'],
                                label='adapted', basis='mechanics', backlog='own special',
                                reason=f"same source skill as another character: same twin (see its row); {_info(prev)}")
            continue
        scored = []
        for c in pool:
            if c['element'] != src['element'] or c['power_class'] != src['category'] or c['id'] in cused[lid]:
                continue
            if abs(c['rank'] - tier) > 1:
                continue                                    # a level-5 skill never takes an endgame special
            if not (10000 <= c['id'] < 12000 if kind == 'humanoid' else 12000 <= c['id'] < 13000 or 22000 <= c['id'] < 23000):
                continue                                    # generic class lines only (not a DLC unique's signature move)
            if sig1 != set(map(tuple, c['signature'])):
                continue                                    # same effect signature, or no mechanical twin
            if abs(__import__('math').log2(max(c['sp'], 1) / max(src['sp'] / (2 if src['category'] == 'physical' else 1), 1))) > 1.6:
                continue                                    # SP within about 3x
            sc = 0.0
            sc += 3 if _cells(c['cells']) == _area(src['up']) else 1 if abs(_cells(c['cells']) - _area(src['up'])) == 1 else 0
            sc += 8 if sig1 == set(map(tuple, c['signature'])) else 2 * len(sig1 & set(map(tuple, c['signature'])))
            sc -= 2 * abs(c['rank'] - tier)
            want = max(src['sp'] / (2 if src['category'] == 'physical' else 1), 1)   # D1 physical SP ~ 2x D5's (Pringer Beam 96/48)
            sc -= 2.0 * abs(__import__('math').log2(max(c['sp'], 1) / want))
            sc -= 4 if c['id'] in gused else 0              # prefer a skill no other mapped character uses
            sc += 3 if c['id'] // 10 == donor_line // 10 and c['id'] % 10 == tier else 0   # the donor's own tier skill
            scored.append((sc, c))
        scored.sort(key=lambda t: (-t[0], t[1]['id']))
        pick = None
        for sc, c in scored:
            if SV and mod.is_dir() and SV.status_of(mod, c['id']) == 'missing':
                continue
            pick = (sc, c)
            break
        base = dict(d1_id=src['id'], d1_name=src['name'], level=e['level'])
        if pick:
            sc, c = pick
            cused[lid].add(c['id']); gused.add(c['id']); memo[(src['id'], kind)] = c
            rows[lid][i] = dict(base, d5_id=c['id'], d5_name=c['name'], label='adapted', basis='mechanics', backlog='own special',
                                reason=f"no same-named D5 skill: element {src['element']}, class {src['category']}, area "
                                       f"{('small', 'medium', 'wide')[_area(src['up'])]}, tier {tier} (source SP {src['sp']}) "
                                       f"-> D5 {c['name']} ({_info(c)})")
        else:
            own = sorted((c for c in pool if c['id'] // 10 == donor_line // 10 and c['id'] not in cused[lid]), key=lambda c: abs(c['id'] % 10 - tier))
            if own:
                c = own[0]
                cused[lid].add(c['id']); gused.add(c['id'])
                rows[lid][i] = dict(base, d5_id=c['id'], d5_name=c['name'], label='donor', basis='donor', backlog='own special',
                                    reason=f'no D5 skill matches this source skill on element/class/area/tier with motions the body has; '
                                           f"donor class {donor} own tier-{tier} skill ({_info(c)})")
            else:
                rows[lid][i] = dict(base, d5_id=None, label='none', basis='none', reason='no candidate')
    for lid, row, entry, kind, donor, learn, src_id in todo:
        if lid in VARIANT_OF and VARIANT_OF[lid] in cused:
            base_rows = rows[VARIANT_OF[lid]]
            rows[lid] = [dict(r, reason=r['reason'] + '; variant of listing %d: same list' % VARIANT_OF[lid]) for r in base_rows]
        entry['skills'] = rows[lid]
        pool = pools['humanoid' if kind == 'humanoid' else 'monster']
        donor_line = (12000 if kind == 'monster' else 11000) + donor % 1000
        if not learn and lid not in SHOPS:                  # no source skills: the donor class's own line, disclosed
            own = sorted((c for c in pool if c['id'] // 10 == donor_line // 10 and c['power_class'] in ('physical', 'magic')), key=lambda c: c['id'])
            for c, lvl in zip(own, (5, 15, 30, 50)):
                entry['skills'].append(dict(
                    d1_id=None, d1_name=None, level=lvl, d5_id=c['id'], d5_name=c['name'], label='donor', basis='donor',
                    reason='the source gives this character no skills and its table stores no per-weapon forte '
                           '(only a stat-growth block); donor class %d own %s skill' % (donor, kind)))
            if not own:
                entry['no_source_skills'] = True
        elif not learn:                                     # shop buildings: earlier batch shipped none, kept
            entry['no_source_skills'] = True
        entry['source'] = ('variant of source character %d (identical stat block), its learn list' % src_id
                           if lid in VARIANT_OF else 'Disgaea Source Switch start.dat[43] learn slots')
        out[str(lid)] = entry
    _motion_notes(out, tables)
    _reference_names(out)
    OUT.write_text(json.dumps(dict(schema=1, game='d1c', about=ABOUT, characters=out), indent=1, ensure_ascii=False) + '\n')
    print('wrote', OUT, len(out))


def _reference_names(out):
    """TEXTHASH-D1C-DD2: the map carries SHA-256 references for every name/title, never the text."""
    from d5lib import textrefs
    for entry in out.values():
        entry['name'] = textrefs.ref(entry['name'])
        entry['title'] = textrefs.ref(entry['title'])
        for row in entry['skills']:
            for key in ('d1_name', 'd5_name'):
                if isinstance(row.get(key), str):
                    row[key] = textrefs.ref(row[key])


ABOUT = ('Reviewed D1C unique skill map (tools/d1c_unique_skillmap.py).  characters[listing id].skills: one row per source '
         'skill with the D5 twin.  label exact = same name in the D5 table; adapted = closest D5 skill (backlog "own '
         'special" = no D5 twin has the source special); donor = no source skill, the donor class line; none = not '
         'attachable.  no_source_skills true = the source gives this character no skills at all.')

if __name__ == '__main__':
    main()
