"""Developer tool: add hand-checked entries to a build's address map (d5lib/data/exe_map_<sha>.json "manual").
    python tools/exe_manual.py SHA12 OLD=NEW [OLD=NEW ...] [--note "why"]"""
import json
import os
import sys

KIT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
path = os.path.join(KIT, "d5lib", "data", f"exe_map_{sys.argv[1]}.json")
with open(path) as f:
    d = json.load(f)
man = d.setdefault("manual", {})
notes = d.setdefault("manual_notes", {})
note = sys.argv[sys.argv.index("--note") + 1] if "--note" in sys.argv else ""
args = sys.argv[2:sys.argv.index("--note")] if "--note" in sys.argv else sys.argv[2:]
for a in args:
    if "=" not in a:
        continue
    o, n = a.split("=")
    man[hex(int(o, 16))] = hex(int(n, 16))
    if note:
        notes[hex(int(o, 16))] = note
    if hex(int(o, 16)) in d.get("missing", []):
        d["missing"].remove(hex(int(o, 16)))
with open(path, "w") as f:
    json.dump(d, f, indent=0)
print(f"{len(man)} manual entries")
