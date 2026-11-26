"""BACKVIEW1: the game draws node root+1 of an animation, never the root's own links (render_root_gate).

Unit cases build their banks in code.  The data case reads the pinned BACKVIEW1 build when present (skipped
otherwise): the rebuilt Kojiro, Chief, Garatea and Baltis pass.  The pre-repair installed layout is a fixture built in
code (`_bank("pt1030")`), not the live install: the BACKVIEW1 sweep repaired the installed banks, so reading the
install no longer proves the gate (TESTFIX-KOJIRO1).  Vanilla anm_resident passes when the game archive is present.
"""
from pathlib import Path

import pytest

from d5lib import anm, gamefs, importcore, ownanim

PROJECT = Path("/Volumes/Data/Projects/D5")
BUILD = PROJECT / "Builds/BACKVIEW1-20261110/d4/mods"
RESIDENT = Path("/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/Data/Anime/ANM_HI_JP.dat")


def _bank(stub_layout):
    """6001 / 6007 (one drawing each) and the 1001 / 1007 stubs naming them, in `stub_layout` order"""
    f = anm.AnmFile([anm.AnmBlock(16730)], [], [])
    anm.add_texture(f, 32, 32, indexed=True)
    f.textures[0].data = bytes([1]) * (32 * 32)
    anm.set_palette(f, 0, [(0, 0, 0, 0), (200, 40, 40, 255)] + [(0, 0, 0, 0)] * 254)
    b = f.blocks[0]
    b.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, 8, 8, 0),
               anm.Cell(0, 0, 0, 0, 0, 0, 16, 8, 0)]
    b.transforms = [anm.Transform(0, 0, 0, 0, 100, 100, 0)]
    b.pivots = [anm.Pivot(0, 0)]
    b.colors = [anm.Color((128, 128, 128, 255) * 5)]
    b.params = [6001, 0, -1, 6007, 0, -1]
    b.keys = [anm.Key(0, 1, 0, 0, 0, 0), anm.Key(0, 0, 1, 0, 0, 0), anm.Key(0, 0, 2, 0, 0, 0)]
    N = anm.Node
    b.nodes = [N(0, 0, 0, 0, 0, 0, 0, 1, -1, 1), N(0, 0, 0, 0, 0, 0, -1, 0, 2, -1), N(0, 0, 0, 0, 0, 0, 1, 1, -1, -1),
               N(0, 0, 0, 0, 0, 0, 0, 1, -1, 4), N(0, 0, 0, 0, 0, 0, -1, 0, 5, -1), N(0, 0, 0, 0, 0, 0, 2, 1, -1, -1)]
    b.animations = [anm.Animation(6001, 0), anm.Animation(6007, 3)]
    for idle, p in ((6001, 0), (6007, 3)):
        b.keys += [anm.Key(0, 5, 0, 0, 0, p), anm.Key(0, anm.NESTED, 0, 0, 0, p)]
        kc, kb, r = len(b.keys) - 2, len(b.keys) - 1, len(b.nodes)
        if stub_layout == "pt1030":                 # [body][root -> child body]: what the installed D4 banks carry
            b.nodes += [N(1, 0x100, 0, 0, 0, 0, kb, 1, -1, -1), N(0, 0x1000, 0, 0, 0, 0, kc, 1, r, -1)]
            root = r + 1
        else:                                       # native: control, container, body
            b.nodes += [N(0, 0x1000, 0, 0, 0, 0, kc, 1, -1, r + 1), N(0, 0, 0, 0, 0, 0, -1, 0, r + 2, -1),
                        N(1, 0x100, 0, 0, 0, 0, kb, 1, -1, -1)]
            root = r
        b.animations.append(anm.Animation(idle - 5000, root))
    return f


def _mod(tmp_path, bank):
    mod = tmp_path / "D4_Unique_Test"
    d = mod / "files/Anime/ANM_HI_JP.dat"
    d.mkdir(parents=True)
    (d / "anm16730.lzs").write_bytes(bank.to_bytes())
    return mod


def _cells(a, aid, game):
    return sorted(it.key.cell for it in anm.evaluate(a, ("id", aid), 0, nested=True, game=game))


def test_game_model_shows_what_the_pt1030_stubs_did_live():
    a = _bank("pt1030")
    assert _cells(a, 1001, False) == [1] and _cells(a, 1007, False) == [2]      # the kit: front and back
    assert _cells(a, 1001, True) == [2]        # the game: 1001 plays 1007's body (INSTALL4 A4: back shown from front)
    assert _cells(a, 1007, True) == []         # and 1007 reads past the node table: shadow and HP bar only
    assert {aid for aid, _ in anm.render_root_problems(a.blocks[0])} == {1001, 1007}


def test_native_stubs_draw_the_same_in_kit_and_game():
    a = _bank("native")
    assert anm.render_root_problems(a.blocks[0]) == []
    assert _cells(a, 1001, True) == _cells(a, 1001, False) == [1]
    assert _cells(a, 1007, True) == _cells(a, 1007, False) == [2]


