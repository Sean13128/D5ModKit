"""MASKWIDE1: the second family word (flags bits 8..31) through the REAL counter call site 0x140547333 (Unicorn).

The u32 family mask is full, so a new kind of row lives in flags bits 8..31 and is asked for with a 64-bit query
(`mov rdi, bit << 32`).  A throwaway family `test_counter` (second-word bit 0) is wired to the existing counter wrapper by
rewriting that wrapper's `mov edi, 32768` in a scratch copy of the asm; the shipped asm is not touched.  What must hold:

  * a row in the second word is found by the 64-bit query (counter allowed), its conditions are honoured;
  * it is invisible to every old 32-bit query (the unmodified counter wrapper does not see it), and an old row is
    invisible to the second-word query (no cross talk);
  * with the second word ignored (--control ignore) or the query truncated to 32 bits (--control trunc) the proof FAILS.

<unicorn python> evility/offline_proof_maskwide1.py [--abi] [--control ignore|trunc]
"""
import argparse
import hashlib
import os
import sys
from pathlib import Path

KIT = Path(os.environ.get('D5_KIT', Path(__file__).resolve().parents[1]))
sys.path[:0] = [str(KIT), str(KIT / 'evility')]
import offline_proof_ex06 as p6                         # noqa: E402
from d5lib import evility as ev                         # noqa: E402

SCRATCH = Path('/Volumes/Data/ai-tmp/claude/maskwide1')
TEST = 'test_counter'
SHIPPED_ASM = ev.ASM_FILE
OLD_QUERY = "    mov edi, 32768\n    call evil_pred\n    mov r14d, eax\n.k_ret:"


def mutated_asm(control, ext_query=True):
    text = Path(ev.ASM_FILE).read_text()
    assert text.count(OLD_QUERY) == 1
    if ext_query:
        new_q = "    mov rdi, 0x100000000\n" if control != 'trunc' else "    mov edi, 0x100000000\n"
        text = text.replace(OLD_QUERY, new_q + OLD_QUERY.split("\n", 1)[1])
    if control == 'ignore':
        old = "    mov eax, dword ptr [rdx + 24]     // MASKWIDE1: the row's second family word, flags bits 8..31\n"
        assert text.count(old) == 1
        text = text.replace(old, "    xor eax, eax\n")
    out = SCRATCH / f'd5evil-maskwide1-{control or "ok"}-{int(ext_query)}.inc.asm'
    out.write_text(text)
    return str(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abi', action='store_true')
    ap.add_argument('--control', choices=('ignore', 'trunc'))
    args = ap.parse_args()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    from abi_engine_ex05c import execute
    original = p6.ORIGINAL.read_bytes()
    assert hashlib.sha256(original).hexdigest() == p6.ORIGINAL_SHA
    ev.EXT_FAMILIES[TEST] = 0
    assert ev.ext_query(TEST) == 0x100000000
    specs = [(n, t, s) for n, (_, t, s) in ((n, ev.wrapper(n)) for n in (
        'potency', 'stats', 'growth', 'dealt', 'taken', 'flight_a', 'flight_b', 'hit', 'status_chance', 'conversion',
        'crit_rate', 'regen', 'achance', 'nullify', 'counter'))]
    _, target, sites = next(s for s in specs if s[0] == 'counter')
    rows = {
        '7100': {'family': TEST},
        '7101': {'family': TEST, 'condition': {'kind': 'char', 'id': 10}},
        '7102': {'family': TEST, 'condition': {'kind': 'char', 'id': 99}},
        '7103': {'family': 'counter'},                          # an OLD row (mask 32768)
        '7104': {'family': 'potency', 'effects': [{'stat': 'atk', 'value': 1}]},
    }
    # (name, learned ids, expected answer with the test query wired in, expected with the shipped wrapper)
    cases = [
        ('ext row allows the counter', (7100,), 1, 0),
        ('ext row, condition holds', (7101,), 1, 0),
        ('ext row, condition fails', (7102,), 0, 0),
        ('no row: the game answer stands', (), 0, 0),
        ('old counter row is not seen by the ext query', (7103,), 0, 1),
        ('old potency row is not seen by the ext query', (7104,), 0, 0),
        ('ext row beside an old counter row', (7100, 7103), 1, 1),
    ]
    ok = n = 0
    for wired, label in ((True, 'ext query'), (False, 'shipped query')):
        if args.control and not wired:
            continue
        ev.ASM_FILE = mutated_asm(args.control, ext_query=True) if wired else SHIPPED_ASM
        patched = ev.build_patch(original, rows)
        info = ev.section_info(patched)
        for name, ids, want_wired, want_shipped in cases:
            want = want_wired if wired else want_shipped
            try:
                detail = execute(patched, info, specs, 'counter', target, sites[0], ids=ids, abi=args.abi,
                                 fixture=p6.dealt(ids=ids))
                got = detail['output']
            except Exception as exc:                       # noqa: BLE001
                got = f'{type(exc).__name__}: {exc}'
            good = got == want
            n += 1
            ok += good
            print(f"{'ok  ' if good else 'FAIL'} [{label}] {name}: got {got}, expected {want}")
    print(f"{ok}/{n} {'abi' if args.abi else 'behavior'}")
    return 0 if ok == n else 1


if __name__ == '__main__':
    sys.exit(main())
