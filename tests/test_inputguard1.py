"""INPUTGUARD1: under [debug] remote=1 the real keyboard, mouse and pads never reach the game (d5inputguard.h).

tools/proof_inputguard.py runs the game's own input functions (pinned exe) against the compiled hooks: remote=0
must equal vanilla, the guard must drop real pad / key / joystick input and keep injected keys, normal and --abi;
each negative control (guard removed from one path, guard always on) must fail.
"""
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "tools"))
sys.path.insert(0, str(KIT / "tests"))

from test_recruit_runtime import pinned_exe  # noqa: E402

pytestmark = pytest.mark.skipif(not pinned_exe(), reason="no pinned exe on this machine")


@pytest.fixture(scope="module")
def proof():
    pytest.importorskip("ziglang")
    import proof_inputguard
    return proof_inputguard


@pytest.fixture(scope="module")
def exe():
    return Path(pinned_exe()).read_bytes()


@pytest.mark.parametrize("abi", [False, True])
def test_guard_on_real_input_paths(proof, exe, abi):
    r = proof.prove(exe, abi)
    assert r["ok"], [v for v in r["verdicts"] if not v["ok"]]


@pytest.mark.parametrize("mutation, fails", [("no-pad-guard", {"pad"}), ("no-joy-guard", {"joy"}),
                                             ("guard-always", {"pad", "keys", "joy"})])
def test_negative_controls_fail(proof, exe, mutation, fails):
    r = proof.prove(exe, False, mutation)
    assert {v["path"] for v in r["verdicts"] if not v["ok"]} == fails


def test_static_slots_and_cooperative_levels(proof, exe):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _, translate = proof.build_proof_dll(exe, td)
    s = proof.static_checks(exe, translate)
    assert s["ok"], s["rows"]


def test_the_guard_adds_no_hook():
    native = KIT / "d5lib" / "native"
    assert "patch_slot" not in (native / "d5inputguard.h").read_text()
    assert "write_code" not in (native / "d5inputguard.h").read_text()
