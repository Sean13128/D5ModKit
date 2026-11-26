"""The harness's silence switch, offline: [audio] silent in d5auto.ini, and the runtime source that acts on it.

What is proven here (no game, no Wine, no installed kit):
  * the ini the kit writes carries the key, and the value mapping is what the runtime parses;
  * every game address d5sound.inc.c names is translatable (d5lib.exemap only knows 0x14xxxxxx addresses);
  * the runtime really compiles with it, and the built d5core.dll carries the four volume-setter addresses.

What is NOT proven here: that the game goes quiet.  That needs the live lane (SILENT-REPORT.md).
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

import pytest

from d5lib import runtime

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "d5lib" / "native"
SOUND = NATIVE / "d5sound.inc.c"

# the addresses d5sound.inc.c has to name (audio_runtime.md 1.1-1.4, 4; verified in the pinned exe)
SETTERS = {0x140226d30: "BGM", 0x140226e30: "message voice", 0x140227320: "SE", 0x140227640: "unit voice"}
MANAGERS = {0x140bd7b60: "BGM", 0x140bd7b68: "message voice", 0x140bd7b70: "SE", 0x140bd7b78: "unit voice"}


# ------------------------------------------------------------------------------- the ini the kit writes
@pytest.mark.parametrize("value,text", [("auto", "auto"), (None, "auto"), ("on", "1"), (True, "1"),
                                        (1, "1"), ("off", "0"), (False, "0"), (0, "0")])
def test_silent_text(value, text):
    assert runtime.silent_text(value) == text


def test_ini_carries_the_audio_section():
    ini = runtime.ini_text({})
    assert "[audio]" in ini
    assert "silent=auto" in ini


def test_ini_writes_an_explicit_switch():
    assert "silent=1" in runtime.ini_text({"silent": True})
    assert "silent=0" in runtime.ini_text({"silent": "off"})


# ------------------------------------------------------------------------------- the runtime source
def test_sound_source_exists():
    assert SOUND.exists(), "d5sound.inc.c is missing"


def test_every_game_address_is_translatable():
    """d5lib.exemap rewrites 0x14xxxxxx addresses for another game build; anything else would stay stale."""
    text = SOUND.read_text()
    bad = [a for a in re.findall(r"0x1[0-9a-fA-F]{8}ULL", text) if not re.fullmatch(r"0x14[0-9a-f]{7}ULL", a)]
    assert bad == [], f"addresses exemap cannot translate: {bad}"


def test_sound_source_names_the_setters_and_managers():
    text = SOUND.read_text().lower()
    for va, what in {**SETTERS, **MANAGERS}.items():
        assert f"0x{va:09x}" in text, f"{what} at 0x{va:x} is not named"


def test_sound_source_reads_the_options_it_never_writes():
    text = SOUND.read_text()
    assert "0x14699f9fa" in text.lower()                 # option i at +i; 20..23 are the volumes
    assert "GetPrivateProfile" not in text              # settings come from d5auto.c


def test_the_feature_is_guarded_to_the_verified_build():
    """Calling a game address is only safe in the build it was read in: elsewhere the switch is compiled out."""
    text = SOUND.read_text()
    head, rest = text.split("#if defined(D5_BUILD_9460A6411699)", 1)
    in_build, other = rest.split("#else", 1)
    assert "VA_SND_SET_BGM" in in_build and "VA_SND_SET_BGM" not in other
    assert '"available":0' in other.replace('\\"', '"')   # it says so instead of calling anything


def test_auto_silent_only_when_remote():
    text = SOUND.read_text()
    assert "return g_remote ? 1 : 0;" in text.split("static int snd_want(void) {")[1][:200]


def test_runtime_wires_it_up():
    auto = (NATIVE / "d5auto.c").read_text()
    assert auto.index('#include "d5sound.inc.c"') < auto.index('#include "d5ctl.inc.c"')
    assert "sound_tick();" in auto                        # every frame: engage, and survive a save load
    assert 'GetPrivateProfileStringA("audio", "silent", "auto"' in auto
    assert "static int g_sound_want" in auto


def test_ctl_has_the_silent_command():
    ctl = (NATIVE / "d5ctl.inc.c").read_text()
    assert '"silent"' in ctl and "sound_set(" in ctl and "sound_report(" in ctl


# ------------------------------------------------------------------------------- silent from the first sound
# SILENTSHIP (2026-10-28): the silence has to be in force BEFORE the first sound.  The masters are 1.0f at
# boot (nothing derives them from the Options at boot) and a save load re-derives them from Options 20..23.
# The runtime therefore patches the four option reads in lifecycle_flows_load_apply to 0 while silent.
READ_SITES = {0x1401cc6d3: 20, 0x1401cc71f: 22, 0x1401cc73e: 23, 0x1401cc75b: 21}


def test_the_load_derivation_sites_are_named():
    text = SOUND.read_text().lower()
    for va, opt in READ_SITES.items():
        assert f"0x{va:09x}" in text, f"the derivation read for option {opt} (0x{va:x}) is not named"


def test_the_patch_is_an_xor_eax_plus_nops():
    """7 bytes at the site ('0f be 05 disp32' -> 'xor eax,eax' + 5 nops): eax = 0, so master = 0 / 10.0."""
    text = SOUND.read_text()
    row = re.search(r"SND_OPT_READ_ZERO\[SND_OPT_READ_LEN\]\s*=\s*\{([^}]*)\}", text)
    assert row, "SND_OPT_READ_ZERO is missing"
    values = [int(v, 16) for v in re.findall(r"0x[0-9a-fA-F]{2}", row.group(1))]
    assert values[:2] == [0x31, 0xc0] and values[2:] == [0x90] * 5, values
    assert "SND_OPT_READ_LEN 7" in text


def test_the_sites_are_checked_before_they_are_patched():
    """A different build must not be patched blindly: the opcode bytes are compared first."""
    text = SOUND.read_text()
    assert "p[0] != 0x0f || p[1] != 0xbe || p[2] != 0x05" in text


def test_every_frame_reassert_not_once_a_second():
    text = SOUND.read_text()
    tick = text.split("static void sound_tick(void) {")[1]
    assert "snd_drifted()" in tick, "the tick does not watch the masters"
    assert ">= 60" not in tick, "the re-assert is still on a 60-frame timer"


def test_status_reports_when_the_silence_took_effect():
    text = SOUND.read_text()
    for key in ('\\"clamped\\":%d', '\\"engaged\\":%ld', '\\"asserts\\":%d', '\\"frame\\":%ld'):
        assert key in text, f"silent status does not report {key}"
    auto = (NATIVE / "d5auto.c").read_text()
    assert "static long g_sound_engaged" in auto and "static int g_sound_asserts" in auto


def test_the_clamp_happens_before_the_masters_are_written():
    text = SOUND.read_text()
    body = text.split("static int sound_apply(int on) {")[1]
    assert body.index("snd_clamp_derivation(1)") < body.index("snd_set_masters(0)")


# ------------------------------------------------------------------- the manager pointer (LIVE7 §2.1)
# LIVE7 (2026-10-28, measured live): the four manager objects are HEAP allocations
# (bgm 0x76c6540, msg 0x76c65a0, se 0xa603520, voice 0xa603da0) outside the module image
# (0x140000000..0x148125000).  The old "in_image(m, 4)" test on the object therefore rejected every manager,
# snd_ready() was false forever and the silence never engaged (silent_status: applied -1, engaged -1,
# masters -1.000 for the whole run).  The object test must be a readability test, not an image-range test.
def test_the_manager_object_is_tested_for_readability_not_the_image_range():
    text = SOUND.read_text()
    assert "static int snd_ptr_ok(" in text, "the manager pointer predicate is gone"
    ptr = text.split("static int snd_ptr_ok(", 1)[1].split("\n}", 1)[0]
    assert "readable(m, 4)" in ptr, "the manager object is not tested with readable()"
    assert "in_image" not in ptr, "the manager object is still tested against the image range (the LIVE7 bug)"
    mgr = text.split("static void *snd_mgr(", 1)[1].split("\n}", 1)[0]
    assert "in_image(pp" in mgr, "the global itself must still be an image address"
    assert "snd_ptr_ok(m)" in mgr
    assert "in_image(m" not in mgr, "the heap manager pointer is still rejected by the image test"


def test_snd_ready_uses_the_fixed_lookup_for_all_four_managers():
    text = SOUND.read_text()
    ready = text.split("static int snd_ready(void) {", 1)[1].split("\n}", 1)[0]
    for va in ("VA_SND_BGM_MGR", "VA_SND_MSG_MGR", "VA_SND_SE_MGR", "VA_SND_VOICE_MGR"):
        assert va in ready, f"snd_ready does not check {va}"
    assert "in_image" not in ready


# ------------------------------------------------------------------------------- the built DLL
def _have_zig() -> bool:
    try:
        import ziglang  # noqa: F401
        return True
    except ImportError:
        return False


def _steam_build_translator():
    """What the installer uses for this game build: d5lib/data/exe_map_9460a6411699.json (no game needed)."""
    from d5lib import exemap
    paths = [p for p in exemap.shipped_maps() if "9460a6411699" in p]
    assert paths, "the shipped map for the Steam build is missing"
    return exemap.translator_from_map(paths[0])


def _build_as(translator):
    from d5lib import exemap
    old = exemap.ACTIVE
    exemap.ACTIVE = translator
    try:
        return runtime.build_core(log=lambda _m: None)
    finally:
        exemap.ACTIVE = old


@pytest.mark.skipif(not _have_zig(), reason="the Zig compiler (pip install ziglang) is not here")
def test_core_builds_for_the_steam_build_and_carries_the_volume_setters():
    """The build the installer makes for Sean's game: translated for 9460a641..., feature compiled in.

    This is also the check that every address d5sound.inc.c names is in that build's map (a missing one
    raises exemap.Unmapped here, as it would at install time).
    """
    dll = _build_as(_steam_build_translator())
    assert dll[:2] == b"MZ"
    for va in SETTERS:
        assert dll.count(struct.pack("<I", va - 0x140000000)), f"the build never reaches 0x{va:x}"
    for va in READ_SITES:                     # the save-load derivation clamp reaches its four sites too
        # they live in a table of unsigned long long, so the 8-byte form is in the binary
        assert dll.count(struct.pack("<Q", va)), f"the build never reaches 0x{va:x}"
    assert b"silent" in dll


@pytest.mark.skipif(not _have_zig(), reason="the Zig compiler (pip install ziglang) is not here")
def test_core_compiles_the_switch_out_for_another_build():
    """Identity build (the 2018 one the kit's own numbers belong to): the switch must not be in the binary."""
    dll = _build_as(_steam_build_translator())      # first, so the cache does not hide a difference
    del dll
    from d5lib import exemap
    dll = _build_as(exemap.Translator(exemap.KNOWN_SHA1))
    for va in SETTERS:
        assert not dll.count(struct.pack("<I", va - 0x140000000)), f"0x{va:x} is in a build that has no proof"
    assert b"silent" in dll