def test_gate_fails_the_pt1030_layout_and_passes_native(tmp_path):
    ok, why = importcore.render_root_gate(_mod(tmp_path / "bad", _bank("pt1030")))
    assert not ok and "1001" in why and "1007" in why
    assert importcore.render_root_gate(_mod(tmp_path / "good", _bank("native"))) == (True, "")


def test_repair_and_normalize_give_the_native_layout(tmp_path):
    a = _bank("pt1030")
    assert sorted(ownanim.fix_render_roots(a.blocks[0])) == [1001, 1007]
    a = anm.parse(a.to_bytes())
    assert anm.render_root_problems(a.blocks[0]) == []
    assert _cells(a, 1001, True) == [1] and _cells(a, 1007, True) == [2]
    assert importcore.render_root_gate(_mod(tmp_path, a)) == (True, "")
    assert ownanim.fix_render_roots(a.blocks[0]) == []          # idempotent


def _bank_file(root, folder, n):
    p = root / folder / "files/Anime/ANM_HI_JP.dat" / f"anm{n:05d}.lzs"
    if not p.is_file():
        pytest.skip(f"{p} not present")
    return anm.parse(gamefs.decode_member(p.read_bytes()))


def test_kojiro_pre_repair_layout_fails_and_the_sweep_repair_passes(tmp_path):
    """TESTFIX-KOJIRO1: Kojiro (D4_Unique_4390 anm 646), Chief (653) and Garatea (826) shipped with the
    [body][root -> child body] wheel-stub layout: the game drew 1001 as 1007's body and 1007 past the node table.
    The BACKVIEW1 sweep repaired the installed banks, so `_bank("pt1030")` (the layout those installed D4 banks
    carried) is the fixed fixture; the live install no longer carries the defect."""
    a = _bank("pt1030")
    assert sorted({aid for _, aid, _ in anm.render_root_mismatches(a)}) == [1001, 1007]
    ok, why = importcore.render_root_gate(_mod(tmp_path / "kojiro_pre_repair", a))
    assert not ok and "1001" in why and "1007" in why
    assert sorted(ownanim.fix_render_roots(a.blocks[0])) == [1001, 1007]        # the sweep's repair
    ok, why = importcore.render_root_gate(_mod(tmp_path / "kojiro_repaired", anm.parse(a.to_bytes())))
    assert ok, why


def test_pinned_backview1_rebuilt_kojiro_and_baltis_pass():
    """The sweep's rebuilt banks (real D4 banks from the frozen BACKVIEW1 build) pass."""
    if not BUILD.is_dir():
        pytest.skip(f"{BUILD} not present")
    for folder, n in (("D4_Unique_4390", 646), ("D4_Unique_4390", 647), ("D4_Unique_5306", 823),
                      ("D4_Unique_5301", 653), ("D4_Unique_5307", 826)):
        assert anm.render_root_mismatches(_bank_file(BUILD, folder, n)) == [], (folder, n)


def test_vanilla_resident_has_the_layout_the_gate_expects():
    if not RESIDENT.is_file():
        pytest.skip("game archive not present")
    from d5lib import lzs, nispack
    with nispack.NisPack(str(RESIDENT)) as pk:
        res = anm.AnmFile.parse(lzs.decompress(pk.read("anm_resident.lzs")))
    assert sum(len(anm.render_root_problems(b)) for b in res.blocks) == 0


def _template_layout_bank():
    """The monster template's layout that ownanim.assemble inherits: root.child -1, root.next -> the drawing, which
    sits BEFORE the root (INSTALL1119A: 76 + 53 animations of the rebuilt Creator Asagi banks)."""
    f = _bank("native")
    b = f.blocks[0]
    N = anm.Node
    for a in b.animations:
        if a.id in (1001, 1007):
            body = b.nodes[a.root + 2]
            old = b.nodes[a.root]
            b.nodes.append(N(body.id, body.flags, 0, 0, 0, 0, body.first_key, body.num_keys, -1, -1))
            b.nodes.append(N(old.id, old.flags, 0, 0, 0, 0, old.first_key, old.num_keys, -1, len(b.nodes) - 1))
            a.root = len(b.nodes) - 1
    return f


def test_assemble_repairs_render_root_of_template_layout():
    """ASAGI4P2: assemble() ends with fix_render_roots, so a rebuilt bank draws in the game what the kit draws."""
    f = _template_layout_bank()
    b = f.blocks[0]
    assert anm.render_root_mismatches(f)
    ownanim.fix_render_roots(b)
    assert not anm.render_root_mismatches(f)
    assert ownanim.fix_render_roots(b) == []          # idempotent: native layouts are left alone
    import inspect
    src = inspect.getsource(ownanim.assemble)
    assert src.index("fix_render_roots(b)") > src.index("anm.AnmFile([b], textures, [])")
