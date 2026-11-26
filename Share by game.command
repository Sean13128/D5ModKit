#!/bin/zsh
# Double-click: export your mods into one folder per game (D1C, D4, DD2 ...), one zip per mod, ready for another
# D5 Mod Kit's "Import folder...".  Never changes your mods.  See docs/SHARING.md.
set -eu
kit_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd -- "$kit_dir"
py="$kit_dir/.venv-macos/bin/python"
if [[ ! -x "$py" ]]; then
  print "Set up the Mac environment first; see docs/MACOS.md."
  read -k1 "?Press any key to close."
  exit 1
fi

print "Share mods by game"
print "Games: D1C, D4, DD2, DRPG (large, about 0.5 GB), Overlord, Other"
read "games?Which games? [D1C,D4,DD2]: "
games="${games:-D1C,D4,DD2}"
out="$HOME/Desktop/D5-share-$(date +%Y%m%d-%H%M)"
read "dest?Save to? [$out]: "
out="${dest:-$out}"

print
"$py" tools/share_bulk.py export "$out" --games "$games" || {
  print "\nExport failed (see above)."
  read -k1 "?Press any key to close."
  exit 1
}
print "\nDone. Send the whole folder privately: the zips hold art from the original games, never publish them."
open "$out"
read -k1 "?Press any key to close."
