import struct

import pytest
from d5lib import masterymigration as migration, packedmastery, savegame

T = (64, 256, 1024, 4096, 16384, 262144)
TARGET = {'family': 14080, 'sprite_family': 1280, 'kind': 'humanoid'}
CLAIMS = [dict(holder='kit:armor', namespace='job_class_id', start=14080, end=14085),
          dict(holder='kit:armor', namespace='char_dat_row', start=1280, end=1285),
          dict(holder='kit:armor', namespace='unlock_flag', start=17289, end=17294)]
OPTIONS = dict(leases={1350: 47}, thresholds={1350: T, 14080: T}, target=TARGET,
               rows=[200, 201, 202, 203, 204, 205], old_rows=[40, 41, 42, 43, 44, 45], claims=CLAIMS, holder='kit:armor')


def fixture(path):
    s = savegame.Save.__new__(savegame.Save)
    s.header = bytearray(savegame.HEADER)
    s.header[:len(savegame.MAGIC)] = savegame.MAGIC
    s.state = bytearray(savegame.STATE_SIZE)
    struct.pack_into('<h', s.state, savegame.ARMY_COUNT, 1)
    u = savegame.Unit(s, 0)
    struct.pack_into('<I', s.state, u.base, 1)
    u.set_class(1352)
    struct.pack_into('<h', s.state, u.base + savegame.U_ROW, 42)
    struct.pack_into('<H', s.state, u.base + migration.SUBCLASS, 1350)
    struct.pack_into('<6I', s.state, u.base + migration.MASTERY, 64, 13, 0, 0, 0, 0)
    flag = 17333
    s.state[savegame.STORY_FLAGS + flag // 8] |= 1 << (flag % 8)
    path.write_bytes(s.to_bytes())
    return s


def test_migrate_copy_roundtrip_and_backup(tmp_path):
    source, dest = tmp_path / 'source.sav', tmp_path / 'copy.sav'
    old = fixture(source)
    original = source.read_bytes()
    result = migration.migrate_copy(source, dest, **OPTIONS)
    assert result['mode'] == migration.REHOME
    assert source.read_bytes() == original == (tmp_path / 'copy.sav.bak').read_bytes()
    migrated = savegame.Save(str(dest))
    u = migrated.units()[0]
    assert u.cls == 14082
    assert savegame._s16(migrated.state, u.base + savegame.U_ROW) == 202
    assert savegame._u16(migrated.state, u.base + migration.SUBCLASS) == 14080
    assert migrated.flag(17291) and migrated.flag(17333)
    area = migrated.state[u.base + migration.MASTERY:u.base + migration.MASTERY + 144]
    assert packedmastery.decode_pool(area, OPTIONS['thresholds'])[0] == {14080: (64, 13, 0, 0, 0, 0)}
    # Everything outside specified fields remains untouched.
    for start, size in [(u.base + savegame.U_CLASS, 4), (u.base + savegame.U_ROW, 2),
                        (u.base + migration.SUBCLASS, 2), (u.base + migration.MASTERY, 144),
                        (savegame.STORY_FLAGS + 17291 // 8, 1)]:
        old.state[start:start + size] = migrated.state[start:start + size]
    assert old.state == migrated.state
    assert result['backup'].endswith('.bak')
    with pytest.raises(FileExistsError):
        migration.migrate_copy(source, dest, **OPTIONS)


@pytest.mark.parametrize('case', ['unowned', 'overflow', 'target_flag', 'stale', 'lease', 'claims', 'source_row', 'flags_claim', 'already_packed'])
def test_refuses_ambiguous_or_lossy_data_without_output(tmp_path, case):
    source, dest = tmp_path / 'source.sav', tmp_path / 'copy.sav'
    s = fixture(source)
    u = savegame.Unit(s, 0)
    opts = dict(OPTIONS)
    if case == 'unowned':
        s.state[u.base + migration.MASTERY + 24] = 1
    elif case == 'already_packed':
        s.state[u.base + migration.MASTERY:u.base + migration.MASTERY + 144] = packedmastery.encode_pool(
            {1350: (64, 13, 0, 0, 0, 0)}, {1350: T})
    elif case == 'overflow':
        struct.pack_into('<I', s.state, u.base + migration.MASTERY + 4, 257)
    elif case == 'target_flag':
        s.state[savegame.STORY_FLAGS + 17289 // 8] |= 1 << (17289 % 8)
    elif case == 'stale':
        s.state[savegame.Unit(s, 5).base + migration.MASTERY] = 1
    elif case == 'lease':
        opts['leases'] = {}
    elif case == 'source_row':
        struct.pack_into('<h', s.state, u.base + savegame.U_ROW, 99)
    elif case == 'flags_claim':
        opts['claims'] = CLAIMS[:2]
    else:
        opts['claims'] = CLAIMS[:1]
    source.write_bytes(s.to_bytes())
    before = source.read_bytes()
    with pytest.raises(ValueError):
        migration.migrate_copy(source, dest, **opts)
    assert source.read_bytes() == before
    assert not dest.exists() and not (tmp_path / 'copy.sav.bak').exists()


# ------------------------------------------------------------------ INTEG7 packed lease map: 1350 -> 1350
T35 = (128, 512, 2048, 8192, 32768, 524288)
INTEG7_PACKED = {1350}          # the Armor Knight pilot's patches/classes/mastery.json declares 1350 packed
BASIC = dict(leases={1350: 47}, thresholds={1350: T35})


def fixture_two(path, counters=(4, 4, 4, 4, 4, 4)):
    """Ben-shaped unit 0 (class 1355, slot-47 counters) plus an all-zero unit 1."""
    s = savegame.Save.__new__(savegame.Save)
    s.header = bytearray(savegame.HEADER)
    s.header[:len(savegame.MAGIC)] = savegame.MAGIC
    s.state = bytearray(savegame.STATE_SIZE)
    struct.pack_into('<h', s.state, savegame.ARMY_COUNT, 2)
    for slot, cls, row, counts in ((0, 1355, 472, counters), (1, 14005, 1120, (0, 0, 0, 0, 0, 0))):
        u = savegame.Unit(s, slot)
        struct.pack_into('<I', s.state, u.base, 1)
        u.set_class(cls)
        struct.pack_into('<h', s.state, u.base + savegame.U_ROW, row)
        struct.pack_into('<H', s.state, u.base + migration.SUBCLASS, 0)
        struct.pack_into('<6I', s.state, u.base + migration.MASTERY, *counts)
    s.state[savegame.STORY_FLAGS + 17336 // 8] |= 1 << (17336 % 8)
    path.write_bytes(s.to_bytes())
    return s


def test_plan_identity_when_the_six_slot_family_is_itself_packed():
    assert migration.plan(leases={1350: 47}, packed={1350}) == dict(mode=migration.IDENTITY, family=1350)
    assert migration.plan(leases={1350: 47}, packed={1350}, target={'family': 1350})['mode'] == migration.IDENTITY
    assert migration.plan(leases={1350: 47}, packed=(), target={'family': 14250}) == \
        dict(mode=migration.REHOME, family=14250)
    with pytest.raises(ValueError, match='its own target'):
        migration.plan(leases={1350: 47}, packed={1350}, target={'family': 14250})
    with pytest.raises(ValueError):
        migration.plan(leases={1350: 47}, packed=())          # no target and no packed 1350
    with pytest.raises(ValueError):
        migration.plan(leases={1350: 47}, packed=(), target={'family': 1350})
    with pytest.raises(ValueError):
        migration.plan(leases={}, packed={1350})              # no record of where 1350 wrote


def test_identity_migration_keeps_the_class_and_touches_only_the_spare_area(tmp_path):
    source, dest = tmp_path / 'source.sav', tmp_path / 'copy.sav'
    before = fixture_two(source)
    original = source.read_bytes()
    result = migration.migrate_copy(source, dest, packed=INTEG7_PACKED, **BASIC)
    assert (result['mode'], result['family']) == (migration.IDENTITY, 1350)
    assert source.read_bytes() == original == (tmp_path / 'copy.sav.bak').read_bytes()
    after = savegame.Save(str(dest))
    ben, other = savegame.Unit(after, 0), savegame.Unit(after, 1)
    assert ben.cls == 1355 and other.cls == 14005
    assert savegame._s16(after.state, ben.base + savegame.U_ROW) == 472
    assert savegame._u16(after.state, ben.base + migration.SUBCLASS) == 0
    assert after.flag(17336) and not after.flag(17505)      # no unlock bit is invented
    area = after.state[ben.base + migration.MASTERY:ben.base + migration.MASTERY + 144]
    assert packedmastery.decode_pool(bytes(area), BASIC['thresholds'])[0] == {1350: (4, 4, 4, 4, 4, 4)}
    # the all-zero unit is left for the hook's own pm_blank initialisation
    assert not any(after.state[other.base + migration.MASTERY:other.base + migration.MASTERY + 144])
    allowed = {ben.base + migration.MASTERY + i for i in range(144)}
    assert {i for i in range(len(before.state)) if before.state[i] != after.state[i]} <= allowed
    assert [c['slot'] for c in result['units_converted']] == [0]


def test_a_packed_family_is_never_rehomed_to_another_family(tmp_path):
    """The exact shape that moved Ben to Necromancer: another target family while 1350 is packed."""
    source, dest = tmp_path / 'source.sav', tmp_path / 'copy.sav'
    fixture_two(source)
    opts = dict(OPTIONS, packed=INTEG7_PACKED,
                target={'family': 14250, 'sprite_family': 1120, 'kind': 'humanoid'})
    with pytest.raises(ValueError, match='its own target'):
        migration.migrate_copy(source, dest, **opts)
    assert not dest.exists() and not (tmp_path / 'copy.sav.bak').exists()


def test_clear_legacy_zeroes_only_the_spare_area(tmp_path):
    source, dest = tmp_path / 'source.sav', tmp_path / 'cleared.sav'
    before = fixture_two(source)
    original = source.read_bytes()
    result = migration.clear_legacy(source, dest)
    assert source.read_bytes() == original == (tmp_path / 'cleared.sav.bak').read_bytes()
    after = savegame.Save(str(dest))
    ben = savegame.Unit(after, 0)
    assert ben.cls == 1355
    assert savegame._s16(after.state, ben.base + savegame.U_ROW) == 472
    assert savegame._u16(after.state, ben.base + migration.SUBCLASS) == 0
    assert after.flag(17336)
    area = bytes(after.state[ben.base + migration.MASTERY:ben.base + migration.MASTERY + 144])
    assert not any(area) and not area.startswith(packedmastery.MAGIC)
    allowed = {ben.base + migration.MASTERY + i for i in range(144)}
    assert {i for i in range(len(before.state)) if before.state[i] != after.state[i]} <= allowed
    assert len({i for i in range(len(before.state)) if before.state[i] != after.state[i]}) == 6
    assert result['units_cleared'][0]['counters']['47'] == [4, 4, 4, 4, 4, 4]
    assert result['units_cleared'][0]['nonzero_bytes'] == 6


def test_clear_legacy_refuses_stale_data_and_leaves_packed_areas_alone(tmp_path):
    source, dest = tmp_path / 'source.sav', tmp_path / 'cleared.sav'
    s = fixture_two(source)
    stale = savegame.Unit(s, 100)                            # outside army + reserve
    s.state[stale.base + migration.MASTERY] = 1
    source.write_bytes(s.to_bytes())
    before = source.read_bytes()
    with pytest.raises(ValueError, match='stale unit data'):
        migration.clear_legacy(source, dest)
    assert source.read_bytes() == before and not dest.exists()

    source.unlink()
    s = fixture_two(source)
    packed = packedmastery.encode_pool({1350: (128, 0, 0, 0, 0, 0)}, BASIC['thresholds'])
    s.state[savegame.Unit(s, 1).base + migration.MASTERY:
            savegame.Unit(s, 1).base + migration.MASTERY + 144] = packed
    source.write_bytes(s.to_bytes())
    result = migration.clear_legacy(source, dest)
    assert [c['slot'] for c in result['units_cleared']] == [0]
    after = savegame.Save(str(dest))
    keep = after.state[savegame.Unit(after, 1).base + migration.MASTERY:
                       savegame.Unit(after, 1).base + migration.MASTERY + 144]
    assert bytes(keep) == packed
