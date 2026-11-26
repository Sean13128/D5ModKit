"""Compare a merged humanoid experiment with the source in the kit evaluator.

This models the initial disabled bindings 21 and 31 only; it is not a native
binding, weapon, attachment, event, or release-safety proof.
"""
import copy
import json
from pathlib import Path

import numpy as np
from d5lib import anm, d4source
from shared_tracks import build

OUT = Path('/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/playtest/anim-renders/prototype')


def disabled_view(a):
    a = copy.deepcopy(a)
    for b in a.blocks:
        for node in b.nodes:
            if node.id in (21, 31):
                for key in b.node_keys(node):
                    key.cell = 0
    return a


def main():
    d = d4source.D4Data('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 4 Complete+')
    body, shared = d.anm(1230), d.anm(1)
    result = build(body, shared, bank_id=1500)
    source = anm.bind_motion_set(shared, 0, body)
    source.blocks = body.blocks + source.blocks
    s, o = disabled_view(source), disabled_view(result)
    checks = []
    for aid in (1, 21, 1001, 1021, 2001, 2011, 4001, 6001, 6007):
        si = next(x for x in anm.list_animations(s) if x['id'] == aid)
        oi = next(x for x in anm.list_animations(o) if x['id'] == aid)
        if (si['length'], si['loop']) != (oi['length'], oi['loop']):
            raise AssertionError((aid, si, oi))
        end = max(anm.frame_times(s, ('id', aid)) + [si['length'] or 0])
        for tick in range(end + 1):
            images = []
            for a in (s, o):
                items = anm.evaluate(a, ('id', aid), tick, nested=True)
                images.append(np.asarray(anm.render_items(a, items, 0, bounds=(-256, -256, 256, 256))[0]))
            if not np.array_equal(*images):
                raise AssertionError((aid, tick))
        checks.append({'motion': aid, 'ticks': end + 1, 'loop': si['loop']})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'kunoichi-shared-experiment.anm').write_bytes(result.to_bytes())
    (OUT / 'kunoichi-shared-proof.json').write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks, indent=2))


if __name__ == '__main__':
    main()
