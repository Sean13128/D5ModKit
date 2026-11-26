#!/bin/bash
# PALFIX2 sandbox install of PALMERGE2. Refuses unless game_dir is the sandbox.
set -eu
ROOT=/Volumes/Data/Projects/D5
TASK=/Volumes/Data/ai-tmp/codex/hurtslot1/gates
SAND="$TASK/sandbox"
KIT="$SAND/game/D5ModKit"
B="$ROOT/Builds/HURTSLOT1-20261102"
PY=/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python
WT="$ROOT/Local/Worktrees/hurtslot1"
PROF="${HURTSLOT_PROFILE:-LIVE5_HURTSLOT1}"
VARIANT="${HURTSLOT_VARIANT:-hurtslot}"
case "$VARIANT:$PROF" in hurtslot:LIVE5_HURTSLOT1|hurtslot_keepcarry:LIVE5_HURTSLOT1_KEEPCARRY) ;; *) exit 1;; esac
MODS="$B/$VARIANT/mods"
OUT="$TASK/proof/$VARIANT"
mkdir -p "$OUT"
"$PY" - "$SAND" <<'PYGUARD'
import os,sys
from pathlib import Path
sand=Path(sys.argv[1]).resolve()
for rel in ('game/D5ModKit/mods','game/D5ModKit/profiles','game/D5ModKit/state','game/D5ModKit/settings.json','game/Data'):
 root=sand/rel
 assert root.exists(), root
 assert root.resolve(strict=True).is_relative_to(sand), root
 for directory, dirs, files in os.walk(root, followlinks=False) if root.is_dir() else [(str(root.parent),[],[root.name])]:
  for name in dirs+files:
   p=Path(directory)/name
   if p.is_symlink():
    target=p.resolve(strict=True)
    assert target.is_relative_to(sand), f'unsafe symlink {p} -> {target}'
print('sandbox link guard passed',flush=True)
PYGUARD
"$PY" - "$KIT" "$SAND/game" "$MODS" "$PROF" "$OUT" "$WT" <<'PY'
import json, shutil, subprocess, sys
from pathlib import Path
kit, game, mods, prof, out, wt = sys.argv[1:7]
kit, game, mods, out, wt = map(Path, (kit, game, mods, out, wt))
assert game.resolve() == Path('/Volumes/Data/ai-tmp/codex/hurtslot1/gates/sandbox/game').resolve()
sys.path.insert(0, str(wt)); sys.path.insert(0, str(wt / 'tools'))
import d1cmotion2_base as base
d = json.loads((kit / 'settings.json').read_text())
assert d['game_dir'] == str(game), d
assert base.require_base_set() == 38
for mod in base.manifest()['banks']:
    target = kit / 'mods' / mod
    shutil.rmtree(target)
    shutil.copytree(base.base_dir(mod) / mod, target)
print('sandbox restored to the pinned TEST28 base for the 19 folders', flush=True)
changes, diffs = [], []
for folder in sorted(mods.iterdir()):
    target = kit / 'mods' / folder.name
    assert target.is_dir(), folder.name
    result = subprocess.run(['diff', '-rq', str(target), str(folder)], capture_output=True, text=True)
    assert result.returncode in (0, 1), result.stderr
    diffs.append(result.stdout)
    for p in sorted(folder.rglob('*')):
        if not p.is_file():
            continue
        assert not p.is_symlink()
        rel = p.relative_to(folder)
        tf = target / rel
        assert tf.is_file(), rel
        if p.read_bytes() != tf.read_bytes():
            assert p.suffix == '.lzs', rel
            changes.append(f'{folder.name}/{rel.relative_to("files/Anime/ANM_HI_JP.dat")}')
(out / 'diff-rq-vs-test28.txt').write_text(''.join(diffs))
print(f'{len(changes)} animation-only bank delta vs TEST28, 19 folders only: {sorted(changes)}',
      flush=True)
assert changes, 'no changed animation banks'
(out / 'diff-vs-test28.txt').write_text('\n'.join(sorted(changes)) + '\n')
for folder in sorted(mods.iterdir()):
    target = kit / 'mods' / folder.name
    shutil.rmtree(target); shutil.copytree(folder, target)
