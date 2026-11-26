"""Listening sheet: per pack, per role, the exact clip files Sean can spot-check."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from d5lib import sfx, sound  # noqa: E402

NEW = Path("/Volumes/Data/ai-tmp/voices2/out/mods")
ROLES = [("attack", [0]), ("skill shout A", [1, 2]), ("cast", [4]), ("skill shout B", [6]),
         ("cast release", [9]), ("lift", [10]), ("throw", [11]), ("move", [13])]
NAME = {}


def label(pack, voice_id):
    return f"{pack.name} (voice {voice_id})"


def main():
    out = {}
    for pack in sorted(p for p in NEW.iterdir() if p.is_dir()):
        vpath = pack / "patches/voices/voices.json"
        if not vpath.exists():
            continue
        data = json.loads(vpath.read_text())
        vid, v = next(iter(data["voices"].items()))
        per_role = defaultdict(lambda: defaultdict(set))
        for line in v["lines"]:
            for lang, f in (line.get("files") or {}).items():
                for role, cats in ROLES:
                    if set(cats) & set(line["cats"]):
                        per_role[role][lang].add(f)
        entry = {}
        for role, cats in ROLES:
            langs = per_role.get(role, {})
            entry[role] = {lang: sorted(files) for lang, files in langs.items()}
        out[pack.name] = dict(voice_id=int(vid), roles=entry,
                              lines=len(v["lines"]))
    Path("/Volumes/Data/ai-tmp/voices2/listening.json").write_text(json.dumps(out, indent=1))
    print("packs", len(out))
    total = sum(len(v["roles"][r][l]) for v in out.values() for r, _ in ROLES for l in ("EN", "JP"))
    print("role-clip entries", total)


if __name__ == "__main__":
    main()
