#!/usr/bin/env python3
"""Assemble the REGEN bundle: LIVE5_TEST3's mod list with the rebuilt D4 packs.

    python tools/build_regen_bundle.py --rebuilt <dir>/mods --out Builds/LIVE5_TEST4-YYYYMMDD \
        [--base Builds/LIVE5_TEST3-20261028] [--label REASON]

What it does (nothing is installed, no profile is written, no game or kit path is touched):

  * copies every folder of the base bundle; the 45 D4 class folders come from --rebuilt instead
  * writes INVENTORY.txt / INVENTORY.json with a per-mod tree_sha256 and where the folder came from
  * writes LEASES.json (base leases, plus the note that this bundle adds no id)
  * writes CHANGES.json (what differs from the base, per mod: which art files changed)
  * writes INSTALL.md: the LIVE5_TEST2/LIVE5_TEST3 safety rules, the game-silent rule from LANE-RULES Sound
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

BASE = Path('/Volumes/Data/Projects/D5')
DEFAULT_BASE = BASE / 'Builds/LIVE5_TEST3-20261028'


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def tree_rows(root: Path):
    rows, total = [], 0
    hasher = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest = sha(path)
        size = path.stat().st_size
        total += size
        rows.append((rel, digest, size))
        hasher.update(rel.encode() + b'\0' + digest.encode() + b'\n')
    return rows, hasher.hexdigest(), total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--rebuilt', required=True, help='mods dir of the regenerated packs')
    ap.add_argument('--base', default=str(DEFAULT_BASE))
    ap.add_argument('--label', default='REGEN (PTSPRITE S1/S2/S3 art)')
    ap.add_argument('--summary', default='REGEN-SUMMARY.json')
    args = ap.parse_args()

    base, out, rebuilt = Path(args.base), Path(args.out), Path(args.rebuilt)
    out_mods = out / 'mods'
    out_mods.mkdir(parents=True, exist_ok=True)
    summary = {}
    sp = rebuilt.parent / args.summary
    if sp.exists():
        for entry in json.loads(sp.read_text()).get('results', []):
            summary[entry['mod']] = entry

    inventory, changes = [], []
    for src_mod in sorted(p for p in (base / 'mods').iterdir() if p.is_dir()):
        name = src_mod.name
        new_src = rebuilt / name if (rebuilt / name).is_dir() else src_mod
        dst = out_mods / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(new_src, dst)
        rows, tree_sha, nbytes = tree_rows(dst)
        origin = args.label if new_src != src_mod else 'LIVE5_TEST3 (unchanged)'
        inventory.append((name, len(rows), nbytes, tree_sha, origin))
        if new_src != src_mod:
            info = summary.get(name, {})
            changes.append(dict(mod=name, changed_art=info.get('changed', []),
                                art_files=info.get('art_files'),
                                unchanged_art=len(info.get('unchanged', [])),
                                table_files=info.get('table_files')))

    (out / 'INVENTORY.txt').write_text(
        '# REGEN bundle — mod inventory\n'
        "# tree_sha256 = sha256 over 'relpath\\0sha256(file)' for every file, in sorted path order\n"
        '# mod\tfiles\tbytes\ttree_sha256\torigin\n'
        + ''.join(f'{n}\t{c}\t{b}\t{s}\t{o}\n' for n, c, b, s, o in inventory))
    (out / 'INVENTORY.json').write_text(json.dumps(
        [dict(mod=n, files=c, bytes=b, tree_sha256=s, origin=o) for n, c, b, s, o in inventory], indent=1))

    base_leases = json.loads((base / 'LEASES.json').read_text())
    leases = dict(base_leases)
    leases['regen_note'] = ('no id is leased, moved or added by this bundle: the rebuild replaces sprite and '
                            'image files only (see playtest/REGEN-REPORT.md)')
    leases['c4_pending'] = base_leases.get('c4_pending', [])
    (out / 'LEASES.json').write_text(json.dumps(leases, indent=1))
    (out / 'CHANGES.json').write_text(json.dumps(dict(
        base=str(base), label=args.label, rebuilt_mods=changes,
        counts=dict(mods=len(inventory), rebuilt=len(changes),
                    art_files_changed=sum(len(c['changed_art']) for c in changes))), indent=1))

    (out / 'INSTALL.md').write_text(INSTALL_MD.format(
        date=out.name.split('-')[-1], n=len(inventory), rebuilt=len(changes),
        art=sum(len(c['changed_art']) for c in changes)))
    print(f'{len(inventory)} folders, {len(changes)} rebuilt ({sum(len(c["changed_art"]) for c in changes)} art '
          f'files) -> {out}')
    return 0


INSTALL_MD = """# LIVE5_TEST4 — install note ({date}, REGEN)

