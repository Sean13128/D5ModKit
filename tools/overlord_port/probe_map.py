import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'tools')
from d5lib import anm, hybridanim
from tools.overlord_port import anm_foreign

TPL = "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods/D4_Class_1190/files/Anime/ANM_HI_JP.dat/anm01460.lzs"
SRC = "/Volumes/Data/ai-tmp/claude/overlord-v3/mods/Overlord Visual/Anime/ANM_HI_EN/anm20300.dat"
tpl = anm.load(TPL)
src = anm_foreign.parse_foreign(open(SRC, "rb").read())
have = {a.id for a in src.blocks[0].animations}
ATTACK = {11: 7011, 17: 7021, 21: 7021, 27: 7031, 31: 7031, 37: 7041, 41: 7041, 47: 7041}


def pick(aid):
    d = aid % 100
    if 1000 <= aid < 1500:
        return 6001
    if aid >= 1500:
        return 7041
    return ATTACK.get(d, 0)


sources = {a.id: pick(a.id) for a in tpl.blocks[0].animations}
bad = {k: v for k, v in sources.items() if v not in have}
print("bad mappings", bad)
print("sample", list(sources.items())[:10])
for aid in [a.id for a in tpl.blocks[0].animations][:20]:
    print(aid, "->", hybridanim.source_for(aid, sources, have))
