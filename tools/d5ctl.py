"""d5ctl -- drive a running Disgaea 5 through d5auto.dll's test harness (needs [debug] remote=1 in d5auto.ini).

Library:
    from tools.d5ctl import Ctl
    c = Ctl(); c.state(); c.keys("K S:3:8 K"); c.shot("screen.png")

Command line (prints the answer):
    python tools/d5ctl.py state            summary of the game state
    python tools/d5ctl.py json state       raw JSON answer of any command
    python tools/d5ctl.py shot out.png [scale]
    python tools/d5ctl.py keys K S S K
    python tools/d5ctl.py launch           start the game (if needed) and wait for the harness
    python tools/d5ctl.py <any harness command ...>
"""
import json
import os
import subprocess
import sys
import tempfile
import time

PIPE = r"\\.\pipe\d5auto_ctl"
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
from d5lib.paths import game_dir as _game_dir  # noqa: E402

GAME_DIR = _game_dir() or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
_TRANSLATE = {}


def running_exe():
    """path of the running disgaea5.exe (None if the game isn't running)"""
    try:
        out = subprocess.check_output(["powershell", "-NoProfile", "-Command",
                                       "(Get-Process disgaea5 -ErrorAction SilentlyContinue | Select -First 1).Path"],
                                      text=True, timeout=15).strip()
        return out or None
    except Exception:
        return None


def game_addr(va):
    """a launch-build address (what the dev tools are written with) in the running game's build: the Steam build
    goes through its shipped address map (d5lib/data/exe_map_<sha12>.json)"""
    if "t" not in _TRANSLATE:
        import hashlib
        from d5lib import exemap
        t = None
        exe = running_exe()
        if exe and os.path.exists(exe):
            # the kit patches the exe at install: the build is the one of the original it backed up
            from d5lib import modsys
            orig = os.path.join(modsys.game_state_dir(os.path.dirname(exe)), "backups", "EXE__disgaea5.exe.full")
            sha = hashlib.sha1(open(orig if os.path.exists(orig) else exe, "rb").read()).hexdigest()
            for p in exemap.shipped_maps():
                if os.path.basename(p) == f"exe_map_{sha[:12]}.json":
                    t = exemap.translator_from_map(p)
        _TRANSLATE["t"] = t
    t = _TRANSLATE["t"]
    return t(va) if t is not None else va


class Ctl:
    def __init__(self, timeout=10.0):
        deadline = time.time() + timeout
        while True:
            try:
                self.h = open(PIPE, "r+b", buffering=0)
                return
            except OSError:
                if time.time() > deadline:
                    raise RuntimeError("the game's harness pipe is not there (game not running, or remote=0)")
                time.sleep(0.2)

    def close(self):
        self.h.close()

    def raw(self, line):
        self.h.write((line.strip() + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = self.h.read(1 << 16)
            if not chunk:
                raise RuntimeError("pipe closed")
            buf += chunk
        return buf.decode("utf-8", "replace").strip()

    def cmd(self, line):
        r = self.raw(line)
        try:
            return json.loads(r)
        except ValueError:
            return {"raw": r}

    # -- helpers
    def state(self):
        return self.cmd("state")

    def keys(self, seq):
        return self.cmd("keys " + seq)

    def wait(self, frames):
        return self.cmd(f"wait {int(frames)}")

    def rd(self, addr, n):
        r = self.cmd(f"rd {addr:x} {n}")
        return bytes.fromhex(r["hex"]) if "hex" in r else None

    def wr(self, addr, data):
        return self.cmd(f"wr {addr:x} {bytes(data).hex()}")

    def shot(self, out_png, scale=0.5, crop=None):
        from PIL import Image
        bmp = os.path.join(tempfile.gettempdir(), "d5ctl_shot.bmp")
        r = self.cmd("shot " + bmp)
        if "error" in r:
            raise RuntimeError(r["error"])
        im = Image.open(bmp)
        im.load()
        if crop:
            im = im.crop(crop)
        if scale and scale != 1:
            im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
        im.save(out_png)
        return out_png


def summary(st):
    lines = [f"frame {st.get('frame')}  mode {st.get('mode')}  IW {st.get('iw')}/{st.get('floormap')}  "
             f"battle {st.get('battle')}  flags 0x{st.get('flags', 0):02x}  auto {st.get('active')} "
             f"[{st.get('status')}]  focus {st.get('focus')}/{st.get('fake_focus')}",
             f"cursor {st.get('cpanel')} {st.get('cursor')}  base {st.get('base')}  gate {st.get('gate')}  "
             f"grid@base {st.get('grid_base')}  dep {st.get('dep')} nav {st.get('nav')} astate {st.get('astate')}"]
    for u in st.get("units", []):
        side = "ALLY " if u["team"] == 0 else f"EN{u['team']}  "
        lines.append(f"  {side}{u['name'][:18]:18} lv{u['lv']:>4} HP {u['hp']}/{u['hpmax']} SP {u['sp']}/{u['spmax']} "
                     f"ATK {u['atk']} DEF {u['def']} INT {u['int']} RES {u['res']}  @{u['p']} ai {u['ai']} "
                     f"f860 {u['f860']} cls {u['cls']}")
    return "\n".join(lines)


def running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq disgaea5.exe"], capture_output=True, text=True).stdout
    return "disgaea5.exe" in out.lower()


def launch(wait=90):
    if not running():
        # the player's "run as administrator" compatibility flag would need a UAC click: start it as the
        # current user instead (only for this launch; the flag itself is left alone)
        env = dict(os.environ, __COMPAT_LAYER="RunAsInvoker")
        subprocess.Popen([os.path.join(GAME_DIR, "disgaea5.exe")], cwd=GAME_DIR, env=env)
    return Ctl(timeout=wait)


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "launch":
        c = launch()
        print(summary(c.state()))
        return 0
    as_json = argv[0] == "json"
    if as_json:
        argv = argv[1:]
    c = Ctl()
    if argv[0] == "shot" and not as_json:
        out = argv[1] if len(argv) > 1 else os.path.join(tempfile.gettempdir(), "d5shot.png")
        scale = float(argv[2]) if len(argv) > 2 else 0.5
        print(c.shot(out, scale))
        return 0
    r = c.cmd(" ".join(argv))
    if argv[0] == "state" and not as_json and "units" in r:
        print(summary(r))
    else:
        print(json.dumps(r) if not isinstance(r, str) else r)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
