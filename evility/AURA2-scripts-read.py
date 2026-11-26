"""Prepared AURA2 live read; NOT run by AURA2B. Based on AURA1-scripts-read.py.

Coordinator must supply the live lease and load test slot 13 with Citri Smart,
Melodia, Noel and Mr. Champloo available. No launch, install, save or count writes.
From live-harness/runner, with its Python/PYTHONPATH and RUNNER_TAG=AURA2:
    $PY ../../AURA2-scripts-read.py
Every mask write is read back. Each toggle is isolated by a verified full restore.
Regen uses captured unit pointers, actual HP +0x2CC8 / HPmax +0x2CD8, one End Turn
per condition, and the round counter. Enemy damage can make a regen read unreadable;
never infer a missing heal from net damage. Run only in a safe test battle.
"""
import struct

IDS = {'Citri Smart': 28304, 'Melodia': 28092, 'Noel': 28020, 'Mr. Champloo': 28008}
SHAPES = {28304: [(2, 0, 4), (66, 1, 4), (2, 0, 1), (66, 1, 1)],
          28092: [(2, 0, 1), (66, 1, 1)],
          28020: [(2048, 0, 1), (2112, 1, 1)],
          28008: [(2, 0, 1), (66, 1, 1)]}
STATS = ('hpmax', 'spmax', 'atk', 'def', 'int', 'res', 'hit', 'spd')


def write_checked(ctl, addr, data):
    ctl.cmd(f'wr {addr:#x} {data.hex()}')
    got = bytes.fromhex(ctl.cmd(f'rd {addr:#x} {len(data)}')['hex'])
    assert got == data, f'write readback at {addr:#x}: {got.hex()} != {data.hex()}'


def write_row_mask(ctl, addr, ev, mask, on):
    before = bytes.fromhex(ctl.cmd(f'rd {addr:#x} 32')['hex'])
    evid, current = struct.unpack_from('<II', before)
    assert evid == ev and current in (0, mask), f'row identity/mask changed at {addr:#x}'
    expected = before[:4] + struct.pack('<I', mask if on else 0) + before[8:]
    # AURA1 wrote at addr (the id), rather than addr+4 (the mask).
    write_checked(ctl, addr + 4, expected[4:8])
    after = bytes.fromhex(ctl.cmd(f'rd {addr:#x} 32')['hex'])
    assert after == expected, f'row identity/body changed at {addr:#x}'


def locate_rows(sec, section_base):
    """Fail closed on a missing, ambiguous or changed installed row run."""
    rows = {}
    for ev, shape in SHAPES.items():
        candidates = []
        for off in range(0, len(sec) - 32 * len(shape) + 1, 16):
            run = [struct.unpack_from('<8I', sec, off + 32 * i) for i in range(len(shape))]
            if all(r[0] == ev and r[6] == 0 and r[7] == 0 and
                   (r[1], r[3], r[5]) == want and r[2] % 8 == r[4] % 8 == 0
                   for r, want in zip(run, shape)):
                candidates.append([(section_base + off + 32 * i, r[1]) for i, r in enumerate(run)])
        assert len(candidates) == 1, f'{ev}: expected one installed run, got {len(candidates)}'
        rows[ev] = candidates[0]
    return rows


def assert_full(snapshot, full):
    assert snapshot == full, f'restore/recalc did not return full snapshot: {snapshot!r} != {full!r}'


