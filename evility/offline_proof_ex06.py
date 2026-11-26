"""EX-06: skill-scope damage rules (Aegis, damage-time skill rules).

A *skill row* is keyed by a magic.dat skill id and applies when the action uses that skill, so it needs
no learned evility on either side.  The rows go into the same table, section and evaluator as evilities;
only the matching differs (action context +0x27670) and only evil_dmg_sum reaches them, through its own
index, because evil_next can only enumerate ids that some unit has learned.

Default mode executes the installed wrappers directly (Unicorn); --abi enters each real patched CALL
instruction with the caller's RSP%16=0 and checks the exact continuation and home space; --build-only
never imports Unicorn and only builds the fixtures and the patch (restricted hosts).

D5_KIT=<worktree> /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \
  evility/offline_proof_ex06.py --json evility/results/ex06-behavior.json
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))
from abi_engine_ex05c import UNIT, OTHER, REC, OREC, ACTION, ARGS, execute

ORIGINAL = Path('/Volumes/Data/Projects/D5/D5modkit/state/games/'
                'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
ORIGINAL_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
BATTLE_TABLE, STRIDE = 0x141BA33B0, 4704
EXTRA = (0x400090000, 0x400098000)
# action context fields the skill pass and the conditions read
SKILL_ID, ELEMENT, TARGET_COUNT, TARGET_ENTRIES, ENTRY_STRIDE = 0x27670, 0x276BC, 160536, 4888, 608


def unit(ids=(), *, team=0, char_id=10, type_code=1, hp=None, max_hp=None):
    b = bytearray(0x4800)
    struct.pack_into('<i', b, 0x3030, len(ids))
    for i, evid in enumerate(sorted(ids)):
        struct.pack_into('<I', b, 0x2f30 + i * 4, evid)
    struct.pack_into('<8H', b, 0x3068, *([50] * 8))
    struct.pack_into('<i', b, 0x2e04, char_id)
    b[0x2e32] = team
    b[0x2e25] = type_code
    if hp is not None:
        struct.pack_into('<q', b, 0x2cc8, hp)
    if max_hp is not None:
        struct.pack_into('<q', b, 0x2cd8, max_hp)
    return b


def record(ptr, *, slot, x=60.0, z=60.0):
    """+756 is the slot; nothing else in this fixture writes that field (see the report note on
    target_class, which reads the same word under the label 'class kind')."""
    b = bytearray(STRIDE)
    struct.pack_into('<Q', b, 0x240, ptr)
    struct.pack_into('<f', b, 8, x)
    struct.pack_into('<f', b, 16, z)
    struct.pack_into('<B', b, 0x2e8, 1)
    struct.pack_into('<h', b, 0x2ee, -1)
    struct.pack_into('<H', b, 756, slot)
    return b


def cell(n):
    return n * 12.0 + 6.0


def fixture(*, skill=0, element=0, direction=None, entries=(), other_slot=1, other_hp=None, other_char=10,
            ids=(), others=(), subject_is_other=False):
    """Complete mapped inputs for one skill-rule case.

    skill:    the action's skill id (0 = a normal attack), at action context +0x27670
    direction: put one target entry for `other_slot` carrying this relative direction
    entries:  explicit [(slot, direction)] target entries, appended to `direction`
    other_char: the other side's class id (unit record +0x2E04) for `target_class`
    others:   [(unit bytes, cell, slot)] further units on the battle map (runtime magnitudes)
    """
    def setup(write):
        table = bytearray(256 * STRIDE)
        subject_rec = record(UNIT, slot=0, x=cell(5), z=cell(5))
        side_rec = record(OTHER, slot=other_slot, x=cell(10), z=cell(10))
        table[0:STRIDE] = subject_rec
        table[other_slot * STRIDE:(other_slot + 1) * STRIDE] = side_rec
        for i, (data, near, slot) in enumerate(others):
            table[slot * STRIDE:(slot + 1) * STRIDE] = record(EXTRA[i], slot=slot,
                                                             x=cell(near[0]), z=cell(near[1]))
            write(EXTRA[i], data)
        write(BATTLE_TABLE, table)
        # `taken` reads its subject from the D record (r8): REC is then the *attacker*
        if subject_is_other:
            write(REC, side_rec)
            write(OREC, subject_rec)
        else:
            write(REC, subject_rec)
            write(OREC, side_rec)
        write(UNIT, unit(ids=ids, team=0))
        write(OTHER, unit(team=1, char_id=other_char, hp=other_hp, max_hp=100))
        write(ACTION, bytes(0x300))
        write(ACTION + SKILL_ID, struct.pack('<I', skill))
        write(ACTION + ELEMENT, struct.pack('<B', element))
        pairs = list(entries) + ([(other_slot, direction)] if direction is not None else [])
        write(ACTION + TARGET_COUNT, struct.pack('<h', len(pairs)))
        for i, (slot, rel) in enumerate(pairs):
            at = ACTION + TARGET_ENTRIES + i * ENTRY_STRIDE
            write(at, struct.pack('<H', slot) + bytes(34) + struct.pack('<i', rel))
    return setup


# taken/hit read the subject from a different argument than the direction entry names, so the two
# shapes get their own constructors
def taken(**kw):
    return fixture(subject_is_other=True, **kw)


def dealt(**kw):
    return fixture(**kw)


AEGIS_DIR = [{'kind': 'attack_dir', 'id': 0}]


def cases(ev):
    """Independent plans: (name, evility rows, skill rows, checks).  One patch is built per plan."""
    def run(name, family, expected, **kw):
        return dict(name=name, family=family, expected=expected, **kw)

    plans = []

    # ---------------------------------------------------------------- Aegis: front-only damage taken
    # D4 mskill.dat row 392 stores 30 at +13 and scales intermediate damage by (100-30)/100 when the
    # attacker stands in front; the same identity keys the row here.  101 -> 70 is the D4 trace's case.
    evilities = {'7010': {'family': 'taken', 'effects': [{'value': -10}]}}
    rules = {'392': {'family': 'taken', 'effects': [{'value': -30}], 'conditions': AEGIS_DIR}}
    checks = [
        run('aegis-front-101-becomes-70', 'taken', 70, skill=392, out_value=101,
            fixture=taken(skill=392, direction=0)),
        run('aegis-full-100-becomes-70', 'taken', 70, skill=392, out_value=100,
            fixture=taken(skill=392, direction=0)),
        run('aegis-side-does-not-apply', 'taken', 101, skill=392, out_value=101,
            fixture=taken(skill=392, direction=1)),
        run('aegis-behind-does-not-apply', 'taken', 101, skill=392, out_value=101,
            fixture=taken(skill=392, direction=2)),
        run('aegis-other-skill-does-not-apply', 'taken', 101, skill=500, out_value=101,
            fixture=taken(skill=500, direction=0)),
        run('aegis-normal-attack-does-not-apply', 'taken', 101, skill=0, out_value=101,
            fixture=taken(skill=0, direction=0)),
        run('aegis-entry-for-another-slot-does-not-apply', 'taken', 101, skill=392, out_value=101,
            fixture=taken(skill=392, entries=[(7, 0)])),
        run('aegis-two-target-entries-second-matches', 'taken', 70, skill=392, out_value=101,
            fixture=taken(skill=392, entries=[(7, 2), (1, 0)])),
        run('aegis-with-a-learned-evility-row-as-well', 'taken', 60, skill=392, out_value=101,
            ids=(7010,), fixture=taken(skill=392, direction=0, ids=(7010,))),
        run('aegis-unit-learned-something-else', 'taken', 70, skill=392, out_value=101,
            ids=(121,), fixture=taken(skill=392, direction=0, ids=(121,))),
    ]
    plans.append(('aegis-front-only', evilities, rules, checks))

    # ---------------------------------------------------------------- the two namespaces are separate
    rules = {'7000': {'family': 'dealt', 'effects': [{'value': -40}]}}
    evilities = {'7000': {'family': 'dealt', 'effects': [{'value': 10}]}}
    checks = [
        run('same-id-both-namespaces-add-up', 'dealt', -30, skill=7000, ids=(7000,),
            fixture=dealt(skill=7000, ids=(7000,))),
        run('same-id-evility-row-alone-other-skill', 'dealt', 10, skill=500, ids=(7000,),
            fixture=dealt(skill=500, ids=(7000,))),
        run('skill-row-alone-unit-learned-nothing', 'dealt', -40, skill=7000,
            fixture=dealt(skill=7000)),
        run('skill-row-for-an-undeclared-skill', 'dealt', 0, skill=555, fixture=dealt(skill=555)),
    ]
    plans.append(('skill-vs-evility-namespace', evilities, rules, checks))

    # ---------------------------------------------------------------- vocabulary and families
    rules = {
        # the whole condition vocabulary applies to a skill row unchanged
        '1001': {'family': 'dealt', 'effects': [{'value': 30}],
                 'conditions': [{'kind': 'element', 'id': 1}]},
        '1002': {'family': 'hit', 'effects': [{'value': 20}],
                 'condition': {'kind': 'attack_dir', 'id': 2}},
        '1004': {'family': 'dealt', 'effects': [{'value': -10, 'per': 'adjacent_ally'}]},
        '1005': {'family': ['dealt', 'taken'], 'effects': [{'value': 8}]},
        '1006': {'family': 'dealt', 'effects': [{'value': 30}],
                 'conditions': [{'kind': 'attack_skill'}, {'kind': 'target_count', 'id': 2}]},
        '1007': {'family': 'taken', 'effects': [{'value': -20}],
                 'conditions': [{'kind': 'other_hp_above', 'id': 50}, {'kind': 'attack_phys'}]},
    }
    checks = [
        run('condition-element-holds', 'dealt', 30, skill=1001, element=1,
            fixture=dealt(skill=1001, element=1)),
        run('condition-element-fails', 'dealt', 0, skill=1001, element=3,
            fixture=dealt(skill=1001, element=3)),
        run('hit-family-behind', 'hit', 70, skill=1002, out_value=50,
            fixture=dealt(skill=1002, direction=2)),
        run('hit-family-front', 'hit', 50, skill=1002, out_value=50,
            fixture=dealt(skill=1002, direction=0)),
        run('counted-magnitude-two-allies', 'dealt', -20, skill=1004,
            fixture=dealt(skill=1004, others=((unit(team=0), (6, 5), 2),
                                              (unit(team=0), (5, 6), 3)))),
        run('counted-magnitude-no-allies', 'dealt', 0, skill=1004,
            fixture=dealt(skill=1004, others=((unit(team=0), (7, 5), 2),))),
        run('two-families-one-row-dealt', 'dealt', 8, skill=1005, fixture=dealt(skill=1005)),
        run('two-families-one-row-taken', 'taken', 99, skill=1005, out_value=92,
            fixture=taken(skill=1005)),
        run('conjunction-target-count-two', 'dealt', 30, skill=1006,
            fixture=dealt(skill=1006, entries=[(1, 0), (2, 1)])),
        run('conjunction-target-count-one', 'dealt', 0, skill=1006,
            fixture=dealt(skill=1006, entries=[(1, 0)])),
        run('other-side-hp-condition-holds', 'taken', 80, skill=1007, out_value=100,
            fixture=taken(skill=1007, other_hp=90)),
        run('other-side-hp-condition-fails', 'taken', 100, skill=1007, out_value=100,
            fixture=taken(skill=1007, other_hp=10)),
    ]
    plans.append(('conditions-and-families', {}, rules, checks))

    # ---------------------------------------------------------------- EX-06b (1): class vs slot
    # `target_class` used to read the other battle record's +0x2F4, which is the unit's *slot* (the
    # number the action context's target entries are keyed by).  It now reads the other unit's class id
    # at unit record +0x2E04; the old behaviour is the explicit `other_slot` condition.  The two are
    # given different values here so a regression to the old word is a visible failure, not a silent one.
    rules = {
        '1010': {'family': 'dealt', 'effects': [{'value': 30}],
                 'conditions': [{'kind': 'target_class', 'id': 10}]},
        '1011': {'family': 'dealt', 'effects': [{'value': 40}],
                 'conditions': [{'kind': 'target_class', 'id': 1}]},
        '1012': {'family': 'dealt', 'effects': [{'value': 50}],
                 'conditions': [{'kind': 'other_slot', 'id': 1}]},
        '1013': {'family': 'dealt', 'effects': [{'value': 60}],
                 'conditions': [{'kind': 'other_slot', 'id': 2}]},
    }
    checks = [
        run('class-matches-the-other-units-class-id', 'dealt', 30, skill=1010,
            fixture=dealt(skill=1010, other_char=10)),
        run('class-does-not-match-the-other-units-slot', 'dealt', 0, skill=1011,
            fixture=dealt(skill=1011, other_char=10, other_slot=1)),
        run('class-does-not-match-this-units-class', 'dealt', 0, skill=1010,
            fixture=dealt(skill=1010, other_char=20)),
        run('slot-condition-matches-the-other-units-slot', 'dealt', 50, skill=1012,
            fixture=dealt(skill=1012, other_char=10, other_slot=1)),
        run('slot-condition-does-not-match-another-slot', 'dealt', 0, skill=1013,
            fixture=dealt(skill=1013, other_char=10, other_slot=1)),
        run('slot-condition-is-not-the-class', 'dealt', 0, skill=1012,
            fixture=dealt(skill=1012, other_char=1, other_slot=7)),
    ]
    plans.append(('class-vs-slot', {}, rules, checks))

    # ---------------------------------------------------------------- EX-06b (2): ailment skill rows
    # damage_status_chance_rules gets no action context; wrap_achance records the ActionContext that
    # every damage_buff_ailment_chance caller passes first, and wrap_astat reads it back.  So a skill row
    # matches in the ailment pass, and action-context-free runs behave exactly as before.
    evilities = {'7020': {'family': 'status_chance', 'effects': [{'value': 5}]}}
    rules = {
        '8100': {'family': 'status_chance', 'effects': [{'value': -20}],
                 'conditions': [{'kind': 'status_class', 'id': 2}]},
        '8101': {'family': 'status_chance', 'effects': [{'value': 10}]},
    }
    checks = [
        run('skill-row-and-status-class-match', 'status_chance', 45, skill=8100, out_value=60,
            ctx=True, status=2, ids=(7020,), fixture=dealt(skill=8100, ids=(7020,))),
        run('skill-row-skips-another-ailment', 'status_chance', 65, skill=8100, out_value=60,
            ctx=True, status=3, ids=(7020,), fixture=dealt(skill=8100, ids=(7020,))),
        run('skill-row-without-a-status-condition', 'status_chance', 75, skill=8101, out_value=60,
            ctx=True, status=3, ids=(7020,), fixture=dealt(skill=8101, ids=(7020,))),
        run('normal-attack-matches-no-skill-row', 'status_chance', 65, skill=0, out_value=60,
            ctx=True, status=2, ids=(7020,), fixture=dealt(skill=0, ids=(7020,))),
        run('no-stashed-context-matches-no-skill-row', 'status_chance', 65, skill=8100, out_value=60,
            ctx=False, status=2, ids=(7020,), fixture=dealt(skill=8100, ids=(7020,))),
        run('skill-row-alone-unit-learned-nothing', 'status_chance', 40, skill=8100, out_value=60,
            ctx=True, status=2, fixture=dealt(skill=8100)),
        run('ailment-percent-floors-at-zero', 'status_chance', 0, skill=8100, out_value=10,
            ctx=True, status=2, fixture=dealt(skill=8100)),
    ]
    plans.append(('ailment-skill-rows', evilities, rules, checks))

    # ---------------------------------------------------------------- EX-06b (3): the stash itself
    # Every static caller of damage_buff_ailment_chance passes the ActionContext as its first argument;
    # this executes the wrapper at each redirected site and checks the slot while the original runs.
    plans.append(('ailment-context-stash', {}, {'8100': {'family': 'status_chance',
                                                         'effects': [{'value': -20}]}},
                  [run('action-context-captured-at-every-site', 'achance', 0,
                       fixture=dealt(skill=8100), watch=True)]))
    # ---------------------------------------------------------------- EX-06b (4): predicate families
    # nullify = damage_nullify_predicate (the hit is nullified); counter = exec_counter_attack_allow
    # (the defender may counter).  Both are consulted only when the game's own answer is "no", and both
    # are evaluated for the *defender*: the nullify wrapper is handed the action context, the counter one
    # is not.
    evilities = {
        '7040': {'family': 'nullify'},
        '7041': {'family': 'nullify', 'condition': {'kind': 'other_hp_above', 'id': 50}},
        '7050': {'family': 'counter'},
        '7051': {'family': 'counter', 'condition': {'kind': 'char', 'id': 10}},
        '7052': {'family': 'counter', 'condition': {'kind': 'char', 'id': 99}},
    }
    rules = {'8200': {'family': 'nullify', 'condition': {'kind': 'element', 'id': 1}}}
    checks = [
        run('nullify-row-makes-the-hit-null', 'nullify', 1, ids=(7040,),
            fixture=dealt(ids=(7040,))),
        run('no-nullify-row-leaves-the-game-answer', 'nullify', 0, fixture=dealt()),
        run('nullify-other-side-hp-condition-holds', 'nullify', 1, ids=(7041,), other_hp=90,
            fixture=dealt(ids=(7041,), other_hp=90)),
        run('nullify-other-side-hp-condition-fails', 'nullify', 0, ids=(7041,), other_hp=10,
            fixture=dealt(ids=(7041,), other_hp=10)),
        run('nullify-skill-row-matches-the-action-element', 'nullify', 1, skill=8200, element=1,
            fixture=dealt(skill=8200, element=1)),
        run('nullify-skill-row-ignores-another-element', 'nullify', 0, skill=8200, element=3,
            fixture=dealt(skill=8200, element=3)),
        run('nullify-skill-row-needs-a-skill', 'nullify', 0, skill=0, element=1,
            fixture=dealt(skill=0, element=1)),
        run('counter-row-allows-the-counter', 'counter', 1, ids=(7050,), fixture=dealt(ids=(7050,))),
        run('no-counter-row-leaves-the-game-answer', 'counter', 0, fixture=dealt()),
        run('counter-row-condition-holds', 'counter', 1, ids=(7051,), fixture=dealt(ids=(7051,))),
        run('counter-row-condition-fails', 'counter', 0, ids=(7052,), fixture=dealt(ids=(7052,))),
    ]
    plans.append(('nullify-and-counter', evilities, rules, checks))
    return plans


def source_shape(ev):
    """the emitted table must carry the skill rows after the evility rows, in id order, flag bit 0 set"""
    rules = {'900': {'family': 'dealt', 'effects': [{'value': 1}]},
             '100': {'family': 'taken', 'effects': [{'value': 2}]}}
    evilities = {'5': {'family': 'dealt', 'effects': [{'value': 3}]},
                 '100': {'family': 'dealt', 'effects': [{'value': 4}]}}
    rows, conds, fx = ev.table(evilities, rules)
    src = ev._asm_source(rows, conds, fx)
    lines = src.splitlines()
    parsed = []
    for line in lines:
        if line.strip().startswith('.long') and line.count(',') == 7:
            words = [int(w) for w in line.split(None, 1)[1].split(',')]
            parsed.append(words)
    rows_in = [w for w in parsed if w[0]]
    flagless = [w[0] for w in rows_in if not w[6] & 1]
    skills = [w[0] for w in rows_in if w[6] & 1]
    assert flagless == [5, 100], flagless
    assert skills == [100, 900], skills
    at = lines.index('evil_skill_count:')
    assert int(lines[at + 1].split()[-1]) == 2, lines[at + 1]
    at = lines.index('evil_skill_index:')
    index = [int(lines[at + 1 + i].split()[-1]) for i in range(2)]
    assert index == [32 * 2, 32 * 3], index          # after the two evility rows, in id order
    return dict(rows=len(rows_in), skill_rows=len(skills), skill_index=index,
                evility_ids=flagless)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', '--site-entry', action='store_true')
    ap.add_argument('--build-only', action='store_true', help='build every case without importing Unicorn')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    from d5lib import evility as ev
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    # by name, never by position: EX-05e inserted crit_rate/regen into WRAPPERS before EX-06b's wrappers
    specs = [(name, target, sites) for name, (_, target, sites) in
             ((n, ev.wrapper(n)) for n in ('potency', 'stats', 'growth', 'dealt', 'taken', 'flight_a',
                                           'flight_b', 'hit', 'status_chance', 'conversion', 'crit_rate',
                                           'regen', 'achance', 'nullify', 'counter'))]
    results, builds = [], []
    for plan_name, evilities, rules, checks in cases(ev):
        patched = ev.build_patch(original, evilities, rules)
        info = ev.section_info(patched)
        ctx_slot = ev.SECTION_SYMBOLS.get('evil_ctx')
        builds.append(dict(plan=plan_name, rows=len(evilities) + len(rules), checks=len(checks),
                           section_size=info['size'], context_slot=hex(ctx_slot) if ctx_slot else None,
                           patched_sha256=hashlib.sha256(patched).hexdigest()))
        for case in checks:
            family = case['family']
            _, target, sites = next(s for s in specs if s[0] == family)
            kw = dict(ids=case.get('ids', ()), abi=args.abi, fixture=case.get('fixture'),
                      out_value=case.get('out_value', 50))
            if case.get('status') is not None:
                kw['supplied_stack_args'] = (case['status'], ARGS[1], ARGS[2])
            if case.get('ctx') is not None:
                kw['preset'] = {ctx_slot: struct.pack('<Q', ACTION if case['ctx'] else 0)}
            if case.get('watch'):
                kw['watch'] = ctx_slot
            for site in sites:
                if args.build_only:
                    regions = []
                    case['fixture'](lambda addr, data: regions.append((hex(addr), len(data))))
                    results.append(dict(name=case['name'], site=hex(site), fixture_built=True,
                                        regions=regions))
                    continue
                try:
                    detail = execute(patched, info, specs, family, target, site, **kw)
                    got = detail['output']
                    assert got == case['expected'], (got, case['expected'])
                    if case.get('watch'):
                        watched = detail['watched']
                        assert watched['at_original'] == ACTION, (f'slot at original entry '
                                                                  f'{watched["at_original"]:#x}')
                        assert watched['after'] == 0, f'slot left as {watched["after"]:#x}'
                        assert watched['before'] == 0, f'slot entered as {watched["before"]:#x}'
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=True,
                                        **detail))
                except Exception as exc:
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=False,
                                        error=f'{type(exc).__name__}: {exc}'))
                r = results[-1]
                print(('PASS ' if r['ok'] else 'FAIL ') + case['name'] + f' {site:#x}' +
                      ('' if r['ok'] else ' ' + r['error']))
    shape = {} if args.build_only else source_shape(ev)
    passed = args.build_only or all(r['ok'] for r in results)
    report = dict(mode='build-only' if args.build_only else 'abi-site-entry' if args.abi else 'behavior',
                  original_sha256=ORIGINAL_SHA, builds=builds, source_shape=shape, checks=results,
                  passed=passed,
                  limitations=['Original-game callees are deterministic volatile-clobbering stubs.',
                               'Executed paths only; Windows unwind and native gameplay are not executed.',
                               'The battle-unit table, unit records and action context are synthetic fixtures.',
                               'The direction and class values are the action-context fields the game itself'
                               ' writes; their native production for a real attack is not re-executed here.',
                               'Build-only is fixture/patch validation, not an emulator pass.'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f'{len(results)} fixtures built' if args.build_only else
          f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
