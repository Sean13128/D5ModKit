"""WRITEWATCH1: the runtime's software write-watch (d5lib/native/d5wwatch.inc.c), offline parts.

1. the page/range maths and the hex helper, built for this machine (Zig) from the same source (WW_HOST_ONLY);
2. the log lines exactly as the C format strings print them, read back by d5lib/wwatch.py;
3. wiring: the command is reachable only from the remote pipe's command loop, nothing arms the watch at load, and the
   unload path removes it.
What only Wine can answer (page faults, the trap flag under CrossOver/Rosetta) is the live `watch selftest`.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
from d5lib import wwatch  # noqa: E402

NATIVE = KIT / "d5lib" / "native"
SRC = (NATIVE / "d5wwatch.inc.c").read_text()

HOST = r"""
#include <stdio.h>
#include <string.h>
#define WW_HOST_ONLY
/*SRC*/
int main(int argc, char **argv) {
    unsigned long long cases[][3] = {{0x147B59E30ull, 8, 0x1000}, {0x147B59FFCull, 8, 0x1000},
                                     {0x147B59000ull, 1, 0x1000}, {0x147B59FFFull, 1, 0x1000},
                                     {0x147B5A000ull, 64, 0x1000}, {0x147B59FC1ull, 64, 0x1000}};
    for (int i = 0; i < 6; i++) {
        unsigned long long pg, n;
        ww_span(cases[i][0], cases[i][1], cases[i][2], &pg, &n);
        printf("SPAN %llx %llx %llx %llx\n", cases[i][0], cases[i][1], pg, n);
    }
    unsigned long long lo = 0x147B59E30ull;
    long long offs[] = {-65, -64, -1, 0, 7, 8, 100};
    for (int i = 0; i < 7; i++) printf("NEAR %lld %d\n", offs[i], ww_is_near(lo + offs[i], lo, 8));
    unsigned char b[4] = {0x60, 0x00, 0x41, 0xff};
    char h[16];
    int k = ww_hex(h, sizeof h, b, 4);
    printf("HEX %s %d\n", h, k);
    k = ww_hex(h, 5, b, 4);
    printf("HEXCAP %s %d\n", h, k);
    return 0;
}
"""


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    d = tmp_path_factory.mktemp("ww")
    (d / "t.c").write_text(HOST.replace("/*SRC*/", SRC))
    exe = d / "t"
    r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-O1", "-w", "-o", str(exe), str(d / "t.c")],
                       capture_output=True, text=True)
    if r.returncode:
        if "No module named ziglang" in r.stderr:
            pytest.skip("no Zig compiler (pip install ziglang)")
        raise RuntimeError(r.stderr[-3000:])
    return subprocess.run([str(exe)], capture_output=True, text=True, check=True).stdout.splitlines()


def test_span_covers_the_range_in_whole_pages(host):
    spans = [tuple(int(w, 16) for w in ln.split()[1:]) for ln in host if ln.startswith("SPAN")]
    assert spans == [
        (0x147B59E30, 8, 0x147B59000, 0x1000),
        (0x147B59FFC, 8, 0x147B59000, 0x2000),       # straddles: both pages
        (0x147B59000, 1, 0x147B59000, 0x1000),
        (0x147B59FFF, 1, 0x147B59000, 0x1000),
        (0x147B5A000, 64, 0x147B5A000, 0x1000),
        (0x147B59FC1, 64, 0x147B59000, 0x2000),
    ]
    for a, n, pg, pn in spans:                       # the property, not only the table
        assert pg <= a and a + n <= pg + pn and pg % 0x1000 == 0 and pn % 0x1000 == 0
        assert pn - 0x1000 < (a + n) - pg            # no page more than needed


def test_near_window_is_64_below_to_the_end(host):
    near = {int(ln.split()[1]): int(ln.split()[2]) for ln in host if ln.startswith("NEAR")}
    assert near == {-65: 0, -64: 1, -1: 1, 0: 1, 7: 1, 8: 0, 100: 0}


def test_hex_helper_respects_its_buffer(host):
    assert "HEX 600041ff 8" in host
    assert "HEXCAP 6000 4" in host                   # cap 5: two bytes + NUL, never past the buffer


def _c_to_py(fmt: str) -> str:
    return re.sub(r"%(-?\d*)(?:ll|l|z)?([xdu])", r"%\1\2", fmt).replace("%.2f", "%.2f")


def _formats():
    """every logf_ format string of the record writer, in order"""
    body = SRC[SRC.index("static void ww_record"):SRC.index("static void ww_protect")]
    return [re.sub(r'"\s*"', "", m) for m in re.findall(r'logf_\(("(?:[^"\\]|\\.)*"(?:\s*"(?:[^"\\]|\\.)*")*)', body)]


def test_log_lines_as_printed_parse_back():
    fmts = [_c_to_py(f.strip('"')) for f in _formats()]
    assert len(fmts) == 4 and fmts[0].startswith("[wwatch] %s n=")
    change = fmts[0] % ("change", 1, 4242, 77, "1400a1b2c", 0x147B59E30, 0, "48890d" + "00" * 13,
                        "6000410100000000", "0aff30080aff3409")
    regs = fmts[1] % ((1,) + tuple(range(0x10, 0x20)) + (0x246,))
    stack = fmts[2] % (1, " 1400a1b2c 14011aa00 d5core.dll+1234")
    raw = fmts[3] % (1, 0x22f000, "".join(f" {i:x}" for i in range(64)))
    near = fmts[0] % ("near", 2, 4242, 77, "1400a1b2c", 0x147B59E28, -8, "00" * 16, "6000410100000000", "-")
    text = "\n".join("10:00:00.000 " + x for x in (change, regs, stack, raw, near, "10:00:01.000 [wwatch] off faults=3"))
    recs = wwatch.records(text)
    assert [r["kind"] for r in recs] == ["change", "near"]
    r = recs[0]
    assert r["rip"] == "1400a1b2c" and r["addr"] == "147b59e30" and r["old"] == "6000410100000000"
    assert r["new"] == "0aff30080aff3409" and r["frame"] == "4242"
    assert r["regs"]["rax"] == 0x10 and r["regs"]["r15"] == 0x1f and r["regs"]["rflags"] == 0x246
    assert r["stack"] == ["1400a1b2c", "14011aa00", "d5core.dll+1234"]
    assert r["rsp"] == 0x22f000 and len(r["raw"]) == 64 and r["raw"][63] == 63
    assert recs[1]["off"] == "-8" and recs[1]["new"] == "-"


def test_command_wiring_and_off_by_default():
    ctl = (NATIVE / "d5ctl.inc.c").read_text()
    auto = (NATIVE / "d5auto.c").read_text()
    assert '#include "d5wwatch.inc.c"' in auto
    assert re.search(r'!strcmp\(c, "watch"\)\) \{[^}]*ctl_watch\(o, argc, argv\);', ctl)
    stop = ctl[ctl.index("static void ctl_stop(void)"):]
    assert "ww_off();" in stop[:stop.index("\n}\n")]
    # ww_arm is reached only from the command (and its selftest); no boot path, no ini switch
    callers = [m.start() for m in re.finditer(r"\bww_arm\(", SRC)]
    fn_of = [SRC.rfind("\nstatic ", 0, p) for p in callers]
    names = {re.match(r"\nstatic [\w \*]*?(\w+)\(", SRC[i:]).group(1) for i in fn_of}
    assert names == {"ww_arm", "ww_selftest", "ctl_watch"}
    assert "ww_" not in auto.replace('#include "d5wwatch.inc.c"', "")
    # the command loop it hangs off runs only with [debug] remote=1
    tick = ctl[ctl.index("static void ctl_tick(void)"):]
    assert tick.index("if (!g_remote) return;") < tick.index('"watch"')
