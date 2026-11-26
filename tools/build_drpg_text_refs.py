"""TEXTHASH-DRPG maintainer tool: DRPG data files carry game text as references (see d5lib/importers/_drpg_text.py).

    python tools/build_drpg_text_refs.py convert            # literal -> references, in place (idempotent)
    python tools/build_drpg_text_refs.py verify [--against REV] [--source DIR] [--game-path P --state S]

``verify`` resolves every file against the real pool (the verified prepared folder plus the Disgaea 5 tables read
through the kit backups), requires every ``@text`` to be found, and, with ``--against REV``, requires the resolved
document to equal the literal document the file held at that git revision (so no text changed).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib.importers import _drpg_text  # noqa: E402

IMP = ROOT / 'd5lib' / 'importers'
FILES = tuple(IMP / name for name in _drpg_text.REFIFY)


def _canon(doc):
    return json.dumps(doc, sort_keys=True, ensure_ascii=False)


def convert():
    for path in FILES:
        doc = json.loads(path.read_text(encoding='utf-8'))
        doc = _drpg_text.refify(path.name, doc)
        path.write_text(_drpg_text.format_doc(doc), encoding='utf-8')
        print(f'{path.name}: {path.stat().st_size} bytes')


def verify(args):
    from d5lib import modsys, paths
    from d5lib.importers import _drpg_build
    game = args.game_path or str(paths.require_game_dir())
    state = args.state or str(modsys.game_state_dir(game, modsys.KIT_DIR))
    fs = _drpg_build.source_fs(dict(game_path=game, state_root=state))
    try:
        from d5lib.importers import _drpg_roster, _drpg_source
        pool = _drpg_roster.TextPool.from_sources(_drpg_source.data(args.source), fs)
    finally:
        fs.reset()
    bad = 0
    for path in FILES:
        doc = _drpg_text.load(path, pool)
        line = f'{path.name}: resolved'
        if args.against:
            old = subprocess.check_output(['git', 'show', f'{args.against}:{path.relative_to(ROOT)}'], cwd=ROOT, text=True)
            old = json.loads(old)
            if path.name == 'drpg-evility-names.json':
                same = _drpg_text.evility_names(doc) == old['names'] and {k: v for k, v in doc.items() if k != 'names'} == {k: v for k, v in old.items() if k != 'names'}
            else:
                same = _canon(doc) == _canon(old)
            line += ' == literal at ' + args.against if same else ' DIFFERS from literal at ' + args.against
            bad += not same
        print(line)
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('convert')
    v = sub.add_parser('verify')
    v.add_argument('--against')
    v.add_argument('--source')
    v.add_argument('--game-path')
    v.add_argument('--state')
    args = ap.parse_args(argv)
    if args.cmd == 'convert':
        convert()
        return 0
    return verify(args)


if __name__ == '__main__':
    raise SystemExit(main())
