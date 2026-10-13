"""move the map cursor to a panel: python tools/cur.py X Z  (learns the key directions on the way)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from d5ctl import Ctl
c = Ctl()
tx, tz = int(sys.argv[1]), int(sys.argv[2])
dirs = {}
for _ in range(40):
    x, z = c.state()['cpanel']
    if (x, z) == (tx, tz):
        break
    best = None
    for k, (dx, dz) in dirs.items():
        d = abs(x + dx - tx) + abs(z + dz - tz)
        if d < abs(x - tx) + abs(z - tz) and (best is None or d < best[0]):
            best = (d, k)
    k = best[1] if best else [k for k in 'DSAW' if k not in dirs][0]
    c.keys(f'{k}:3:10')
    nx, nz = c.state()['cpanel']
    if (nx, nz) != (x, z) and abs(nx - x) + abs(nz - z) == 1:
        dirs[k] = (nx - x, nz - z)
        opp = {'D': 'A', 'A': 'D', 'S': 'W', 'W': 'S'}[k]
        dirs[opp] = (x - nx, z - nz)
print('cursor', c.state()['cpanel'], dirs)
