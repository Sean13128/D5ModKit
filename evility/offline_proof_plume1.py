"""PLUME1: capped ally power aura, real-call-path and baseline differential proofs.

Run with the kit Python, optionally --abi and --json OUT. Original game functions
are volatile-clobbering synthetic stubs; no process, installation or gameplay.
The differential builds the pinned 45c77f0 Python/assembly from git in scratch.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'evility')]
from d5lib import evility as ev
import offline_proof_ex05e as h
import offline_proof_evilfx2 as fx2
import offline_proof_drpgevil1b as drpg
from abi_engine_ex05c import execute

BASE = '45c77f0'
DEFEATS = 0x146A5F054
RID = 26304


def plume_rows():
    """PLUME1's capped power aura over D5's six defeat counters (`max` + `defeated_any`).  Row 26304 itself moved on to the holder's own count
    (DD2EVIL3, evility/offline_proof_dd2evil3.py); the old shape stays here as the fixture of the `max` machinery these cases prove."""
    return {RID: {'family': ['power', 'aura'], 'effects': [{'value': 10, 'per': 'defeated_any', 'max': 200}],
                  'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 65535, 'id': RID}]}}


def cases():
    def plan(name, expected, counts=(0, 0, 0, 0, 0, 0), *, team=0,
             provider=True, provider_team=0, distance=1, on_map=True, ids=()):
        others = ((h.unit((RID,), team=provider_team), (5, 5 + distance), 2),) if provider else ()
        return dict(name=name, family='power', field='output', expected=expected,
                    ids=ids, fixture=h.fixture(h.unit(ids, team=team), on_map=on_map,
                    other=h.unit(team=1), others=others,
                    regions=[(DEFEATS, struct.pack('<6H', *counts))]))
    return [
        plan('zero-defeats-no-change', 0),
        plan('one-defeat-plus-ten', 10, (0, 1, 0, 0, 0, 0)),
        plan('nineteen-defeats-below-cap', 190, (0, 19, 0, 0, 0, 0)),
        plan('twenty-defeats-at-cap', 200, (0, 20, 0, 0, 0, 0)),
        plan('twenty-one-defeats-capped', 200, (0, 21, 0, 0, 0, 0)),
        plan('six-team-maxima-capped', 200, (99,) * 6),
        plan('defeated-any-counts-every-team', 60, (1, 1, 1, 1, 1, 1)),
        plan('enemy-recipient-not-buffed', 0, (0, 21, 0, 0, 0, 0), team=1),
        plan('enemy-provider-not-buffed', 0, (0, 21, 0, 0, 0, 0), provider_team=1),
        plan('absent-provider-no-change', 0, (0, 21, 0, 0, 0, 0), provider=False),
        plan('far-ally-map-wide-buffed', 200, (0, 21, 0, 0, 0, 0), distance=100),
        plan('off-map-recipient-no-change', 0, (0, 21, 0, 0, 0, 0), on_map=False),
        plan('holder-is-not-its-own-ally', 0, (0, 21, 0, 0, 0, 0), provider=False, ids=(RID,)),
    ]


def baseline(directory):
    """Read git objects only; do not touch another branch/worktree."""
    source = subprocess.check_output(['git', '-C', str(KIT), 'show', BASE + ':d5lib/evility.py'])
    asm = subprocess.check_output(['git', '-C', str(KIT), 'show', BASE + ':d5lib/native/d5evil.inc.asm'])
    pyfile, asmfile = directory / 'baseline.py', directory / 'baseline.asm'
    pyfile.write_bytes(source)
    asmfile.write_bytes(asm)
    spec = importlib.util.spec_from_file_location('d5lib._plume1_baseline', pyfile)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ASM_FILE = str(asmfile)
    return mod


def build(module, original, rows):
    patched = module.build_patch(original, rows)
    specs = [(module.WRAPPER_NAMES[tag], target, sites) for tag, target, sites in module.WRAPPERS]
    return patched, module.section_info(patched), specs


def run_case(bundle, case, abi):
    patched, info, specs = bundle
    _, target, sites = next(s for s in specs if s[0] == case['family'])
    for site in sites:
        result = execute(patched, info, specs, case['family'], target, site,
                         ids=case.get('ids', ()), abi=abi, fixture=case['fixture'],
                         out_value=case.get('out_value', 50),
                         original_rax=case.get('original_rax', 0),
                         supplied_stack_args=case.get('supplied_stack_args'),
                         stub_returns=case.get('stub_returns'))
        yield site, result


def state(result):
    """Every exposed game-state byte vector/value, excluding addresses and cost."""
    return {key: result[key] for key in ('output', 'hp', 'sp', 'potency', 'aggregate',
            'base_stats', 'final_stats', 'rsp_delta', 'watched', 'inout_writes',
            'integer_nonvolatiles_preserved', 'xmm6_15_preserved', 'home_writer')}


def old_aura_plans():
    # All prior aura families: potency/stats plus damage-time families, regen and crit_damage.
    for family, stat in (('potency', 'atk'), ('stats', 'atk')):
        row = {7900: {'family': [family, 'aura'], 'effects': [{'stat': stat, 'value': 17}],
                     'conditions': [{'kind': 'near_has', 'of': 1, 'radius': 30, 'id': 7900}]}}
        checks = []
        for team in (0, 1):
            checks.append(dict(name=f'legacy-{family}-team-{team}', family=family,
                               fixture=h.fixture(h.unit(team=team), other=h.unit(team=1),
                               others=((h.unit((7900,)), (5, 6), 2),))))
        yield family, row, checks
    for name, rows, checks in h.cases(ev):   # every ex05e plan, not only aura rows: all must stay identical
        yield 'ex05e-' + name, rows, checks
    yield 'drpgevil1b', drpg.ROWS, drpg.cases()
    yield 'evilfx2', fx2.ROWS, fx2.cases()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    original = h.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == h.ORIGINAL_SHA
    checks = []
    bundle = build(ev, original, plume_rows())
    for case in cases():
        for site, result in run_case(bundle, case, args.abi):
            assert result[case['field']] == case['expected'], (case['name'], result, case['expected'])
            checks.append(dict(name=case['name'], site=hex(site), ok=True))
    scratch = Path('/Volumes/Data/ai-tmp/claude/dd2evil3/plume1proofs')
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='differential-', dir=scratch) as tmp:
        old = baseline(Path(tmp))
        for name, rows, cases_ in old_aura_plans():
            # The original rows/conditions/effects must preserve their exact encoded words.
            assert ev.table(rows) == old.table(rows), name + ': old encoding changed'
            before, after = build(old, original, rows), build(ev, original, rows)
            for case in cases_:
                first = list(run_case(before, case, args.abi))
                second = list(run_case(after, case, args.abi))
                assert len(first) == len(second)
                for (site, a), (other_site, b) in zip(first, second):
                    assert site == other_site and state(a) == state(b), (name, case['name'], state(a), state(b))
                    checks.append(dict(name='differential-' + name + '-' + case['name'], site=hex(site), ok=True))
    report = dict(mode='abi' if args.abi else 'behavior', baseline=BASE,
                  patched_sha256=hashlib.sha256(bundle[0]).hexdigest(), passed=True, checks=checks)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f"{len(checks)}/{len(checks)} checks passed (Plume + byte-identical legacy state/encoding)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
