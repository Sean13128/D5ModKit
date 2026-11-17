"""patches/exe (d5lib.exebytes): data-only checked byte patches.

Needs a vanilla Steam disgaea5.exe (sha1 9460a641...): set D5_CLEAN_EXE to its path; skipped otherwise.  The test
patches overwrite a few bytes of a conditional jump with a no-op; the original bytes are read from that exe."""
import json
import os
import sys
import types

import pytest

sys.dont_write_bytecode = True
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
EXE = os.environ.get("D5_CLEAN_EXE", "")
pytestmark = pytest.mark.skipif(not os.path.exists(EXE), reason="set D5_CLEAN_EXE to a vanilla Steam disgaea5.exe")

from d5lib import exebytes, exemap  # noqa: E402
from d5lib.gamefs import EXE_FILE  # noqa: E402

VA, OFF, N = 0x1401AF645, 0x1AEA45, 6           # a 6-byte conditional jump in the Steam build
NOP6 = bytes.fromhex("660F1F440000")
STEAL = {"va": hex(VA), "new": NOP6.hex().upper(), "what": "steal"}     # "orig" is read from the exe below


class Ctx:
    def __init__(self, folders, exe):
        self.mod_folders, self.exe, self.skipped_features, self.logs = folders, exe, [], []

    def get(self, f):
        return self.exe

    def put(self, f, data):
        self.exe = data

    def log(self, m):
        self.logs.append(m)


@pytest.fixture
def exe():
    old = exemap.ACTIVE
    exemap.use(exemap.Translator(exemap.KNOWN_SHA1))
    exemap.reset_ledger()
    data = open(EXE, "rb").read()
    STEAL["orig"] = data[OFF:OFF + N].hex().upper()
    exemap.use(exemap.translator_for(data))
    yield data
    exemap.reset_ledger()
    exemap.use(old)


def mod(root, name, patches, settings=None, build=None):
    d = root / name / "patches" / "exe"
    d.mkdir(parents=True)
    (root / name / "mod.json").write_text(json.dumps({"name": name, "settings": settings or {}}))
    doc = {"patches": patches}
    if build:
        doc["build"] = build
    (d / "p.json").write_text(json.dumps(doc))
    return str(root / name)


def run(folders, exe):
    exemap.reset_ledger()
    ctx = Ctx(folders, exe)
    exebytes._finalize(ctx)
    return ctx


def test_no_mods_no_change(exe):
    assert run([], exe).exe == exe


def test_applies_bytes(tmp_path, exe):
    out = run([mod(tmp_path, "A", [STEAL])], exe).exe
    diff = [i for i in range(len(exe)) if exe[i] != out[i]]
    assert diff and all(OFF <= i < OFF + N for i in diff)
    assert out[OFF:OFF + N] == NOP6


def test_wrong_orig_skips_mod_whole(tmp_path, exe):
    bad = dict(STEAL, va="0x1401AF700", new="660F1F440000")
    ctx = run([mod(tmp_path, "A", [STEAL, bad])], exe)
    assert ctx.exe == exe and [n for n, _ in ctx.skipped_features] == ["mod A"]


def test_two_mods_same_site_second_skipped(tmp_path, exe):
    ctx = run([mod(tmp_path, "A", [STEAL]), mod(tmp_path, "B", [STEAL])], exe)
    assert ctx.exe[OFF:OFF + N] == NOP6
    (name, why), = ctx.skipped_features
    assert name == "mod B" and "mod A" in why and "B" in why


def test_bad_mod_does_not_stop_next(tmp_path, exe):
    bad = dict(STEAL, orig="000000000000")
    ctx = run([mod(tmp_path, "A", [bad]), mod(tmp_path, "B", [STEAL])], exe)
    assert ctx.exe[OFF:OFF + N] == NOP6 and len(ctx.skipped_features) == 1


