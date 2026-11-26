"""EVCAP2 offline proof: the learned-evility capacity extension (.d5lc) at the game's own call sites.

Default mode executes the installed wrappers from the real patched CALL sites (Unicorn): every static call
site of FUN_14015e630 (getter, 20) and unitstats_set_clear_bit_idx_skill 0x14015E6D0 (setter, 123) is
executed with the caller's argument registers and the exact `site+5` continuation is required.  ``--abi``
enters each patched CALL instruction instead (RSP%16 = 0 before the call), so the wrapper's own prologue,
its inner calls and its epilogue are exercised as the game makes them.  ``--build-only`` never imports
Unicorn.

What a case proves: our contribution (does the extension answer for an id the game refused, does it leave
the game's own answer and the bitmap alone) and the call/ABI contract.  The original getter/setter are
`ret` stubs whose answer each case sets, and the unit records, Skill key array and store are synthetic.

    D5_KIT=<worktree> <venv>/python evility/offline_proof_evcap.py --json evility/results/evcap-{...}.json
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

ORIGINAL = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
                'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
ORIGINAL_SHA = '49a7530baa1c3e15e4bf9c63c56fefd71d7e51a6e641bce80280b37b2db282ce'
from d5lib import learned as _learned     # noqa: E402  (the shared slot hash / capacity constants)

BASE_IDS = list(range(1, 1001))          # a stand-in ordered Skill table: positions 0..999
EXT_IDS = [21000, 21001]                 # rows that only exist beyond the bitmap
TABLE = BASE_IDS + EXT_IDS


def cases(sym):
    """(name, kind, expected output, kwargs) for every behaviour this extension claims"""
    def slot(serial, ident):
        """the slot the extension's own hash picks (d5lib.learned.slot: one hash, asm and runtime)"""
        return _learned.slot(serial, ident)

    def store_entry(serial, ident, state=1):
        """a pre-seeded store entry in the slot the hash picks, plus the live-slot count"""
        off = slot(serial, ident) * 16
        return {sym['store'] + off: struct.pack('<QII', serial, ident, state) + bytes(4),
                sym['used']: struct.pack('<I', 1 if state == 1 else 0)}

    out = []

    def case(name, kind, expect, **kw):
        kw.setdefault('keys', TABLE)
        out.append(dict(name=name, kind=kind, expect=expect, **kw))

    # ---- the game keeps its own answers ------------------------------------------------------------
    case('get-native-bit-is-the-games-answer', 'get', 1, ident=42, native_answer=1)
    case('get-native-answer-comes-back-untouched', 'get', 0xABCDEF01, ident=42, native_answer=0xABCDEF01)
    case('get-native-miss-below-the-bitmap-stays-a-miss', 'get', 0, ident=42, native_answer=0)
    case('get-id-absent-from-the-table-is-not-learned', 'get', 0, ident=99999, native_answer=0)
    case('set-native-id-is-left-to-the-game', 'set', 0, ident=42, native_answer=0)
    case('set-native-id-unknown-to-the-table-keeps-minus-one', 'set', 0xFFFFFFFF, ident=99999,
         native_answer=0xFFFFFFFF)

    # ---- the extension's own positions -------------------------------------------------------------
    case('get-extension-id-unlearned', 'get', 0, ident=21000, native_answer=0)
    case('get-extension-id-learned', 'get', 1, ident=21000, native_answer=0,
         preset=store_entry(1, 21000))
    case('get-extension-id-learned-reads-the-right-id', 'get', 0, ident=21001, native_answer=0,
         preset=store_entry(1, 21000))
    case('get-extension-id-other-unit-is-not-learned', 'get', 0, ident=21000, native_answer=0,
         unit_a=dict(serial=1), unit_b=dict(serial=2), preset=store_entry(2, 21000))
    case('set-extension-id-records-the-learning', 'set', 0, ident=21000, on=True,
         native_answer=0xFFFFFFFF)
    case('set-extension-id-again-is-idempotent', 'set', 0, ident=21000, on=True,
         native_answer=0xFFFFFFFF, preset=store_entry(1, 21000))
    case('set-extension-id-off-clears-it', 'set', 0, ident=21000, on=False,
         native_answer=0xFFFFFFFF, preset=store_entry(1, 21000))
    case('set-extension-id-off-when-absent-is-the-native-done', 'set', 0, ident=21000, on=False,
         native_answer=0xFFFFFFFF)
    case('set-serial-zero-is-refused', 'set', 0xFFFFFFFF, ident=21000, on=True,
         native_answer=0xFFFFFFFF, unit_a=dict(serial=0))
    case('get-serial-zero-is-not-learned', 'get', 0, ident=21000, native_answer=0,
         unit_a=dict(serial=0), preset=store_entry(0, 21000))
    case('set-full-store-is-refused', 'set', 0xFFFFFFFF, ident=21000, on=True,
         native_answer=0xFFFFFFFF, fill_store=_learned.STORE_MAX_USED)

    # ---- the boundary between the bitmap and the store ---------------------------------------------
    case('boundary-position-999-is-the-games', 'get', 0, ident=1000, native_answer=0)
    case('boundary-position-1000-is-ours', 'get', 1, ident=21000, native_answer=0,
         preset=store_entry(1, 21000))
    case('boundary-position-1001-is-ours', 'get', 1, ident=21001, native_answer=0,
         preset=store_entry(1, 21001))
    case('boundary-position-999-set-stays-native', 'set', 0, ident=1000, on=True, native_answer=0)

    # ---- the generation guard ----------------------------------------------------------------------
    case('guard-verified-on-first-use', 'get', 0, ident=21000, native_answer=0, state=0,
         expect_state=1)
    case('guard-refuses-a-row-inserted-below-the-bitmap', 'get', 0, ident=21000, native_answer=0,
         keys=[0] + TABLE, preset=store_entry(1, 21000), expect_state=2)
    case('guard-refuses-a-changed-id', 'get', 0, ident=21000, native_answer=0,
         keys=TABLE[:3] + [99999] + TABLE[4:], preset=store_entry(1, 21000), expect_state=2)
    case('guard-refuses-a-shorter-table', 'get', 0, ident=21000, native_answer=0,
         keys=TABLE[:500], maxi=499, preset=store_entry(1, 21000), expect_state=2)
    case('guard-refusal-also-stops-the-setter', 'set', 0xFFFFFFFF, ident=21000, on=True,
         native_answer=0xFFFFFFFF, keys=TABLE[:3] + [99999] + TABLE[4:], expect_state=2)
    case('guard-refusal-leaves-the-bitmap-alone', 'get', 0, ident=21000, native_answer=0,
         unit_a=dict(serial=1, learned=(0, 999)), keys=[0] + TABLE, expect_state=2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', '--site-entry', action='store_true')
    ap.add_argument('--build-only', action='store_true')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    from d5lib import learned
    import evcap_engine as engine
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA, 'pinned exe changed'
    man = learned.manifest(TABLE)
    patched = learned.build_patch(original, man)
    info = learned.section_info(patched)
    sym = learned.data_symbols(info)
    results = []
    for case in cases(sym):
        kind = case['kind']
        sites = learned.GET_SITES if kind == 'get' else learned.SET_SITES
        unit_kw = {}
        for role, ptr in (('unit_a', engine.UNIT), ('unit_b', engine.OTHER)):
            spec = case.get(role)
            if spec:
                unit_kw[role] = engine.unit(spec.get('serial', 1), spec.get('learned', ()))
        preset = dict(case.get('preset') or {})
        if case.get('fill_store'):
            # live slots at their own hash positions is not what "full" means to a probe; a dense run of
            # live slots from the store's start is what a spent probe budget looks like
            n = case['fill_store']
            preset[sym['store']] = b''.join(struct.pack('<QII', 9000 + i, 50000 + i, 1) for i in range(n))
            preset[sym['used']] = struct.pack('<I', n)
        per_case = dict(name=case['name'], kind=kind, sites=len(sites), ok=True, failures=[])
        for site in sites:
            if args.build_only:
                per_case['build_only'] = True
                continue
            try:
                got = engine.run(patched, info, sym, kind, site, ident=case['ident'],
                                 on=case.get('on', False), abi=args.abi,
                                 keys=case.get('keys'), maxi=case.get('maxi'),
                                 native_answer=case.get('native_answer', 0),
                                 state=case.get('state'), preset=preset, **unit_kw)
                expect = case['expect']
                actual = got['output'] if kind == 'set' else got['low_byte']
                if kind == 'get' and case.get('native_answer', 0) > 0xFF:
                    actual = got['output']          # the whole native answer must survive
                assert actual == expect & 0xFFFFFFFF, f'answer {actual:#x} != {expect:#x}'
                if 'expect_state' in case:
                    assert got['state'] == case['expect_state'], \
                        f"guard state {got['state']} != {case['expect_state']}"
                if case['name'] == 'set-extension-id-records-the-learning':
                    assert got['store'] == [[1, 21000, 1]], f"store {got['store']!r}"
                    assert got['used'] == 1, f"used {got['used']}"
                if case['name'] == 'set-extension-id-off-clears-it':
                    assert got['store'] == [[1, 21000, 2]], f"store {got['store']!r}"
                    assert got['used'] == 0, f"used {got['used']}"
                # the receipts keep one full sample per case (the sites are identical by construction)
                per_case.setdefault('sample', dict(got, site=hex(site)))
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
                per_case['ok'] = False
                per_case['failures'].append(dict(site=hex(site), error=error))
                print(f"FAIL {case['name']} {site:#x} {error}")
        results.append(per_case)
    passed = args.build_only or all(r['ok'] for r in results)
    sites_used = sorted({r['kind'] for r in results})
    report = dict(mode='build-only' if args.build_only else 'abi-site-entry' if args.abi else 'behavior',
                  original_sha256=ORIGINAL_SHA, section=info['section'],
                  base_count=man['base_count'], ext_ids=man['ext_ids'],
                  generation=man['generation'], sites=dict(get=len(learned.GET_SITES),
                                                           set=len(learned.SET_SITES)),
                  kinds=sites_used, checks=results, passed=passed,
                  limitations=[
                      'The original getter/setter are `ret` stubs whose answer each case sets: the game\'s own '
                      'search and bit test are not executed, only the wrapper\'s use of their answer.',
                      'Unit records, the Skill key array and the store are synthetic fixtures; the live '
                      'pointers (0x140A04E48 / 0x140A04E38) are replaced by the fixtures at run time.',
                      'Executed paths only.  Windows unwind records are generated and statically audited, not '
                      'exercised, and nothing here is gameplay acceptance.',
                      'The inlined bitmap consumers in d5lib/learned.py\'s census are not hooked and are not '
                      'exercised by this proof (see EVCAP2-REPORT.md).'])
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    total = sum(r['sites'] for r in results)
    good = sum(r['sites'] - len(r['failures']) for r in results)
    print(f"{good}/{total} checks passed ({len(results)} cases)")
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
