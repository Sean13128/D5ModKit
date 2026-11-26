# usage: tabledump.py KITROOT OUT  -- encode the merged table of every installed mod; write the data-section text
import sys, os, json, glob, hashlib
kit, out = sys.argv[1:3]
sys.dont_write_bytecode = True
sys.path.insert(0, kit)
from d5lib import evility as ev
mods = "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods"
acc, rules = {}, {}
n = 0
for d in sorted(glob.glob(mods + "/*")):
    p = d + f"/patches/{ev.FOLDER}/{ev.DATA_FILE}"
    if os.path.exists(p):
        n += 1
        for k, e in (json.load(open(p)).get("evilities") or {}).items():
            ev._merge(acc, k, e)
    p = d + f"/patches/{ev.SKILL_FOLDER}/{ev.SKILL_DATA_FILE}"
    if os.path.exists(p):
        for k, e in (json.load(open(p)).get("rules") or {}).items():
            rules.setdefault(int(k), {}).update(e)
rows, conds, fx = ev.table(acc, rules)
src = ev._asm_source(rows, conds, fx, ())
i = src.index("    .align 16\nevil_tbl:")
data = src[i:]
open(out, "w").write(data)
print(n, "mods with evilities;", len(acc), "ids,", len(rules), "skill rules;", len(rows), "rows", len(conds), "conds", len(fx), "fx;", hashlib.sha256(data.encode()).hexdigest()[:16])
