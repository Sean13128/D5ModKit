"""Section-header capacity: kit features share one code section instead of spending a header each.

The pinned exe holds 11 section headers and vanilla uses 7. Every feature that appended its own header would run
out after four; `exepatch` grows the last kit section instead, so the whole kit costs one header. These are
synthetic PEs -- no game files, no native execution.
"""
import struct

import pefile

from d5lib import exepatch

BASE = exepatch.IMAGE_BASE
SITE = BASE + 0x1020             # five 0xCC bytes inside .text, a hook site with no exemap translation


def fixture(size_of_headers=0x400):
    """a minimal PE: .text (exec) + .pdata with one runtime function, no game data"""
    data = bytearray(0x800)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HHIIIHH', data, 0x84, 0x8664, 2, 0, 0, 0, 0xf0, 0x22)
    oh = 0x98
    struct.pack_into('<H', data, oh, 0x20b)
    struct.pack_into('<Q', data, oh + 24, BASE)
    struct.pack_into('<II', data, oh + 32, 0x1000, 0x200)
    struct.pack_into('<II', data, oh + 56, 0x3000, size_of_headers)
    struct.pack_into('<I', data, oh + 108, 16)
    struct.pack_into('<II', data, oh + 112 + 3 * 8, 0x2000, 12)
    for n, (name, rva, raw, flags) in enumerate([
            (b'.text', 0x1000, 0x400, 0x60000020),
            (b'.pdata', 0x2000, 0x600, 0x40000040)]):
        struct.pack_into('<8sIIIIIIHHI', data, oh + 0xf0 + 40 * n,
                         name, 0x200, rva, 0x200, raw, 0, 0, 0, 0, flags)
    data[0x400:0x600] = b'\xcc' * 0x200
    struct.pack_into('<III', data, 0x600, 0x1000, 0x1001, 0x2010)
    data[0x610:0x614] = bytes((1, 0, 0, 0))
    return bytes(data)


def tight_headers():
    """the same PE with SizeOfHeaders cut to the section table: room for exactly one more header"""
    raw = bytearray(fixture())
    struct.pack_into('<I', raw, 0x98 + 60, 0x200)
    return bytes(raw)


def names(exe):
    pe = pefile.PE(data=exe, fast_load=True)
    return [s.Name.rstrip(b'\0').decode('ascii', 'replace') for s in pe.sections]


def build_hook(exe, name, site=SITE, digest=None):
    return exepatch.add_hook_section(exe, name, [], native_hooks=[(site, b'\xcc' * 5, '    ret', 0xE9)],
                                     digest=digest)


def test_first_feature_takes_one_header_then_every_feature_shares_it():
    exe = fixture()
    before = len(names(exe))
    # the unwind sections (.d5el, .d5cm) are covered separately: they need a claim header and real code
    features = [b'.d5mod', b'.d5ev', b'.d5cl', b'.d5qr', b'.d5ul', b'.d5wl', b'.d5sg',
                b'.d5ei', b'.d5c4', b'.d5fx', b'.d5id', b'.d5sc', b'.d5auto']
    for n, name in enumerate(features):
        exe = build_hook(exe, name, SITE + 8 * n)
    # the first feature took a header; the other fourteen grew into it (15 features, 4 headers available)
    assert len(names(exe)) == before + 1
    assert names(exe)[-1] == '.d5mod'
    for name in features:
        assert exepatch.has_feature(exe, name), name
    assert not exepatch.has_feature(exe, b'.d5nope')
    # every hook site still lands inside that one section, and its code is intact
    pe = pefile.PE(data=exe, fast_load=True)
    last = max(pe.sections, key=lambda s: s.VirtualAddress)
    lo, hi = BASE + last.VirtualAddress, BASE + last.VirtualAddress + last.Misc_VirtualSize
    for n in range(len(features)):
        at = SITE + 8 * n
        op = exe[pe.get_offset_from_rva(at - BASE)]
        rel = struct.unpack('<i', exe[pe.get_offset_from_rva(at - BASE) + 1:][:4])[0]
        assert op == 0xE9
        assert lo <= at + 5 + rel < hi


def test_no_header_room_grows_the_last_kit_section_instead_of_raising():
    exe = fixture()                      # headers: 0x400, table ends 0x1d8 (4 more fit)
    exe = build_hook(exe, b'.d5mod')
    assert len(names(exe)) == 3
    exe = bytearray(exe)
    struct.pack_into('<I', exe, 0x98 + 60, 0x200)      # room for 0 more: table now ends at 0x200
    exe = bytes(exe)
    grown = build_hook(exe, b'.d5ev', SITE + 8)
    assert len(names(grown)) == 3, 'no second header may be taken'
    assert exepatch.has_feature(grown, b'.d5ev') and exepatch.has_feature(grown, b'.d5mod')
    assert exepatch.is_patched(grown)


