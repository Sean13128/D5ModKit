"""d5ctl_relay -- `d5ctl` for macOS: the kit's tools/d5ctl.py over the live harness relay.

`tools/d5ctl.py` talks to the Windows named pipe `\\\\.\\pipe\\d5auto_ctl`, so it cannot run from macOS at
all (`hire_test.py` dies with "pipe not found").  This module offers the same surface (`Ctl` with
cmd/raw/keys/rd/wr/shot/state, plus running_exe/game_addr/launch/summary) on top of
`live-harness/d5link.py`, which relays every command through `client/d5pipe.exe` inside the Wine prefix.

Two fixes over the original, both of which cost the LIVE3 lane a session:

1. `game_addr()` -- the original asks PowerShell for the running exe, which does not exist on macOS, so it
   returned launch-build addresses unchanged.  `walk.py` then read/wrote the hub leader at 0x142349160
   (zeros) instead of the Steam build's 0x141E2CD60 -- "go_to_npc() never converged".  Here the mapping
   comes from the kit's shipped exe map, keyed by the sha1 of the pinned vanilla exe backup.
2. Addresses past the exe *file* size (the 128-unit roster at 0x145235C58) are not translated by the
   runtime's rd/wr; `live_addr()` translates them from the same map.  A record's fields must be reached as
   `live_addr(base) + offset` -- the map has no entry for every field offset.

Use as a drop-in module:

    from d5ctl_relay import install_adapter, Ctl
    install_adapter()                 # sys.modules['d5ctl'] = this module
    import walk                       # walk.py's `from d5ctl import Ctl, game_addr` now works

    python tools/d5ctl_relay.py state
    python tools/d5ctl_relay.py json texts
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE.parent
sys.path.insert(0, str(KIT))
HARNESS = Path(os.environ.get("D5_HARNESS", "/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/live-harness"))
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

from d5lib import exemap  # noqa: E402
from d5lib.paths import game_dir as _game_dir  # noqa: E402

GAME_DIR = Path(_game_dir() or "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete")

_TRANSLATE: dict = {}


# ------------------------------------------------------------------ addresses
def vanilla_exe() -> Path:
    """The pinned, unmodified disgaea5.exe whose sha1 keys the exe map (the kit keeps it as a backup)."""
    env = os.environ.get("D5_RELAY_VANILLA_EXE")
    if env:
        return Path(env)
    state = KIT / "state" / "games"
    for p in sorted(state.glob("*/backups/EXE__disgaea5.exe.full")):
        return p
    exe = GAME_DIR / "disgaea5.exe"
    if exe.exists():
        return exe
    raise RuntimeError("no vanilla exe (backup or game folder) to map game addresses from")


def _translator():
    if "t" not in _TRANSLATE:
        path = vanilla_exe()
        sha1 = hashlib.sha1(path.read_bytes()).hexdigest()
        found = None
        for p in exemap.shipped_maps():
            if os.path.basename(p) == f"exe_map_{sha1[:12]}.json":
                found = exemap.translator_from_map(p)
                break
        if found is None:
            raise RuntimeError(f"no exe map for the exe sha1 {sha1[:12]} ({path})")
        _TRANSLATE["t"] = found
        _TRANSLATE["size"] = path.stat().st_size
    return _TRANSLATE["t"]


def image_file_size() -> int:
    """The exe's file size: the runtime's rd/wr translate below base+this and nothing above it."""
    _translator()
    return _TRANSLATE["size"]


def game_addr(va: int) -> int:
    """A launch-build address in the running (Steam) build -- same contract as tools/d5ctl.py."""
    return _translator()(va)


def live_addr(va: int) -> int:
    """An address the runtime's rd/wr takes: it translates only inside the exe file size, so a static
    address past it (the roster, the leader record's later copies) is translated here."""
    if va < 0x140000000:
        return va
    if va < 0x140000000 + image_file_size():
        return va
    return _translator()(va)


def running_exe():
    """Path of the running game (None when it is not running).  d5link finds the Wine process."""
    from d5link import game_pids
    return str(GAME_DIR / "disgaea5.exe") if game_pids() else None


def running() -> bool:
    from d5link import game_pids
    return bool(game_pids())


# ------------------------------------------------------------------ the Ctl object
class Ctl:
    """The three calls walk.py / hire_test.py / battle_nav.py make, over the macOS relay."""

    def __init__(self, timeout: float = 10.0, game=None, shot_dir=None):
        if game is not None:
            self.g = game
        else:
            from d5link import Game
            self.g = Game().connect(timeout)
        try:                                        # the game ignores the keyboard unless it believes it has focus
            self.g.focus(True)
        except Exception:                           # noqa: BLE001 - focus is best effort
            pass
        self.shot_dir = Path(shot_dir or HARNESS / "evidence" / "shots")
        self.shot_dir.mkdir(parents=True, exist_ok=True)

    # -- plumbing (same contract as tools/d5ctl.py)
    def cmd(self, line):
        return self.g.cmd(line)

    def raw(self, line):
        return json.dumps(self.g.cmd(line))

    def keys(self, seq):
        return self.g.keys(seq)

    def wait(self, frames):
        return self.g.wait(int(frames))

    def state(self):
        return self.g.state()

    def rd(self, addr, n):
        r = self.g.cmd(f"rd {int(addr):x} {int(n)}")
        return bytes.fromhex(r["hex"]) if "hex" in r else None

    def wr(self, addr, data):
        return self.g.cmd(f"wr {int(addr):x} {bytes(data).hex()}")

    def shot(self, path, scale=0.5):
        p = Path(path)
        if not p.is_absolute():
            p = self.shot_dir / p.name
        return self.g.shot(p, scale=scale)

    def close(self):
        pass


def launch(wait: int = 90) -> Ctl:
    from d5link import Game, game_pids
    g = Game()
    if not game_pids():
        g.launch_steam()
    g.wait_up(wait)
    return Ctl(game=g)


def summary(st: dict) -> str:
    """The state summary tools/d5ctl.py prints (kept byte-compatible enough for scripts)."""
    from d5link import state_summary
    return state_summary(st)


def install_adapter() -> None:
    """Make `import d5ctl` (and `from d5ctl import Ctl, game_addr`) resolve to this module."""
    mod = type(sys)("d5ctl")
    mod.Ctl = Ctl
    mod.game_addr = game_addr
    mod.live_addr = live_addr
    mod.running_exe = running_exe
    mod.running = running
    mod.launch = launch
    mod.summary = summary
    mod.GAME_DIR = str(GAME_DIR)
    sys.modules["d5ctl"] = mod


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 1
    if argv[0] == "launch":
        print(summary(launch().state()))
        return 0
    if argv[0] == "addr":                       # addr 142349160 -> the running build's address
        for a in argv[1:]:
            print(f"0x{int(a, 16):x} -> 0x{game_addr(int(a, 16)):x}")
        return 0
    as_json = argv[0] == "json"
    if as_json:
        argv = argv[1:]
    c = Ctl()
    if argv[0] == "shot" and not as_json:
        print(c.shot(argv[1] if len(argv) > 1 else "shot.png",
                     float(argv[2]) if len(argv) > 2 else 0.5))
        return 0
    r = c.cmd(" ".join(argv))
    if argv[0] == "state" and not as_json:
        print(summary(r))
    else:
        print(json.dumps(r) if not isinstance(r, str) else r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
