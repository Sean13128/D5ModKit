"""FACILITY1: the runtime's `facility` / `giveup` commands (d5lib/native/d5ctl.inc.c), offline.

1. host build: the FACILITY1 block of d5ctl.inc.c is cut out and compiled for this machine (Zig) with stand-ins
   for the runtime around it (reply buffer, log) and for the two game calls; a fake image (signatures and PE
   timestamp copied in) lets every argument parse and every refusal path run for real;
2. the signatures against the pinned exe (and a one-byte mutation that must fail), via tools/proof_facility.py;
3. the Unicorn site-entry proof (normal and --abi) on the pinned exe;
4. tools/d5ctl.py's Ctl.facility / Ctl.giveup raise with the runtime's reason.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tests"))
SRC = KIT / "d5lib" / "native" / "d5ctl.inc.c"

HOST = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
typedef int LONG; typedef unsigned int DWORD; typedef unsigned short WORD;
typedef struct { char pad[0x3C]; int e_lfanew; } IMAGE_DOS_HEADER;
typedef struct { DWORD Signature; struct { WORD m; WORD n; DWORD TimeDateStamp; } FileHeader; } IMAGE_NT_HEADERS64;
typedef struct { char *p; size_t n, cap; } SB;
static void sbf(SB *s, const char *fmt, ...);
static void sb_str(SB *s, const char *t) { sbf(s, "\"%s\"", t); }
#include <stdarg.h>
static void sbf(SB *s, const char *fmt, ...) {
    va_list a; va_start(a, fmt); s->n += vsnprintf(s->p + s->n, s->cap - s->n, fmt, a); va_end(a);
}
static unsigned char *g_base; static volatile LONG g_frame;
static int readable(const void *p, size_t n) { (void)p; (void)n; return 1; }
static void logf_(const char *f, ...) { (void)f; }
#define _stricmp strcasecmp
static int menu_calls[8], n_menu, n_script;
#define FAC_CALL_MENU_OPEN(id) (menu_calls[n_menu++] = (id), 1LL)
#define GU_CALL_SCRIPT(id, out) (n_script++, (id) == 2013 ? 7 : -1)
#define IMAGE_SIZE 0x7C00000
/*BLOCK*/
static void put32(unsigned rva, int v) { memcpy(g_base + rva, &v, 4); }
static void put64(unsigned rva, unsigned long long v) { memcpy(g_base + rva, &v, 8); }
static int get32(unsigned rva) { int v; memcpy(&v, g_base + rva, 4); return v; }
int main(int argc, char **argv) {
    g_base = calloc(1, IMAGE_SIZE);
    put32(0x3C, 0x100); put32(0x108, (int)FAC_TIMESTAMP);
    for (int i = 0; i < 4; i++) memcpy(g_base + FAC_SIGS[i].rva, FAC_SIGS[i].b, FAC_SIGS[i].n);
    for (int i = 0; i < 3; i++) memcpy(g_base + GU_SIGS[i].rva, GU_SIGS[i].b, GU_SIGS[i].n);
    /* the scenario: words before "--" set memory, the rest is the command line */
    unsigned M = 0x7000000, P = 0x7100000, B = 0x7200000, BM = 0x7300000;   /* fake objects inside the image */
    int i = 1;
    int base = 1, flags = 1, battle = 0, guide = 0, target = 0, talk = 0;
    for (; i < argc && strcmp(argv[i], "--"); i++) {
        if (!strcmp(argv[i], "nobase")) base = 0;
        else if (!strcmp(argv[i], "noflags")) flags = 0;
        else if (!strcmp(argv[i], "battle")) battle = 1;
        else if (!strcmp(argv[i], "badts")) put32(0x108, 1);
        else if (!strncmp(argv[i], "flip=", 5)) g_base[strtoul(argv[i] + 5, 0, 16)] ^= 1;
        else if (!strncmp(argv[i], "busy", 4)) put32(P + 0x14, 1);
        else if (!strcmp(argv[i], "target")) target = 1;
        else if (!strcmp(argv[i], "talk")) talk = 1;
        else if (!strncmp(argv[i], "pending", 7)) put32(M, 36);
        else if (!strncmp(argv[i], "guide", 5)) guide = 1;
        else if (!strncmp(argv[i], "sub=", 4)) put32(B + 0x14, atoi(argv[i] + 4));
        else if (!strncmp(argv[i], "queued", 6)) g_base[BM + 0xB5] = 1;
    }
    if (base) {
        put64(FAC_TASK_MANAGER, (unsigned long long)(g_base + M)); put64(FAC_POCKET, (unsigned long long)(g_base + P));
        if (get32(M) == 0) put32(M, -1);
        put32(M + 4, 13); put32(P + 0xB0, target ? 0 : -1); put32(P + 0xB8, talk ? 5 : -1);
    }
    if (flags) memset(g_base + FAC_FLAGS + 9600 / 8, 0xFF, (14100 - 9600) / 8);
    g_base[FAC_GUIDE_BYTE] = guide;       /* it lies inside that range of the flag bitmap (ids 10000..) */
    if (battle) {
        put64(GU_BATTLE, (unsigned long long)(g_base + B)); put64(B, (unsigned long long)(g_base + GU_BATTLE_VT));
        put64(GU_BM, (unsigned long long)(g_base + BM)); g_base[GU_BM_ALIVE] = 1;
        if (!get32(B + 0x14)) put32(B + 0x14, 2);
        put32(BM + 0xC0610, 0); g_base[GU_BITS_A] = 0xFF; g_base[FAC_GUIDE_BYTE] |= 0x04;
    }
    char out[8192]; SB o = {out, 0, sizeof out}; out[0] = 0;
    char *av[8]; int ac = 0;
    for (i++; i < argc && ac < 8; i++) av[ac++] = argv[i];
    if (!strcmp(av[0], "giveup")) ctl_giveup(&o); else ctl_facility(&o, ac, av);
    printf("{\"reply\":%s,\"menu\":[", out);
    for (int k = 0; k < n_menu; k++) printf("%s%d", k ? "," : "", menu_calls[k]);
    printf("],\"script\":%d,\"pending\":%d,\"guide\":%d,\"shop\":%d,\"restore\":%d,\"bm_n\":%d,\"bm0\":%d,"
           "\"bm_b5\":%d,\"lose\":%d,\"bits\":%d}\n", n_script, base ? get32(M) : 0, g_base[FAC_GUIDE_BYTE],
           g_base[FAC_SHOP_MODE], g_fac.on, get32(BM + 0x80), get32(BM), g_base[BM + 0xB5], get32(BM + 0xC0610),
           g_base[GU_BITS_A]);
    return 0;
}
"""


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    src = SRC.read_text()
    block = src[src.index("/* ------------------------------------------------------------------ facility / giveup"):
                src.index("/* ------------------------------------------------------------------ command dispatch")]
    d = tmp_path_factory.mktemp("fac")
    (d / "t.c").write_text(HOST.replace("/*BLOCK*/", block))
    exe = d / "t"
    r = subprocess.run([sys.executable, "-m", "ziglang", "cc", "-O1", "-w", "-o", str(exe), str(d / "t.c")],
                       capture_output=True, text=True)
    if r.returncode:
        if "No module named ziglang" in r.stderr:
            pytest.skip("no Zig compiler (pip install ziglang)")
        raise AssertionError(r.stderr[-3000:])

    def run(*words, scenario=()):
        out = subprocess.run([str(exe), *scenario, "--", *words], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)
    return run


