"""D1CLIST3 part 2: voice commands in the vanilla D5 choreographies of the twins of D1 skills 801-805, 811-814
(read-only, clean copy under Disgaea Source). operand/10000 = category, %10000 = actor (0 = caster): decomp 14018c650.
Run: D5Modkit/.venv-macos/bin/python -I tools/d1clist3_d5_heal_voice.py"""
import sys,re,json
sys.dont_write_bytecode=True
sys.path.insert(0,__import__('os').path.join(__import__('os').path.dirname(__file__),'..'))
from d5lib import skills, database
from d5lib.gamefs import GameFS
fs=GameFS('/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)')
t=database.load_table('magic.dat',fs.read('Database/Database_0.dat/magic.dat'))
print(t.rows[0].keys() if hasattr(t.rows[0],'keys') else t.rows[0])
sc=skills.vanilla_scripts(fs)
want=['Heal','Mega Heal','Giga Heal','Omega Heal','Espoir','Braveheart','Shield','Magic Boost','Magic Wall']
nm=lambda r: r['name_EN']
rows=[r for r in t.rows if nm(r) in want]
print([(r['id'],nm(r)) for r in rows])
res={}
for r in rows:
    sid=int(r['id']); root=sc.root_of(sid)
    tree=sc.tree(root) if root else []
    v=[]
    for e in tree:
        for l in (sc.text(e) or '').splitlines():
            if 'voice' in l: v.append((e,l.strip()))
    res[sid]=(nm(r),root,tree,v)
    print(sid,nm(r),root,len(tree)); [print('   ',x) for x in v]
print('--- Omega')
for e in res[1404][2]:
    print(e, [l.strip() for l in (sc.text(e) or '').splitlines() if 'call_event' in l or 'voice' in l or 'sound' in l][:12])
