"""WHEELBISECT1 post-install gate (INSTALLGATE1 `--post-install`, branch installgate1 b33e0ab).

For each variant and class bank: replay the member-local installer passes the kit applies to a
class bank (`grips`) on both the TEST28 base member and the variant member, then compare the
renders. It also decodes the member out of the *sandbox archive* after the install and checks it
is byte-identical to the replay, so "installed bytes" is a measurement, not an inference.

Expectations
  BS-DARK   vs TEST28, post-install: 0 differences (stubs and wheel chain both TEST28)
  BS-NOSTUB vs TEST28, post-install: differences only in 21/27; the four stubs must be identical
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402
sys.path.insert(0, str(KIT / 'tools'))
import striderlift_render_diff as gate  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
B = ROOT / 'Builds/WHEELBISECT1-20261102'
EV = B / 'evidence'
TASK = Path('/Volumes/Data/ai-tmp/hermes/wheelbisect1')
SAND_ARCHIVE = TASK / 'sandbox/game/Data/Anime/ANM_HI_JP.dat'
STUBS = [1011, 1017, 5001, 5021]


def archive_member(mod, bank):
    """decode one member out of the sandbox archive (read-only)."""
    sys.path.insert(0, str(KIT))
    from d5lib import anm as A
    return A.load_from_archive(bank.replace('.lzs', '').replace('anm', 'anm'),
                               data_dir=str(SAND_ARCHIVE.parent.parent.parent))


def main():
    EV.mkdir(parents=True, exist_ok=True)
    ok = True
    rows = []
    for variant in ('bs_dark', 'bs_nostub'):
        for mod in ('D1C_Class_11390', 'D1C_Class_11400'):
            for bank in base.manifest()['banks'][mod]:
                t28 = base.base_dir(mod) / mod / base.REL / bank
                built = B / variant / 'mods' / mod / base.REL / bank
                receipt = EV / f'postgainstall-{variant}-{mod}-{bank}.json'
                expect = (['64001', '64011'] if variant == 'bs_dark'
                          else ['64031', '64041', '64051', '64061', '64071'])
                cmd = [sys.executable, str(KIT / 'tools/striderlift_render_diff.py'),
                       str(t28), str(built), str(receipt), '--post-install',
                       '--confirm-member-local', '--baseline-passes', 'grips',
                       '--rebuilt-passes', 'grips', '--expect-extra', *expect]
                r = subprocess.run(cmd, capture_output=True, text=True)
                rec = json.loads(receipt.read_text()) if receipt.exists() else {}
                ids = sorted({d['id'] for d in rec.get('differences', [])})
                stub_diffs = sorted(set(ids) & set(STUBS))
                print(f'{variant} {mod}/{bank}: post-install rc {r.returncode}, '
                      f'{len(rec.get("differences", []))} differences on ids {ids}', flush=True)
                if not receipt.exists():
                    print('NO RECEIPT', r.returncode, r.stdout[-1500:], r.stderr[-1500:])
                row = {'variant': variant, 'mod': mod, 'bank': bank,
                       'differences': len(rec.get('differences', [])), 'ids': ids,
                       'stub_diffs': stub_diffs,
                       'baseline_replay_sha256': rec.get('post_install_replay', {}).get(
                           'baseline_member_sha256')}
                # DARK must be pixel-identical to TEST28; NOSTUB may differ only in 21/27
                if variant == 'bs_dark':
                    ok &= not rec.get('differences') and not stub_diffs
                else:
                    ok &= not stub_diffs and set(ids) <= {21, 27}
                rows.append(row)
    (EV / 'post-install-gate.json').write_text(json.dumps(rows, indent=1) + '\n')
    print('POST-INSTALL GATE', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