def main():
    # Importing common initializes the live pipe. Kept inside main for offline helper tests.
    import sys
    sys.path.insert(0, '/Volumes/Data/Projects/D5/Subprojects/Engine-Extensions/SWEEP2-scripts')
    import common as h
    import time

    c = h.c
    P = {'t0': time.strftime('%H:%M:%S'), 'steps': {}, 'toggle': {},
         'measurement': 'MEMORY-WRITTEN masks/HP; game recalc and End Turn'}

    def store():
        result = h.results()
        result['aura2'] = P
        h.save_results(result)

    def rd(addr, n):
        return bytes.fromhex(h.rdh(addr, n))

    # Read the complete PE section table (AURA1 assumed it fit in the first 0x400).
    hdr = rd(0x140000000, 0x1000)
    pe = struct.unpack_from('<I', hdr, 0x3c)[0]
    nsec = struct.unpack_from('<H', hdr, pe + 6)[0]
    osz = struct.unpack_from('<H', hdr, pe + 20)[0]
    start = pe + 24 + osz
    sh = rd(0x140000000 + start, 40 * nsec)
    sections = {}
    for off in range(0, len(sh), 40):
        name = sh[off:off + 8].rstrip(b'\0').decode()
        vs, va = struct.unpack_from('<II', sh, off + 8)
        sections[name] = (va, vs)
    va, vs = sections['.d5mod']
    sec = b''.join(rd(0x140000000 + va + off, min(4096, vs - off)) for off in range(0, vs, 4096))
    rows = locate_rows(sec, 0x140000000 + va)
    P['rows'] = rows
    store()

    def setmask(ev, which, on):
        for addr, mask in rows[ev]:
            if which == 'all' or (which == 'aura') == bool(mask & 64):
                write_row_mask(c, addr, ev, mask, on)

    def restore_all():
        # Best effort across all rows even when one write/readback raises.
        errors = []
        for ev in IDS.values():
            for addr, mask in rows[ev]:
                try:
                    write_row_mask(c, addr, ev, mask, True)
                except Exception as exc:
                    errors.append(f'{ev} {addr:#x}: {exc}')
        assert not errors, errors

    pointers = {}
    full = None

    def read_unit(name):
        up = pointers[name]  # Never look the unit up again after End Turn.
        q = struct.unpack('<10q', rd(up + 0x2cc8, 80))
        n = struct.unpack('<i', rd(up + 0x3030, 4))[0]
        assert 0 <= n <= 64, (name, n)
        ids = list(struct.unpack(f'<{n}I', rd(up + 0x2f30, n * 4))) if n else []
        return dict(zip(('hp', 'sp') + STATS, q), evil_ids=ids)

    def snap():
        # Recalc every unit first; only then take a simultaneous snapshot.
        for up in pointers.values():
            c.cmd(f'call 14021bfb0 {up:#x}')
        time.sleep(0.15)
        return {name: read_unit(name) for name in pointers}

    def reset():
        restore_all()
        restored = snap()
        # Max-HP removal can legitimately clamp current HP. Restore only current
        # resources (explicit fixture writes), never derived stats/maxima, then
        # require an exact snapshot including HP/SP and the learned lists.
        for name, up in pointers.items():
            for key, offset in (('hp', 0x2cc8), ('sp', 0x2cd0)):
                if restored[name][key] != full[name][key]:
                    write_checked(c, up + offset, struct.pack('<q', full[name][key]))
        restored = snap()
        P['last_restored'] = restored
        store()
        assert_full(restored, full)

    def diff(a, b):
        return {name: {k: a[name][k] - b[name][k] for k in STATS} for name in pointers}

    try:
        s0, base, enemies, _ = h.enter(P, store)
        assert P['entered'], 'battle entry failed'
        occupied = {tuple(u['p']) for u in s0['units'] if u.get('p')}
        tiles = h.r6h.spread_tiles(h.bs, base, occupied, len(IDS))
        assert len(tiles) == len(IDS), 'insufficient safe deployment tiles'
        for name, tile in zip(IDS, tiles):
            h.deploy(P, [(name, tile)])
            h.closeSel()
            up = h.upo(name)
            assert up, f'{name} not deployed'
            pointers[name] = up
        # All providers must be on-map, same side, within the actual radius.
        units = [h.bn.unit(c, name) for name in IDS]
        assert all(u and int(u.get('team', 0) or 0) == 0 for u in units)
        assert all(0 < h.bs._dist(tuple(a['p'][:2]), tuple(b['p'][:2])) <= 30
                   for i, a in enumerate(units) for b in units[i + 1:])
        P['pointers'] = pointers
        full = snap()
        P['full'] = full
        assert_full(snap(), full)
        required = {'Citri Smart': [7133, 28304, 28305],
                    'Melodia': [7132, 28092, 28093, 28095],
                    'Noel': [7130, 7131, 28020, 28021]}
        for name, expected in required.items():
            assert full[name]['evil_ids'] == expected, (name, full[name]['evil_ids'], expected)
        assert 28008 in full['Mr. Champloo']['evil_ids'], 'Champloo control missing'
        store()
        # Citri AURA ONLY first, per AURA1. Always restore/recalc/assert before
        # the next toggle, including before/after the known-good Champloo control.
        for ev, which in ((28304, 'aura'), (28008, 'aura'), (28092, 'aura'),
                          (28304, 'self'), (28092, 'self')):
            reset()
            setmask(ev, which, False)
            off = snap()
            delta = diff(full, off)
            P['toggle'][f'{ev}_{which}'] = {'off': off, 'full_minus_off': delta}
            store()
            reset()
        citri = P['toggle']['28304_aura']['full_minus_off']
        control = P['toggle']['28008_aura']['full_minus_off']
        P['acceptance'] = {
            'citri_aura_reaches_both': all(citri[n][k] > 0 for n in ('Melodia', 'Noel')
                                         for k in ('hpmax', 'atk', 'def', 'int', 'res')),
            'champloo_control_reaches_others': all(control[n]['atk'] > 0 for n in IDS if n != 'Mr. Champloo'),
            'citri_aura_leaves_own_stats': all(v == 0 for v in citri['Citri Smart'].values()),
        }
        store()

        def round_number():
            return struct.unpack('<h', rd(0x145574aa8, 2))[0]

        # No stat/max-HP inflation: leave room for regen but start near full HP.
        # Damage/death or changing max HP makes the net-HP comparison unreadable.
        for label, on in (('control_row_off', False), ('row_on', True)):
            reset()
            setmask(28020, 'all', on)
            for name, up in pointers.items():
                hm = full[name]['hpmax']
                assert hm >= 16, f'{name}: HP too small for this safety setup'
                write_checked(c, up + 0x2cc8, struct.pack('<q', hm - max(3, hm // 4)))
            before = {name: read_unit(name) for name in pointers}
            r0 = round_number()
            ended = h.end_turn()
            time.sleep(3)
            after = {name: read_unit(name) for name in pointers}
            r1 = round_number()
            rec = {'before_MEMORY_WRITTEN': before, 'after_real': after, 'round_before': r0,
                   'round_after': r1, 'end_turn': ended,
                   'noel_provider_heal_floor': before['Noel']['hpmax'] * 8 // 100,
                   'net_hp': {n: after[n]['hp'] - before[n]['hp'] for n in pointers}}
            P.setdefault('regen', {})[label] = rec
            store()
            assert ended.get('ok') and r1 == r0 + 1, 'one real round did not complete'
            assert all(after[n]['hp'] > 0 for n in pointers), 'regen unreadable: a unit died'
            assert all(after[n]['hpmax'] == before[n]['hpmax'] for n in pointers), 'regen unreadable: max HP changed'
            # AURA1's invalid net-damage inference is never repeated: raw values
            # and round counts are evidence; combat makes causal healing pending.
            rec['interpretation'] = 'net HP only; inspect combat damage/other healing before accepting regen'
            restore_all()
            snap()  # Rebuild real maxima before restoring current resources.
            for name, up in pointers.items():
                for key, offset in (('hp', 0x2cc8), ('sp', 0x2cd0)):
                    write_checked(c, up + offset, struct.pack('<q', full[name][key]))
            reset()  # Exact full snapshot gate before the next condition.
        store()
    except Exception as exc:
        P['error'] = f'{type(exc).__name__}: {exc}'
        store()
        raise
    finally:
        # Attempt all restorations even if a mask readback/restore gate fails.
        try:
            restore_all()
            if pointers and full is not None:
                reset()
                P['final_restored'] = snap()
                assert_full(P['final_restored'], full)
        finally:
            try:
                P['left'] = h.d._give_up(h.bn, c)
            finally:
                store()
    assert all(P['acceptance'].values()), P['acceptance']
    return P


if __name__ == '__main__':
    main()
