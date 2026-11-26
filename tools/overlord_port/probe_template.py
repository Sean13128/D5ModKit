import sys
sys.path.insert(0, '.')
from pathlib import Path
from d5lib import anm, gamefs, d4unique

GAME = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete')
STATE = Path('/Volumes/Data/Projects/D5/D5Modkit/state/games/Disgaea_5_Complete-d8040a88')
fs = gamefs.GameFS(str(GAME), backup_resolver=d4unique.Originals(STATE))
ms = fs.list_members("Anime/ANM_HI_JP.dat")
want = ["anm01460.lzs", "anm01461.lzs", "anm01462.lzs"]
print([w for w in want if w in ms])
for mid in want:
    if mid not in ms:
        continue
    a = anm.parse(fs.read("Anime/ANM_HI_JP.dat/" + mid))
    ids = {x.id for x in a.blocks[0].animations}
    im = anm.render_frame(a, ("id", 1), 0, 0)
    print(mid, "anims", len(ids), "has1", 1 in ids, "bbox", im.getchannel("A").getbbox())
fs.reset()
