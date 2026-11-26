import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'tools')
from d5lib import anm, hybridanim
from tools.overlord_port import anm_foreign

TPL = "/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods/D4_Class_1190/files/Anime/ANM_HI_JP.dat/anm01460.lzs"
SRC = "/Volumes/Data/ai-tmp/claude/overlord-v3/mods/Overlord Visual/Anime/ANM_HI_EN/anm20300.dat"
tpl = anm.load(TPL)
src = anm_foreign.parse_foreign(open(SRC, "rb").read())
b = src.blocks[0]
draw = {}
for an in b.animations:
    cells = [k.cell for ni, d, p in b.walk(an.root) for k in b.node_keys(b.nodes[ni]) if k.cell]
    draw[an.id] = len(cells)
print("per-animation drawing keys:", draw)
have = {k for k, v in draw.items() if v}
print("have drawings:", sorted(have))

ATTACK = {11: 7011, 17: 7021, 21: 7021, 27: 7031, 31: 7031, 37: 7041, 41: 7041, 47: 7041}


def pick(aid):
    d = aid % 100
    if 1000 <= aid < 1500:
        want = 6001
    elif aid >= 1500:
        want = 7041
    else:
        want = ATTACK.get(d, 0)
    if want in have:
        return want
    for alt in (0, 7001, 6001, 7011, 7041):
        if alt in have:
            return alt
    raise SystemExit("no drawing animation in the source")


sources = {a.id: pick(a.id) for a in tpl.blocks[0].animations}
out = hybridanim.compose(tpl, src, 224, sources, (), print)
print("compose ok | anims", len(out.blocks[0].animations), "| cells", len(out.blocks[0].cells),
      "| tex", len(out.textures), "| pal", len(out.palettes))
raw = out.to_bytes()
back = anm.parse(raw)
ids = {a.id for a in back.blocks[0].animations}
print("strict parse ok", len(raw), "| has id 1:", 1 in ids, "| ids", len(ids))
for aid in (1, 7, 1001, 2001, 3001):
    if aid not in ids:
        print("anim", aid, "absent")
        continue
    im = anm.render_frame(back, ("id", aid), 0, 0)
    print("anim", aid, "render", im.size, "alpha bbox", im.getchannel("A").getbbox())
open("/Volumes/Data/ai-tmp/hermes/p4-overlord-20261027/hybrid_anm00224.raw", "wb").write(raw)
print("wrote probe bytes")
