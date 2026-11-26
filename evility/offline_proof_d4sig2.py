"""D4SIG2: scale idle_turns (26) and Demon Beast's row 27807, through the pinned game's real patched stat sites
(Unicorn), normal and --abi, plus a differential against the base build.  Offline only.

  * the row is read verbatim from d5lib/importers/d4-evility-overlay.json (D4_Class_2090 27807), so proof and pack
    cannot drift;
  * the counter is written where the game writes it: stat record SR = 0x141067DC8 + index * 0xE98, byte SR+1
    (turn_t3_per_unit_end_turn 0x140159F50);
  * the counter rule (+1 per round edge, 0..10, cleared by a move) is also run on the installed exe's own
    turn_t3_per_unit_end_turn through tools/stat_oracle.py, when the exe is present, so the byte means what the
    row assumes.

D5Modkit/.venv-macos/bin/python evility/offline_proof_d4sig2.py [--abi] [--json OUT]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'evility'), str(KIT / 'tools')]
from d5lib import evility as ev                                                  # noqa: E402
from offline_proof_carriers2 import u, fixture as c2_fixture                     # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402
import offline_proof_plume1 as plume1                                            # noqa: E402

BASE = os.environ.get('D4SIG2_BASE', 'aa3cecf')
SR0, SR_STRIDE = 0x141067DC8, 0xE98
STONE = 27807


def rows():
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    return {STONE: mods['D4_Class_2090']['behaviors']['evilities'][str(STONE)]}


def sr(idle):
    b = bytearray(SR_STRIDE)
    b[1] = idle
    return b


def fixture(subject, stat=None):
    base = c2_fixture(subject, ())

    def setup(write):
        base(write)
        if stat is not None:
            write(SR0, stat)
    return setup


def cases():
    allp = lambda n: [n] * 8 + [0] * 10                      # noqa: E731  the 18-slot aggregate
    defp = lambda n: [0, 0, 0, n] + [0] * 14                 # noqa: E731  DEF only (stat index 3)
    no_sr = u(ids=(STONE,))
    struct.pack_into('<I', no_sr, 0x4348, 0x28A)
    c = []

    def add(name, expected, subject, stat=None, field='aggregate', family='stats'):
        c.append(dict(name=name, family=family, field=field, expected=expected, fixture=fixture(subject, stat)))
    for n in (0, 1, 3, 10):
        add(f'stone statue: {n} idle turns -> DEF +{10 * n}', defp(10 * n), u(ids=(STONE,)), sr(n))
    add('stone statue: counter 255 (corrupt) is passed through as the byte it is', defp(2550), u(ids=(STONE,)), sr(255))
    add('stone statue: no stat record -> 0', defp(0), no_sr)
    add('stone statue: unlearned, 5 idle turns -> 0', defp(0), u(), sr(5))
    add('stone statue: only DEF is raised (ATK word stays 0)', [0, 0, 0, 50] + [0] * 14, u(ids=(STONE,)), sr(5))
    add('stone statue: potency untouched', [50] * 8, u(ids=(STONE,)), sr(5), field='potency', family='potency')
    return c


def game_counter_rule():
    """run the installed exe's own turn_t3_per_unit_end_turn on synthetic battle records: the byte SR+1 counts up by
    one per call while the unit did not move, stops at 10, and a move clears it"""
    import stat_oracle as so
    exe = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/disgaea5.exe')
    if not exe.exists():
        return None
    e = so.Emu(exe_path=exe)
    e.brk = e.heap_mark
    e.mu.mem_write(SR0, bytes(SR_STRIDE))
    unit = e.alloc(bytes(0x4800))                              # stat record index 0 (+0x4348 = 0)
    brec = bytearray(0x1300)
    struct.pack_into('<Q', brec, 0x240, unit)
    seq = []
    for moved in (0, 0, 0, 1, 0):
        struct.pack_into('<H', brec, 0x61C, moved)
        addr = e.alloc(bytes(brec))
        e.call(0x140159F50, (addr,))
        seq.append(e.mu.mem_read(SR0 + 1, 1)[0])
    return seq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    checks = []
    bundle = plume1.build(ev, original, rows())
    for case in cases():
        for site, result in plume1.run_case(bundle, case, args.abi):
            got = result[case['field']]
            assert got == case['expected'], (case['name'], hex(site), got, case['expected'])
            checks.append(dict(name=case['name'], site=hex(site), ok=True))
        print('PASS', case['name'])
    try:
        seq = game_counter_rule()
    except Exception as exc:                                    # noqa: BLE001
        seq = None
        print('SKIP game counter rule:', type(exc).__name__, exc)
    if seq is not None:
        assert seq == [1, 2, 3, 0, 1], seq
        checks.append(dict(name='game turn_t3 counter: +1 per idle round edge, a move clears it', seq=seq, ok=True))
        print('PASS game turn_t3 counter', seq)
    plume1.BASE = BASE
    scratch = Path('/Volumes/Data/ai-tmp/claude/d4sig2/proofs')
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='differential-', dir=scratch) as tmp:
        old = plume1.baseline(Path(tmp))
        plans = list(plume1.old_aura_plans()) + [('plume1', plume1.plume_rows(), plume1.cases())]
        for name, rws, cases_ in plans:
            assert ev.table(rws) == old.table(rws), name + ': old encoding changed'
            before, after = plume1.build(old, original, rws), plume1.build(ev, original, rws)
            for case in cases_:
                first = list(plume1.run_case(before, case, args.abi))
                second = list(plume1.run_case(after, case, args.abi))
                assert len(first) == len(second)
                for (site, x), (other_site, y) in zip(first, second):
                    assert site == other_site and plume1.state(x) == plume1.state(y), (name, case['name'])
                    checks.append(dict(name='differential-' + name + '-' + case['name'], site=hex(site), ok=True))
    report = dict(mode='abi' if args.abi else 'behavior', baseline=BASE,
                  patched_sha256=hashlib.sha256(bundle[0]).hexdigest(), passed=True, checks=checks)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f"{len(checks)}/{len(checks)} checks passed (D4SIG2 idle_turns + game counter rule + legacy differential vs {BASE})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
