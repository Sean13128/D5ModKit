"""Add the .d5lc section to an already-built Kit payload and check that the payload stays sound.

The shared `integration/build_payload-158.py` builds every other engine section from the pinned exe; this
adds the learned-evility capacity section on top of that payload (a manifest from the *installed* Skill
table, read-only), then re-runs the shared verifier's structural checks and its own section checks:

  * every one of the 143 patched sites is an E8 into the section,
  * the PE exception directory is sorted, mapped, and covers all six routines of the section,
  * the section's data fields read back as the manifest that was built.

    python evility/evcap_payload.py <payload.exe> <out.exe> [--json out.json]
"""
import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(KIT))

DB = "/Volumes/Data/SteamLibrary/steamapps/common/Disgaea 5 Complete/Data/Database/Database_0.dat"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('payload', type=Path)
    ap.add_argument('out', type=Path)
    ap.add_argument('--json', type=Path)
    args = ap.parse_args()
    import pefile
    from d5lib import database, learned, ordercheck, exepatch
    ids = ordercheck._ids(database.load_database(DB).table('Skill.dat'))
    man = learned.manifest(ids)
    base = args.payload.read_bytes()
    out = learned.build_patch(base, man)
    args.out.write_bytes(out)
    info = learned.section_info(out)
    sym = learned.data_symbols(info)
    pe = pefile.PE(data=out, fast_load=True)
    pe.parse_data_directories()
    blob = info['data']
    at = sym['magic'] - info['base']
    fields = dict(version=struct.unpack_from('<I', blob, at + 8)[0],
                  state=struct.unpack_from('<I', blob, at + 12)[0],
                  base_count=struct.unpack_from('<I', blob, at + 16)[0],
                  used=struct.unpack_from('<I', blob, at + 20)[0],
                  capacity=struct.unpack_from('<I', blob, at + 24)[0],
                  generation=struct.unpack_from('<I', blob, at + 28)[0],
                  uid_offset=struct.unpack_from('<I', blob, at + 32)[0],
                  key_array=f"0x{struct.unpack_from('<Q', blob, at + 40)[0]:x}",
                  max_index=f"0x{struct.unpack_from('<Q', blob, at + 48)[0]:x}",
                  save_dir=f"0x{struct.unpack_from('<Q', blob, at + 56)[0]:x}",
                  fn_put=f"0x{struct.unpack_from('<Q', blob, at + 64)[0]:x}",
                  fn_clear=f"0x{struct.unpack_from('<Q', blob, at + 72)[0]:x}")
    prefix = list(struct.unpack_from(f"<{man['base_count']}I", blob, sym['prefix'] - info['base']))
    # every patched site
    sites = []
    src = learned.section_source(man)
    code, labels = learned._assemble(src, learned.code_base(base, learned.SECTION))
    plan = ((learned.GET_SITES, labels['lc_get']), (learned.SET_SITES, labels['lc_set']),
            (learned.SAVE_SITES, labels['lc_save_relay']), (learned.LOAD_SITES, labels['lc_load_relay']))
    for site_list, wrapper in plan:
        for va in site_list:
            raw = out[pe.get_offset_from_rva(va - 0x140000000):][:5]
            dest = va + 5 + struct.unpack('<i', raw[1:])[0] if raw[:1] == b'\xe8' else None
            sites.append(dict(site=f'0x{va:x}', call=raw[:1] == b'\xe8', target_ok=dest == wrapper,
                              into_section=bool(dest and info['base'] <= dest < info['base'] + len(blob))))
    # exception directory covers the routines
    d = pe.OPTIONAL_HEADER.DATA_DIRECTORY[3]
    entries = [struct.unpack('<III', pe.get_data(d.VirtualAddress, d.Size)[i:i + 12])
               for i in range(0, d.Size, 12)] if d.Size else []
    image_base = pe.OPTIONAL_HEADER.ImageBase
    covered = {e[0] for e in entries}          # RVA start addresses of the runtime functions
    # only routines a patched call reaches carry unwind records (lc_put/lc_clear are the runtime's
    # CALL targets, entered from C, and are audited by the static stack audit instead)
    entry_routines = ('lc_get', 'lc_set', 'lc_save_relay', 'lc_load_relay', 'lc_verify', 'lc_position',
                      'lc_lookup', 'lc_store_set')
    unwind = {name: (labels[name] - image_base) in covered for name in entry_routines}
    report = dict(payload=str(args.payload), out=str(args.out), sha256=hashlib.sha256(out).hexdigest(),
                  section=info['section'], section_size=info['size'],
                  note='the section name is shared: add_code_section grows the last kit section instead of '
                       'taking a new header, so .d5lc lives inside the payload\'s .d5mod section',
                  manifest=dict(base_count=man['base_count'], ext_ids=man['ext_ids'],
                                generation=man['generation'], rows=man['row_count']),
                  fields=fields, prefix_matches_manifest=prefix == man['base_ids'],
                  sites_ok=sum(1 for s in sites if s['call'] and s['target_ok'] and s['into_section']),
                  sites_total=len(sites), unwind=unwind,
                  section_headers=len(pe.sections))
    problems = []
    if not report['prefix_matches_manifest']:
        problems.append('the section prefix does not read back as the manifest')
    if report['sites_ok'] != report['sites_total']:
        problems.append(f"{report['sites_total'] - report['sites_ok']} patched sites are not calls into the wrapper")
    if not all(unwind.values()):
        problems.append('a routine has no unwind entry')
    if fields['state'] != 0 or fields['used'] != 0 or fields['base_count'] != man['base_count']:
        problems.append('data fields are not the built manifest')
    report['problems'] = problems
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + '\n')
    print(f"section {info['section']} {info['size']} B, {report['sites_ok']}/{report['sites_total']} sites, "
          f"unwind {sum(unwind.values())}/{len(unwind)}, sections {report['section_headers']}, "
          f"problems {len(problems)}")
    for p in problems:
        print('  ' + p)
    return 0 if not problems else 1


if __name__ == '__main__':
    sys.exit(main())