src_prof = mods.parent / 'profile' / prof
shutil.rmtree(kit / 'profiles' / prof, ignore_errors=True)
shutil.copytree(src_prof, kit / 'profiles' / prof)
old = json.loads((kit / 'profiles/LIVE5_TEST28/load_order.json').read_text())
new = json.loads((kit / 'profiles' / prof / 'load_order.json').read_text())
assert old == new and len(new) == 188, (len(new), old == new)
d['profile'] = prof
(kit / 'settings.json').write_text(json.dumps(d, indent=2))
assert json.loads((kit / 'settings.json').read_text())['profile'] == prof
print('staged', prof, '188-entry order identical to TEST28', flush=True)
PY
cd "$KIT"
export PYTHONPATH="$TASK/pydeps${PYTHONPATH:+:$PYTHONPATH}"
export ZIG_GLOBAL_CACHE_DIR="$TASK/zig-cache"
mkdir -p "$TASK/pydeps"
ln -sfn "$ROOT/Local/python-macos/lib/python3.12/site-packages/ziglang" "$TASK/pydeps/ziglang"
"$PY" - "$KIT/settings.json" "$SAND/game" "$PROF" <<'PY'
import json, sys
from pathlib import Path
d = json.loads(Path(sys.argv[1]).read_text())
assert d['game_dir'] == sys.argv[2]
assert Path(sys.argv[2]).resolve() == Path('/Volumes/Data/ai-tmp/codex/hurtslot1/gates/sandbox/game').resolve()
assert d['profile'] == sys.argv[3]
print('Final sandbox install guard passed', d['game_dir'], d['profile'])
PY
# The cloned kit's state files name the LIVE game and its exe is already patched: point every state
# file at the sandbox and start from the vanilla exe backup (pinned sha 49a7530b...).
"$PY" - "$KIT" "$SAND/game" <<'PYQ'
import hashlib, json, shutil, sys
from pathlib import Path
kit, game = map(Path, sys.argv[1:3])
live = '/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete'
hits = [p for p in (kit / 'state').rglob('*.json') if live in p.read_text(errors='ignore')]
for p in hits:
    d = json.loads(p.read_text())
    if d.get('game_dir') == live:
        d['game_dir'] = str(game)
        p.write_text(json.dumps(d, indent=2))
        print('state repointed:', p.relative_to(kit), '->', d['game_dir'], flush=True)
still = [p for p in (kit / 'state').rglob('*.json') if live in p.read_text(errors='ignore')]
assert not still, ('state still names the live game', still)
vanilla = next((kit / 'state/games').glob('*/backups/EXE__disgaea5.exe.full'), None)
assert vanilla and vanilla.is_file(), 'no vanilla exe backup in the cloned kit'
h = hashlib.sha256(vanilla.read_bytes()).hexdigest()
assert h.startswith('49a7530b'), h
shutil.copyfile(vanilla, game / 'disgaea5.exe')
print('sandbox exe restored from the vanilla backup', h[:16], flush=True)
PYQ
shasum -a 256 "$SAND/game/disgaea5.exe" > "$OUT/exe-before.txt"
set +e
"$PY" tools/install_mods.py > "$OUT/install.log" 2>&1
rc=$?
set -e
tail -8 "$OUT/install.log"
shasum -a 256 "$SAND/game/disgaea5.exe" > "$OUT/exe-after.txt"
"$PY" - "$SAND/game/disgaea5.exe" <<'PY' | tee "$OUT/sections.txt"
import pefile, sys
names = [s.Name.rstrip(b'\0').decode('ascii') for s in pefile.PE(sys.argv[1]).sections]
print(names); assert '.d5tw' not in names
PY
[ "$rc" -eq 0 ]
grep -q '^Install complete' "$OUT/install.log"
[ "$(grep -c '^Building mod:' "$OUT/install.log")" -eq 188 ]
[ "$(shasum -a 256 "$SAND/game/disgaea5.exe" | cut -d' ' -f1)" = \
  '95d03f92632f97eac82b02ac1796f4e3e7d90afcfb5eda934dc0b8a56a3041a7' ]
echo "Install complete; 188 mods; expected executable hash; no .d5tw: PASS ($PROF)"