def test_no_header_room_without_a_kit_section_says_why():
    exe = fixture()
    n = 0
    while True:                          # spend every free header on non-kit sections
        try:
            exe = exepatch.add_hook_section(exe, b'.zz%d' % n, [],
                                            native_hooks=[(SITE + 8 * n, b'\xcc' * 5, '    ret', 0xE9)])
        except ValueError:
            break
        n += 1
        assert n < 20, 'the header table never filled'
    assert len(names(exe)) == n + 2      # .text and .pdata plus one per non-kit section
    try:
        build_hook(exe, b'.d5mod', SITE + 8 * n)
    except ValueError as exc:
        message = str(exc)
    assert 'no room for another section header' in message
    assert '.d5mod' in message and '.zz' in message


def test_a_non_kit_last_section_never_grows():
    exe = fixture() + b'overlay'         # the overlay, not a kit section, ends the file
    out = build_hook(exe, b'.d5mod')
    assert len(names(out)) == 3          # took a header instead of growing
    assert b'overlay' in out


def test_an_overlay_after_a_kit_section_takes_a_new_header():
    exe = build_hook(fixture(), b'.d5mod') + b'\0overlay'
    out = build_hook(exe, b'.d5ev', SITE + 8)
    assert len(names(out)) == 4          # could not grow past the overlay, but a header was still free
    assert exepatch.has_feature(out, b'.d5ev')
    assert b'overlay' in out


def test_a_data_only_kit_section_is_not_grown():
    exe = bytearray(fixture())
    # a kit section without IMAGE_SCN_MEM_EXECUTE as the last section
    struct.pack_into('<8sIIIIIIHHI', exe, 0x98 + 0xf0 + 40 * 2, b'.d5dt', 0x10, 0x3000, 0x10, 0x800,
                     0, 0, 0, 0, 0x40000040)
    struct.pack_into('<H', exe, 0x86, 3)
    struct.pack_into('<I', exe, 0x98 + 56, 0x4000)
    out = build_hook(bytes(exe) + b'\0' * 0x10, b'.d5mod')
    assert len(names(out)) == 4 and exepatch.has_feature(out, b'.d5mod')
    assert names(out)[-1] == '.d5mod'


def test_claim_block_names_the_feature_and_its_code_length():
    exe = build_hook(fixture(), b'.d5ev')
    block = exepatch.CLAIM_MAGIC + b'.d5ev\0\0\0'
    at = exe.rindex(block)
    length, digest = struct.unpack('<II', exe[at + 14:at + 22])
    assert length == 1                   # the `ret` of the one hook
    assert digest == 0                   # this feature has no configuration to compare
    assert exepatch.CLAIM_SIZE == 28


def test_a_stray_claim_magic_is_not_a_feature():
    """P2: has_feature must not accept a coincidence.  A magic + name inside code, with no room for the rest of the
    block, or naming a region that starts before the section, is not a claim."""
    exe = build_hook(build_hook(fixture(), b'.d5ev'), b'.d5mod', site=SITE + 8)
    forged = bytearray(exe)
    pe = pefile.PE(data=exe, fast_load=True)
    section = pe.sections[-1]
    start = section.PointerToRawData
    size = section.Misc_VirtualSize
    # a magic and a name at the head of the section, where no claim block can start: whatever follows them is
    # either too short for the block or describes a region that leaves the section
    forged[start:start + 20] = exepatch.CLAIM_MAGIC + b'.d5xx\0\0\0' + b'\0' * 2 + b'\0' * 4
    assert not exepatch.has_feature(bytes(forged), b'.d5xx')
    claims = exepatch.feature_claims(bytes(forged))
    assert not [c for c in claims if c['name'] == b'.d5xx' and c['valid']]


def test_a_claim_from_other_inputs_counts_as_not_installed():
    """P2: a claim carrying a different configuration digest is stale, so the feature is rebuilt instead of skipped."""
    import struct as _s
    exe = build_hook(fixture(), b'.d5ev', digest=0x1234)
    assert exepatch.has_feature(exe, b'.d5ev', digest=0x1234)
    assert not exepatch.has_feature(exe, b'.d5ev', digest=0x5678)
    assert exepatch.has_feature(exe, b'.d5ev')      # a caller with no configuration still sees the claim


def test_a_claim_whose_hook_does_not_land_is_not_installed():
    """P2: a half-applied patch (hook site back to its original bytes) must not suppress the rebuild."""
    exe = bytearray(build_hook(fixture(), b'.d5ev'))
    assert exepatch.has_feature(bytes(exe), b'.d5ev', hooks=[(SITE, 0xE9)])
    pe = pefile.PE(data=bytes(exe), fast_load=True)
    off = pe.get_offset_from_rva(SITE - BASE)
    # still a jmp, but no longer into the kit section (back into .text)
    exe[off:off + 5] = b'\xe9' + struct.pack('<i', (BASE + 0x1000) - (SITE + 5))   # jmp back into .text
    assert not exepatch.has_feature(bytes(exe), b'.d5ev', hooks=[(SITE, 0xE9)])


