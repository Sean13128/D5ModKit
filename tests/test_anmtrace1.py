"""ANMTRACE1: the runtime's `anmtrace` / `actorprobe` commands (d5lib/native/d5anmtrace.inc.c), offline.

1. host build (tools/proof_anmtrace.py's HOST stand-ins): the commands against a fake image -- every site hooked and
   put back byte for byte (sha256 of the code pages), refusals, a prologue mismatch skipping one hook, the handlers'
   log lines and the guard verdict, the probe's per-frame lines;
2. every log line kind parsed by d5lib/anmtrace.py;
3. the prologue signatures on the pinned exe (and a flip), the Unicorn site proof normal and --abi.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))
sys.path.insert(0, str(KIT / "tools"))

from d5lib import anmtrace  # noqa: E402

SITES = {"lookup": 0x301240, "bank": 0x3FFCB0, "setup": 0x14E7E0, "create": 0x14DFD0, "seek": 0x2F28C0}


@pytest.fixture(scope="module")
def proof():
    import proof_anmtrace
    return proof_anmtrace


@pytest.fixture(scope="module")
def host(proof, tmp_path_factory):
    import subprocess
    try:
        exe = proof.build_host(tmp_path_factory.mktemp("anm"))
    except RuntimeError as exc:
        if "No module named ziglang" in str(exc):
            pytest.skip("no Zig compiler (pip install ziglang)")
        raise

    def run(*cmds, scenario=()):
        words = []
        for c in cmds:
            words += c.split() + [","]
        out = subprocess.run([str(exe), *scenario, "--", *words[:-1]], capture_output=True, text=True,
                             check=True).stdout.splitlines()
        r = {"replies": [json.loads(x[6:]) for x in out if x.startswith("REPLY ")],
             "log": [x[4:] for x in out if x.startswith("LOG ")],
             "sites": {x.split()[1]: x.split()[2] for x in out if x.startswith("SITE ")},
             "v": {x.split()[1]: int(x.split()[2]) for x in out if x.startswith("V ")}}
        r["inflight"], r["protect"] = (int(w) for w in out[-1].split()[1::2])
        return r
    return run


def test_guard_hooks_every_site_and_off_puts_the_bytes_back(host, tmp_path):
    a, b, c = (tmp_path / n for n in ("before", "on", "after"))
    r = host(f"dump {a}", "anmtrace guard", "sites", f"dump {b}", "anmtrace off", "sites", f"dump {c}")
    on, off = r["replies"]
    assert on == {"ok": 1, "mode": "guard", "hooks": {k: "on" for k in SITES}}
    assert off == {"ok": 1, "mode": "off", "hooks": {k: "off" for k in SITES}}
    sha = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (a, b, c)}
    assert sha["before"] == sha["after"] != sha["on"]                     # off = the original code pages
    diff = sum(x != y for x, y in zip(a.read_bytes(), b.read_bytes()))
    assert diff <= 25                                                      # 5 sites x jmp rel32
    assert r["log"][0] == "[anmtrace] state mode=guard lookup=1 bank=1 setup=1 create=1 seek=1"
    assert r["log"][1] == "[anmtrace] state mode=off lookup=0 bank=0 setup=0 create=0 seek=0"


def test_nothing_is_written_before_on_or_on_another_build(host):
    r = host("anmtrace status", "anmtrace", "sites")
    assert r["replies"][0]["mode"] == "off" and r["protect"] == 0 and r["log"] == []
    assert all(not s.startswith("e9") for s in r["sites"].values())
    r = host("anmtrace on", "sites", scenario=("badts",))
    assert r["replies"][0] == {"error": "refused", "reason": "unsupported game build (PE timestamp)"}
    assert r["protect"] == 0 and all(not s.startswith("e9") for s in r["sites"].values())
    assert "usage" in host("anmtrace nope")["replies"][0]["error"]


def test_a_prologue_mismatch_skips_that_hook_only(host):
    r = host("anmtrace on", "sites", scenario=(f"flip={SITES['setup'] + 9:X}",))
    hooks = r["replies"][0]["hooks"]
    assert hooks["setup"] == "prologue mismatch" and [k for k, v in hooks.items() if v == "on"] == \
        ["lookup", "bank", "create", "seek"]
    assert not r["sites"]["setup"].startswith("e9") and r["sites"]["seek"].startswith("e9")
    assert "[anmtrace] skip hook=setup rva=0x14E7E0 reason=prologue" in r["log"]


def test_handlers_log_each_kind_and_guard_skips_only_a_null_seek(host):
    r = host("anmtrace guard", "handlers")
    assert r["v"] == {"lookup_miss": 0, "lookup_hit": 0, "bank": 0, "setup": 0, "create": 0, "seek_null": 1,
                      "seek_ok": 0, "seek_noplayer": 0}
    ev = [anmtrace.parse_line(x) for x in r["log"][1:]]
    assert [d["event"] for d in ev] == ["miss", "bank", "setup", "create", "nullseek"]   # no line for a hit / ok seek
    miss, bank, setup, create, seek = ev
    assert miss["id"] == 643 and miss["caller"] == 0x3FFCE1
    assert bank["id"] == 643 and bank["flag"] == 0 and bank["arg"] == 1 and bank["slot"] == -1
    assert (setup["slot"], setup["anim"], setup["palette"], setup["motion"], setup["kind"], setup["alt"]) == \
        (3, 643, 0, 1007, 1, 645)
    assert (create["anim"], create["palette"], create["motion"], create["kind"]) == (643, 0, 1007, 1)  # shorts
    assert seek["group"] == 643 and seek["motion"] == 1007 and seek["guard"] == 1 and seek["frame"] == 12
    assert r["inflight"] == 0


def test_trace_mode_logs_a_null_seek_but_lets_it_through_and_off_logs_nothing(host):
    r = host("anmtrace on", "handlers")
    assert r["v"]["seek_null"] == 0 and anmtrace.parse_line(r["log"][-1])["guard"] == 0
    r = host("handlers")
    assert r["v"]["seek_null"] == 0 and r["log"] == []


def test_actorprobe_logs_one_line_per_frame_for_n_frames(host):
    r = host("actorprobe 3 2", "tick 3")
    assert r["replies"] == [{"ok": 1, "slot": 3, "frames": 2}]
    start, *samples = [anmtrace.parse_line(x) for x in r["log"]]
    assert start["event"] == "start" and len(samples) == 2 and [s["n"] for s in samples] == [0, 1]
    s = samples[0]
    want = {"anm": 643, "loader": -1, "pend_anm": -1, "pend_motion": -1, "kind": 1, "vis": 1, "draw": 0,
            "o_group": 643, "o_motion": 1007, "o_palette": 0, "tick": 49 << 16, "step30": 0x10000, "step40": -1,
            "held": 0, "palette": 0, "pslot": 7, "rec": 643, "npal": 1, "ntex": 2, "motion": 1007}
    assert {k: s[k] for k in want} == want and s["tick_frames"] == 49.0
    r = host("noplayer", "actorprobe 3 1", "tick 1")
    assert anmtrace.parse_line(r["log"][-1])["player"] == "none"
    for bad in ("actorprobe", "actorprobe 3", "actorprobe 256 5", "actorprobe 3 0"):
        assert "usage" in host(bad)["replies"][0]["error"]
    assert host("actorprobe 3 9", "actorprobe off", "tick 2")["log"] == ["[actorprobe] start slot=3 frames=9"]


def test_reader_parses_a_real_log_tail(tmp_path):
    p = tmp_path / "d5auto.log"
    p.write_text("13:00:00.001 d5auto loaded (game base 0000000140000000)\n"
                 "13:00:01.002 [anmtrace] miss id=643 caller=0x3ffce1\n"
                 "13:00:01.003 [actorprobe] sample slot=12 frame=5 n=0 actor=none\n")
    rows = anmtrace.read(p)
    assert [(d["src"], d["event"], d["time"]) for d in rows] == [("anmtrace", "miss", "13:00:01.002"),
                                                                  ("actorprobe", "sample", "13:00:01.003")]
    assert anmtrace.read(p, src="anmtrace")[0]["id"] == 643 and rows[1]["actor"] == "none"


# ---------------------------------------------------------------- exe bytes
@pytest.fixture(scope="module")
def pinned():
    from test_recruit_runtime import pinned_exe
    if pinned_exe() is None:
        pytest.skip("the pinned exe is not on this machine")
    return Path(pinned_exe()).read_bytes()


def test_signatures_match_the_pinned_exe_and_a_flip_fails(proof, pinned):
    hooks = proof.c_hooks(proof.SRC.read_text())
    assert [(n, rva) for n, rva, _, _ in hooks] == list(SITES.items())
    assert proof.check_signatures(pinned, hooks)["ok"]
    _, _, secs = proof.sections(pinned)
    rva = SITES["seek"] + 7
    off = next(ro + rva - va for _, va, vs, rs, ro in secs if va <= rva < va + max(vs, rs))
    bad = bytearray(pinned)
    bad[off] ^= 1
    s = proof.check_signatures(bytes(bad), hooks)
    assert [r["hook"] for r in s["signatures"] if not r["match"]] == ["seek"]


@pytest.mark.parametrize("abi", [[], ["--abi"]])
def test_site_proof(proof, pinned, abi, tmp_path):
    assert proof.main(abi + ["--out", str(tmp_path / "r.json")]) == 0
