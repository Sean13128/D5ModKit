"""EVCAP3/EVCAP4 simulated save -> quit -> load round trip on *copies* of the real saves (offline).

The game does not run.  What runs is the real runtime code (d5lib/native/d5learn.inc.c, built for the host by
evility/evcap3_host.c) against the real assembled `.d5lc` section, driven exactly as learn_tick() is driven by
the game's save and load relays:

  session A  two units "learn" two evilities that live past the 1,000-bit bitmap, then the game saves: its
             writer reports slot 1 with success (what lc_save_relay publishes), the runtime builds
             "<savedir>/Save_001.sav", checks the file really is a slot file of this game, hashes it and
             writes "<save>.d5learn.json".
  quit       the process ends; a new one starts with an empty store (that is what quitting does).
  session B  the game loads that slot: the runtime reads the companion, validates it against the save's bytes
             and this table's generation, and refills the store.
  session C  a save with no companion loads native-only, and a companion that does not match its save is
             refused and kept aside -- never paired, never silently read as "no learning".

The save file itself is only ever read: every check compares its bytes and the decoded native learning before
and after, so "old saves load unchanged" is measured, not assumed.  Save2 is known-bad (AGENTS.md) and is not
opened.  Everything happens under /Volumes/Data/ai-tmp/evcap3/saves on copies.

    python evility/evcap3_save_roundtrip.py [--json evility/results/evcap3-save.json]
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))

from d5lib import database, learned, ordercheck, savegame  # noqa: E402

DB = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/Data/Database/Database_0.dat"
SAVES = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/D5ModKit/"
             "profiles/.shared_saves/27885847/SaveData")
SCRATCH = Path("/Volumes/Data/ai-tmp/evcap4/saves")
PINNED = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/'
              'Disgaea_5_Complete-d8040a88/backups/EXE__disgaea5.exe.full')
BITMAP_OFF, BITMAP_LEN = 0x2E70, 125
SERIAL_OFF = 0x3060


def learned_sets(save, table_ids):
    """{slot: {...}} for every unit the save lists: serial, name, native learned ids, bitmap digest"""
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


def build_host(binary):
    cc = shutil.which('cc') or shutil.which('clang') or 'cc'
    subprocess.run([cc, '-O1', '-DD5LEARN_HOST', '-o', str(binary),
                    str(KIT / 'evility' / 'evcap3_host.c')], check=True, capture_output=True)
    return str(binary)


def run(binary, section, keys, savedir, *actions):
    r = subprocess.run([binary, section, keys, savedir] + list(actions), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def pairs_from(stdout):
    out = []
    for line in stdout.splitlines():
        if line.startswith('-- '):
            break
        serial, ident = line.split()
        out.append((int(serial), int(ident)))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path, default=Path('evility/results/evcap3-save.json'))
    ap.add_argument('--save', default='Save_001.sav')
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    ids = ordercheck._ids(database.load_database(DB).table('Skill.dat'))
    # today's table has 998 rows, so two new rows would still sit inside the bitmap.  Pad it to 1,000 and
    # add six ids above every existing one: the last two are the ones past the bitmap (positions 1,002/1,003)
    new_ids = [int(ids[-1]) + i for i in (1, 2, 3, 4, 5, 6)]
    table = list(ids) + new_ids                    # the table shape the plan will produce
    extensions = new_ids[-2:]
    man = learned.manifest(table)

    src = SAVES / args.save
    work = SCRATCH / args.save
    shutil.copy2(src, work)                        # a copy: the real save is never touched
    source_sha = hashlib.sha256(src.read_bytes()).hexdigest()
    before_bytes = work.read_bytes()
    save = savegame.Save(str(work))
    before = learned_sets(save, ids)

    binary = build_host(SCRATCH / 'evcap3_host')
    section = SCRATCH / 'section.bin'
    keys = SCRATCH / 'keys.bin'
    code, _labels = learned._assemble(learned.section_source(man),
                                      learned.code_base(PINNED.read_bytes(), learned.SECTION))
    section.write_bytes(code)
    keys.write_bytes(b''.join(struct.pack('<I', i) for i in table))
    savedir = SCRATCH / 'SaveData'
    savedir.mkdir(exist_ok=True)
    shutil.copy2(work, savedir / args.save)
    game_save = savedir / args.save
    sidecar = Path(str(game_save) + learned.SIDECAR_SUFFIX)

    checks = []

    def check(name, ok, detail=None):
        checks.append(dict(name=name, ok=bool(ok), detail=detail))

    units = len(before)
    native_total = sum(len(v['learned']) for v in before.values())
    serials = [v['serial'] for v in before.values() if v['serial']]
    check('save-parsed', units > 0, dict(units=units, army=save.army_count, reserve=save.reserve_count))
    check('native-learning-decoded', native_total > 0, dict(learned_total=native_total))
    check('store-ceiling-covers-the-plan', learned.STORE_MAX_USED >= 128 * 768,
          dict(capacity=learned.STORE_CAPACITY, max_used=learned.STORE_MAX_USED,
               pairs_planned=128 * 768))

    # ---- session A: learn past the bitmap, then the game saves ---------------------------------------
    a, b = serials[0], serials[1]
    plan = {a: [extensions[0]], b: [extensions[0], extensions[1]]}
    acts = [f'put={a}:{extensions[0]}', f'put={b}:{extensions[0]}', f'put={b}:{extensions[1]}',
            'saveslot=1']
    run(binary, section, keys, savedir, *acts)
    check('session-A-wrote-the-companion', sidecar.exists(), dict(path=str(sidecar)))
    doc = json.loads(sidecar.read_text()) if sidecar.exists() else {}
    ok, problems, quarantine = learned.sidecar_validate(doc, str(game_save), table) if doc else (False, ['none'], [])
    check('companion-validates-against-the-save', ok and not quarantine, dict(problems=problems))
    check('companion-carries-exactly-the-new-learning',
          {int(k, 16): v['learned'] for k, v in (doc.get('units') or {}).items()} == plan,
          dict(units=len(doc.get('units') or {})))
    check('companion-is-bound-to-the-save-bytes',
          doc.get('save', {}).get('sha256') == hashlib.sha256(game_save.read_bytes()).hexdigest())

    # ---- quit: a fresh process starts with an empty store --------------------------------------------
    fresh = pairs_from(run(binary, section, keys, savedir, 'dump').stdout)
    check('quit-empties-the-store', fresh == [], dict(pairs=len(fresh)))

    # ---- session B: load that slot -------------------------------------------------------------------
    loaded = pairs_from(run(binary, section, keys, savedir, 'load=1', 'dump').stdout)
    want = sorted((serial, ident) for serial, idents in plan.items() for ident in idents)
    check('load-restores-every-extension-evility', loaded == want, dict(got=loaded, want=want))
    check('load-did-not-touch-the-save-bytes', game_save.read_bytes() == before_bytes)
    after = learned_sets(savegame.Save(str(game_save)), ids)
    check('old-evilities-load-unchanged', after == before,
          dict(units=len(after), learned_total=sum(len(v['learned']) for v in after.values())))
    check('every-bitmap-byte-unchanged',
          all(before[s]['bitmap_sha256'] == after[s]['bitmap_sha256'] for s in before), dict(bitmaps=len(before)))

    # ---- a second save in the same session reproduces the same companion -----------------------------
    run(binary, section, keys, savedir, 'load=1', 'saveslot=1')
    doc2 = json.loads(sidecar.read_text())
    check('save-after-load-is-the-same-learning',
          {int(k, 16): v['learned'] for k, v in doc2['units'].items()} == plan,
          dict(units=len(doc2['units'])))

    # ---- session C: an old save with no companion loads native-only ----------------------------------
    old = savedir / 'Save_002.sav'
    shutil.copy2(work, old)
    r = run(binary, section, keys, savedir, 'load=2', 'dump')
    check('a-save-with-no-companion-loads-native-only', pairs_from(r.stdout) == [],
          dict(log=[l for l in r.stderr.splitlines() if 'companion' in l]))

    # ---- session D: a companion that does not match its save is refused, never paired ----------------
    bad = savedir / 'Save_003.sav'
    shutil.copy2(work, bad)
    shutil.copy2(sidecar, str(bad) + learned.SIDECAR_SUFFIX)
    tamper = savegame.Save(str(bad))            # a real, still-valid save with other bytes
    tamper.state[0x1000] ^= 0x01
    tamper.write()
    r = run(binary, section, keys, savedir, 'load=3', 'dump')
    rejected = Path(str(bad) + learned.SIDECAR_SUFFIX + learned.SIDECAR_REJECTED)
    check('a-mismatched-companion-is-refused-and-kept', pairs_from(r.stdout) == [] and rejected.exists(),
          dict(rejected=rejected.exists(),
               log=[l for l in r.stderr.splitlines() if 'does not match' in l]))
    tampered = learned_sets(savegame.Save(str(bad)), ids)
    check('a-refused-companion-changes-no-native-learning',
          all(tampered[s]['learned'] == before[s]['learned'] for s in before), dict(units=len(tampered)))

    # ---- the new save site only binds a file the game's own writer produced ---------------------------
    junk = savedir / 'Save_004.sav'
    junk.write_bytes(b'not a slot file at all' * 16)
    junk_side = Path(str(junk) + learned.SIDECAR_SUFFIX)
    r = run(binary, section, keys, savedir, f'put={a}:{extensions[1]}', 'saveslot=4')
    check('a-file-that-is-not-a-slot-file-gets-no-companion',
          not junk_side.exists() and 'not a slot file' in r.stderr,
          dict(log=[l for l in r.stderr.splitlines() if 'not a slot file' in l]))
    r = run(binary, section, keys, savedir, f'put={a}:{extensions[1]}', 'saveslot=5')
    check('a-slot-with-no-file-gets-no-companion',
          not Path(str(savedir / 'Save_005.sav') + learned.SIDECAR_SUFFIX).exists()
          and 'cannot read back' in r.stderr,
          dict(log=[l for l in r.stderr.splitlines() if 'cannot read back' in l]))

    # ---- an agent run ([debug] remote=1) writes nothing at all under the save folder ------------------
    before_list = sorted(p.name for p in savedir.iterdir())
    keep_sidecar_before = sidecar.read_text()
    r = run(binary, section, keys, savedir, 'remote=1', f'put={a}:{extensions[1]}', 'saveslot=1')
    check('an-agent-run-writes-nothing-under-the-save-folder',
          sorted(p.name for p in savedir.iterdir()) == before_list and sidecar.read_text() == keep_sidecar_before,
          dict(log=[l for l in r.stderr.splitlines() if 'remote=1' in l]))

    # ---- the autosave is a slot file too (slot 0 -> AutoSave.sav) ------------------------------------
    auto = savedir / 'AutoSave.sav'
    shutil.copy2(work, auto)
    run(binary, section, keys, savedir, f'put={a}:{extensions[0]}', 'saveslot=0')
    auto_side = Path(str(auto) + learned.SIDECAR_SUFFIX)
    auto_doc = json.loads(auto_side.read_text()) if auto_side.exists() else {}
    aok, aprob, _ = learned.sidecar_validate(auto_doc, str(auto), table) if auto_doc else (False, ['none'], [])
    check('an-autosave-gets-a-companion-bound-to-AutoSave.sav',
          aok and auto_doc.get('save', {}).get('name') == 'AutoSave.sav', dict(problems=aprob))

    # ---- the table moved: the companion must not be written at all ----------------------------------
    moved = SCRATCH / 'moved-keys.bin'
    moved.write_bytes(b''.join(struct.pack('<I', i) for i in [0] + table))
    keep = sidecar.read_text()
    r = run(binary, section, moved, savedir, f'put={a}:{extensions[1]}', 'saveslot=1')
    check('a-moved-table-writes-no-companion', 'NOT written' in r.stderr and sidecar.read_text() == keep,
          dict(log=[l for l in r.stderr.splitlines() if 'NOT written' in l]))

    # ---- the real save is untouched ------------------------------------------------------------------
    check('source-save-unchanged', hashlib.sha256(src.read_bytes()).hexdigest() == source_sha,
          dict(sha256=source_sha))

    report = dict(save=args.save, source=str(src), scratch=str(SCRATCH), table_rows=len(table),
                  extension_ids=extensions, generation=man['generation'],
                  capacity=learned.STORE_CAPACITY, max_used=learned.STORE_MAX_USED,
                  units=units, native_learned=native_total, plan=[list(x) for x in want],
                  checks=checks, passed=all(c['ok'] for c in checks),
                  limitations=[
                      'Offline: the runtime code is real (the same C the DLL builds) and the section is the '
                      'real assembled section, but the game itself does not run, so "the game saves" and '
                      '"the game loads" are the relays\' documented behaviour being driven directly.',
                      'The save is never written: it is read for its hash and parsed for its learning. A live '
                      'save/reload in game is still the acceptance step (EVCAP3-REPORT.md).',
                      'Save2 is known-bad and is not opened.'])
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=1) + '\n')
    for c in checks:
        print(('PASS ' if c['ok'] else 'FAIL ') + c['name'] + ('' if c['ok'] else f"  {c['detail']}"))
    print(f"{sum(c['ok'] for c in checks)}/{len(checks)} checks passed; {units} units, "
          f"{native_total} native learned evilities")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
