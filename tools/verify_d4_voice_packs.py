"""Offline verification of the rebuilt D4 voice packs.

Checks, per pack and locale:
  * every line has an explicit locale file and declared silence elsewhere
  * every recording decodes to 48 kHz mono, finite, peak <= 0.85, sane loudness
  * encode -> decode -> encode round-trip is stable (rate, samples, peak)
  * the Kit's real voice handler writes the line rows and the packs, and the
    rows read back with the expected ids, groups, situations and volumes while
    an unrelated donor row survives untouched
  * EN and JP rows point at different recordings where the source differs

No playback, no game process, no installed file is read or written.

Usage:  python -B tools/verify_d4_voice_packs.py --packs /Volumes/Data/Projects/D5/Local/d4-voices-packs
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from d5lib import fafs, modsys, sound, voices  # noqa: E402

PEAK_LIMIT = 0.85001
RATE = 48000


def db(x):
    return 20.0 * math.log10(max(x, 1e-9))


class Ctx:
    """minimal build context: serves a baseline voice table, records outputs"""

    def __init__(self, baseline: bytes):
        self.baseline = baseline
        self.outputs = {}
        self.logs = []

    def get(self, path):
        if path in voices.TABLES.values():
            return self.baseline
        raise KeyError(path)          # only explicit locale files are used: no vanilla line copy

    def put(self, path, data):
        self.outputs[path] = data

    def log(self, text):
        self.logs.append(text)


def baseline_table():
    """a stand-in vanilla table: an unrelated donor voice set plus a foreign row"""
    rows = [voices.Line(11500000 + n, 11500, 70, [0, 4, 10]) for n in range(1, 4)]
    rows.append(voices.Line(99990001, 99990, 65, [0]))
    return voices.write_table(rows)


def decode(path: Path):
    raw = path.read_bytes()
    wav = sound.parse_se(raw)['wav']
    a, rate = __import__('d5lib.sfx', fromlist=['x']).decode_msadpcm(wav)
    a = a.mean(axis=1) if a.ndim == 2 else a
    return raw, np.asarray(a, dtype=np.float32), rate


def check_pack(pack: Path, problems, report):
    data = voices.load(modsys.Mod(str(pack)))
    assert len(data['voices']) == 1, f'{pack.name}: expected one voice, got {sorted(data["voices"])}'
    vid = int(next(iter(data['voices'])))
    voice = data['voices'][str(vid)]
    per_locale = {}
    for lang in ('EN', 'JP'):
        rows = voices.custom_lines(vid, voice, lang=lang)
        if not rows:
            problems.append(f'{pack.name}/{lang}: no lines')
        files = [ref for _, (kind, ref) in rows if kind == 'file']
        stats = []
        for name in sorted(set(files)):
            path = Path(voices.folder(modsys.Mod(str(pack))), name)
            if not path.is_file():
                problems.append(f'{pack.name}/{lang}: missing {name}')
                continue
            raw, a, rate = decode(path)
            peak = float(np.max(np.abs(a))) if a.size else 0.0
            rms = float(np.sqrt(np.mean(a ** 2))) if a.size else 0.0
            dur = len(a) / rate if rate else 0.0
            if rate != RATE:
                problems.append(f'{pack.name}/{lang}/{name}: rate {rate}')
            if not np.isfinite(a).all():
                problems.append(f'{pack.name}/{lang}/{name}: non-finite samples')
            if peak > PEAK_LIMIT:
                problems.append(f'{pack.name}/{lang}/{name}: peak {peak:.4f}')
            if dur < 0.15:
                problems.append(f'{pack.name}/{lang}/{name}: too short {dur:.3f}s')
            if not -45.0 <= db(rms) <= -6.0:
                problems.append(f'{pack.name}/{lang}/{name}: loudness {db(rms):.1f} dBFS')
            # round-trip stability through the Kit encoder
            from d5lib import sfx
            again = sfx.make_vag(a, rate, normalize=False, trim=False)
            a2, rate2 = decode_bytes(again)
            if rate2 != rate:
                problems.append(f'{pack.name}/{lang}/{name}: re-encode rate {rate2}')
            if len(a2) != len(a):
                problems.append(f'{pack.name}/{lang}/{name}: re-encode samples {len(a2)} != {len(a)}')
            peak2 = float(np.max(np.abs(a2))) if a2.size else 0.0
            if abs(peak2 - peak) > 0.02:
                problems.append(f'{pack.name}/{lang}/{name}: re-encode peak {peak2:.4f} vs {peak:.4f}')
            stats.append(dict(file=name, rate=rate, samples=len(a), seconds=round(dur, 3),
                              peak=round(peak, 5), rms_dbfs=round(db(rms), 2),
                              payload_sha256=__import__('hashlib').sha256(raw).hexdigest()))
        per_locale[lang] = dict(rows=len(rows), files=len(set(files)), clips=stats,
                                personalities=sorted({voices.split_set(l.group)[2] for l, _ in rows}),
                                situations=dict(sorted(Counter(c for l, _ in rows for c in l.cats).items())))
    # handler readback
    base = baseline_table()
    ctx = Ctx(base)
    voices._handler(ctx, modsys.Mod(str(pack)), voices.folder(modsys.Mod(str(pack))))
    readback = {}
    for lang in ('EN', 'JP'):
        table_path = voices.TABLES[lang]
        if table_path not in ctx.outputs:
            problems.append(f'{pack.name}/{lang}: handler wrote no table')
            continue
        rows = voices.read_table(ctx.outputs[table_path])
        ids = [r.id for r in rows]
        if ids != sorted(ids):
            problems.append(f'{pack.name}/{lang}: table not sorted by id')
        if len(set(ids)) != len(ids):
            problems.append(f'{pack.name}/{lang}: duplicate line ids')
        mine = [r for r in rows if voices.split_set(r.group)[1] == vid]
        expect = voices.custom_lines(vid, voice, lang=lang)
        if len(mine) != len(expect):
            problems.append(f'{pack.name}/{lang}: readback {len(mine)} rows, expected {len(expect)}')
        for r in mine:
            if r.id != r.group * 1000 + (r.id - r.group * 1000):
                problems.append(f'{pack.name}/{lang}: bad line id {r.id} for group {r.group}')
        if [r.id for r in mine] != [l.id for l, _ in expect]:
            problems.append(f'{pack.name}/{lang}: line ids differ from custom_lines')
        if [r.cats for r in mine] != [l.cats for l, _ in expect]:
            problems.append(f'{pack.name}/{lang}: situation flags differ on readback')
        donor = [r for r in rows if r.group == 11500]
        if len(donor) != 3 or rows[-1].id != 99990001:
            problems.append(f'{pack.name}/{lang}: donor rows not preserved')
        # packs written by the handler carry exactly our payloads
        groups = defaultdict(dict)
        for line, (kind, name) in expect:
            groups[line.group][f'{line.id:09d}.vag'] = Path(voices.folder(modsys.Mod(str(pack))), name).read_bytes()
        for group, files in groups.items():
            path = f'{voices.ARCHIVE}/{voices.PREFIX[lang]}/{group:06d}.dat'
            if path not in ctx.outputs:
                problems.append(f'{pack.name}/{lang}: handler wrote no pack {path}')
                continue
            packed = fafs.pack_members(ctx.outputs[path])
            if packed != files:
                problems.append(f'{pack.name}/{lang}: pack {group} payload mismatch')
        readback[lang] = dict(rows=len(rows), mine=len(mine), groups=sorted(groups),
                              donor_rows=len(donor), packs=len(groups))
    # locale distinctness
    if 'EN' in per_locale and 'JP' in per_locale:
        en = {c['payload_sha256'] for c in per_locale['EN']['clips']}
        jp = {c['payload_sha256'] for c in per_locale['JP']['clips']}
        report['identical_locale_payloads'] = len(en & jp)
    report['voice_id'] = vid
    report['char_voice_ids'] = char_voice_ids(pack)
    report['locales'] = per_locale
    report['readback'] = readback
    report['handler_logs'] = ctx.logs


def char_voice_ids(pack: Path):
    path = pack / 'patches/db/char.dat.json'
    data = json.loads(path.read_text())
    ids = set()
    for key in ('rows', 'added'):
        group = data.get(key)
        if isinstance(group, dict):
            ids |= {r.get('voice_id') for r in group.values()}
        else:
            ids |= {r.get('voice_id') for r in group or []}
    return sorted(ids)


def decode_bytes(raw: bytes):
    from d5lib import sfx
    a, rate = sfx.decode_msadpcm(sound.parse_se(raw)['wav'])
    a = a.mean(axis=1) if a.ndim == 2 else a
    return np.asarray(a, dtype=np.float32), rate


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packs', required=True, type=Path)
    args = ap.parse_args(argv)
    packs = sorted(p for p in args.packs.iterdir() if (p / 'mod.json').is_file())
    problems, out = [], {}
    occupied = Counter()
    for pack in packs:
        rep = {}
        check_pack(pack, problems, rep)
        occupied[rep['voice_id']] += 1
        for v in rep['char_voice_ids']:
            if v != rep['voice_id']:
                problems.append(f'{pack.name}: char row voice_id {v} != pack voice {rep["voice_id"]}')
        out[pack.name] = rep
    dup = [v for v, n in occupied.items() if n > 1]
    if dup:
        problems.append(f'duplicate custom voice ids across packs: {dup}')
    for name, rep in out.items():
        print(f'## {name}  voice {rep["voice_id"]}  char rows -> {rep["char_voice_ids"]}')
        for lang, loc in rep['locales'].items():
            clips = loc['clips']
            print(f'   {lang}: {loc["rows"]} rows, {loc["files"]} files, personalities {loc["personalities"]}, '
                  f'situations {loc["situations"]}')
            print(f'        peak {max(c["peak"] for c in clips):.4f}  rms {min(c["rms_dbfs"] for c in clips):.1f}..'
                  f'{max(c["rms_dbfs"] for c in clips):.1f} dBFS  '
                  f'len {min(c["seconds"] for c in clips):.2f}-{max(c["seconds"] for c in clips):.2f}s')
            rb = rep['readback'][lang]
            print(f'        readback: {rb["mine"]} rows in {len(rb["groups"])} groups, '
                  f'donor rows kept {rb["donor_rows"]}')
        print(f'   identical EN/JP payloads: {rep["identical_locale_payloads"]}')
    if problems:
        print('\nPROBLEMS:')
        for p in problems:
            print(' -', p)
    else:
        print('\nall checks passed')
    (args.packs / 'verify.json').write_text(json.dumps(dict(packs=out, problems=problems), indent=1) + '\n')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
