"""WINHIDE1: `win offscreen|hide|show|state` (d5winhide.h): the Win32 call sequence against a stub windows.h, and
the wiring in d5ctl.inc.c.  What the real game window does under Wine cannot be shown offline."""
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent
NATIVE = KIT / "d5lib" / "native"
STUB = KIT / "tests" / "winhide_stub"


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    pytest.importorskip("ziglang")
    exe = tmp_path_factory.mktemp("wh") / "driver"
    subprocess.run([sys.executable, "-m", "ziglang", "cc", "-I", str(STUB), "-I", str(NATIVE), "-o", str(exe),
                    str(STUB / "driver.c")], check=True)
    return subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout


def test_call_sequence(out):
    flags = "flags=215"                                   # 0x215 = NOSIZE | NOZORDER | NOACTIVATE | NOOWNERZORDER: no resize, no focus
    assert "null:0" in out
    assert '{"mode":0,"visible":1,"iconic":0,"x":100,"y":50,"w":1280,"h":720}' in out
    assert f"SetWindowPos 3920 0 0 0 {flags}" in out       # default: right of the 1920-wide virtual screen
    assert f"SetWindowPos -5000 10 0 0 {flags}" in out
    assert f"SetWindowPos 100 50 0 0 {flags}" in out       # show returns to the first position, not the second
    assert out.count("ShowWindow 0") == 1                  # SW_HIDE exactly once; never a minimise (6)
    assert "ShowWindow 6" not in out and "ShowWindow 2" not in out
    assert "ShowWindow 8" in out                           # SW_SHOWNA: shown without taking focus
    assert out.count('{"ok":1,"mode":0}') == 3             # show, show, show again: idempotent
    assert '"error":"win offscreen' in out


def test_wired_into_the_runtime():
    ctl = (NATIVE / "d5ctl.inc.c").read_text()
    assert '!strcmp(c, "win")' in ctl and "winhide_cmd(g_hwnd" in ctl
    assert "g_wh_mode" in ctl.split("find_game_window")[1][:400], "a hidden window must still be found"
    guard = ctl.split('"input_guard")')[1][:300]
    assert "winhide_cmd" in guard, "set input_guard 0 (Sean plays) puts the window back"
    assert '#include "d5winhide.h"' in (NATIVE / "d5auto.c").read_text()


def test_core_builds_with_it():
    pytest.importorskip("ziglang")
    from d5lib import runtime
    assert runtime.build_core(log=lambda _m: None)[:2] == b"MZ"