def test_value_substitution(tmp_path, exe):
    p = dict(STEAL, new="660F00000000", values=[{"offset": 2, "size": 4, "setting": "cost", "default": 100}])
    assert run([mod(tmp_path, "A", [p], {"cost": 7})], exe).exe[OFF + 2:OFF + N] == b"\x07\0\0\0"
    assert run([mod(tmp_path, "B", [p])], exe).exe[OFF + 2:OFF + N] == b"\x64\0\0\0"
    assert run([mod(tmp_path, "C", [p], {"cost": -1})], exe).exe[OFF + 2:OFF + N] == b"\xff" * 4
    ctx = run([mod(tmp_path, "D", [p], {"cost": 2 ** 32})], exe)
    assert ctx.exe == exe and ctx.skipped_features


def test_build_prefix(tmp_path, exe):
    other = run([mod(tmp_path, "A", [STEAL], build="deadbeef")], exe)
    assert other.exe == exe and "deadbeef" in other.skipped_features[0][1]
    same = run([mod(tmp_path, "B", [STEAL], build=exemap.ACTIVE.sha1[:8])], exe)
    assert same.exe[OFF:OFF + N] == NOP6


def test_runs_after_kit_exe_patches_before_grips():
    from d5lib import modsys
    modsys.load_handlers()
    mods = [fn.__module__ for fn in modsys.ordered_finalizers()]
    assert mods.index("d5lib.runtime") < mods.index("d5lib.exebytes") < mods.index("d5lib.grips")
    assert mods.index("d5lib.outfits") < mods.index("d5lib.exebytes")


def test_mod_overlapping_a_kit_feature_is_the_one_skipped(tmp_path, exe):
    # a kit finalizer (here: outfits) has already claimed the range; exebytes runs after it
    exemap.reset_ledger()
    with exemap.owner("outfits"):
        exemap.claim(VA, N, "kit patch")
    ctx = Ctx([mod(tmp_path, "Data", [STEAL])], exe)
    with exemap.owner("exebytes"):
        exebytes._finalize(ctx)
    assert ctx.exe == exe
    (name, why), = ctx.skipped_features
    assert name == "mod Data" and "outfits" in why and "Data" in why


BAD = [
    ("missing orig", {"va": hex(VA), "new": "6600"}),
    ("missing va", {"orig": "00", "new": "00"}),
    ("patches not a list", 5),
    ("patches a string", "abc"),
    ("entry not an object", ["x"]),
    ("va outside image", {"va": "0x1FFFFFFFF", "orig": "00", "new": "00"}),
    ("va not a number", {"va": "zz", "orig": "00", "new": "00"}),
    ("value without setting", dict(STEAL, values=[{"offset": 0, "size": 1}])),
    ("value without offset", dict(STEAL, values=[{"setting": "a", "size": 1}])),
    ("values not a list", dict(STEAL, values=5)),
    ("value outside new", dict(STEAL, values=[{"offset": 4, "size": 4, "setting": "a", "default": 1}])),
    ("length mismatch", dict(STEAL, new="66")),
]


@pytest.mark.parametrize("label,bad", BAD, ids=[b[0] for b in BAD])
def test_malformed_mod_is_skipped_not_fatal(tmp_path, exe, label, bad):
    d = tmp_path / "A" / "patches" / "exe"
    d.mkdir(parents=True)
    (tmp_path / "A" / "mod.json").write_text('{"name": "A"}')
    (d / "p.json").write_text(json.dumps({"patches": bad if isinstance(bad, (int, str, list)) and not isinstance(bad, dict) else [bad]}))
    ctx = run([str(tmp_path / "A"), mod(tmp_path, "B", [STEAL])], exe)
    assert [n for n, _ in ctx.skipped_features] == ["mod A"]
    assert ctx.exe[OFF:OFF + N] == NOP6


def test_mod_named_like_a_kit_module_cant_share_its_owner(tmp_path, exe):
    # a mod folder called "runtime" whose patch fails must not release the kit's own claim
    exemap.reset_ledger()
    with exemap.owner("runtime"):
        exemap.claim(VA, N, "kit patch")
    bad = dict(STEAL, va="0x1401AF700", new="660F1F440000")
    ctx = Ctx([mod(tmp_path, "runtime", [bad])], exe)
    exebytes._finalize(ctx)
    assert [(e["owner"], e["start"]) for e in exemap.LEDGER] == [("runtime", VA)]
    assert [n for n, _ in ctx.skipped_features] == ["mod runtime"]


