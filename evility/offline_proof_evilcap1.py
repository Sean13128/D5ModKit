"""EVILCAP1: map_class_ally / map_class_enemy and the Magichange conditions, through the pinned game's real patched CALL
sites (Unicorn), normal and --abi, plus a differential against the base build.  Offline only.

  * the three shipped rows are read verbatim from d5lib/importers/d4-evility-overlay.json (Marona 27875, Gig 27851,
    Ash 27878), so proof and pack cannot drift;
  * the Magichange fields are written where the game writes them (stat record SR = 0x141067DC8 + index * 0xE98:
    host slot participant SR+0x4B8+0x10*s, slot turns SR+0x4E0+s, participant flag SR+0x4E2), and the slot test is
    cross-checked against the game's own cmdmenu_preds_p_15cfe0 (0x14015CFE0) run on the installed exe;
  * differential: every legacy plan PLUME1 diffed (ex05e, drpgevil1b, evilfx2, aura fixtures) plus Plume's row runs
    on the base build (integ-next 166237b, built from git objects) and on this build with identical Unicorn state.

D5Modkit/.venv-macos/bin/python evility/offline_proof_evilcap1.py [--abi] [--json OUT]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'evility'), str(KIT / 'tools')]
from d5lib import evility as ev                                                  # noqa: E402
from abi_engine_ex05c import execute                                             # noqa: E402
from offline_proof_carriers2 import u, fixture as c2_fixture                     # noqa: E402
from offline_proof_oleffects import ORIGINAL, ORIGINAL_SHA                      # noqa: E402
import offline_proof_plume1 as plume1                                            # noqa: E402

BASE = '166237b'
SR0, SR_STRIDE = 0x141067DC8, 0xE98
SPIRITS = list(range(14550, 14556))
MARONA, GIG, ASH = 27875, 27851, 27878
ENEMY_ROW, WEAPON_ROW = 7750, 7760


def overlay_rows():
    mods = json.loads((KIT / 'd5lib/importers/d4-evility-overlay.json').read_text())['mods']
    return {rid: mods[pack]['behaviors']['evilities'][str(rid)]
            for pack, rid in (('D4_Unique_440', MARONA), ('D4_Unique_340', GIG), ('D4_Unique_450', ASH))}


ROWS = {**overlay_rows(),
        ENEMY_ROW: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 7, 'per': 'map_class_enemy'}], 'filter': 14550},
        WEAPON_ROW: {'family': 'stats', 'effects': [{'stat': 'atk', 'value': 9}], 'conditions': [{'kind': 'magichanged'}]}}


def sr(slots=((0, 0), (0, 0)), duals=(0, 0), weapon=0):
    """a stat record: slots = ((participant uid, turns) for slot 0, 1), dual participant uids, the +0x4E2 byte"""
    b = bytearray(SR_STRIDE)
    for s, (uid, turns) in enumerate(slots):
        struct.pack_into('<Q', b, 0x4B8 + 0x10 * s, uid)
        b[0x4E0 + s] = turns
    for s, uid in enumerate(duals):
        struct.pack_into('<Q', b, 0x4C0 + 0x10 * s, uid)
    b[0x4E2] = weapon
    return b


def fixture(subject, others=(), stat=None):
    base = c2_fixture(subject, others)

    def setup(write):
        base(write)
        if stat is not None:
            write(SR0, stat)                                 # the subject's stat record index is 0 (u() leaves it)
    return setup


def cases():
    no_sr = u(ids=(GIG,))
    struct.pack_into('<I', no_sr, 0x4348, 0x28A)
    no_sr_ash = u(ids=(ASH,))
    struct.pack_into('<I', no_sr_ash, 0x4348, 0x28A)
    up = [100] * 8                                           # potency words start at 50; +50
    # D4SIG3: Phantom Lover and Eccarlate raise ATK..SPD only (D4 FUN_1401b4010 applies the percent to those six), so
    # HP and SP stay 0 in the 18-slot aggregate
    allp = lambda n: [0, 0] + [n] * 6 + [0] * 10             # noqa: E731
    c = []

    def add(name, family, field, expected, subject, others=(), stat=None):
        c.append(dict(name=name, family=family, field=field, expected=expected,
                      fixture=fixture(subject, others, stat)))
    # ---- map_class_ally (Marona, Phantom Lover) --------------------------------------------------------------
    m = lambda: u(ids=(MARONA,), char_id=18150)             # noqa: E731
    add('marona: two ally Spirits -> +10', 'stats', 'aggregate', allp(10), m(),
        ((u(char_id=14550), 1, True), (u(char_id=14553), 2, True)))
    add('marona: one ally + two enemy Spirits -> +5 (enemies not counted)', 'stats', 'aggregate', allp(5), m(),
        ((u(char_id=14550), 1, True), (u(char_id=14551, team=1), 2, True), (u(char_id=14555, team=1), 3, True)))
    add('marona: enemy Spirits only -> 0', 'stats', 'aggregate', allp(0), m(),
        ((u(char_id=14550, team=1), 1, True), (u(char_id=14552, team=1), 2, True)))
    add('marona: ally non-Spirit -> 0', 'stats', 'aggregate', allp(0), m(), ((u(char_id=2120), 1, True),))
    add('marona: ally Spirit off the map -> 0', 'stats', 'aggregate', allp(0), m(), ((u(char_id=14550), 1, False),))
    add('marona: unlearned -> 0', 'stats', 'aggregate', allp(0), u(char_id=18150), ((u(char_id=14550), 1, True),))
    # ---- map_class_enemy ---------------------------------------------------------------------------------------
    e = lambda team=0: u(ids=(ENEMY_ROW,), team=team)        # noqa: E731
    agg = lambda atk: [0, 0, atk] + [0] * 15                 # noqa: E731
    add('enemy scale: two enemy, one ally of the class -> +14', 'stats', 'aggregate', agg(14), e(),
        ((u(char_id=14550, team=1), 1, True), (u(char_id=14550, team=1), 2, True), (u(char_id=14550), 3, True)))
    add('enemy scale: holder on team 1, team-0 units are its enemies -> +14', 'stats', 'aggregate', agg(14), e(1),
        ((u(char_id=14550), 1, True), (u(char_id=14550), 2, True), (u(char_id=14550, team=1), 3, True)))
    add('enemy scale: other class -> 0', 'stats', 'aggregate', agg(0), e(), ((u(char_id=14551, team=1), 1, True),))
    # ---- magichange_host (Gig, Jet Black Sword) ----------------------------------------------------------------
    g = lambda: u(ids=(GIG,))                                # noqa: E731
    add('gig: slot 0 holds a participant -> potency +50', 'potency', 'potency', up, g(), stat=sr(((0x1234, 3), (0, 0))))
    add('gig: slot 1 holds a participant -> potency +50', 'potency', 'potency', up, g(), stat=sr(((0, 0), (0x55, 1))))
    add('gig: no participant -> no change', 'potency', 'potency', [50] * 8, g(), stat=sr())
    add('gig: dual uid alone (no primary) -> no change', 'potency', 'potency', [50] * 8, g(),
        stat=sr(duals=(0x77, 0x88)))
    add('gig: the unit is itself a weapon (+0x4E2), not a wielder -> no change', 'potency', 'potency', [50] * 8, g(),
        stat=sr(weapon=1))
    add('gig: no stat record -> no change', 'potency', 'potency', [50] * 8, no_sr)
    add('gig: unlearned, wielding -> no change', 'potency', 'potency', [50] * 8, u(), stat=sr(((0x1234, 3), (0, 0))))
    add('gig: row does not reach the stat aggregate', 'stats', 'aggregate', allp(0), g(), stat=sr(((0x1234, 3), (0, 0))))
    # ---- magichange_turns 1 (Ash, Eccarlate) ---------------------------------------------------------------------
    a = lambda: u(ids=(ASH,))                                # noqa: E731
    add('ash: slot 0 last turn (1) -> +100', 'stats', 'aggregate', allp(100), a(), stat=sr(((9, 1), (0, 0))))
    add('ash: slot 0 two turns left -> 0', 'stats', 'aggregate', allp(0), a(), stat=sr(((9, 2), (0, 0))))
    add('ash: slot 0 three turns left -> 0', 'stats', 'aggregate', allp(0), a(), stat=sr(((9, 3), (0, 0))))
    add('ash: turns byte 1 on an empty slot -> 0', 'stats', 'aggregate', allp(0), a(), stat=sr(((0, 1), (0, 0))))
    add('ash: slot 1 on its last turn, slot 0 not -> +100', 'stats', 'aggregate', allp(100), a(),
        stat=sr(((9, 3), (8, 1))))
    add('ash: empty slot 0 at 1, slot 1 at 2 -> 0', 'stats', 'aggregate', allp(0), a(), stat=sr(((0, 1), (8, 2))))
    add('ash: no stat record -> 0', 'stats', 'aggregate', allp(0), no_sr_ash)
    add('ash: unlearned on its last turn -> 0', 'stats', 'aggregate', allp(0), u(), stat=sr(((9, 1), (0, 0))))
    # ---- magichanged ------------------------------------------------------------------------------------------
    w = lambda: u(ids=(WEAPON_ROW,))                         # noqa: E731
    add('magichanged: participant byte set -> +9', 'stats', 'aggregate', agg(9), w(), stat=sr(weapon=1))
    add('magichanged: byte clear (wielder only) -> 0', 'stats', 'aggregate', agg(0), w(), stat=sr(((9, 1), (0, 0))))
    return c


def game_slot_test(slot_cases):
    """the game's own slot test, cmdmenu_preds_p_15cfe0(record, slot), on the same stat-record bytes"""
    import stat_oracle as so
    exe = Path('/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/disgaea5.exe')
    e = so.Emu(exe_path=exe)
    out = []
    for stat, slot in slot_cases:
        e.brk = e.heap_mark
        e.mu.mem_write(SR0, bytes(stat))
        unit = e.alloc(bytes(0x4800))                       # stat record index 0
        out.append(e.call(0x14015CFE0, (unit, slot)) & 0xFF)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    original = ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == ORIGINAL_SHA
    checks = []
    bundle = plume1.build(ev, original, ROWS)
    for case in cases():
        for site, result in plume1.run_case(bundle, case, args.abi):
            got = result[case['field']]
            assert got == case['expected'], (case['name'], hex(site), got, case['expected'])
            checks.append(dict(name=case['name'], site=hex(site), ok=True))
        print('PASS', case['name'])
    # our magichange_host slot rule == the game's own slot predicate
    probes = [(sr(((0x1234, 3), (0, 0))), 0), (sr(((0, 0), (0x55, 1))), 1), (sr(((0, 0), (0x55, 1))), 0),
              (sr(duals=(0x77, 0x88)), 0), (sr(weapon=1), 0)]
    game = game_slot_test(probes)
    ours = [int(struct.unpack_from('<Q', st, 0x4B8 + 0x10 * s)[0] != 0) for st, s in probes]
    assert game == ours, (game, ours)
    checks.append(dict(name='slot rule agrees with cmdmenu_preds_p_15cfe0 on the installed exe', probes=game, ok=True))
    print('PASS slot rule agrees with the game\'s cmdmenu_preds_p_15cfe0', game)
    # differential: legacy plans state-identical against the base build
    plume1.BASE = BASE
    scratch = Path('/Volumes/Data/ai-tmp/claude/evilcap1/proofs')
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='differential-', dir=scratch) as tmp:
        old = plume1.baseline(Path(tmp))
        plans = list(plume1.old_aura_plans()) + [('plume1', plume1.plume_rows(), plume1.cases())]
        for name, rows, cases_ in plans:
            assert ev.table(rows) == old.table(rows), name + ': old encoding changed'
            before, after = plume1.build(old, original, rows), plume1.build(ev, original, rows)
            for case in cases_:
                first = list(plume1.run_case(before, case, args.abi))
                second = list(plume1.run_case(after, case, args.abi))
                assert len(first) == len(second)
                for (site, x), (other_site, y) in zip(first, second):
                    assert site == other_site and plume1.state(x) == plume1.state(y), (name, case['name'])
                    checks.append(dict(name='differential-' + name + '-' + case['name'], site=hex(site), ok=True))
    report = dict(mode='abi' if args.abi else 'behavior', baseline=BASE,
                  patched_sha256=hashlib.sha256(bundle[0]).hexdigest(), passed=True, checks=checks)
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f"{len(checks)}/{len(checks)} checks passed (EVILCAP1 rows + game slot predicate + legacy differential vs {BASE})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