def test_unwind_sections_share_the_grown_section_and_keep_the_directory_valid():
    raw = fixture()
    entries = []
    for name in (b'.d5el', b'.d5cm'):
        base = exepatch.code_base(raw)
        # a 16-byte claim header then a fixed frame (sub rsp,0x28 / add rsp,0x28 / ret), as the
        # .d5el and .d5cm writers lay them out (the unwind emitter starts at base + 16)
        code = b'D5TEST\0\0\0\0\0\0\0\0\0\0' + b'\x48\x83\xec\x28\x48\x83\xc4\x28\xc3'
        patches = [(SITE + (0 if name == b'.d5el' else 8), b'\xcc' * 5, base + 16, 0xE8)]
        raw = exepatch.add_code_section(raw, name, code, patches)
        pe = pefile.PE(data=raw)
        directory = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
        assert directory.Size % 12 == 0
        table = list(struct.iter_unpack('<III', pe.get_data(directory.VirtualAddress, directory.Size)))
        assert table == sorted(table)
        assert all(a < b and u % 4 == 0 for a, b, u in table)
        assert all(left[1] <= right[0] for left, right in zip(table, table[1:]))
        assert len(table) > len(entries)                  # vanilla entries kept, new ones added
        assert table[:len(entries)] == entries
        entries = table
    assert len(names(raw)) == 3                            # .d5cm grew into .d5el: one header for both
    sections = {exepatch.has_feature(raw, n) for n in (b'.d5el', b'.d5cm')}
    assert sections == {True}
    pe = pefile.PE(data=raw)
    kit = [s for s in pe.sections if s.Name.startswith(b'.d5')]
    assert len(kit) == 1
    lo = BASE + kit[0].VirtualAddress
    hi = lo + kit[0].Misc_VirtualSize
    for _, _, unwind in entries:
        if BASE + kit[0].VirtualAddress <= BASE + unwind < hi:
            assert pe.get_data(unwind, 1) == b'\x01'


def test_existing_section_payload_is_preserved_when_growing():
    exe = build_hook(fixture(), b'.d5mod')
    pe = pefile.PE(data=exe, fast_load=True)
    last = max(pe.sections, key=lambda s: s.VirtualAddress)
    old = pe.get_data(last.VirtualAddress, last.Misc_VirtualSize)
    exe2 = build_hook(exe, b'.d5ev', SITE + 8)
    pe2 = pefile.PE(data=exe2, fast_load=True)
    last2 = max(pe2.sections, key=lambda s: s.VirtualAddress)
    new = pe2.get_data(last2.VirtualAddress, last2.Misc_VirtualSize)
    assert new.startswith(old)
    assert pe2.OPTIONAL_HEADER.SizeOfImage >= last2.VirtualAddress + last2.Misc_VirtualSize


def test_thirty_features_share_the_same_single_section():
    """more features than the exe has free headers (4) or even total headers (11) still fit"""
    exe = fixture()
    before = len(names(exe))
    features = [b'.d5f%02d' % n for n in range(30)]
    for n, name in enumerate(features):
        exe = build_hook(exe, name, SITE + 8 * n)
    assert len(names(exe)) == before + 1
    assert all(exepatch.has_feature(exe, name) for name in features)
    pe = pefile.PE(data=exe, fast_load=True)
    assert pe.OPTIONAL_HEADER.SizeOfImage >= max(
        s.VirtualAddress + s.Misc_VirtualSize for s in pe.sections)


def test_a_writable_feature_makes_the_shared_section_writable_and_keeps_it_executable():
    exe = build_hook(fixture(), b'.d5fx', SITE)                 # read-only kit section first
    pe = pefile.PE(data=exe, fast_load=True)
    assert max(pe.sections, key=lambda s: s.VirtualAddress).Characteristics == 0x60000020
    exe = exepatch.add_hook_section(exe, b'.d5auto', [],
                                    native_hooks=[(SITE + 8, b'\xcc' * 5, '    ret', 0xE9)], writable=True)
    pe = pefile.PE(data=exe, fast_load=True)
    shared = max(pe.sections, key=lambda s: s.VirtualAddress)
    assert shared.Name.startswith(b'.d5fx')                     # grew, no second header
    assert shared.Characteristics & 0x80000000                  # IMAGE_SCN_MEM_WRITE
    assert shared.Characteristics & 0x20000000                  # still executable
    assert exepatch.has_feature(exe, b'.d5auto')
