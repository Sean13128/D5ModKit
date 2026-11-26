"""BATTLENAV1: pure logic of tools/battle_nav.py (queue check, target error, facing key, execute_checked, on_map).

No game: a fake control pipe answers `rd`, `texts`, `state` and records the keys.  Proven live in LIVE1120C
(2026-11-20): L on the map undoes the cursor unit's queued action; I opens the menu and Execute then runs.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import battle_nav as bn  # noqa: E402


class FakeCtl:
    BM = 0x200000000

    def __init__(self, queue=0, lines=None, bm=None, cursor=(7, 4)):
        self.queue, self.lines, self.cursor = queue, list(lines or []), list(cursor)
        self.bm = self.BM if bm is None else bm
        self.keys_sent, self.on_key = [], {}

    def cmd(self, line):
        if line.startswith("rd "):
            _, addr, _n = line.split()
            addr = int(addr, 16)
            if addr == bn.BM_PTR:
                return {"hex": self.bm.to_bytes(8, "little").hex()}
            if addr == self.bm + bn.BM_QUEUE_COUNT:
                return {"hex": self.queue.to_bytes(4, "little", signed=True).hex()}
            raise AssertionError(line)
        if line == "texts":
            return {"list": [[0, 0, 0, 0, t] for t in self.lines]}
        raise AssertionError(line)

    def raw(self, line):
        assert line == "state"
        return '{"cpanel": %s}' % list(self.cursor)

    def keys(self, seq):
        self.keys_sent.append(seq)
        for k in seq.split():
            fn = self.on_key.get(k.split(":")[0])
            if fn:
                fn(self)


def test_queue_count_reads_the_battle_manager_field():
    assert bn.queue_count(FakeCtl(queue=3)) == 3
    assert bn.queue_count(FakeCtl(queue=0)) == 0


def test_queue_count_is_none_when_unreadable():
    assert bn.queue_count(FakeCtl(bm=0)) is None            # no battle manager yet

    class Broken:
        def cmd(self, line):
            raise OSError("pipe closed")
    assert bn.queue_count(Broken()) is None


def test_target_error_finds_the_red_line_in_the_first_six_texts():
    assert bn.target_error(FakeCtl(lines=["Select target", "No target."])) == "No target."
    assert bn.target_error(FakeCtl(lines=["Out of range.", "x"])) == "Out of range."
    assert bn.target_error(FakeCtl(lines=["a", "b", "c", "d", "e", "f", "No target."])) is None   # past the window
    assert bn.target_error(FakeCtl(lines=["Select target"])) is None


def test_on_map_sees_the_menu_prompt_after_the_unit_panel_lines():
    assert bn.on_map([";044; Menu"])
    assert bn.on_map(["Wood Golem", "Lv 8", ";044; Menu"])          # cursor on a unit: two name lines first
    assert not bn.on_map(["Commence assigned actions"])
    assert not bn.on_map([])
    assert not bn.on_map(None)


def test_facing_key_w_is_toward_larger_y():
    assert bn.facing_key((7, 4), (7, 5)) == "W"             # LIVE1120C: W hit the unit at y+1
    assert bn.facing_key((7, 4), (7, 3)) == "S"
    assert bn.facing_key((7, 4), (8, 4)) == "D"
    assert bn.facing_key((7, 4), (6, 4)) == "A"
    assert bn.facing_key((7, 4), (9, 5)) == "D"             # dominant axis
    assert bn.facing_key((7, 4), (8, 7)) == "W"
    assert bn.facing_key((7, 4), (7, 4)) is None


def test_execute_checked_does_not_press_when_nothing_is_queued(monkeypatch):
    c = FakeCtl(queue=0, lines=["Commence assigned actions"])
    monkeypatch.setattr(bn, "battle_menu", lambda c: True)
    out = bn.execute_checked(c, wait=0.1)
    assert out["queued"] == 0 and out["left_menu"] is False and "nothing queued" in out["note"]
    assert c.keys_sent == []                                 # Execute would be a silent no-op: K never pressed


def test_execute_checked_reports_leaving_the_menu(monkeypatch):
    c = FakeCtl(queue=1, lines=["Commence assigned actions"])
    monkeypatch.setattr(bn, "battle_menu", lambda c: True)
    monkeypatch.setattr(bn.time, "sleep", lambda s: None)
    c.on_key["K"] = lambda cc: cc.lines.__setitem__(slice(None), ["Battle log"])
    out = bn.execute_checked(c, wait=1.0)
    assert out["queued"] == 1 and out["left_menu"] is True and out["texts"] == ["Battle log"]
    assert c.keys_sent == ["K:1:10"]


def _selector(c):
    c.lines[:] = ["Select target"]


def test_cast_facing_presses_the_key_once_and_reports_the_queue(monkeypatch):
    monkeypatch.setattr(bn.time, "sleep", lambda s: None)
    monkeypatch.setattr(bn, "menu", lambda c, e: True)
    c = FakeCtl(queue=0, lines=["Special Skill List", "Angered Tree"])
    c.on_key["W"] = lambda cc: setattr(cc, "faced", True)
    c.on_key["K"] = lambda cc: setattr(cc, "queue", 1) if getattr(cc, "faced", False) else None   # confirm queues
    assert bn.cast(c, "Wood Golem", "Angered Tree", (7, 5), menu_open=True, facing="W") is True
    assert "W:1:14" in c.keys_sent                           # one facing press, no cursor walk
    assert not any(k.startswith(("A:", "D:", "S:1:14")) for k in c.keys_sent)
    assert bn.cast.last_error is None


def test_cast_returns_false_and_cancels_on_a_target_error(monkeypatch):
    monkeypatch.setattr(bn.time, "sleep", lambda s: None)
    monkeypatch.setattr(bn, "menu", lambda c, e: True)
    c = FakeCtl(queue=0, lines=["Special Skill List", "Remote Trail"])

    def refuse(cc):
        cc.lines[:] = ["No target."]
    c.on_key["W"] = refuse
    assert bn.cast(c, "Death", "Remote Trail", (7, 5), menu_open=True, facing="W") is False
    assert bn.cast.last_error == "No target."
    assert c.keys_sent.count("L:1:10") == 3                  # backs out of the selector
    assert c.queue == 0


def test_cast_is_false_when_the_confirm_queued_nothing(monkeypatch):
    monkeypatch.setattr(bn.time, "sleep", lambda s: None)
    monkeypatch.setattr(bn, "menu", lambda c, e: True)
    c = FakeCtl(queue=0, lines=["Special Skill List", "Angered Tree"])
    assert bn.cast(c, "Wood Golem", "Angered Tree", (7, 5), menu_open=True, facing="S") is False
