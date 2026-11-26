"""LONGTAIL2 offline proof: Baal Slave (DD2 640 "Basic Principles", row 26307 = nullify_dealt + alias to D5's Softening Aura 2072)
through the pinned game's REAL code: the kit's wrap_nullify at the game's own call site 0x1401BF0F0 (compute_target) runs the game's
real damage_nullify_predicate (0x1401FE0D0, including its Softening Aura 2072 test and every other id it reads), then the kit's rows.

  half 1  "won't be targeted by allies": the holder (alias 2072 in its list) is the DEFENDER; the game's own code nullifies a hit by a unit of
          its side (the pinned exe is the control: same answer without the kit)
  half 2  "won't target allies when attacking": the holder is the ATTACKER; the kit's nullify_dealt row nullifies a hit with positive damage on
          a unit that the game's ally relation (events_env_team_of + cmdmenu_preds_p_2d8e00) puts on its side

<unicorn python> evility/offline_proof_longtail2_baal.py [--abi] [--control NAME]
Controls (a deliberately broken build; the proof must then FAIL): bl-v, bl-ally, bl-side, bl-id, bl-align (needs --abi)

Not covered: the six other call sites of the predicate the kit redirects (same wrapper, other return addresses), the redirected callers' own
use of the answer, a live battle, the charm / mind-control branch of events_env_team_of (stat record +1263 / +3614: not set in the fixtures).
"""
import argparse
import hashlib
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(KIT), str(KIT / "tools"), str(KIT / "evility")]
from d5lib import evility as ev                                  # noqa: E402
import stat_oracle as so                                         # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA        # noqa: E402

SCRATCH = Path("/Volumes/Data/ai-tmp/claude/longtail2")
SITES = (0x1401BF0F0, 0x1401BF6DD, 0x1401C0A30, 0x14060B657)      # the four redirected callers of damage_nullify_predicate
BAAL, SOFT = 26307, 2072
ROWS = {
    BAAL: {"family": "nullify_dealt"},
    26308: {"family": "nullify_dealt", "conditions": [{"kind": "hp_below", "id": 50}]},     # a row with a condition on the attacker
    26309: {"family": "nullify"},                                                          # a plain nullify row on a defender
}


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        "bl-v": ("    cmp qword ptr [rsp + 0xA8], 0     // v: the hit's damage\n    jle .n_ret\n    mov rcx, qword ptr [rsp + 0x40]   // A rec\n    mov rdx",
                 "    mov rcx, qword ptr [rsp + 0x40]   // A rec\n    mov rdx"),
        "bl-ally": ("    mov ecx, esi\n    call 0x1402d8e00                  // cmdmenu_preds_p_2d8e00(A's team, D's team): does the defender count as an ally\n    test al, al\n    jz .n_ret\n    mov r14d, 1",
                    "    mov ecx, esi\n    mov r14d, 1"),
        "bl-side": ("    mov rsi, qword ptr [rcx + 0x240]  // the attacker's unit record: the holder", "    mov rsi, qword ptr [rdx + 0x240]  // the attacker's unit record: the holder"),
        "bl-id": ("    mov rdi, 0x40000000000            // nullify_dealt: second-word bit 10", "    mov rdi, 0x20000000000"),
    }
    if control == "bl-align":      # a 0x38 frame: every call inside wrap_nullify is made with rsp 8 off a 16-byte boundary
        a = text.index("wrap_nullify:")
        b = text.index("// wrap_counter(rcx = attacker rec", a)
        w = text[a:b].replace("sub rsp, 0x40", "sub rsp, 0x38").replace("add rsp, 0x40", "add rsp, 0x38")
        out = SCRATCH / f"d5evil-longtail2-{control}.inc.asm"
        out.write_text(text[:a] + w + text[b:])
        return out
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f"d5evil-longtail2-{control}.inc.asm"
    out.write_text(text.replace(old, new))
    return out


