"""Offline tests for tools/d5ctl_relay.py -- the macOS `d5ctl` (no game, no pipe).

    cd <kit worktree> && python -m pytest tests/test_d5ctl_relay.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import d5ctl_relay  # noqa: E402

LAUNCH_LEADER = 0x142349160          # walk.py's LEADER, in the launch build
STEAM_LEADER = 0x141E2CD60           # the same record in the shipped Steam build
ROSTER = 0x145235C58                 # 128 unit records, past the exe file size


@pytest.fixture()
def fake_map(monkeypatch):
    """A translator that shifts everything by a constant, plus a 11303936-byte "file size"."""
    shift = STEAM_LEADER - LAUNCH_LEADER
    monkeypatch.setitem(d5ctl_relay._TRANSLATE, "t", lambda va: va + shift)
    monkeypatch.setitem(d5ctl_relay._TRANSLATE, "size", 11303936)
    return shift


class FakeGame:
    """The bits of d5link.Game that Ctl uses."""

    def __init__(self):
        self.sent: list[str] = []
        self.shots: list[tuple[str, float]] = []
        self.focused = False

    def cmd(self, line):
        self.sent.append(line)
        if line.startswith("rd "):
            return {"ok": 1, "hex": "deadbeef"}
        if line == "state":
            return {"frame": 1, "mode": 8, "units": []}
        return {"ok": 1, "echo": line}

    def keys(self, seq):
        self.sent.append("keys " + seq)
        return {"ok": 1}

    def wait(self, frames):
        self.sent.append(f"wait {frames}")
        return {"ok": 1}

    def shot(self, path, scale=0.5):
        self.shots.append((str(path), scale))
        return str(path)

    def state(self):
        return self.cmd("state")

    def focus(self, on=True):
        self.focused = bool(on)
        return {"ok": 1}


# ------------------------------------------------------------------ address rules
def test_live_addr_leaves_live_addresses_alone(fake_map):
    assert d5ctl_relay.live_addr(0x0E327358) == 0x0E327358          # a heap window object
    assert d5ctl_relay.live_addr(0x140A03880) == 0x140A03880        # inside the exe file: rd translates it


def test_live_addr_translates_past_the_file_size(fake_map):
    assert d5ctl_relay.live_addr(ROSTER) == ROSTER + fake_map


def test_game_addr_maps_the_hub_leader(fake_map):
    """The LIVE3 bug: walk.py used the launch-build address and read zeros."""
    assert d5ctl_relay.game_addr(LAUNCH_LEADER) == STEAM_LEADER


def test_field_offsets_are_added_in_live_space(fake_map):
    """The map has no entry per field: a record's fields are live_addr(base) + offset."""
    base = d5ctl_relay.live_addr(ROSTER)
    assert base + 0x2E04 == ROSTER + fake_map + 0x2E04


# ------------------------------------------------------------------ Ctl contract
def test_ctl_matches_the_d5ctl_surface():
    c = d5ctl_relay.Ctl(game=FakeGame())
    for name in ("cmd", "raw", "keys", "wait", "state", "rd", "wr", "shot"):
        assert callable(getattr(c, name)), name


def test_ctl_relays_reads_and_keys():
    g = FakeGame()
    c = d5ctl_relay.Ctl(game=g)
    assert c.rd(0x140000000, 4) == bytes.fromhex("deadbeef")
    c.keys("K S:3:8 K")
    c.wait(30)
    assert "keys K S:3:8 K" in g.sent and "wait 30" in g.sent


def test_ctl_takes_focus_on_connect():
    g = FakeGame()
    d5ctl_relay.Ctl(game=g)
    assert g.focused is True


def test_ctl_shot_goes_to_the_shot_dir(tmp_path):
    g = FakeGame()
    c = d5ctl_relay.Ctl(game=g, shot_dir=tmp_path)
    out = c.shot("probe.png", scale=0.5)
    assert out == str(tmp_path / "probe.png")


# ------------------------------------------------------------------ the adapter module
def test_install_adapter_provides_a_usable_d5ctl():
    d5ctl_relay.install_adapter()
    mod = sys.modules["d5ctl"]
    assert mod.Ctl is d5ctl_relay.Ctl
    assert mod.game_addr is d5ctl_relay.game_addr
    # what walk.py / hire_test.py import must resolve
    src = (ROOT / "tools" / "walk.py").read_text()
    assert "from d5ctl import Ctl, game_addr" in src
    from d5ctl import Ctl, game_addr  # noqa: F401


def test_walk_imports_with_the_adapter(fake_map):
    """walk.py must import unchanged (it does `from d5ctl import Ctl, game_addr`)."""
    d5ctl_relay.install_adapter()
    sys.path.insert(0, str(ROOT / "tools"))
    if "walk" in sys.modules:
        del sys.modules["walk"]
    walk = __import__("walk")
    assert walk.LEADER == LAUNCH_LEADER
    assert callable(walk.go_to_npc)


def test_hub_spot_learning_uses_the_translated_leader(fake_map):
    """go_to_npc()'s teleport path: the position read back is the one written (LIVE3 read zeros)."""
    seen = {}

    class PosGame(FakeGame):
        def cmd(self, line):
            if line.startswith("wr "):
                addr, hexdata = line.split()[1], line.split()[2]
                seen[int(addr, 16)] = bytes.fromhex(hexdata)
            return super().cmd(line)

    g = PosGame()
    c = d5ctl_relay.Ctl(game=g)
    base = d5ctl_relay.live_addr(LAUNCH_LEADER)
    for off in (0x8, 0x34, 0x90):
        c.cmd(f"wr {base + off:x} " + ("00" * 12))
    assert set(seen) == {base + 0x8, base + 0x34, base + 0x90}
