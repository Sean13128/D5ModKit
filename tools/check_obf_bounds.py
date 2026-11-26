"""Native-header bounds gate (DD2SPEC3): every effect model a stage's packs carry, read as D5's loader reads it.

    python tools/check_obf_bounds.py <mods dir> [<mods dir> ...]
Exit 1 when any model has a read or copy outside its own bytes (d5lib.obfbounds)."""
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import obfbounds, ykcmp  # noqa: E402

failed, n = {}, 0
for root in sys.argv[1:]:
    for f in sorted(glob.glob(f"{root}/*/patches/skills/*.obf")):
        data = Path(f).read_bytes()
        data = ykcmp.decompress(data) if ykcmp.is_ykcmp(data) else data
        n += 1
        problems = obfbounds.check(data)
        if problems:
            failed[f] = problems
print(json.dumps(dict(models=n, failing=len(failed), problems=failed), indent=1))
sys.exit(1 if failed else 0)