def run(e, site, *, attacker, defender, a_team=0, d_team=0, damage=100, hp=1000, abi=False, section=None):
    """-> 1 when the predicate answers 'nullified'.  attacker / defender = evility id tuples, teams = unit byte +0x2E32"""
    X, mu = e.X, e.mu
    e.brk = e.heap_mark

    def unit(ids, team, hp_=1000):
        u = bytearray(0x4800)
        ids = sorted(ids)
        struct.pack_into("<i", u, 0x3030, len(ids))
        for i, v in enumerate(ids):
            struct.pack_into("<i", u, 0x2F30 + 4 * i, v)
        struct.pack_into("<I", u, 0x4348, 0x28A)           # no stat record: nothing here reads one
        u[0x2E32] = team
        struct.pack_into("<q", u, 0x2CC8, hp_)
        struct.pack_into("<q", u, 0x2CD8, 1000)
        return e.alloc(u)

    def rec(u):
        r = bytearray(4704)
        struct.pack_into("<Q", r, 0x240, u)
        return e.alloc(r)

    a, d = rec(unit(attacker, a_team, hp)), rec(unit(defender, d_team))
    ctx = e.alloc(bytes(0x28000))
    rsp = so.STACK + 0x100000 - 0x200                          # at a CALL: 16-aligned, [rsp+0x20] / [rsp+0x28] = the stack arguments
    mu.mem_write(rsp + 0x20, struct.pack("<q", 0))              # tgt_i
    mu.mem_write(rsp + 0x28, struct.pack("<q", damage))         # v: the hit's damage
    mu.reg_write(X.UC_X86_REG_RSP, rsp)
    regs = {X.UC_X86_REG_RCX: a, X.UC_X86_REG_RDX: d, X.UC_X86_REG_R8: 0, X.UC_X86_REG_R9: ctx,
            X.UC_X86_REG_RBX: 0x1010, X.UC_X86_REG_RBP: 0x1111, X.UC_X86_REG_RSI: 0x2222, X.UC_X86_REG_RDI: 0x3333,
            X.UC_X86_REG_R12: 0x4444, X.UC_X86_REG_R13: 0x5555, X.UC_X86_REG_R14: 0x6666, X.UC_X86_REG_R15: 0x7777}
    for r, v in regs.items():
        mu.reg_write(r, v)
    for i in range(6, 16):
        mu.reg_write(getattr(X, f"UC_X86_REG_XMM{i}"), 0x1000 + i)
    bad, hooks, saved = [], [], {}
    import capstone
    from unicorn import UC_HOOK_CODE
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    nonvol = (X.UC_X86_REG_RBX, X.UC_X86_REG_RBP, X.UC_X86_REG_RSI, X.UC_X86_REG_RDI, X.UC_X86_REG_R12, X.UC_X86_REG_R13,
              X.UC_X86_REG_R14, X.UC_X86_REG_R15, X.UC_X86_REG_RSP)
    xmms = [getattr(X, f"UC_X86_REG_XMM{i}") for i in range(6, 16)]

    def code(uc, addr, size, _):
        if addr == site:
            saved.update({r: uc.reg_read(r) for r in nonvol + tuple(xmms)})
        elif addr == site + 5 and saved:
            for r, v in saved.items():
                if uc.reg_read(r) != v:
                    bad.append(f"register {r} changed across the redirected call")
        if abi and section and section[0] <= addr < section[1]:
            ins = next(md.disasm(bytes(uc.mem_read(addr, size)), addr))
            if ins.mnemonic == "call" and uc.reg_read(X.UC_X86_REG_RSP) % 16:
                bad.append(f"misaligned call at {addr:#x}")

    hooks.append(mu.hook_add(UC_HOOK_CODE, code))
    try:
        mu.emu_start(site, site + 5, count=3_000_000)
    finally:
        for h in hooks:
            mu.hook_del(h)
    assert not bad, bad
    return mu.reg_read(X.UC_X86_REG_RAX) & 0xFF


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--abi", action="store_true")
    ap.add_argument("--control")
    args = ap.parse_args()
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    patched = ev.build_patch(original, ROWS)
    info = ev.section_info(patched)
    tmp = Path(tempfile.mkdtemp(prefix="lt2-baal-", dir=str(SCRATCH)))
    (tmp / "kit.exe").write_bytes(patched)
    kit, game = so.Emu(exe_path=tmp / "kit.exe"), so.Emu(exe_path=ORIGINAL)
    section = (info["code"], info["base"] + len(info["data"]))
    site = SITES[0]
    around = tuple(range(1, 41))
    cases = [
        # --- the game as control
        ("pinned exe: an ally hits the Softening Aura holder: nullified (game's own half 1)", game, dict(attacker=(), defender=(SOFT,)), 1),
        ("pinned exe: an enemy hits the Softening Aura holder: not nullified", game, dict(attacker=(), defender=(SOFT,), a_team=1), 0),
        ("pinned exe: the holder of 2072 hits an ally: not nullified (D5 has no such rule)", game, dict(attacker=(SOFT,), defender=()), 0),
        ("pinned exe: a unit carrying the kit's row id means nothing to the game", game, dict(attacker=(BAAL,), defender=()), 0),
        # --- half 1, with the kit: unchanged
        ("kit: an ally hits the holder (2072 + row): nullified by the game's own code", kit, dict(attacker=(), defender=(SOFT, BAAL)), 1),
        ("kit: an enemy hits the holder: not nullified", kit, dict(attacker=(), defender=(SOFT, BAAL), a_team=1), 0),
        ("kit: an ally with no 2072 hits an unprotected unit: not nullified", kit, dict(attacker=(), defender=()), 0),
        ("kit: the real 2072 alone attacking an ally: unchanged (0)", kit, dict(attacker=(SOFT,), defender=()), 0),
        # --- half 2: the holder attacks
        ("kit: the holder hits an ally (same team 0): nullified", kit, dict(attacker=(SOFT, BAAL), defender=()), 1),
        ("kit: the holder hits an enemy (team 1): damage stays", kit, dict(attacker=(SOFT, BAAL), defender=(), d_team=1), 0),
        ("kit: the holder hits an enemy (team 5): damage stays", kit, dict(attacker=(SOFT, BAAL), defender=(), d_team=5), 0),
        ("kit: the holder (team 0) hits a team 4 unit: the game's relation says ally: nullified", kit, dict(attacker=(SOFT, BAAL), defender=(), d_team=4), 1),
        ("kit: the holder on team 4 hits team 0: ally: nullified", kit, dict(attacker=(BAAL,), defender=(), a_team=4, d_team=0), 1),
        ("kit: the holder on team 1 hits team 5: ally (1/5 group): nullified", kit, dict(attacker=(BAAL,), defender=(), a_team=1, d_team=5), 1),
        ("kit: the holder on team 1 hits team 0: an enemy: damage stays", kit, dict(attacker=(BAAL,), defender=(), a_team=1, d_team=0), 0),
        ("kit: the holder on team 3 hits team 3: ally: nullified", kit, dict(attacker=(BAAL,), defender=(), a_team=3, d_team=3), 1),
        ("kit: the holder on team 3 hits team 0: damage stays", kit, dict(attacker=(BAAL,), defender=(), a_team=3, d_team=0), 0),
        ("kit: a heal or buff (damage 0) on an ally: left alone", kit, dict(attacker=(BAAL,), defender=(), damage=0), 0),
        ("kit: negative damage on an ally: left alone", kit, dict(attacker=(BAAL,), defender=(), damage=-5), 0),
        ("kit: damage 1 on an ally: nullified", kit, dict(attacker=(BAAL,), defender=(), damage=1), 1),
        ("kit: a unit without the row hits an ally: damage stays", kit, dict(attacker=(27691,), defender=()), 0),
        ("kit: the row on the DEFENDER does not nullify an ally's hit on it", kit, dict(attacker=(), defender=(BAAL,)), 0),
        ("kit: 40 other ids around the row, holder hits an ally", kit, dict(attacker=around + (BAAL,), defender=()), 1),
        ("kit: 40 other ids around the row, holder hits an enemy", kit, dict(attacker=around + (BAAL,), defender=(), d_team=1), 0),
        ("kit: row with a condition, holder under 50% HP: nullified", kit, dict(attacker=(26308,), defender=(), hp=300), 1),
        ("kit: row with a condition, holder at full HP: damage stays", kit, dict(attacker=(26308,), defender=(), hp=1000), 0),
        ("kit: an ordinary nullify row on the defender still works", kit, dict(attacker=(), defender=(26309,)), 1),
        ("kit: both halves at once (holder vs holder): nullified", kit, dict(attacker=(SOFT, BAAL), defender=(SOFT, BAAL)), 1),
    ]
    bad = 0
    for label, e, kw, want in cases:
        try:
            got = run(e, site, abi=args.abi and e is kit, section=section, **kw)
        except AssertionError as ex:
            got = f"ABI {ex}"
        ok = got == want
        bad += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {label:95} {str(got)[:60]} (expected {want})")
    # the other three redirected callers go through the same wrapper
    for s in SITES[1:]:
        for label, kw, want in (("holder hits an ally", dict(attacker=(BAAL,), defender=()), 1), ("holder hits an enemy", dict(attacker=(BAAL,), defender=(), d_team=1), 0)):
            got = run(kit, s, abi=args.abi, section=section, **kw)
            ok = got == want
            bad += not ok
            print(f"{'ok  ' if ok else 'FAIL'} kit site {s:#x}: {label:80} {got} (expected {want})")
    n = len(cases) + 2 * len(SITES[1:])
    print(f"{n - bad}/{n} {'abi' if args.abi else 'behavior'}; kit build sha256 {hashlib.sha256(patched).hexdigest()[:16]}, pinned exe {game.exe_sha[:16]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
