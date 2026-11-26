"""D4SIG10b offline proof: Roc's Miasma of Silence (D4 115, row 27115, second-word family special_seal) through the pinned game's REAL code.

Sites (kit build, run from the call instruction to its return, the game's own callee executing for real, the pinned exe as control):
  wrap_roc_skill  0x14054785D (executor, FUN_140547750)  0x1402D0A90 (AI, list_skills)  0x14062E7BD (menu, command_ctl_s1_update)
                  0x14062EC38 (menu, command_ctl_s1_enter): the real cmdmenu_env_stat_row_can_use_skill body (0x140155280)
  wrap_roc_geo    0x140156A47: the real unit_effect_table_sum (0x14015B890); plus the real cmdmenu_preds_p_156820 (the base of "Skill") run from its
                  first instruction through the patched call.
Adjacency is the game's own ai_transition_within_range / path_query_footprints_within (real code), hostility the kit's evil_hostile table.

D5Modkit/.venv-macos/bin/python evility/offline_proof_d4sig10b.py [--abi] [--control NAME]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'evility'), str(KIT / 'tools')]
from d5lib import evility as ev                                                  # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402
import offline_proof_d4sig7 as s7                                                # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/d4sig10')
OVERLAY = KIT / 'd5lib/importers/d4-evility-overlay.json'
ROC = 27115
SKILL_SITES = (0x14054785D, 0x1402D0A90, 0x14062E7BD, 0x14062EC38)
GEO_SITE = 0x140156A47
P156820 = 0x140156820
UNITS, USTRIDE = 0x141BA33B0, 4704
SR0, SRSTRIDE = 0x141067DC8, 0xE98
GROUND = 0x140A72710                      # unit_effect_table_sum's rows: 61 bytes each
CTX_PTR, MODE = 0x140BDFD08, 0x145574AAF


def mutated_asm(control):
    text = Path(ev.ASM_FILE).read_text()
    edits = {
        'roc-adjacent': ("    call 0x140153ff0                    // ai_transition_within_range(other, unit, 1, -1)\n    test al, al\n    jz .rc_next\n", ""),
        'roc-hostile': ("    jnc .rc_next                        // not hostile\n", ""),
        'roc-dead': ("    jle .rc_next                        // dead\n", ""),
        'roc-obj51': ("    jb .rc_next                         // object / Geo class 51, 52\n", ""),
        'roc-obj48': ("    je .rc_next                         // 48xx\n", ""),
        'roc-obj5000': ("    jb .rc_next                         // 5000..5009\n", ""),
        'roc-holder': ("    call evil_pred                      // rsi = the candidate's unit record\n    test eax, eax\n    jz .rc_next\n", ""),
        'roc-id': ("    mov rdi, 0x1000000000               // F2_SPECIAL_SEAL", "    mov rdi, 0x800000000               // F2_SPECIAL_SEAL"),
        'roc-class': ("    movzx eax, byte ptr [rsi + 0x3f2]\n    cmp eax, 2\n    ja .rs_done", "    movzx eax, byte ptr [rsi + 0x3f2]\n    cmp eax, 1\n    ja .rs_done"),
        'roc-items': ("    movzx eax, byte ptr [rsi + 0x3f2]\n    cmp eax, 2\n    ja .rs_done", "    movzx eax, byte ptr [rsi + 0x3f2]\n    cmp eax, 4\n    ja .rs_done"),
        'roc-skillcall': ("    jz .rs_done\n    xor edi, edi\n", "    jz .rs_done\n    nop\n"),
        'roc-geocol': ("    cmp esi, 10\n    jne .rcg_done\n", ""),
        'roc-geokeep': ("    test dil, dil\n    jnz .rcg_done\n", ""),
        'roc-geocall': ("    jz .rcg_done\n    mov edi, 1\n", "    jz .rcg_done\n    nop\n"),
    }
    old, new = edits[control]
    assert text.count(old) == 1, (control, text.count(old))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    out = SCRATCH / f'd5evil-d4sig10b-{control}.inc.asm'
    out.write_text(text.replace(old, new))
    return out


class RocRig(s7.DragonRig):
    def reset(self):
        e = self.e
        e.brk = e.heap_mark
        e.mu.mem_write(UNITS, bytes(USTRIDE * 256))
        e.mu.mem_write(SR0, bytes(SRSTRIDE * 0x28A))
        e.mu.mem_write(GROUND, bytes(61 * 0x4007))
        e.mu.mem_write(CTX_PTR, struct.pack('<Q', e.alloc(bytes(0x100))))
        e.mu.mem_write(MODE, b'\x00')

    def rec(self, ids=(), team=0, hp=100, char=1000):
        b = bytearray(s7.dunit(ids, 0x28A))
        b[0x2e32] = team
        struct.pack_into('<q', b, 0x2cc8, hp)
        struct.pack_into('<i', b, 0x2e04, char)
        return self.e.alloc(bytes(b))

    def put(self, slot, cell, rec, active=1, carried=-1):
        """a battle unit in table slot `slot` standing on panel `cell` = (x, z), footprint one panel"""
        va = UNITS + slot * USTRIDE
        b = bytearray(USTRIDE)
        b[0x2e8] = active
        struct.pack_into('<Q', b, 0x240, rec)
        struct.pack_into('<h', b, 0x2ee, carried)
        struct.pack_into('<h', b, 0x2f0, -1)
        struct.pack_into('<f', b, 8, cell[0] * 12 + 6)
        struct.pack_into('<f', b, 0x10, cell[1] * 12 + 6)
        struct.pack_into('<q', b, 0x10a4, 0)                 # footprint cell (0, 0)
        struct.pack_into('<h', b, 0x11a4, 1)
        self.e.mu.mem_write(va, bytes(b))
        return va

    def row(self, cls, rid=1, motion=0):
        b = bytearray(0x474)
        struct.pack_into('<I', b, 0, rid)
        b[0x3f2] = cls
        b[0x3f7] = motion
        return self.e.alloc(bytes(b))

    def status(self, rec, k, v=1, stat=3):
        """a stat record for rec with status counter k set (stat index `stat`)"""
        self.e.mu.mem_write(rec + 0x4348, struct.pack('<I', stat))
        self.e.mu.mem_write(SR0 + stat * SRSTRIDE + 0xE1C + k, bytes([v]))

    def entry(self, addr, regs, maxn=20_000_000):
        """the real function body from its first instruction to its return"""
        e = self.e
        X, mu = e.X, e.mu
        rsp = self.so.STACK + 0x100000 - 0x400
        mu.mem_write(rsp, struct.pack('<Q', self.so.RET))
        mu.reg_write(X.UC_X86_REG_RSP, rsp)
        for r, v in regs.items():
            mu.reg_write(getattr(X, 'UC_X86_REG_' + r.upper()), v)
        mu.emu_start(addr, self.so.RET, count=maxn)
        return mu.reg_read(X.UC_X86_REG_RAX)


_RIGS = {}


def rigs():
    if not _RIGS:
        original = ORIGINAL.read_bytes()
        assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
        st = json.loads(OVERLAY.read_text())['mods']['D4_Class_2110']
        assert st['behaviors']['evilities'][str(ROC)] == {'family': 'special_seal'}, st['behaviors']
        assert [r['id'] for r in st['skill_rows'] if r['id'] == ROC] == [ROC]
        assert all(v['evility1'] == ROC and v['evility_count'] == 1 for v in st['char_links'].values()) and len(st['char_links']) == 6
        assert ev.EXT_FAMILIES['special_seal'] == 4
        patched = ev.build_patch(original, {ROC: {'family': 'special_seal'}})
        info = ev.section_info(patched)
        SCRATCH.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix='d4sig10b-', dir=SCRATCH))
        (tmp / 'kit.exe').write_bytes(patched)
        _RIGS.update(kit=RocRig(tmp / 'kit.exe'), control=RocRig(ORIGINAL),
                     section=(info['code'], info['base'] + len(info['data'])), sha=hashlib.sha256(patched).hexdigest())
    return _RIGS


def section(abi):
    r = rigs()
    kit, control, sect = r['kit'], r['control'], r['section']
    ok = n = 0

    def report(name, problems):
        nonlocal ok, n
        n += 1
        ok += not problems
        print(('ok   ' if not problems else 'FAIL ') + 'roc: ' + name + ('' if not problems else ': ' + '; '.join(problems)))

    HOLD, NONE, OTHER = (ROC,), (), (5, 9, 27807, 27114, 27116, 40000)
    A = (5, 5)

    def world(rig, roc_cell=(6, 5), roc_ids=HOLD, roc_team=1, roc_hp=100, roc_char=1000, roc_active=1, roc_slot=7, asker_team=0, asker_ids=(),
             extra=None):
        """asker in slot 3 on A, a candidate holder in `roc_slot`; returns the asker's battle unit"""
        rig.reset()
        arec = rig.rec(asker_ids, asker_team)
        au = rig.put(3, A, arec)
        if roc_cell is not None:
            rig.put(roc_slot, roc_cell, rig.rec(roc_ids, roc_team, roc_hp, roc_char), roc_active)
        for slot, cell, rec in (extra or ()):
            rig.put(slot, cell, rec)
        return au, arec

    def skill(rig, site, cls, a, sc, rid=1, motion=0, ailment=None, **kw):
        au, arec = world(rig, **kw)
        if ailment:
            rig.status(arec, *ailment)
        return rig.start(site, dict(rcx=au, rdx=rig.row(cls, rid, motion), r8=0), {}, a, sc, None) & 0xFF

    # --- the four call sites of can_use_skill: the same table at each
    for site in SKILL_SITES:
        tag = f'site {site:#x}: '
        a, sc = abi, sect
        for cls, name, want in ((0, 'unique skill (class 0)', 0), (1, 'weapon skill (class 1)', 0), (2, 'spell (class 2)', 0),
                                (3, 'item (class 3)', 1), (4, 'Overload skill (class 4)', 1), (5, 'basic action (class 5)', 1)):
            got = skill(kit, site, cls, a, sc)
            ctl = skill(control, site, cls, 0, None)
            report(tag + f'adjacent hostile Roc holder, {name}: {"blocked" if not want else "usable"}',
                   [] if (got, ctl) == (want, 1) else [f'kit {got}, pinned exe {ctl}, want ({want}, 1)'])
        negs = (
            ('no holder nearby (the game alone)', dict(roc_cell=None), 1),
            ('holder two panels away', dict(roc_cell=(7, 5)), 1),
            ('holder on a diagonal panel (Manhattan 2)', dict(roc_cell=(6, 6)), 1),
            ('holder adjacent from the other side (x - 1)', dict(roc_cell=(4, 5)), 0),
            ('holder adjacent above (z + 1)', dict(roc_cell=(5, 6)), 0),
            ('holder adjacent, battle slot 255', dict(roc_slot=255), 0),
            ('holder adjacent, battle slot 0', dict(roc_slot=0), 0),
            ('allied holder adjacent (same team)', dict(roc_team=0), 1),
            ('holder of a team that is not hostile (team 2)', dict(roc_team=2), 1),
            ('holder of another hostile team (3) adjacent', dict(roc_team=3), 0),
            ('dead holder (HP 0) adjacent', dict(roc_hp=0), 1),
            ('holder with negative HP adjacent', dict(roc_hp=-1), 1),
            ('holder not on the map (inactive slot)', dict(roc_active=0), 1),
            ('holder that is a Geo Symbol (char 4811)', dict(roc_char=4811), 1),
            ('holder that is an object class 51xx (5100)', dict(roc_char=5100), 1),
            ('holder that is an object class 52xx (5299)', dict(roc_char=5299), 1),
            ('holder in the 5000..5009 object range', dict(roc_char=5005), 1),
            ('holder char 5010 (not an object) still seals', dict(roc_char=5010), 0),
            ('holder char 4999 (not an object) still seals', dict(roc_char=4999), 0),
            ('holder of class id 0x12CA (= 4810, a Geo Symbol)', dict(roc_char=0x12CA), 1),
            ('adjacent unit with no row', dict(roc_ids=NONE), 1),
            ('adjacent unit with other ids (27114, 27116, ...)', dict(roc_ids=OTHER), 1),
            ('a holder as the ASKED unit with nobody near: its own skills unaffected', dict(roc_cell=None, asker_ids=HOLD), 1),
            ('a holder asked, an ally holder adjacent: unaffected', dict(roc_team=0, asker_ids=HOLD), 1),
            ('a team-1 asker with a team-0 holder adjacent (hostile the other way): blocked', dict(asker_team=1, roc_team=0), 0),
        )
        for name, kw, want in negs:
            got = skill(kit, site, 1, a, sc, **kw)
            report(tag + name + f': weapon skill {"blocked" if not want else "usable"}', [] if got == want else [f'got {got}'])
        # the game's own ailment is unchanged: Amnesia (status 3) blocks a weapon skill by itself, with or without a holder
        for kw, name in ((dict(roc_cell=None), 'no holder'), (dict(), 'holder adjacent')):
            got = skill(kit, site, 1, a, sc, ailment=(3, 1), **kw)
            ctl = skill(control, site, 1, 0, None, ailment=(3, 1), **kw)
            report(tag + f'a unit already under Amnesia (the game blocks the skill), {name}: still blocked, same as the pinned exe', [] if (got, ctl) == (0, 0) else [f'{got} {ctl}'])
        got = skill(kit, site, 2, a, sc, ailment=(3, 1), roc_cell=None)
        ctl = skill(control, site, 2, 0, None, ailment=(3, 1), roc_cell=None)
        report(tag + 'Amnesia and a spell (the game allows it): unchanged', [] if got == ctl == 1 else [f'{got} {ctl}'])
        # null row: the game's own answer passes through
        au, _ = world(kit)
        got = kit.start(site, dict(rcx=au, rdx=0, r8=0), {}, a, sc, None) & 0xFF
        au, _ = world(control)
        ctl = control.start(site, dict(rcx=au, rdx=0, r8=0), {}, 0, None, None) & 0xFF
        report(tag + 'a null skill row: the game\'s own answer, no Roc test', [] if got == ctl else [f'{got} {ctl}'])
        # the game says no for another reason (cost above SP): stays no, not turned into yes
        au, arec = world(kit, roc_cell=None)
        kit.e.mu.mem_write(arec + 0x2cd0, struct.pack('<q', 0))
        got = kit.start(site, dict(rcx=au, rdx=kit.row(1), r8=50), {}, a, sc, None) & 0xFF
        au, arec = world(control, roc_cell=None)
        control.e.mu.mem_write(arec + 0x2cd0, struct.pack('<q', 0))
        ctl = control.start(site, dict(rcx=au, rdx=control.row(1), r8=50), {}, 0, None, None) & 0xFF
        report(tag + 'not enough SP (the game says no): unchanged', [] if got == ctl else [f'{got} {ctl}'])

    # --- the Skill command's gate: column 10 of unit_effect_table_sum at its one call in cmdmenu_preds_p_156820
    def geo(rig, col, a, sc, silence_under=0, **kw):
        au, arec = world(rig, **kw)
        if silence_under:
            # the unit stands on ground effect kind 9 whose column 10 holds `silence_under` (the game's own table read)
            rig.e.mu.mem_write(au + 0xb70, struct.pack('<H', 9))
            rig.e.mu.mem_write(au + 0xbb0, struct.pack('<h', 1))
            rig.e.mu.mem_write(GROUND + 9 * 61 + col, bytes([silence_under]))
        return rig.start(GEO_SITE, dict(rcx=au, rdx=col), {}, a, sc, None) & 0xFFFFFFFF

    tag = f'site {GEO_SITE:#x}: '
    a, sc = abi, sect
    for name, kw, want in (('adjacent hostile holder', dict(), 1), ('no holder', dict(roc_cell=None), 0), ('holder two panels away', dict(roc_cell=(7, 5)), 0),
                           ('allied holder', dict(roc_team=0), 0), ('dead holder', dict(roc_hp=0), 0), ('object holder', dict(roc_char=4811), 0),
                           ('unit without the row', dict(roc_ids=NONE), 0), ('holder on a diagonal panel', dict(roc_cell=(6, 6)), 0)):
        got, ctl = geo(kit, 10, a, sc, **kw), geo(control, 10, 0, None, **kw)
        report(tag + f'column 10 (Silence): {name}: {got} (pinned exe {ctl})', [] if (got, ctl) == (want, 0) else [f'want ({want}, 0)'])
    for col in (0, 9, 11, 31):
        got, ctl = geo(kit, col, a, sc), geo(control, col, 0, None)
        report(tag + f'column {col} with a holder adjacent: the game\'s answer only', [] if got == ctl == 0 else [f'{got} {ctl}'])
    got, ctl = geo(kit, 10, a, sc, silence_under=3), geo(control, 10, 0, None, silence_under=3)
    report(tag + 'the unit really stands on a Silence panel (game answer 3), holder adjacent: 3 kept', [] if got == ctl == 3 else [f'{got} {ctl}'])
    got, ctl = geo(kit, 10, a, sc, silence_under=1, roc_cell=None), geo(control, 10, 0, None, silence_under=1, roc_cell=None)
    report(tag + 'a real Silence panel and no holder: 1 as the game says', [] if got == ctl == 1 else [f'{got} {ctl}'])

    # --- the real base of "Skill" (cmdmenu_preds_p_156820, first instruction to return) through the patched call
    def base(rig, **kw):
        au, arec = world(rig, **kw)
        return rig.entry(P156820, dict(rcx=au)) & 0xFFFFFFFF

    for name, kw, want in (('adjacent hostile holder', dict(), 0), ('no holder', dict(roc_cell=None), 1), ('holder two panels away', dict(roc_cell=(7, 5)), 1),
                           ('allied holder', dict(roc_team=0), 1), ('dead holder', dict(roc_hp=0), 1), ('holder as asked unit, nobody near', dict(roc_cell=None, asker_ids=HOLD), 1)):
        got, ctl = base(kit, **kw), base(control, **kw)
        report(f'cmdmenu_preds_p_156820 (the real body): {name}: Skill {"enabled" if want else "disabled"}, pinned exe {ctl}',
               [] if (got, ctl) == (want, 1) else [f'got {got} {ctl}'])
    return ok, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    if args.control:
        ev.ASM_FILE = str(mutated_asm(args.control))
    ok, n = section(args.abi)
    assert ok == n, f'{ok}/{n} checks passed'
    sha = rigs()['sha']
    if args.json:
        args.json.write_text(json.dumps(dict(mode='abi' if args.abi else 'behavior', patched_sha256=sha, passed=True, checks=n), indent=1) + '\n')
    print(f"{n}/{n} checks passed (D4SIG10b Roc, {'abi' if args.abi else 'behavior'}; patched exe {sha[:16]})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
