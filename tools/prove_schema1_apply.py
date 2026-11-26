"""SCHEMA1 proof (read-only): apply every held pack's char/Quest/item/JobRank db patch to the original tables and print
sha256 of each result to a JSON file; run once on the old tree and once on the new, then cmp the two files.
Usage: python tools/prove_schema1_apply.py OUT.json  (run from the worktree root)."""
import sys, json, hashlib
sys.dont_write_bytecode=True; sys.path.insert(0,'.')
from pathlib import Path
from d5lib import database, dbpatch, gamefs, modsys, importcore
G=Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")
inst=modsys.Installer(str(G),str(importcore.ROOT),log=lambda *a:None)
fs=gamefs.GameFS(str(G),backup_resolver=inst.backup_resolver)
raw={m:fs.read(importcore.DB_ARCHIVE+'/'+m) for m in ('char.dat','Quest.dat','item.dat','JobRank.dat')}
fs.reset()
out={}
H=Path("/Volumes/Data/Projects/D5/Local/mods-holding/20261108-PLAYTEST-RESET/mods")
for mod in sorted(H.iterdir()):
    for m in raw:
        f=mod/'patches/db'/(m+'.json')
        if f.is_file():
            t=database.load_table(m,raw[m]); dbpatch.apply_patch(t,json.loads(f.read_text()),strict=True)
            out[mod.name+'/'+m]=hashlib.sha256(t.to_bytes()).hexdigest()
for m in raw:  # vanilla round trip
    out['vanilla/'+m]=hashlib.sha256(database.load_table(m,raw[m]).to_bytes()).hexdigest()+(' =raw' if database.load_table(m,raw[m]).to_bytes()==raw[m] else ' !=raw')
json.dump(out,open(sys.argv[1],'w'),indent=0,sort_keys=True); print(len(out))
