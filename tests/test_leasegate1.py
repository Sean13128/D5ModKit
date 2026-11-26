"""LEASEGATE1: the cross-importer used-id gate (importcore.UsedIds) -- offline, no game needed."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from d5lib import importcore as ic            # noqa: E402


def make_mod(root, name, char=(), anm=(), slot=()):
    mod = Path(root) / name
    (mod / "patches/db").mkdir(parents=True)
    (mod / "mod.json").write_text('{"name": "%s"}' % name)
    (mod / "patches/db/char.dat.json").write_text(json.dumps({"added": [{"id": i} for i in char]}))
    (mod / "patches/db/Quest.dat.json").write_text(json.dumps({"added": [{"id": 900 + s, "sort_order": s} for s in slot]}))
    d = mod / "files/Anime/ANM_HI_JP.dat"
    d.mkdir(parents=True)
    for n in anm:
        (d / f"anm{n:05d}.lzs").write_bytes(b"x")
    return mod


class NoGame(ic.UsedIds):
    """Vanilla = nothing; leases = what the test plants."""
    planted = []

    def vanilla(self):
        return {}, {5}

    def vanilla_ids(self, kind):
        return {}

    def index(self):
        if self._index is None:
            ic.lease_claims, saved = (lambda **_kwargs: self.planted), ic.lease_claims
            try:
                super().index()
            finally:
                ic.lease_claims = saved
        return self._index


def test_planted_collisions(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    make_mod(other, "Held_Pack", char=[7000], anm=[643, 644], slot=[544])
    mine = tmp_path / "mine"
    mine.mkdir()
    clash = make_mod(mine, "New_Pack", char=[7000, 7010], anm=[644, 800], slot=[544, 9])
    clean = make_mod(mine, "Clean_Pack", char=[7020], anm=[900, 5 + 1000], slot=[10])
    NoGame.planted = [("d4", "D4_Pack", {"anm": {900}, "char.dat": {7020}})]
    used = NoGame("g", "s", [other, mine])
    ok, why = used.check(clash)
    assert not ok and "Held_Pack" in why and "char.dat 7000" in why and "anm 644" in why and "Quest.dat:slot 544" in why
    ok, why = used.check(clean)
    assert not ok and "lease d4:D4_Pack" in why and "anm 900" in why and "char.dat 7020" in why
    ok, why = used.check(other / "Held_Pack")              # its own folder name never counts; `mine` has no overlap with it
    assert not ok and "New_Pack" in why and "Held_Pack" not in why
    vanilla = make_mod(mine, "Vanilla_Pack", anm=[5])
    assert "vanilla" in used.check(vanilla)[1]
    solo = NoGame("g", "s", [])
    NoGame.planted = []
    assert solo.check(clean) == (True, "")


def test_art_window_matches_lease_span():
    assert ic.art_window(786) == (786, 787, 788, 10786, 10787)


def test_re_leased_d1c_three_are_free_against_every_recorded_lease():
    """The D1C three leased 643-655 / slots 544-545, which installed D4_Unique_210, Zed and DD2_Unique_420 hold."""
    by_owner = {}
    for source, owner, claims in ic.lease_claims():
        by_owner.setdefault(owner, []).append((source, claims))
    for owner in ("D1C_Unique_2500", "D1C_Unique_5390", "D1C_Unique_6601"):
        mine = {(k, i) for _, c in by_owner[owner] for k, ids in c.items() for i in ids}
        assert mine
        for other, entries in by_owner.items():
            if other == owner:
                continue
            theirs = {(k, i) for _, c in entries for k, ids in c.items() for i in ids}
            assert not mine & theirs, (owner, other, sorted(mine & theirs)[:4])
