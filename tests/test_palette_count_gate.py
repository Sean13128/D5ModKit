"""WRITEWATCH1: D2 palette counts as D5 reads them, and the palette_count gate.

The write-watch capture named 0x1402F9684 (`mov [r8+rax*4+0x829], ecx` in 0x1402F9550, called by start_basic_attack and
start_skill_action): it copies the attacker's palette into the 256-colour buffer 0x1469AF859, as many colours as the
PaletteInfo row's i32 at +4.  DD2 banks carried D2's big-endian count, which D5 reads as 0x01000000.
"""
import shutil
import struct
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))

from d5lib import anm, d2anm, gamefs, importcore  # noqa: E402

INSTALLED = Path("/Volumes/Data/Projects/D5/Local/Installed D5ModKit/mods/DD2_Class_22680")
BANK = "files/Anime/ANM_HI_JP.dat/anm02640.lzs"


def test_d2_count_is_a_big_endian_i32():
    st, read, _ = d2anm.CODECS[3]
    row = read(st.unpack(struct.pack(">II", 0x1234, 256)))       # D2 bytes: offset, then the count as BE i32
    assert (row.num_colors, row.unk) == (0, 256)                  # byte-faithful read: the count lands in unk
    assert row.num_colors | row.unk << 16 == 0x01000000           # what the game read before the fix
    f = anm.AnmFile.__new__(anm.AnmFile)
    b = anm.AnmBlock(0)
    b.palette_infos = [row, anm.PaletteInfo(0, 0, 0x400), anm.PaletteInfo(0, 0, 16)]
    f.blocks = [b]
    d2anm.d5_palette_counts(f)
    assert [(p.num_colors, p.unk) for p in b.palette_infos] == [(256, 0), (256, 0), (16, 0)]   # 1024 clamped
    assert struct.unpack("<i", struct.pack(*(("<IHH",) + (0, 256, 0)))[4:])[0] == 256  # D5 reads +4..+7 = 256


def _pack(tmp, data):
    mod = tmp / "DD2_Class_22680"
    (mod / Path(BANK).parent).mkdir(parents=True)
    (mod / BANK).write_bytes(data)
    return mod


@pytest.mark.skipif(not INSTALLED.is_dir(), reason="installed kit not here")
def test_gate_fails_the_installed_shark_pack_and_passes_the_repaired_rows(tmp_path):
    # the installed pack may already carry repaired counts: rebuild the D2 big-endian state from whatever it holds
    a = anm.parse(gamefs.decode_member((INSTALLED / BANK).read_bytes()))
    for b in a.blocks:
        for p in b.palette_infos:
            p.num_colors, p.unk = 0, 256                                # D2's count as the byte-faithful read keeps it
    raw = anm.lzs_compress(a.to_bytes())
    ok, why = importcore.palette_count_gate(_pack(tmp_path / "before", raw))
    assert not ok and "anm02640.lzs" in why and "0x1000000" in why
    assert {p.num_colors | p.unk << 16 for b in a.blocks for p in b.palette_infos} == {0x01000000}
    for b in a.blocks:
        for p in b.palette_infos:
            p.num_colors, p.unk = 256, 0
    ok, why = importcore.palette_count_gate(_pack(tmp_path / "after", anm.lzs_compress(a.to_bytes())))
    assert ok, why


def test_gate_passes_banks_with_256_or_16(tmp_path):
    if not INSTALLED.is_dir():
        pytest.skip("installed kit not here")
    for name in ("D4_Class_2190", "DD2_Unique_300"):                # Rifle Demon (attacks live), Pringer Z (DD2, casts)
        src = INSTALLED.parent / name
        if not src.is_dir():
            continue
        mod = tmp_path / name
        shutil.copytree(src / "files", mod / "files")
        assert importcore.palette_count_gate(mod) == (True, ""), name