def test_applied_mod_logs_its_code_changes(tmp_path, exe):
    ctx = run([mod(tmp_path, "A", [STEAL])], exe)
    assert "A: patches the game's code at 1 sites (6 bytes)" in "\n".join(ctx.logs)


def test_describe_counts_sites_and_bytes(tmp_path):
    from d5lib.modsys import Mod
    one = dict(STEAL, orig="000000000000")      # describe() counts bytes, it checks nothing
    two = dict(STEAL, va="0x1401AF700", orig="0000", new="6690")
    assert exebytes.describe(Mod(mod(tmp_path, "A", [one, two]))) == "A: patches the game's code at 2 sites (8 bytes)"
    assert exebytes.describe(Mod(str(tmp_path))) == ""


def test_entry_in_a_kit_section_or_outside_the_game_sections_is_rejected(tmp_path, exe):
    from d5lib import exepatch
    exemap.reset_ledger()
    with exemap.owner("kit hook"):
        patched = exepatch.add_hook_section(exe, b".d5tt", [(exemap.Native(VA + 0x100), exe[OFF + 0x100:OFF + 0x100 + N], "ret", 0xE9)])
    exemap.reset_ledger()
    base = exepatch.IMAGE_BASE + exepatch.pefile.PE(data=patched, fast_load=True).sections[-1].VirtualAddress
    # wholly inside the kit section; straddling its start; the section table headers (not a section at all)
    for label, va in (("inside", base + 8), ("straddle", base - 3), ("headers", 0x140000400)):
        entry = {"va": va, "orig": b"\xC3\xC3\xC3\xC3", "new": b"\x90" * 4, "what": f"p.json #0 ({label})"}
        with pytest.raises(ValueError) as cm:
            exebytes.apply(patched, [entry], "mod X")
        assert label in str(cm.value) and "p.json #0" in str(cm.value)
        assert exemap.LEDGER == []
    assert "kit" in str(pytest.raises(ValueError, exebytes.apply, patched, [dict(entry, va=base + 8)], "mod X").value)
    # and through the finalizer: the mod is skipped with the file and entry named, the exe stays as it was
    ctx = Ctx([mod(tmp_path, "K", [dict(STEAL, va=hex(base + 8), orig="C3C3C3C3", new="90909090")])], patched)
    exebytes._finalize(ctx)
    assert ctx.exe == patched
    (name, why), = ctx.skipped_features
    assert name == "mod K" and "p.json #0" in why and "kit" in why
    # a game address still applies on the kit-patched exe
    ok = Ctx([mod(tmp_path, "G", [STEAL])], patched)
    exebytes._finalize(ok)
    assert not ok.skipped_features and ok.exe[OFF:OFF + N] == NOP6


def test_mod_over_generic_human_immediates_clashes_with_the_kit(tmp_path, exe):
    from d5lib import newclasses
    exemap.use(exemap.translator_for(exe))
    exemap.reset_ledger()
    with exemap.owner("newclasses"):
        newclasses.generic_patch(exe)
    mine = [e for e in exemap.LEDGER if e["what"] == "human test immediate"]
    assert mine
    exemap.reset_ledger()
    with exemap.owner("newclasses"):
        newclasses.generic_patch(exe)
    e0 = mine[0]
    from d5lib.exepatch import pefile
    pe = pefile.PE(data=exe, fast_load=True)
    off = pe.get_offset_from_rva(e0["start"] - 0x140000000)
    entry = {"va": hex(e0["start"]), "orig": exe[off:off + 4].hex(), "new": "90" * 4, "what": "imm"}
    ctx = Ctx([mod(tmp_path, "Data", [entry])], exe)
    with exemap.owner("exebytes"):
        exebytes._finalize(ctx)
    (name, why), = ctx.skipped_features
    assert name == "mod Data" and "newclasses" in why and "clash" in why, why
