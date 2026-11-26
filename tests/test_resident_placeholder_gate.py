"""D4BANK-ID: a registry monster unique's placeholder anm N+2 goes into anm_resident (the game binds N+2 while
bank N loads and finds it among loaded records only), even when no mod declares a class."""
import json
from types import SimpleNamespace

from d5lib import anm, facepatch, importcore, newclasses


def _mod(tmp_path, kind, n, with_placeholder=True):
    mod = tmp_path / f"u{n}"
    (mod / "patches" / "characters").mkdir(parents=True)
    (mod / "patches" / "characters" / "unique.json").write_text(json.dumps(
        dict(schema=1, identity=10000 + n, physical=n, kind=kind)))
    anime = mod / "files" / "Anime" / "ANM_HI_JP.dat"
    anime.mkdir(parents=True)
    if with_placeholder:
        block = anm.AnmBlock(n + 2)
        block.animations = [anm.Animation(1, 0)]
        (anime / f"anm{n + 2:05d}.lzs").write_bytes(anm.AnmFile([block], [], []).to_bytes())
    return mod


def test_gate_replays_the_installer_and_checks_an_installed_resident(tmp_path):
    monster = _mod(tmp_path, "monster", 643)
    assert importcore.resident_placeholder_gate(monster) == (True, "")
    ok, why = importcore.resident_placeholder_gate(_mod(tmp_path, "monster", 653, with_placeholder=False))
    assert not ok and "655" in why
    assert importcore.resident_placeholder_gate(_mod(tmp_path, "humanoid", 663, with_placeholder=False))[0]
    # installed form: today's install (no block 645) fails, a resident holding it passes
    assert not importcore.resident_placeholder_gate(monster, resident_ids={612, 2022})[0]
    assert importcore.resident_placeholder_gate(monster, resident_ids={645})[0]


def test_finalize_adds_unique_placeholder_without_class_specs(tmp_path, monkeypatch):
    mod = _mod(tmp_path, "monster", 643)
    data = (mod / "files/Anime/ANM_HI_JP.dat/anm00645.lzs").read_bytes()
    added = {}
    monkeypatch.setattr(facepatch, "add_resident_blocks",
                        lambda raw, blocks, log=None: added.setdefault(raw, sorted(blocks)) and raw + b"+")
    puts = {}
    ctx = SimpleNamespace(
        outputs={"anime/anm_hi_jp.dat/anm00645.lzs": (None, data)},
        fs=SimpleNamespace(read_raw=lambda vp: vp.encode()),
        _class_specs={}, _evility_aliases={}, log=lambda *a: None,
        _char_uniques={10643: dict(identity=10643, physical=643, kind="monster"),
                       10663: dict(identity=10663, physical=663, kind="humanoid")},
        put=lambda vp, raw: puts.__setitem__(vp, raw))
    newclasses._finalize(ctx)
    assert sorted(puts) == sorted(newclasses.RESIDENT)
    assert all(v == [645] for v in added.values())


def _row_mod(tmp_path, n, body_type, with_placeholder=True):
    """a DRPG-style pack: a plain char.dat row (no unique.json) with its own body bank N"""
    mod = tmp_path / f"r{n}"
    (mod / "patches" / "db").mkdir(parents=True)
    (mod / "patches" / "db" / "char.dat.json").write_text(json.dumps(
        {"table": "char.dat", "added": [dict(id=743, sprite_id=n, body_type=body_type)]}))
    anime = mod / "files" / "Anime" / "ANM_HI_JP.dat"
    anime.mkdir(parents=True)
    for k in (0, 1, 2) if with_placeholder else (0, 1):
        block = anm.AnmBlock(n + k)
        block.animations = [anm.Animation(0, 0)]
        (anime / f"anm{n + k:05d}.lzs").write_bytes(anm.AnmFile([block], [], []).to_bytes())
    return mod


def test_gate_covers_plain_char_rows_of_monster_kind(tmp_path):
    """NODRAW2: Beatrice 743 (sprite 16730, body_type 1) had no unique.json, so the gate said 'no registry unique'
    and the installer left anm16732 loose: invisible in battle as a real recruit."""
    assert importcore.resident_placeholder_gate(_row_mod(tmp_path, 16730, 1)) == (True, "")
    ok, why = importcore.resident_placeholder_gate(_row_mod(tmp_path, 16740, 1, with_placeholder=False))
    assert not ok and "16742" in why
    # installed form: a resident without 16732 fails (today's install), with it passes
    mod = _row_mod(tmp_path, 16750, 1)
    assert not importcore.resident_placeholder_gate(mod, resident_ids={612, 2022})[0]
    assert importcore.resident_placeholder_gate(mod, resident_ids={16752})[0]
    assert importcore.resident_placeholder_gate(_row_mod(tmp_path, 16330, 0, with_placeholder=False))[0]


def test_finalize_adds_placeholder_of_plain_monster_row(tmp_path, monkeypatch):
    from d5lib.database import load_table
    added = {}
    monkeypatch.setattr(facepatch, "add_resident_blocks",
                        lambda raw, blocks, log=None: added.setdefault(raw, sorted(blocks)) and raw + b"+")
    block = anm.AnmBlock(16732)
    block.animations = [anm.Animation(0, 0)]
    data = anm.AnmFile([block], [], []).to_bytes()
    rows = [dict(sprite_id=16730, body_type=1), dict(sprite_id=16330, body_type=0),   # humanoid: not added
            dict(sprite_id=2020, body_type=1)]                                         # vanilla: N+2 not loose
    puts = {}
    ctx = SimpleNamespace(
        outputs={"anime/anm_hi_jp.dat/anm16732.lzs": (None, data),
                 "anime/anm_hi_jp.dat/anm16332.lzs": (None, data)},
        fs=SimpleNamespace(read_raw=lambda vp: vp.encode()),
        _class_specs={}, _evility_aliases={}, _monster_rows=rows, log=lambda *a: None,
        put=lambda vp, raw: puts.__setitem__(vp, raw))
    newclasses._finalize(ctx)
    assert sorted(puts) == sorted(newclasses.RESIDENT)
    assert all(v == [16732] for v in added.values())


def test_humanoid_class_that_ships_its_placeholder_gets_it_resident():
    """PAGECRASH2: a humanoid class's loose N+2 is released while a wheel unit's render node still draws from it
    (Recruiter D4 page crashes); every vanilla humanoid keeps N+2 resident, so the installer now does the same.
    A humanoid class that does not ship N+2 (vanilla family, already resident) is left alone."""
    def bank(n):
        block = anm.AnmBlock(n)
        block.animations = [anm.Animation(1, 0)]
        return anm.AnmFile([block], [], []).to_bytes()
    specs = {14080: dict(kind="humanoid", sprite_family=1340),     # D4 Armor Knight: ships anm01342
             14090: dict(kind="humanoid", sprite_family=1150),     # reuses a vanilla family: nothing shipped
             14630: dict(kind="monster", sprite_family=2340)}
    ctx = SimpleNamespace(outputs={"anime/anm_hi_jp.dat/anm01342.lzs": (None, bank(1342)),
                                   "anime/anm_hi_jp.dat/anm02342.lzs": (None, bank(2342))},
                          fs=None, _monster_rows=[], log=lambda *a, **k: None)
    assert newclasses.humanoid_class_pictures(ctx, specs) == [1340]
    blocks = newclasses.monster_picture_blocks(ctx, specs)
    assert sorted(blocks) == [1342, 2342]
    assert blocks[1342].blocks[0].id == 1342
