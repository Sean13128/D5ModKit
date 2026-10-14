#!/bin/zsh
set -eu
kit_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
cd -- "$kit_dir"
if [[ ! -x "$kit_dir/.venv-macos/bin/python" ]]; then
  print "Set up the Mac environment first; see docs/MACOS.md."
  exit 1
fi
exec "$kit_dir/.venv-macos/bin/python" "$kit_dir/D5ModKit.pyw" >> "$kit_dir/macos-launch.log" 2>&1
