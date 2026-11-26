"""Typed conversion harness uses synthetic review contracts, never native-fidelity claims."""
import copy
import struct
import unittest

from d5lib import d4inventory, d4scripts as ds, script


def proved(**fields):
    return dict(status="verified", source_evidence=["synthetic source contract"],
                target_evidence=["synthetic receiver contract"], **fields)


def spec(role="number", source_bits=16, target_bits=16, signed=True, source_scale=(1, 1), target_scale=(1, 1)):
    return proved(role=role, source_type=dict(bits=source_bits, signed=signed, scale=list(source_scale)),
                  target_type=dict(bits=target_bits, signed=signed, scale=list(target_scale)))


def command(opcode, operands=None, **fields):
    return proved(target_opcode=opcode, native_equivalence="verified", operands=operands or {}, **fields)


def pack(events, parser=script):
    sf = parser.ScriptFile()
    sf.events = events
    return sf.to_bytes()


class ScriptsTests(unittest.TestCase):
    def fixture(self, body=None):
        p = d4inventory.script_reader()
        if body is None:
            branch = p.Ins(0x0140, conds=[p.Cond(p.Var(10001), 0x0A, 1)])
            done = p.Ins(0x0108)
            branch.target = done
            body = [branch, p.Ins(0x4418, [1, 255, 0, 0, 0, 0]), p.Ins(0x0148), done]
        roots = [p.Event(base + 1, [p.Ins(0x0104, [100]), p.Ins(0x0108)])
                 for base in (12000000, 12100000, 12200000)]
        source = ds.Source(pack([p.Event(100, body), *roots], p))
        receiver = ds.Receiver(pack([script.Event(42, [script.Ins(0x0108)])]))
        contracts = dict(schema=ds.CONTRACT_SCHEMA, source_script_sha256=source.sha256,
                         receiver_script_sha256=receiver.sha256, commands={
                             "0104": command("0104", {"arg.0": spec("event", 24, 24, False)}),
                             "0108": command("0108"), "0148": command("0148"),
                             "0140": command("0140", {"condition.0.lhs": spec(), "condition.0.rhs": spec()},
                                             comparisons={"10": proved(target=10)}, logic={}),
                             "4418": command("4418", {f"arg.{i}": spec(source_bits=s * 8, target_bits=t * 8)
                                                       for i, (s, t) in enumerate(zip(p.SIGS[0x4418], script.SIGS[0x4418]))}),
                         }, variables={"1:10001": proved(namespace="local", role="number", target_kind=1, target_id=20001,
                                                         source_type=spec()["source_type"], target_type=spec()["target_type"],
                                                         value_domain_verified=True)})
        occupancy = dict(complete=True, receiver_script_sha256=receiver.sha256, event_ids=[16500000],
                         evidence=["synthetic complete occupancy"])
        return source, receiver, contracts, occupancy

    def run_scene(self, fixture):
        s, r, c, o = fixture
        return ds.translate_scene(s, r, 1, c, occupancy=o)

    def test_closed_scene_emits_readable_bundle_and_preserves_widened_branch_destination(self):
        source, receiver, contracts, occupancy = self.fixture()
        report, bundle = self.run_scene((source, receiver, contracts, occupancy))
        self.assertIsNotNone(bundle)
        self.assertEqual(report["summary"]["emitted_events"], 4)
        self.assertNotIn(16500000, report["event_allocations"].values())
        parsed = script.ScriptFile.from_bytes(bundle, strict=True)
        body = parsed.get(report["event_allocations"]["100"])
        self.assertIs(body.code[0].target, body.code[-1])
        self.assertEqual(body.code[0].conds[0].lhs.id, 20001)
        self.assertEqual(body.code[1].args[1], 65535)  # signed 8-bit -1 sign-extends to 16-bit
        source_body = source.event(100)
        self.assertEqual(len(body.encode()) - source_body["source_bytes"], 4)
        for root in parsed.events:
            if root is not body:
                self.assertEqual(root.code[0].args[0], body.id)
        self.assertEqual(parsed.to_bytes(), bundle)
        self.assertEqual(report["acceptance"]["gameplay"], "not-tested")

    def test_unknown_command_blocks_itself_and_all_callers(self):
        fixture = self.fixture()
        del fixture[2]["commands"]["4418"]
        report, bundle = self.run_scene(fixture)
        self.assertIsNone(bundle)
        self.assertEqual(report["summary"]["blocked_events"], 4)
        self.assertTrue(any(i["reason"] == "blocked-callee-closure" for e in report["events"] for i in e["issues"]))

    def test_partial_native_input_domain_blocks_wait_one_and_dynamic_values(self):
        p = d4inventory.script_reader()
        for value, expected in ((2, None), (32767, None), (1, "source-literal-outside-reviewed-range"),
                                (65535, "source-literal-outside-reviewed-range"),
                                (p.Var(10001), "source-literal-range-requires-literal")):
            with self.subTest(value=value):
                fixture = self.fixture([p.Ins(0x0A00, [value]), p.Ins(0x0108)])
                operand = spec()
                operand["source_literal_range"] = [2, 32767]
                fixture[2]["commands"]["0a00"] = command("0a00", {"arg.0": operand})
                report, bundle = self.run_scene(fixture)
                body = next(e for e in report["events"] if e["source_id"] == 100)
                coverage = body["instruction_coverage"][0]
                if expected:
                    self.assertIsNone(bundle)
                    self.assertEqual(coverage["reason"], expected)
                    self.assertEqual(report["summary"]["blocked_events"], 4)
                else:
                    self.assertIsNotNone(bundle)
                    self.assertEqual(coverage["status"], "compiled-under-supplied-contract")

    def test_reviewed_literal_range_is_signed_before_scale_and_sentinels(self):
        s, r, c, o = self.fixture()
        translator = ds.Translator(s, r, c, {}, o)
        operand = spec(source_bits=8, target_bits=16, source_scale=(1, 10), target_scale=(1, 10))
        operand["source_literal_range"] = [-2, -1]
        self.assertEqual(translator.operand(255, operand, 1, 2), 65535)
        self.assertEqual(translator.operand(254, operand, 1, 2), 65534)
        operand["sentinels"] = {"0": proved(target_raw=0)}
        with self.assertRaisesRegex(ds.ContractError, "outside-reviewed-range"):
            translator.operand(0, operand, 1, 2)

    def test_malformed_literal_review_ranges_fail_closed(self):
        s, r, c, o = self.fixture()
        translator = ds.Translator(s, r, c, {}, o)
        for bounds in (None, "2,3", [2], [3, 2], [False, 2], [2, 3.0], [-32769, 2], [2, 32768]):
            with self.subTest(bounds=bounds):
                operand = spec()
                operand["source_literal_range"] = bounds
                with self.assertRaisesRegex(ds.ContractError, "invalid-source-literal-range"):
                    translator.operand(2, operand, 2, 2)

    def test_mode_instruction_coverage_keeps_partial_translation_distinct_from_emission(self):
        fixture = self.fixture()
        del fixture[2]["commands"]["4418"]
        report, bundle = self.run_scene(fixture)
        self.assertIsNone(bundle)
        for mode in report["mode_coverage"].values():
            self.assertEqual(mode["events"], 2)
            self.assertEqual(mode["instructions"], 6)
            self.assertEqual(mode["compiled_instructions"], 5)
            self.assertEqual(mode["blocked_instructions"], 1)
            self.assertEqual(mode["undecoded_events"], [])
        fixture[2]["commands"]["4418"] = command("4418")
        fixture[2]["commands"]["4418"]["native_equivalence"] = "unresolved"
        report, _ = self.run_scene(fixture)
        command_report = next(c for c in report["required_contracts"]["commands"] if c["opcode"] == "4418")
        self.assertEqual(command_report["status"], "missing")

    def test_event_reference_cannot_be_mislabeled_as_scalar_to_bypass_fresh_ids(self):
        fixture = self.fixture()
        fixture[2]["commands"]["0104"]["operands"]["arg.0"]["role"] = "number"
        report, bundle = self.run_scene(fixture)
        self.assertIsNone(bundle)
        self.assertTrue(any(i["reason"] == "event-call-reference-not-remapped" for e in report["events"] for i in e["issues"]))

    def test_enum_values_need_context_domains(self):
        s, r, c, o = self.fixture()
        t = ds.Translator(s, r, c, {}, o)
        enum = spec("enum")
        with self.assertRaisesRegex(ds.ContractError, "enum-domain"):
            t.operand(1, enum, 2, 2)
        enum["namespace"] = "enum:assignment-operation"
        c["namespaces"] = {"enum:assignment-operation": {"1": proved(target=2)}}
        self.assertEqual(t.operand(1, enum, 2, 2), 2)

    def test_variable_destination_requires_bank_and_value_domain_contract(self):
        p = d4inventory.script_reader()
        fixture = self.fixture([p.Ins(0x1400, [1, 10500, 1, 1]), p.Ins(0x0108)])
        c = fixture[2]
        bank, operation = spec("enum", 8, 8, False), spec("enum", 8, 8, False)
        bank["namespace"], operation["namespace"] = "enum:storage", "enum:assignment"
        c["commands"]["1400"] = command("1400", {"arg.0": bank, "arg.1": spec("variable-address", signed=False),
                                                   "arg.2": operation, "arg.3": spec()})
        c["namespaces"] = {"enum:storage": {"1": proved(target=1)}, "enum:assignment": {"1": proved(target=1)}}
        c["variable_addresses"] = {"1:10500": proved(namespace="flag", target_id=20500, target_raw=1, value_domain_verified=True)}
        report, bundle = self.run_scene(fixture)
        self.assertIsNotNone(bundle)
        body = script.ScriptFile.from_bytes(bundle).get(report["event_allocations"]["100"])
        self.assertEqual(body.code[0].args[1], 20500)
        c["variable_addresses"]["1:10500"]["target_raw"] = 2
        self.assertIsNone(self.run_scene(fixture)[1])

    def test_fingerprint_or_occupancy_failure_prevents_any_emission(self):
        for field in ("source_script_sha256", "receiver_script_sha256"):
            fixture = self.fixture()
            fixture[2][field] = "wrong"
            report, bundle = self.run_scene(fixture)
            self.assertIsNone(bundle)
            self.assertEqual(report["summary"]["ready_events"], 0)
        fixture = self.fixture()
        fixture[3]["complete"] = False
        self.assertIsNone(self.run_scene(fixture)[1])

    def test_source_duplicate_event_and_unknown_grammar_fail_closed(self):
        p = d4inventory.script_reader()
        raw = pack([p.Event(1, [p.Ins(0x0108)]), p.Event(1, [p.Ins(0x0108)])], p)
        self.assertEqual(ds.Source(raw).event(1)["error"], "ambiguous-source-event")
        raw = struct.pack("<III", 1, 0, 100) + b"\xff\xff"
        self.assertIn("unknown script command", ds.Source(raw).event(100)["error"])

    def test_fresh_allocator_exhaustion_collisions_and_call_width(self):
        self.assertEqual(ds.allocate_events([2, 1], {10, 12}, 10, 13), {1: 11, 2: 13})
        for args in (([1, 2], {10}, 10, 11), ([1, 1], set(), 1, 10), ([1], set(), 1, 1 << 24)):
            with self.assertRaises(ValueError):
                ds.allocate_events(*args)

    def test_occupied_event_ids_reject_coercions_booleans_and_outside_u32(self):
        for invalid in ("16500000", True, False, 16500000.0, None, -1, 1 << 32):
            with self.subTest(invalid=invalid):
                fixture = self.fixture()
                fixture[3]["event_ids"] = [invalid]
                with self.assertRaisesRegex(ValueError, "u32"):
                    self.run_scene(fixture)
                with self.assertRaisesRegex(ValueError, "u32"):
                    ds.allocate_events([100], [invalid])
        fixture = self.fixture()
        fixture[3]["event_ids"] = "16500000"
        with self.assertRaisesRegex(ValueError, "JSON array"):
            self.run_scene(fixture)

    def test_occupied_u32_ids_can_exceed_call_width_without_affecting_proposals(self):
        # The actual original D5 directory contains event 150208011.
        self.assertEqual(ds.allocate_events([100], [0, 150208011, (1 << 32) - 1], 16500000, 16500000), {100: 16500000})

    def test_signed_unsigned_sentinel_scaling_and_overflow_are_explicit(self):
        s, r, c, o = self.fixture()
        translator = ds.Translator(s, r, c, {}, o)
        self.assertEqual(translator.operand(255, spec(source_bits=8, target_bits=16), 1, 2), 65535)
        self.assertEqual(translator.operand(255, spec(source_bits=8, target_bits=16, signed=False), 1, 2), 255)
        scaled = spec(source_scale=(1, 10), target_scale=(1, 1))
        self.assertEqual(translator.operand(120, scaled, 2, 2), 12)
        with self.assertRaisesRegex(ds.ContractError, "rounding"):
            translator.operand(121, scaled, 2, 2)
        with self.assertRaisesRegex(ds.ContractError, "overflow"):
            translator.operand(32767, spec(target_bits=8), 2, 1)
        sentinel = spec(source_bits=8, target_bits=16, signed=False)
        sentinel["sentinels"] = {"255": proved(target_raw=65535)}
        self.assertEqual(translator.operand(255, sentinel, 1, 2), 65535)

    def test_same_number_or_name_cannot_supply_missing_resource_contract(self):
        s, r, c, o = self.fixture()
        t = ds.Translator(s, r, c, {}, o)
        with self.assertRaisesRegex(ds.ContractError, "missing-namespace-map"):
            t.operand(104, spec("effect"), 2, 2)
        c["namespaces"] = {"effect": {"104": proved(target=104, dependency_status="not-converted")}}
        with self.assertRaisesRegex(ds.ContractError, "unready-resource"):
            t.operand(104, spec("effect"), 2, 2)
        c["namespaces"]["effect"]["104"]["dependency_status"] = "ready"
        self.assertEqual(t.operand(104, spec("effect"), 2, 2), 104)

    def test_qualified_resource_namespaces_keep_readiness_gate(self):
        for role in ("effect", "sound", "voice", "sprite", "motion"):
            with self.subTest(role=role):
                s, r, c, o = self.fixture()
                t = ds.Translator(s, r, c, {}, o)
                namespace = role + ":bank"
                operand_spec = spec(role)
                operand_spec["namespace"] = namespace
                c["namespaces"] = {namespace: {"104": proved(target=104, dependency_status="not-converted")}}
                with self.assertRaisesRegex(ds.ContractError, "unready-resource"):
                    t.operand(104, operand_spec, 2, 2)
                c["namespaces"][namespace]["104"]["dependency_status"] = "ready"
                self.assertEqual(t.operand(104, operand_spec, 2, 2), 104)

    def test_namespace_roots_and_spelling_cannot_change_operand_role(self):
        s, r, c, o = self.fixture()
        t = ds.Translator(s, r, c, {}, o)
        for namespace in ("actor:bank", "effect:", "effect::bank", "Effect:bank", "effect :bank", "effect: bank"):
            with self.subTest(namespace=namespace):
                operand_spec = spec("effect")
                operand_spec["namespace"] = namespace
                c["namespaces"] = {namespace: {"104": proved(target=104, dependency_status="ready")}}
                with self.assertRaises(ds.ContractError):
                    t.operand(104, operand_spec, 2, 2)

    def test_variable_rename_without_runtime_value_domain_is_rejected(self):
        fixture = self.fixture()
        fixture[2]["variables"]["1:10001"]["value_domain_verified"] = False
        report, bundle = self.run_scene(fixture)
        self.assertIsNone(bundle)
        self.assertTrue(any("runtime-value-domain" in i["reason"] for e in report["events"] for i in e["issues"]))

    def test_mismatched_variable_consumer_role_is_rejected(self):
        s, r, c, o = self.fixture()
        t = ds.Translator(s, r, c, {}, o)
        with self.assertRaisesRegex(ds.ContractError, "runtime-value-domain"):
            t.operand(script.Var(10001), spec("actor"), 2, 2)

    def test_dynamic_call_is_never_assumed_to_match_literal_closure(self):
        p = d4inventory.script_reader()
        fixture = self.fixture([p.Ins(0x0104, [p.Var(10001)]), p.Ins(0x0108)])
        report, bundle = self.run_scene(fixture)
        self.assertIsNone(bundle)
        self.assertIn("dynamic-call-closure-incomplete", report["global_issues"])
        self.assertEqual(len(report["modes"]["normal"]["dynamic_calls"]), 1)

    def test_argument_interface_required_even_with_known_callee(self):
        s, r, c, o = self.fixture()
        p = s.parser
        roots = [p.Event(base + 1, [p.Ins(0x0104, [100, 120]), p.Ins(0x0108)])
                 for base in (12000000, 12100000, 12200000)]
        s = ds.Source(pack([s.event(100)["event"], *roots], p))
        c["source_script_sha256"] = s.sha256
        report, bundle = ds.translate_scene(s, r, 1, c, occupancy=o)
        self.assertIsNone(bundle)
        self.assertTrue(any("missing-callee-argument-interface" in i["reason"] for e in report["events"] for i in e["issues"]))
        parameter = spec(source_bits=32, target_bits=32, source_scale=(1, 10), target_scale=(1, 10))
        parameter["callee_variable"] = "1:10001"
        c["interfaces"] = {"100": proved(arguments=[parameter])}
        report, bundle = ds.translate_scene(s, r, 1, c, occupancy=o)
        self.assertIsNotNone(bundle)

    def test_comparison_and_logic_need_separate_contracts(self):
        fixture = self.fixture()
        fixture[2]["commands"]["0140"]["comparisons"] = {}
        report, bundle = self.run_scene(fixture)
        self.assertIsNone(bundle)
        self.assertTrue(any(i["reason"] == "missing-comparison-contract" for e in report["events"] for i in e["issues"]))

    def test_condition_type_rules_cover_multiple_terms_without_dropping_logic(self):
        fixture = self.fixture()
        source, receiver, contracts, occupancy = fixture
        p = source.parser
        done = p.Ins(0x0108)
        branch = p.Ins(0x0140, conds=[p.Cond(1, 10, 1), p.Cond(2, 15, 3)], logic=[20], target=done)
        fixture = self.fixture([branch, p.Ins(0x0148), done])
        c = fixture[2]["commands"]["0140"]
        c["operands"] = {"condition.*.lhs": spec(), "condition.*.rhs": spec()}
        c["comparisons"]["15"] = proved(target=15)
        c["logic"]["20"] = proved(target=20)
        report, bundle = self.run_scene(fixture)
        self.assertIsNotNone(bundle)
        body = script.ScriptFile.from_bytes(bundle).get(report["event_allocations"]["100"])
        self.assertEqual([x.op for x in body.code[0].conds], [10, 15])
        self.assertEqual(body.code[0].logic, [20])

    def test_missing_signedness_is_not_inferred_from_high_bit(self):
        fixture = self.fixture()
        del fixture[2]["commands"]["4418"]["operands"]["arg.1"]["source_type"]["signed"]
        self.assertIsNone(self.run_scene(fixture)[1])

    def test_d4_parser_never_mutates_receiving_grammar(self):
        before = copy.deepcopy(script.SIGS)
        self.run_scene(self.fixture())
        self.assertEqual(script.SIGS, before)


if __name__ == "__main__":
    unittest.main()
