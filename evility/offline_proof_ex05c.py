"""EX-05c synthetic behavior and actual patched-site ABI proof.

Default executes wrappers with synthetic unit/battle records and explicit original-game
stubs. --abi enters each real patched CALL with caller RSP%16=0. Both paths check
behavior; ABI mode additionally exercises the redirection. --build-only never imports
Unicorn and validates fixtures/patch construction in restricted hosts.

D5_KIT=/Volumes/Data/Projects/D5/Local/Worktrees/engine-ext-capacity \\
 /Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python \\
 evility/offline_proof_ex05c.py --abi --json /private/tmp/ex05c-abi.json
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
from abi_engine_ex05c import UNIT, OTHER, REC, OREC, AGG, execute

ORIGINAL = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
                'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
ORIGINAL_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
NAMES = ('potency', 'stats', 'growth', 'dealt', 'taken', 'flight', 'flight', 'hit', 'status_chance', 'conversion')
PROVIDER = 0x400080000
BATTLE_TABLE, STRIDE = 0x141BA33B0, 4704


def unit(ids=(), *, team=0, char_id=10, type_code=1, base=None, maxima=None):
    b = bytearray(0x4800)
    struct.pack_into('<i', b, 0x3030, len(ids))
    for i, evid in enumerate(sorted(ids)):
        struct.pack_into('<I', b, 0x2f30 + i * 4, evid)
    struct.pack_into('<8H', b, 0x3068, *([50] * 8))
    struct.pack_into('<i', b, 0x2e04, char_id)
    b[0x2e32] = team
    b[0x2e25] = type_code
    if base is not None:
        struct.pack_into('<8q', b, 0x2d18, *base)
    if maxima is not None:
        struct.pack_into('<8q', b, 0x2cd8, *maxima)
    return b


def record(ptr, *, x=60.0, z=60.0, slot=0, kind=0, active=1):
    b = bytearray(STRIDE)
    struct.pack_into('<Q', b, 0x240, ptr)
    struct.pack_into('<f', b, 8, x)
    struct.pack_into('<f', b, 16, z)
    struct.pack_into('<B', b, 0x2e8, active)
    struct.pack_into('<h', b, 0x2ee, -1)
    struct.pack_into('<h', b, 0x2f4, kind)
    struct.pack_into('<H', b, 756, slot)
    return b


def fixture(*, own=None, other=None, provider=None, distance=1, provider_active=1,
            subject_kind=0, other_kind=0, regions=()):
    """Complete mapped inputs; no dependence on process/game/global state."""
    def setup(write):
        table = bytearray(256 * STRIDE)
        for slot, rec in ((0, record(UNIT, kind=subject_kind)),
                          (1, record(OTHER, x=180, slot=1, kind=other_kind))):
            table[slot * STRIDE:(slot + 1) * STRIDE] = rec
        if provider is not None:
            rec = record(PROVIDER, x=60 + distance * 12, slot=2, active=provider_active)
            table[2 * STRIDE:3 * STRIDE] = rec
            write(PROVIDER, provider)
        write(BATTLE_TABLE, table)
        write(REC, table[:STRIDE])
        write(OREC, table[STRIDE:2 * STRIDE])
        if own is not None:
            write(UNIT, own)
        if other is not None:
            write(OTHER, other)
        for address, data in regions:
            write(address, data)
    return setup


def cases(ev):
    """Return independent 512-row and vocabulary plans; fixtures never construct Uc."""
    dense = {8000 + i: {'family': 'dealt', 'effects': [{'value': i % 7 + 1}]}
             for i in range(512)}
    baseline = {'potency': 50, 'stats': 0, 'growth': 17, 'dealt': 0, 'taken': 50,
                'flight': 0, 'hit': 50, 'status_chance': 50, 'conversion': 0}
    neutral = [dict(name=f'all-sites-{tag:x}-neutral', family=family, target=target,
                    expected=baseline[family])
               for family, (tag, target, _sites) in zip(NAMES, ev.WRAPPERS)]
    plans = [('all-14-sites', {7500: {'family': 'dealt', 'effects': [{'value': 7}]}}, neutral)]
    lookups = []
    for index in (0, 255, 511):
        lookups.append(dict(name=f'table512-index-{index}', family='dealt',
                            ids=(8000 + index,), expected=index % 7 + 1, instruction_max=6000))
    for missing in (7999, 8512, 0x7fffffff):
        lookups.append(dict(name=f'table512-miss-{missing}', family='dealt',
                            ids=(missing,), expected=0, instruction_max=6000))
    lookups.append(dict(name='table512-multiple-learned', family='dealt',
                        ids=(8000, 8255, 8511), expected=sum(i % 7 + 1 for i in (0, 255, 511))))
    lookups.append(dict(name='table512-duplicate-learned-counted-once', family='dealt',
                        ids=(8511, 8511), expected=1))
    lookups.append(dict(name='table512-full-64-learned-list', family='dealt',
                        ids=tuple(range(1000, 1063)) + (8511,), expected=1, instruction_max=20000))
    plans.append(('capacity', dense, lookups))
    aura_rows = {
        7100: {'family': ['stats', 'aura'], 'effects': [{'stat': 'atk', 'value': 25}],
               'condition': {'kind': 'near_has', 'of': 1, 'radius': 1, 'id': 7100}},
        7101: {'family': ['potency', 'aura'], 'effects': [{'stat': 'atk', 'value': 30}],
               'condition': {'kind': 'near_has', 'of': 1, 'radius': 1, 'id': 7101}}}
    aura_checks = []
    for evid, stage, expect in ((7100, 'stats', 25), (7101, 'potency', 80)):
        for family in ('stats', 'potency'):
            aura_checks.append(dict(name=f'aura-{evid}-only-{stage}-stage-via-{family}', family=family,
                                    fixture=fixture(own=unit(), provider=unit([evid])),
                                    expected=expect if family == stage else (50 if family == 'potency' else 0)))
        for suffix, kw in (('distant', {'distance': 3}), ('enemy', {'provider': unit([evid], team=1)}),
                           ('inactive', {'provider_active': 0}), ('absent', {'provider': None})):
            setup = {'own': unit(), 'provider': unit([evid])}
            setup.update(kw)
            aura_checks.append(dict(name=f'aura-{evid}-{suffix}', family=stage,
                                    fixture=fixture(**setup), expected=50 if stage == 'potency' else 0))
        aura_checks.append(dict(name=f'aura-{evid}-does-not-affect-provider-alone', family=stage,
                                fixture=fixture(own=unit([evid])), expected=50 if stage == 'potency' else 0))
    plans.append(('aura-stage-empty-recipient', aura_rows, aura_checks))
    order_rows = {
        7900: {'family': ['potency', 'aura'], 'effects': [{'stat': 'atk', 'value': -20}],
               'condition': {'kind': 'near_has', 'of': 1, 'radius': 1, 'id': 7900}},
        7901: {'family': 'potency', 'effects': [{'stat': 'atk', 'value': 300}]}}
    plans.append(('aura-learned-id-order', order_rows, [
        dict(name='aura-lower-id-before-learned-clamp', family='potency',
             fixture=fixture(own=unit([7901]), provider=unit([7900])), expected=300)]))

    conversions = {
        7200: {'family': 'conversion', 'effects': [{'stat': 'hit', 'from': 'spd', 'value': 30}]},
        7201: {'family': 'conversion', 'effects': [{'stat': 'spd', 'from': 'hit', 'value': 50}]},
        7202: {'family': 'conversion', 'effects': [{'stat': 'atk', 'from': 'def', 'value': -30}]}}
    base = [100, 200, 300, 301, 500, 600, 701, 803]
    initial = [1000] * 8
    conversion_checks = []
    for label, learned, changes in (
            ('single', (7200,), {6: 1240}),
            ('both-use-base-no-feedback', (7200, 7201), {6: 1240, 7: 1350}),
            ('signed-truncation', (7202,), {2: 910}),
            ('unlearned', (), {})):
        expected = initial.copy()
        for index, value in changes.items():
            expected[index] = value
        conversion_checks.append(dict(name='conversion-' + label, family='conversion', ids=learned,
                                      fixture=fixture(own=unit(learned, base=base, maxima=initial)),
                                      field='final_stats', expected=expected))
    def original_conversion(write):
        # Model an original override writing its output first. If conversion runs
        # before this callee, the +240 contribution is erased and this case fails.
        write(UNIT + 0x2cd8, struct.pack('<8q', *([2000] * 8)))
    conversion_checks.append(dict(name='conversion-after-original-override', family='conversion',
                                  ids=(7200,), fixture=fixture(own=unit([7200], base=base, maxima=initial)),
                                  original_effect=original_conversion, field='final_stats',
                                  expected=[2000] * 6 + [2240, 2000], base_expected=base))
    for case in conversion_checks:
        case['base_expected'] = base
    plans.append(('base-stat-conversion', conversions, conversion_checks))

    typed_rows, typed_checks = {}, []
    for i, kind in enumerate(('other_human', 'other_monster', 'other_male', 'other_female',
                              'self_human', 'self_monster', 'self_male', 'self_female')):
        evid = 7300 + i
        typed_rows[evid] = {'family': 'taken', 'effects': [{'value': 20}],
                            'condition': {'kind': kind}}
        for code in (0, 1, 2, 11, 12, 99):
            for gender_flip in ((False, True) if kind.endswith(('male', 'female')) else (False,)):
                human, monster = code in (1, 2), code in (11, 12)
                male, female = code in (1, 11), code in (2, 12)
                if gender_flip:
                    male, female = female, male
                match = {'human': human, 'monster': monster, 'male': male, 'female': female}[kind.split('_')[1]]
                # taken's subject is the defender (OTHER); its other side is the attacker (UNIT).
                who = unit(([4301] if gender_flip else []), type_code=code)
                defender = unit([evid], type_code=code if kind.startswith('self_') else 1)
                if gender_flip and kind.startswith('self_'):
                    defender = unit([evid, 4301], type_code=code)
                typed_checks.append(dict(name=f'type-{kind}-{code}-flip{int(gender_flip)}', family='taken',
                                         fixture=fixture(own=who, other=defender), expected=60 if match else 50))
    plans.append(('attacker-and-self-typing', typed_rows, typed_checks))

    poison_rows, poison_checks = {}, []
    for i, kind in enumerate(('target_status', 'self_status')):
        evid = 7400 + i
        poison_rows[evid] = {'family': 'dealt', 'effects': [{'value': 17}],
                             'condition': {'kind': kind, 'id': 0}}
        for active in (False, True):
            status = bytearray(3736 * 2)
            status[(1 if kind == 'target_status' else 0) * 3736 + 1257] = int(active)
            own, other = unit([evid]), unit()
            struct.pack_into('<i', own, 0x4348, 0)
            struct.pack_into('<i', other, 0x4348, 1)
            poison_checks.append(dict(name=f'poison-{kind}-{active}', family='dealt',
                                      fixture=fixture(own=own, other=other, regions=((0x141067dc8, status),)),
                                      expected=17 if active else 0))
    poison_rows[7402] = {'family': 'status_chance', 'effects': [{'value': 17}],
                         'condition': {'kind': 'status_class', 'id': 0}}
    poison_checks.append(dict(name='poison-status-class-zero', family='status_chance', ids=(7402,),
                              stack_args=(0, 0, 0), expected=67))
    plans.append(('status-index-zero', poison_rows, poison_checks))
    return plans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', '--site-entry', action='store_true')
    ap.add_argument('--build-only', action='store_true', help='build all plans without importing Unicorn')
    ap.add_argument('--json', type=Path)
    ap.add_argument('--legacy', choices=('base', 'ex05', 'ex05b'),
                    help='run unchanged prior proof; ABI adapter covers its original nine wrappers')
    args = ap.parse_args()
    from d5lib import evility as ev
    if args.legacy and args.build_only:
        ap.error('--build-only applies to EX-05c; legacy modes require an emulator-capable host')
    if args.legacy:
        # The unchanged prior ABI driver has a nine-entry NAMES tuple and cannot
        # enumerate the new tenth wrapper. Keep its original 13-site suite intact;
        # the EX-05c suite separately executes all 14 sites, including conversion.
        import runpy
        from types import SimpleNamespace
        old = Path('/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/evility')
        sys.path.insert(0, str(old))
        import abi_site_proof
        prior = abi_site_proof.run_abi
        def compatible_run(module, *positional, **named):
            proxy = SimpleNamespace(**vars(module))
            proxy.WRAPPERS = module.WRAPPERS[:9]
            return prior(proxy, *positional, **named)
        abi_site_proof.run_abi = compatible_run
        script = old / {'base': 'offline_proof.py', 'ex05': 'offline_proof_ex05.py',
                        'ex05b': 'offline_proof_ex05b.py'}[args.legacy]
        os.environ['D5_KIT'] = str(KIT)
        sys.argv = [str(script)] + (['--abi'] if args.abi else []) + (['--json', str(args.json)] if args.json else [])
        runpy.run_path(str(script), run_name='__main__')
        return 0
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    specs = [(name, target, sites) for name, (_, target, sites) in zip(NAMES, ev.WRAPPERS)]
    results, builds = [], []
    for plan_name, rows, checks in cases(ev):
        patched = ev.build_patch(original, rows)
        info = ev.section_info(patched)
        builds.append(dict(plan=plan_name, rows=len(rows), checks=len(checks),
                           section_size=info['size'], patched_sha256=hashlib.sha256(patched).hexdigest()))
        for case in checks:
            family = case['family']
            _, target, sites = next(s for s in specs if s[0] == family and ('target' not in case or s[1] == case['target']))
            for site in sites:
                if args.build_only:
                    regions = []
                    if case.get('fixture'):
                        case['fixture'](lambda addr, data: regions.append((hex(addr), len(data))))
                    results.append(dict(name=case['name'], site=hex(site), fixture_built=True, regions=regions))
                    continue
                try:
                    detail = execute(patched, info, specs, family, target, site,
                                     ids=case.get('ids', ()), abi=args.abi,
                                     fixture=case.get('fixture'),
                                     out_value=case.get('out_value', 50),
                                     original_rax=case.get('original_rax', 0),
                                     supplied_stack_args=case.get('stack_args'),
                                     original_effect=case.get('original_effect'))
                    if 'base_expected' in case:
                        assert detail['base_stats'] == case['base_expected'], detail['base_stats']
                    got = detail[case.get('field', 'output')]
                    assert got == case['expected'], (got, case['expected'])
                    if 'instruction_max' in case:
                        assert detail['instructions'] <= case['instruction_max'], detail['instructions']
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=True, **detail))
                except Exception as exc:
                    results.append(dict(name=case['name'], family=family, site=hex(site), ok=False,
                                        error=f'{type(exc).__name__}: {exc}'))
                r = results[-1]
                print(('PASS ' if r['ok'] else 'FAIL ') + case['name'] + f' {site:#x}' +
                      ('' if r['ok'] else ' ' + r['error']))
    passed = args.build_only or all(r['ok'] for r in results)
    report = dict(mode='build-only' if args.build_only else 'abi-site-entry' if args.abi else 'behavior',
                  original_sha256=ORIGINAL_SHA, builds=builds, checks=results, passed=passed,
                  limitations=['Original-game callees are deterministic volatile-clobbering stubs.',
                               'Executed paths only; Windows unwind and native gameplay are not executed.',
                               'Build-only is fixture/patch validation, not an emulator pass.'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f'{len(results)} fixtures built' if args.build_only else
          f"{sum(r['ok'] for r in results)}/{len(results)} checks passed")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
