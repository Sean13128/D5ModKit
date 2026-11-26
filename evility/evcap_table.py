"""Print the installed Skill.dat manifest (read-only; the game folder is only opened for reading)."""
import json
import os
import sys

sys.path.insert(0, os.environ.get('D5_KIT', '.'))
from d5lib import database, learned, ordercheck

DB = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/Data/Database/Database_0.dat"
OUT = "/Volumes/Data/ai-tmp/evcap2/skill-table.json"

db = database.load_database(DB)
ids = ordercheck._ids(db.table('Skill.dat'))
print('rows', len(ids), 'sorted', ids == sorted(ids), 'min', ids[0], 'max', ids[-1])
print('positions of ids >= 20000:', [i for i, x in enumerate(ids) if x >= 20000][:8])
man = learned.manifest(ids)
print('base_count', man['base_count'], 'ext_ids', man['ext_ids'], 'generation', hex(man['generation']))
json.dump({'ids': ids,
           'manifest': {k: (len(v) if k == 'base_ids' else v) for k, v in man.items()}},
          open(OUT, 'w'))
print('wrote', OUT)
