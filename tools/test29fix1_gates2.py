"""TEST29FIX1 focused gates: class banks get all three checks, unique banks the TEST29c check."""
import json
import subprocess
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/striderlift4')
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
BUILD = ROOT / 'Builds/TEST29FIX1-20261101'
T29 = ROOT / 'Builds/D1CMOTION2-20261101/mods'
EV = BUILD / 'evidence'
PY = sys.executable
CLASS = [m for m in base.manifest()['banks'] if m.startswith('D1C_Class_')]
C_STUBS = (1011, 1017, 5001, 5021)


def gate(baseline, rebuilt, receipt, exempt, extra=(), pin=None):
    cmd = [PY, str(KIT / 'tools/striderlift_render_diff.py'), str(baseline), str(rebuilt),
           str(EV / receipt), '--baseline-label', 'baseline', '--exempt', *map(str, exempt)]
    if extra:
        cmd += ['--expect-extra', *map(str, extra)]
    if pin:
        cmd += ['--baseline-sha256', pin]
    r = subprocess.run(cmd, capture_output=True, text=True)
    tail = (r.stdout.strip().splitlines() or [''])[-1]
    print(f'gate {receipt}: rc={r.returncode} {tail[:140]}', flush=True)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-800:], flush=True)
    return r.returncode == 0


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else 'all'
    ok = True
    for mod, banks in base.manifest()['banks'].items():
        for bank in banks:
            pin = base.expected(mod, bank)
            b28 = base.bank_path(mod, bank)
            b29 = T29 / mod / base.REL / bank
            pb = BUILD / 'mods' / mod / base.REL / bank
            pc = BUILD / 'candidate-c/mods' / mod / base.REL / bank
            is_class = mod in CLASS
            if is_class and which in ('all', 'class'):
                ok &= gate(b29, pb, f'b-vs-test29-{mod}-{bank[:-4]}.json', ())
                ok &= gate(b28, pb, f'b-vs-test28-{mod}-{bank[:-4]}.json', (21, 27), (65003, 65004), pin)
                ok &= gate(b28, pc, f'c-vs-test28-{mod}-{bank[:-4]}.json', (21, 27) + C_STUBS, (), pin)
            elif not is_class and which in ('all', 'unique'):
                ok &= gate(b28, pc, f'c-vs-test28-{mod}-{bank[:-4]}.json', (21, 27), (), pin)
    print('FOCUSED GATES PASS' if ok else 'GATE FAILURE', flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
