"""D1CMOTION3 gates: render-diff every shipped bank against its **TEST28** base, then prove the
hurt slot actually changed.

Every baseline is resolved through `tools/d1cmotion2_base.py`, whose sha256 set is
`tools/test28-base.json` (verified equal to `Local/Installed D5ModKit/mods`). The receipt records
the baseline sha256 and the diff is refused if that sha is not the pinned TEST28 one — a TEST26
backup or a rebuilt pack can no longer stand in for the baseline (that is how D1CMOTION2 shipped a
TEST26 base with clean gates).

  python tools/d1cmotion2_gates.py [--mods DIR] [--out DIR] [banks...]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import d1cmotion2_base as base  # noqa: E402
from d5lib import anm  # noqa: E402

BUILD = base.ROOT / 'Builds/D1CMOTION2-20261101'


def short(mod):
    return mod.rsplit('_', 1)[1]


def entries(only=None):
    doc = base.manifest()
    for mod, banks in doc['banks'].items():
        for bank in banks:
            if only and f'{mod}/{bank}' not in only and mod not in only:
                continue
            yield mod, bank


def render_diff(mods, out, only=None):
    rows = []
    for mod, bank in entries(only):
        built = mods / mod / base.REL / bank
        if not built.is_file():
            raise SystemExit(f'{mod}/{bank}: built bank missing at {built}')
        receipt = out / 'proofs' / f'render-diff-{short(mod)}-{bank[:-4]}.json'
        want = base.expected(mod, bank)
        cmd = [sys.executable, str(HERE / 'striderlift_render_diff.py'),
               str(base.bank_path(mod, bank)), str(built), str(receipt),
               '--exempt', '21', '27', '--expect-extra', '65003', '65004',
               '--baseline-label', 'TEST28', '--baseline-sha256', want]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        print(f'{mod}/{bank}: {proc.stdout.strip().splitlines()[-1] if proc.stdout else proc.stderr[-400:]}',
              flush=True)
        if proc.returncode != 0:
            raise SystemExit(f'{mod}/{bank}: render gate failed\n{proc.stdout}\n{proc.stderr}')
        doc = json.loads(receipt.read_text())
        if doc['baseline_sha256'] != want:
            raise SystemExit(f'{mod}/{bank}: receipt baseline is not TEST28: {doc["baseline_sha256"]}')
        rows.append(dict(mod=mod, bank=bank, baseline_sha256=doc['baseline_sha256'],
                         samples=doc['samples_compared'], exempt=doc['exempt_samples'],
                         differences=len(doc['differences']), extra=doc['extra_ids'],
                         receipt=str(receipt)))
    return rows


def hurt_check(mods, out):
    """All keys of 21 and 27 must be non-blank and differ from the TEST28 base."""
    rows, bad = [], []
    for mod, bank in entries():
        old = anm.load(base.bank_path(mod, bank).read_bytes())
        new = anm.load((mods / mod / base.REL / bank).read_bytes())
        oi = {x['id']: x['index'] for x in anm.list_animations(old)}
        ni = {x['id']: x['index'] for x in anm.list_animations(new)}
        row = dict(mod=mod, member=bank)
        for aid in (21, 27):
            times_o = list(anm.frame_times(old, oi[aid]))
            times_n = list(anm.frame_times(new, ni[aid]))
            blank = changed = 0
            for t in times_n:
                io, _ = anm.render_items(old, anm.evaluate(old, oi[aid], t, nested=True), palette_index=0)
                im, _ = anm.render_items(new, anm.evaluate(new, ni[aid], t, nested=True), palette_index=0)
                if im.getchannel('A').getbbox() is None:
                    blank += 1
                if io.tobytes() != im.tobytes():
                    changed += 1
            row[str(aid)] = dict(keys_before=times_o, keys_after=times_n, blank_keys=blank,
                                 changed_keys=changed)
            if blank or changed != len(times_n) or len(times_n) != 7:
                bad.append((mod, bank, aid, blank, changed, times_n))
        rows.append(row)
        print(f'{mod}/{bank}: 21 {row["21"]["changed_keys"]}/7 27 {row["27"]["changed_keys"]}/7', flush=True)
    (out / 'hurt-slot-changed.json').write_text(json.dumps(rows, indent=2) + '\n')
    if bad:
        raise SystemExit(f'hurt slot not fully changed/non-blank: {bad}')
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mods', default=str(BUILD / 'mods'))
    ap.add_argument('--out', default=str(BUILD / 'install-proof'))
    ap.add_argument('banks', nargs='*')
    args = ap.parse_args()
    mods, out = Path(args.mods), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'proofs').mkdir(parents=True, exist_ok=True)
    only = set(args.banks) or None
    print(f'base pins: {base.require_base_set()} banks; '
          f'{base.require_installed_match()} files equal the installed TEST28 kit', flush=True)
    rows = render_diff(mods, out, only)
    hurt = hurt_check(mods, out) if not only else []
    total = dict(banks=len(rows), samples=sum(r['samples'] for r in rows),
                 exempt=sum(r['exempt'] for r in rows), differences=sum(r['differences'] for r in rows))
    (out / 'gate-summary.json').write_text(json.dumps(dict(base=str(base.class_base()),
                                                           unique_base=str(base.unique_base()),
                                                           totals=total, banks=rows), indent=2) + '\n')
    print(f"GATES PASS: {total['banks']} banks, {total['samples']} samples, "
          f"{total['exempt']} exempt (21/27), {total['differences']} differences outside")
    print(f"hurt slot: {len(hurt)} banks fully changed (7/7 keys, non-blank)")


if __name__ == '__main__':
    main()