def test_list_names_all_eighteen_in_cryswars_order(host):
    r = host("facility", "list")["reply"]
    names = [f["name"] for f in r["facilities"]]
    assert len(names) == 18 and len(set(names)) == 18
    assert names[0] == "equipment_shop" and names[14] == "recruiter" and names[17] == "carnage_dimension_guide"
    assert host("facility")["reply"]["facilities"][14]["route"] == 36


def test_top_level_facility_writes_the_pending_task(host):
    r = host("facility", "recruiter")
    assert r["reply"] == {"ok": 1, "facility": "recruiter", "index": 14, "route": 36, "kind": "top"}
    assert r["pending"] == 36 and r["menu"] == []


def test_a_facility_by_index_and_case_insensitive_name(host):
    assert host("facility", "4")["reply"]["facility"] == "quest_shop"
    assert host("facility", "Quest_Shop")["reply"]["facility"] == "quest_shop"


def test_nested_facility_calls_menu_open_with_its_route(host):
    r = host("facility", "skill_shop")
    assert r["reply"]["kind"] == "nested" and r["menu"] == [140] and r["pending"] == -1


def test_shop_sets_its_selector_and_waits_to_restore_it(host):
    r = host("facility", "item_shop")
    assert r["menu"] == [50] and r["shop"] == 0x40 and r["restore"] == 1


def test_guide_sets_the_carnage_bit_and_queues_the_world_map(host):
    r = host("facility", "carnage_dimension_guide")
    assert r["pending"] == 9 and r["guide"] & 1 and r["restore"] == 1, r


