"""run auto until the start of player turn N (default 2) of a floor, then switch auto off"""
import sys, os, time, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from d5ctl import Ctl
n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
c = Ctl()
c.cmd('auto on')
log = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'd5auto.log')
start = os.path.getsize(log)
t0 = time.time()
while time.time() - t0 < 600:
    with open(log, 'rb') as f:
        f.seek(start)
        new = f.read().decode('utf-8', 'replace')
    if f'di: player turn {n}' in new:
        c.cmd('auto off')
        break
    c.wait(10)
print('paused' if time.time() - t0 < 600 else 'timeout', c.state()['mode'])