What this is: **the same {n} mod folders the profile `LIVE5_TEST2` enables**, with **{rebuilt} of our D4 class
packs replaced** by versions whose sprite/animation banks and faces/cut-ins were rebuilt with the fixed
converter (PTSPRITE S1 one body per stand pose, S2 stand ground line, S3 no automatic matte). Every table file
(evilities, skills, char rows, voices, mastery, help) is **byte-identical** to LIVE5_TEST3 — {art} art files
changed, nothing else. Sean's own folders are byte-identical copies; nothing of his is edited. The exe is
unchanged (a mod-only install; no new hook, no exe rewrite).

Evidence classes (`Subprojects/Engine-Extensions/playtest/REGEN-REPORT.md`):
* **offline-proven** — every rebuilt folder's non-art files hash-identical to LIVE5_TEST3 (the pipeline
  refuses a non-art difference); `check_ownership` 0 on the enabled set; kit suite = the known env failures;
  `sprite_audit` reports 0 packs with `stand_items=2` (it reported 19 in LIVE5_TEST3);
* **unverified in game** — every visual until Sean's next playtest; the idle-loop ground swing is diagnosed but
  not fixed (PTSPRITE open work 1), so a few idles may still bob.

## Install (same safety rules as LIVE5_TEST2 / LIVE5_TEST3)

1. Game **closed**, `live-harness/PLAY` **absent**, one editor at a time.
2. Back up the **resolved** kit path (`Local/Installed D5ModKit` is a symlink: `rsync -a "<resolved>/" <backup>/`,
   never `cp -a` on the link). The live AutoSave `6cd44ae2…` must stay untouched.
3. Copy the **{rebuilt} changed folders** with whole-folder `cp -R` (`rm -rf` that folder first). **Never
   `rsync --delete`** into `mods/` — LIVE3 wiped 101 folders that way. `INVENTORY.txt` lists every folder with
   its `tree_sha256` and whether this bundle changed it.
4. Keep the existing profile `LIVE5_TEST2` (same mod list, same order); press **Install**. A mod-only install
   does not rebuild the exe.
5. **Fully restart the game** before checking any menu (LANE-RULES).

## Game silent per LANE-RULES Sound

Do not launch the game through Steam directly for a check. **Never mute the Mac.** Do not use the in-game
Options sliders (they try to write SystemSave).

*Note for the live lane that installs this bundle:* LIVE6 (2026-10-27, `live-verify/LIVE6-REPORT.md`) measured
that the QUIET **0-audio-device gate does not boot this game on this Wine build** — no waveOut/WASAPI device
makes `xaudio2_9.dll` page-fault at `+0xC88E` (and `xaudio2_8` at the same offset when 9 is disabled), so the
primary rule in LANE-RULES Sound is not usable as written yet. Until the SILENT runtime (`[audio] silent=auto`)
is installed, quiet the game with `live-harness/game_mute_watch.py` **after** the harness pipe is up (LIVE6 also
found it calls `audio_restore()` and deletes the gate's override when the game is down), and start
`hide_game.sh` so the window stays out of Sean's workspace.

## Verify in game (short list)

1. **Create Character / class change wheel**: Kunoichi (`D4_Class_1230`) and one monster — the stand picture is
   **one** character, not two or three copies offset from each other; the feet sit on the tile.
2. **Ground line**: Orc (`2020`), Mystic Beast (`2130`), Winged Warrior (`2030`), Death (`2120`), Roc (`2110`):
   no float above the tile and no sink into it. Ignore the idle bob if it still swings (known, open).
3. **Faces**: open the character's face/portrait — the D4 face keeps its **white background** (S3), it is no
   longer cut out with transparent corners.
4. **Tables unchanged**: the Evilities tab and the Skill list look exactly as in LIVE5_TEST3 (this bundle changes
   art only). Cu Sith still has **no** UNIQUE evility — expected, see REGEN-REPORT §4.
5. The AutoSave loads and the roster is intact.

## Rollback

Reinstall profile `LIVE5_TEST2` from the kit backup taken in step 2 and verify the exe sha256 is `352df4a5…`.
"""


if __name__ == '__main__':
    raise SystemExit(main())
