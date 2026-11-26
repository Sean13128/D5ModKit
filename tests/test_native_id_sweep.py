"""Synthetic x64 instructions only; no game or research fixtures."""
import importlib.util
from pathlib import Path
import unittest

try:
    from capstone import Cs, CS_ARCH_X86, CS_MODE_64
except ImportError:
    Cs=None

path=Path(__file__).resolve().parents[1]/'tools/native_id_sweep.py'
spec=importlib.util.spec_from_file_location('native_id_sweep',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


@unittest.skipUnless(Cs,'optional Capstone research dependency unavailable')
class NativeIdSweepTests(unittest.TestCase):
    def analyze(self, raw, bits=32):
        cs=Cs(CS_ARCH_X86,CS_MODE_64);cs.detail=True
        insns=list(cs.disasm(bytes.fromhex(raw),0x1000))
        return module.analyze(insns,{0x2000:dict(register='edx',bits=bits,role='synthetic-query')},{77},{0x80:'synthetic-id-array'})

    def test_literal_argument_records_assignment(self):
        q,_,_=self.analyze('ba4d000000 e8f60f0000')
        self.assertEqual(q[0]['id'],77)
        self.assertEqual(q[0]['assignment']['source']['address'],'0x1000')

    def test_call_and_branch_boundaries_refuse_propagation(self):
        for raw in ('ba4d000000 e800000000 e8f10f0000',
                    'ba4d000000 7500 e8f40f0000',
                    'ba4d000000 eb00 e8f40f0000'):
            q,_,_=self.analyze(raw)
            self.assertEqual(q[-1]['resolution'],'dynamic-or-unresolved')

    def test_memory_overwrite_does_not_retain_literal(self):
        q,_,_=self.analyze('ba4d000000 8b11 e8f40f0000')
        self.assertIsNone(q[0]['id'])

    def test_subregister_requires_enough_known_bits(self):
        raw='66ba4d00 e8f70f0000'
        self.assertIsNone(self.analyze(raw,32)[0][0]['id'])
        self.assertEqual(self.analyze(raw,16)[0][0]['id'],77)

    def test_matching_constant_is_not_automatically_an_evility(self):
        q,typed,literals=self.analyze('b84d000000 83f84d c3')
        self.assertFalse(q);self.assertFalse(typed)
        self.assertEqual(len(literals),2)

    def test_typed_memory_comparison_is_only_a_candidate(self):
        _,typed,_=self.analyze('8b8180000000 83f84d c3')
        self.assertEqual(typed[0]['confidence'],'field-offset-context-candidate')


if __name__=='__main__':unittest.main()