@pytest.mark.parametrize("words,scenario,reason", [
    (("facility", "nope"), (), "no facility nope"),
    (("facility", "18"), (), "no facility 18"),
    (("facility", "recruiter"), ("badts",), "unsupported game build"),
    (("facility", "recruiter"), ("flip=18AE24",), "signature mismatch at rva 0x18AE20"),
    (("facility", "recruiter"), ("noflags",), "native unlock flag not set"),
    (("facility", "recruiter"), ("nobase",), "not in the Pocket Netherworld"),
    (("facility", "recruiter"), ("pending",), "not idle (task manager)"),
    (("facility", "skill_shop"), ("busy",), "a facility is open or transitioning"),
    (("facility", "carnage_dimension_guide"), ("guide",), "guide context already active"),
    (("giveup",), (), "not in a battle"),
    (("giveup",), ("battle", "sub=28"), "turn runner is active"),
    (("giveup",), ("battle", "sub=42"), "dispatcher"),
    (("giveup",), ("battle", "queued"), "already pending"),
    (("giveup",), ("battle", "flip=620E30"), "signature mismatch at rva 0x620E28"),
])
def test_refusals_name_the_reason_and_change_nothing(host, words, scenario, reason):
    r = host(*words, scenario=scenario)
    assert "error" in r["reply"] and reason in json.dumps(r["reply"])
    assert r["menu"] == [] and r["script"] == 0 and r["restore"] == 0 and r["bm_n"] == 0
    assert r["pending"] in (-1, 0, 36)


def test_giveup_takes_the_s4_yes_path_and_queues_the_dispatcher(host):
    r = host("giveup", scenario=("battle",))
    assert r["reply"] == {"ok": 1, "substate": 2, "script": 7}
    assert r["script"] == 1 and r["lose"] == 2                      # script 2013, restore mode 2 (progress lost)
    assert r["bm_n"] == 1 and r["bm0"] == 9001 and r["bm_b5"] == 1   # {9001, 1} queued, pending
    assert r["bits"] == 0xFB and not r["guide"] & 4                  # the two world-map bits cleared


# ---------------------------------------------------------------- exe bytes
@pytest.fixture(scope="module")
def proof():
    from test_recruit_runtime import pinned_exe
    if pinned_exe() is None:
        pytest.skip("the pinned exe is not on this machine")
    import proof_facility
    return proof_facility


sys.path.insert(0, str(KIT / "tools"))


def test_signatures_match_the_pinned_exe_and_a_flip_fails(proof):
    from test_recruit_runtime import pinned_exe
    fac, gu, _ = proof.c_tables(SRC.read_text())
    data = Path(pinned_exe()).read_bytes()
    assert proof.check_signatures(data, fac, gu)["ok"]
    rva = 0x18AE24
    _, _, secs = proof.sections(data)
    off = next(ro + rva - va for _, va, vs, rs, ro in secs if va <= rva < va + max(vs, rs))
    bad = bytearray(data)
    bad[off] ^= 1
    s = proof.check_signatures(bytes(bad), fac, gu)
    assert not s["ok"] and [r["rva"] for r in s["signatures"] if not r["match"]] == ["0x18AE20"]


@pytest.mark.parametrize("abi", [[], ["--abi"]])
def test_site_entry_proof(proof, abi, tmp_path):
    assert proof.main(abi + ["--out", str(tmp_path / "r.json")]) == 0


# ---------------------------------------------------------------- tools/d5ctl.py
def test_ctl_helpers_raise_with_the_runtimes_reason():
    import importlib.util                     # by path: other tests put a stand-in d5ctl in sys.modules
    spec = importlib.util.spec_from_file_location("d5ctl_facility1", KIT / "tools" / "d5ctl.py")
    d5ctl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d5ctl)
    c = object.__new__(d5ctl.Ctl)
    c.raw = lambda line: json.dumps({"error": "refused", "reason": "native unlock flag not set"})
    with pytest.raises(RuntimeError, match="native unlock flag not set"):
        c.facility("recruiter")
    c.raw = lambda line: json.dumps({"ok": 1, "facility": "recruiter"} if line.startswith("facility")
                                    else {"ok": 1, "substate": 2})
    assert c.facility("recruiter")["facility"] == "recruiter" and c.giveup()["ok"]


def test_an_idle_refusal_reports_what_the_idle_test_read(host):
    r = host("facility", "recruiter", scenario=("pending",))["reply"]
    assert r["manager"] == [36, 13, 0, 0] and r["base"] == [0, 0, -1, -1]
    r = host("facility", "skill_shop", scenario=("busy",))["reply"]
    assert r["base"][0] == 1


def test_an_npc_in_talk_range_is_not_busy_but_a_running_talk_is(host):
    # FACILITY1 run 3: right after a load the base read [0, 0, 0, -1]: +0xB0 = talk target (actor 0 in range)
    r = host("facility", "recruiter", scenario=("target",))
    assert r["reply"]["ok"] == 1 and r["pending"] == 36
    r = host("facility", "recruiter", scenario=("talk",))
    assert "not idle" in r["reply"]["reason"] and r["pending"] == -1
