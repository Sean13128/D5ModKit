"""EVCAP2 save round-trip on *copies* of the real saves (they are test data).

What it proves, offline and without launching the game:

  1. every roster unit of a real save still has its learned-evility bitmap decoded to the same evility ids
     through the generated manifest -- i.e. the extension adds positions *after* the 1,000 the save uses and
     moves no existing bit's meaning;
  2. the kit's own writer round-trips the save (state byte-identical after write + re-read) and the decoded
     learned sets are identical before and after;
  3. the versioned companion (.d5learn.json) validates against the exact save bytes, refuses a changed save,
     refuses a different table generation, and quarantines (never drops) an id the table no longer has;
  4. nothing here writes anywhere but the scratch copies.

Save2 is known-bad (AGENTS.md) and is not opened at all.  Source saves are copied first; the originals and
the installed kit are only read.

    python evility/evcap_save_roundtrip.py [--json evility/results/evcap-save.json]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))

from d5lib import database, learned, ordercheck, savegame  # noqa: E402

DB = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/Data/Database/Database_0.dat"
SAVES = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/D5ModKit/"
             "profiles/.shared_saves/27885847/SaveData")
SCRATCH = Path("/Volumes/Data/ai-tmp/evcap2/saves")
BITMAP_OFF, BITMAP_LEN = 0x2E70, 125
SERIAL_OFF = 0x3060


def learned_sets(save, table_ids):
    """{serial: (name, learned ids, bitmap sha256)} for every unit the save lists"""
    out = {}
    for u in save.units():
        rec = save.state[0x23B2B8 + u.slot * savegame.UNIT:][:savegame.UNIT]
        bitmap = bytes(rec[BITMAP_OFF:BITMAP_OFF + BITMAP_LEN])
        serial = int.from_bytes(rec[SERIAL_OFF:SERIAL_OFF + 8], 'little')
        name = bytes(rec[0xBC8:0xC08]).split(b'\0')[0].decode('utf-8', 'replace')
        out[u.slot] = dict(slot=u.slot, serial=serial, name=name,
                           learned=sorted(learned.learned_from_bitmap(bitmap, table_ids)),
                           bitmap_sha256=hashlib.sha256(bitmap).hexdigest())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path, default=Path('evility/results/evcap-save.json'))
    ap.add_argument('--save', default='Save_001.sav')
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    ids = ordercheck._ids(database.load_database(DB).table('Skill.dat'))
    man = learned.manifest(ids)
    src = SAVES / args.save
    work = SCRATCH / args.save
    shutil.copy2(src, work)                       # a copy: the real save is never touched
    before_bytes = work.read_bytes()
    save = savegame.Save(str(work))
    before = learned_sets(save, ids)

    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    units = len(before)
    setbits = sum(len(v['learned']) for v in before.values())
    check('save-parsed', units > 0, dict(units=units, army=save.army_count, reserve=save.reserve_count))
    check('every-learned-bit-has-a-table-row',
          all(all(0 <= ids.index(i) < learned.BIT_CAPACITY for i in v['learned']) for v in before.values()),
          dict(learned_total=setbits))
    check('serial-unique-and-nonzero',
          len({v['serial'] for v in before.values()}) == units and all(v['serial'] for v in before.values()),
          dict(serials=len({v['serial'] for v in before.values()})))
    check('manifest-keeps-every-save-bit-native', man['base_count'] <= learned.BIT_CAPACITY,
          dict(base_count=man['base_count'], extra_rows=len(man['ext_ids'])))

    # 2. the kit's own writer round-trip
    second = SCRATCH / ("roundtrip-" + args.save)
    shutil.copy2(work, second)
    copy = savegame.Save(str(second))
    copy.write()
    reread = savegame.Save(str(second))
    after = learned_sets(reread, ids)
    check('writer-roundtrip-state-identical', bytes(reread.state) == bytes(copy.state),
          dict(state_sha=hashlib.sha256(bytes(reread.state)).hexdigest()[:16]))
    check('learned-sets-identical-after-roundtrip', before == after,
          dict(units=len(after), learned_total=sum(len(v['learned']) for v in after.values())))
    check('bitmap-untouched-by-write',
          all(before[s]['bitmap_sha256'] == after[s]['bitmap_sha256'] for s in before),
          dict(bitmaps=len(before)))

    # 3. the companion
    extensions = [ids[-1] + 1, ids[-1] + 2]        # two would-be rows beyond the current table
    table_with_ext = list(ids) + extensions
    serials = [v['serial'] for v in before.values() if v['serial']]
    extra = {serials[0]: [extensions[0]], serials[1]: [extensions[0], extensions[1]]}
    doc = learned.sidecar_doc(str(work), table_with_ext, extra,
                              unit_names={v['serial']: v['name'] for v in before.values()})
    side = str(work) + learned.SIDECAR_SUFFIX
    learned.sidecar_write(side, doc)
    ok, problems, quarantine = learned.sidecar_validate(learned.sidecar_read(side), str(work), table_with_ext)
    check('sidecar-validates', ok and not quarantine, dict(problems=problems, units=len(doc['units'])))
    ok2, problems2, _ = learned.sidecar_validate(doc, str(second), table_with_ext)
    check('sidecar-refuses-a-renamed-save', not ok2, dict(problems=problems2))
    ok3, problems3, _ = learned.sidecar_validate(doc, str(work), ids)
    check('sidecar-refuses-a-different-generation', not ok3, dict(problems=problems3))
    doc2 = json.loads(json.dumps(doc))
    doc2['units'][f'{serials[0]:016x}']['learned'].append(999999)
    ok4, problems4, quarantine4 = learned.sidecar_validate(doc2, str(work), table_with_ext)
    check('sidecar-quarantines-an-unknown-id',
          ok4 and quarantine4 and quarantine4[0]['id'] == 999999, dict(quarantine=quarantine4))
    doc3 = json.loads(json.dumps(doc))
    doc3['schema'] = 99
    ok5, problems5, _ = learned.sidecar_validate(doc3, str(work), table_with_ext)
    check('sidecar-refuses-an-unknown-schema', not ok5, dict(problems=problems5))

    # 4. the copies are the only things touched
    check('source-save-unchanged', src.read_bytes() == before_bytes,
          dict(sha256=hashlib.sha256(before_bytes).hexdigest()))
    report = dict(save=args.save, source=str(src), scratch=str(SCRATCH),
                  table_rows=len(ids), generation=man['generation'],
                  units=[dict(slot=v['slot'], serial=v['serial'], name=v['name'],
                              learned=len(v['learned'])) for v in before.values()],
                  checks=checks, passed=all(c['ok'] for c in checks),
                  limitations=[
                      'Offline: the save is parsed and re-written by the kit\'s own reader/writer; the game '
                      'does not run, so "loads" here means the save still parses to the same state and the '
                      'decoded learned sets are unchanged.',
                      'The companion is written and validated beside a scratch copy only; the game cannot read '
                      'a companion yet (applying it to the in-memory store needs the native load path, '
                      'which is phase 2).',
                      'Save2 is known-bad and is not opened.'])
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=1) + '\n')
    for c in checks:
        print(('PASS ' if c['ok'] else 'FAIL ') + c['name'] + ('' if c['ok'] else f"  {c['detail']}"))
    print(f"{sum(c['ok'] for c in checks)}/{len(checks)} checks passed; "
          f"{units} units, {setbits} learned evilities decoded")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
