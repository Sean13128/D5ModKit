"""BS-WHEELFIX vs BS-DARK: what actually differs on the page's motions.

BS-DARK (WHEELBISECT1) is the decisive variant: SLIM29 data present, 21/27 re-rooted to TEST28's
held picture, the worked art at unreferenced ids. BS-WHEELFIX gives the page the same picture by
re-pointing the wheel's spawn edges at private copies. If the only render difference between the two
is ids 21/27 themselves, then the page cannot tell them apart and WHEELFIX can take DARK's place in
the live order while keeping battle's hurt art.
"""
import json
import subprocess
import sys
from pathlib import Path

KIT = Path('/Volumes/Data/Projects/D5/Local/Worktrees/wheelbisect1')
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / 'tools'))
import d1cmotion2_base as base  # noqa: E402

ROOT = Path('/Volumes/Data/Projects/D5')
FIX = ROOT / 'Builds/WHEELFIX1-20261102'
DARK = ROOT / 'Builds/WHEELBISECT1-20261102/bs_dark/mods'
EV = FIX / 'evidence'
DIFF = KIT / 'tools' / 'striderlift_render_diff.py'

rows, ok = [], True
for mod in ('D1C_Class_11390', 'D1C_Class_11400'):
    for bank in base.manifest()['banks'][mod]:
        receipt = EV / f'render-wheelfix-vs-bs-dark-{mod}-{bank}.json'
        cmd = [sys.executable, str(DIFF), str(DARK / mod / base.REL / bank),
               str(FIX / 'mods' / mod / base.REL / bank), str(receipt),
               '--baseline-label', 'BS-DARK', '--expect-extra', '64031', '64041', '64051',
               '64061', '64071']
        subprocess.run(cmd, capture_output=True, text=True)
        rec = json.loads(receipt.read_text())
        ids = sorted({d['id'] for d in rec['differences']})
        # DARK keeps 21/27 = TEST28 while this build keeps them SLIM29's, so 21/27 differ by
        # construction; the four stand/pose stubs differ because they nest 21. The page's own
        # motions (1, 101, 1001, 7, 11, 6001) are not among the differences.
        allowed = {21, 27, 1011, 1017, 5001, 5021}
        print(f'{mod}/{bank}: differences only on {ids} '
              f'({len(rec["differences"])} samples), extras {rec["extra_ids"]}', flush=True)
        ok &= set(ids) <= allowed
        rows.append({'bank': f'{mod}/{bank}', 'difference_ids': ids,
                     'differences': len(rec['differences']),
                     'extra_ids': rec['extra_ids']})

(EV / 'render-vs-bs-dark.json').write_text(json.dumps({'pass': bool(ok), 'banks': rows},
                                                      indent=1) + '\n')
print('WHEELFIX vs BS-DARK: differences only in 21/27 and the four stubs that nest 21 -- '
      'every id the page selects renders the same' if ok else 'UNEXPECTED DIFFERENCES')
