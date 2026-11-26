#!/bin/bash
# PALFIX2 sandbox: APFS clone of a *pre-install* game data tree + a clone of the installed kit.
# Nothing is written back to Local/Installed D5ModKit, the Steam game folder, saves or Steam.
# game_dir is pinned to the sandbox before anything is staged.
set -eu
ROOT=/Volumes/Data/Projects/D5
TASK=/Volumes/Data/ai-tmp/codex/hurtslot1/gates
SAND="$TASK/sandbox"
# a pristine pre-mod copy of the same install (read-only source), so the installer starts from a
# vanilla Skill table instead of the already-edited one that blocked EDFBISECT2's sandbox
GAME='/Volumes/Data/CharForge-Backup/2026-10-16-211736/Game before D5ModKit'
KIT="$SAND/game/D5ModKit"
LIVEKIT="$ROOT/Local/Installed D5ModKit"
PY=/Volumes/Data/ai-tmp/hermes/engine-ext-evility/.venv/bin/python
OUT="$TASK/proof"
WT="$ROOT/Local/Worktrees/hurtslot1"
[ ! -e "$SAND" ] || { echo 'Sandbox already exists' >&2; exit 1; }
mkdir -p "$SAND/game" "$OUT"
for f in Data disgaea5.exe d3dcompiler_47.dll d5core.dll d5core_live0.dll d5auto.dll d5auto.ini \
         d5fx.dat d5looks.bin; do
  [ ! -e "$GAME/$f" ] || cp -Rc "$GAME/$f" "$SAND/game/$f"
done
LIVE_RESOLVED="$(cd "$LIVEKIT" && pwd -P)"
[ -d "$LIVE_RESOLVED" ] || { echo 'installed kit not found' >&2; exit 1; }
cp -Rc "$LIVE_RESOLVED" "$KIT"
# Fail closed before modifying anything if a copied link could escape this sandbox.
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
"$PY" - "$KIT" "$SAND/game" "$WT" "$OUT" <<'PY'
import hashlib, json, shutil, sys
from pathlib import Path
kit, game, wt, out = map(Path, sys.argv[1:])
assert game.resolve() == Path('/Volumes/Data/ai-tmp/codex/hurtslot1/gates/sandbox/game').resolve()
p = kit / 'settings.json'
d = json.loads(p.read_text())
d['game_dir'] = str(game)
d['profile'] = 'LIVE5_TEST28'
p.write_text(json.dumps(d, indent=2))
assert json.loads(p.read_text())['game_dir'] == str(game)
print('game_dir pinned to the sandbox:', json.loads(p.read_text())['game_dir'], flush=True)
sys.path.insert(0, str(wt)); sys.path.insert(0, str(wt / 'tools'))
import d1cmotion2_base as base
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
for mod in base.manifest()['banks']:
    target = kit / 'mods' / mod
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(base.base_dir(mod) / mod, target)
n = 0
for mod, banks in base.manifest()['banks'].items():
    for bank, want in banks.items():
        assert sha(kit / 'mods' / mod / base.REL / bank) == want, f'sandbox {mod}/{bank} is not TEST28'
        n += 1
print(f'sandbox base is TEST28: {n} pinned banks', flush=True)
PY
echo "prepare: PASS"
