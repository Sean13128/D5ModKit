"""Conservative D4 scene IR and contract-driven D5 emitter (offline only).

No opcode, actor, variable, resource or native behavior is assumed equivalent
because its number/name matches. Contracts are reviewed input, not discovered
proof. The emitter checks their coverage, types, bounds and dependency closure.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from fractions import Fraction
import hashlib
import re
import struct

from . import crypt, d4inventory, script

SCHEMA = "d4-typed-scene/1"
CONTRACT_SCHEMA = "d4-scene-contracts/1"
EVENT_MAX = (1 << 24) - 1
EVENT_TABLE_MAX = (1 << 32) - 1
NAMESPACES = {"event", "actor", "effect", "effect-slot", "sound", "voice", "motion", "sprite",
              "flag", "local", "system-variable", "particle", "camera", "enum", "variable-address"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def proof(record):
    return (record.get("status") == "verified"
            and all(isinstance(record.get(k), list) and record[k]
                    and all(isinstance(v, str) and v.strip() for v in record[k])
                    for k in ("source_evidence", "target_evidence")))


def variable_hint(vid):
    """Classification hints only; never a value/ID conversion rule."""
    if 10001 <= vid <= 10016:
        return "local-candidate"
    if vid == 10100:
        return "loop-local-candidate"
    if 10000 <= vid < 20000:
        return "flag-or-local-candidate"
    return "system-variable-or-unknown"


def role_hint(opcode, index):
    if opcode in (0x0100, 0x0104, 0x0106):
        return "event" if index == 0 else "callee-argument-contract-required"
    if opcode in (0x1400, 0x1410):
        return ("storage-selector-enum", "variable-address", "assignment-operation-enum", "assigned-value-contract-required")[index]
    if opcode in (0x3C00, 0x3CF4):
        return ("effect-slot", "effect")[index] if opcode == 0x3C00 else ("effect", "enum")[index]
    if opcode in (0x4610, 0x4612, 0x4618) and index == 0:
        return "sound-candidate"
    if opcode in (0x4630, 0x4632) and index == 0:
        return "voice-selector-contract-required"
    if opcode == 0x6510:
        return ("actor", "motion", "enum")[index]
    if opcode == 0x6410:
        return ("actor", "encoded-sprite-or-actor-source")[index]
    if opcode >> 8 in (0x64, 0x65, 0x66, 0x67, 0x68, 0x6C) and index == 0:
        return "actor-candidate"
    if opcode >> 8 in (0x72, 0x78):
        return "native-operation-contract-required"
    return "unclassified"


def layout(ins, parser):
    """(operand path, source value, literal slot width); includes special fields."""
    if ins.cid in (0x0104, 0x0106):
        return [(f"arg.{i}", v, 3 if i == 0 else 4) for i, v in enumerate(ins.args)]
    if ins.cid == 0x0140:
        return [(f"condition.{i}.{side}", getattr(c, side), 2)
                for i, c in enumerate(ins.conds) for side in ("lhs", "rhs")]
    if ins.cid in (0x1400, 0x1410):
        return [(f"arg.{i}", v, w) for i, (v, w) in enumerate(zip(ins.args, (1, 2, 1, 2)))]
    if ins.cid == 0x6E20:
        return [("arg.0", ins.args[0], None)]
    return [(f"arg.{i}", v, w) for i, (v, w) in enumerate(zip(ins.args, parser.SIGS[ins.cid]))]


def value_ir(value, width, hint):
    if isinstance(value, int):
        return dict(kind="literal", raw_unsigned=value, slot_bytes=width, suggested_role=hint,
                    signedness="unresolved", scale="unresolved")
    if isinstance(value, bytes):
        return dict(kind="bytes", hex=value.hex(), suggested_role="text-encoding-contract-required")
    return dict(kind="variable", variable_id=value.id, variable_kind=value.kind, slot_bytes=width,
                suggested_namespace=variable_hint(value.id), suggested_role=hint,
                runtime_value_domain="unresolved")


class Source:
    def __init__(self, raw, language="EN"):
        self.raw, self.language, self.sha256 = raw, language, sha(raw)
        if len(raw) < 4:
            raise ValueError("truncated D4 script directory")
        count = struct.unpack_from("<I", raw)[0]
        base = 4 + count * 8
        if base > len(raw):
            raise ValueError("truncated D4 script directory")
        offsets = struct.unpack_from(f"<{count}I", raw, 4)
        ids = struct.unpack_from(f"<{count}I", raw, 4 + count * 4)
        self.code = raw[base:]
        if count and (offsets[0] != 0 or list(offsets) != sorted(offsets) or offsets[-1] > len(self.code)):
            raise ValueError("invalid D4 script offsets")
        self.index = defaultdict(list)
        for i, (eid, lo, hi) in enumerate(zip(ids, offsets, (*offsets[1:], len(self.code)))):
            self.index[eid].append(dict(row_index=i, offset=base + lo, lo=lo, hi=hi))
        self.parser, self.cache = d4inventory.script_reader(), {}

    def event(self, eid):
        if eid in self.cache:
            return self.cache[eid]
        records = self.index.get(eid, [])
        if len(records) != 1:
            return dict(source_id=eid, error="missing-event" if not records else "ambiguous-source-event",
                        occurrences=records, event=None, ir=None)
        row = records[0]
        blob = self.code[row["lo"]:row["hi"]]
        result = dict(source_id=eid, sha256=sha(blob), source_offset=row["offset"],
                      source_bytes=len(blob), row_index=row["row_index"], event=None, ir=None)
        try:
            event = self.parser.parse_event(eid, self.code, row["lo"], row["hi"])
            if event.encode() != blob:
                raise ValueError("D4 byte roundtrip mismatch")
            index = {id(ins): i for i, ins in enumerate(event.code)}
            instructions, pos = [], 0
            for i, ins in enumerate(event.code):
                operands = [dict(path=path, **value_ir(value, width, role_hint(ins.cid, j)))
                            for j, (path, value, width) in enumerate(layout(ins, self.parser))]
                entry = dict(index=i, source_offset=pos, opcode=f"{ins.cid:04x}", operands=operands)
                if ins.cid == 0x0140:
                    entry.update(target_instruction=index[id(ins.target)] if ins.target is not None else len(event.code),
                                 comparisons=[c.op for c in ins.conds], logic=ins.logic)
                instructions.append(entry)
                pos += ins.size()
            result.update(event=event, ir=instructions)
        except (ValueError, IndexError, KeyError, struct.error, OverflowError) as ex:
            result["error"] = str(ex)
        self.cache[eid] = result
        return result

    def closure(self, root):
        todo, seen, dynamic = [root], set(), []
        while todo:
            eid = todo.pop()
            if eid in seen:
                continue
            seen.add(eid)
            record = self.event(eid)
            if record.get("error"):
                continue
            for i, ins in enumerate(record["event"].code):
                if ins.cid in (0x0100, 0x0104, 0x0106):
                    if isinstance(ins.args[0], int):
                        todo.append(ins.args[0])
                    else:
                        dynamic.append(dict(event=eid, instruction=i, variable_id=ins.args[0].id,
                                            variable_kind=ins.args[0].kind))
        return dict(root=root, events=sorted(seen), dynamic_calls=dynamic)


class Receiver:
    def __init__(self, raw):
        self.sha256 = sha(raw)
        plain = raw if script.ScriptFile._looks_plain(raw) else crypt.decode(raw)
        parsed = script.ScriptFile.from_bytes(plain, strict=True)
        if parsed.to_bytes() != plain:
            raise ValueError("receiver script does not roundtrip byte-identically")
        counts = Counter(e.id for e in parsed.events)
        if any(n != 1 for n in counts.values()):
            raise ValueError("ambiguous receiver event IDs")
        self.events = {e.id: e for e in parsed.events}


def allocate_events(source_ids, occupied, start=16500000, end=EVENT_MAX):
    """Deterministic fresh proposals; these are not kit/native leases."""
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= EVENT_MAX:
        raise ValueError("event allocation range must fit 24-bit call operands")
    ids = list(source_ids)
    if any(type(eid) is not int for eid in ids) or len(ids) != len(set(ids)):
        raise ValueError("duplicate or invalid source allocation keys")
    try:
        occupied_ids = list(occupied)
    except TypeError as ex:
        raise ValueError("occupied event IDs must be integers in the u32 table range") from ex
    if any(type(eid) is not int or not 0 <= eid <= EVENT_TABLE_MAX for eid in occupied_ids):
        raise ValueError("occupied event IDs must be integers in the u32 table range")
    used, mapping, cursor = set(occupied_ids), {}, start
    for eid in sorted(ids):
        while cursor in used and cursor <= end:
            cursor += 1
        if cursor > end:
            raise ValueError("fresh event range exhausted")
        mapping[eid] = cursor
        used.add(cursor)
        cursor += 1
    return mapping


class ContractError(ValueError):
    pass


def namespace_root(namespace):
    """Canonical qualified domains preserve their native resource/type root."""
    if not isinstance(namespace, str) or not re.fullmatch(r"[a-z][a-z0-9-]*(?::[a-z][a-z0-9-]*)*", namespace):
        raise ContractError("noncanonical-namespace")
    root = namespace.split(":", 1)[0]
    if root not in NAMESPACES | {"number"}:
        raise ContractError("unknown-namespace-root")
    return root


def _scale(t):
    n, d = t["scale"]
    if type(n) is not int or type(d) is not int or n <= 0 or d <= 0:
        raise ContractError("invalid-positive-rational-scale")
    return Fraction(n, d)


def _type(t, width):
    if t.get("bits") != width * 8 or type(t.get("signed")) is not bool:
        raise ContractError("missing-or-mismatched-signedness/width")
    return _scale(t)


def _signed(raw, t):
    if type(raw) is not int or not 0 <= raw < (1 << t["bits"]):
        raise ContractError("source-literal-outside-width")
    return raw - (1 << t["bits"]) if t["signed"] and raw >= 1 << (t["bits"] - 1) else raw


def _encoded(value, t):
    if value.denominator != 1:
        raise ContractError("scaling-requires-unspecified-rounding")
    v, bits = int(value), t["bits"]
    lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if t["signed"] else (0, (1 << bits) - 1)
    if not lo <= v <= hi:
        raise ContractError("target-literal-overflow")
    return v % (1 << bits)


class Translator:
    def __init__(self, source, receiver, contracts, allocations, occupancy):
        self.source, self.receiver, self.contracts = source, receiver, contracts
        self.allocations, self.occupancy = allocations, occupancy

    def mapped(self, namespace, value):
        root = namespace_root(namespace)
        if namespace == "event" and value in self.allocations:
            return self.allocations[value]
        m = self.contracts.get("namespaces", {}).get(namespace, {}).get(str(value), {})
        if not proof(m):
            raise ContractError(f"missing-namespace-map:{namespace}:{value}")
        target = m.get("target")
        if type(target) is not int:
            raise ContractError(f"invalid-namespace-target:{namespace}:{value}")
        if root in ("effect", "sound", "voice", "sprite", "motion") and m.get("dependency_status") != "ready":
            raise ContractError(f"unready-resource:{namespace}:{value}")
        return target

    def operand(self, value, spec, swidth, twidth, *, address_key=None):
        if not proof(spec):
            raise ContractError("missing-operand-type/semantic-contract")
        role = spec.get("role")
        if role not in NAMESPACES | {"number"}:
            raise ContractError("unknown-operand-namespace")
        namespace = spec.get("namespace", role)
        if namespace_root(namespace) != role:
            raise ContractError("namespace-root-role-mismatch")
        if role == "enum" and namespace == role:
            raise ContractError("explicit-enum-domain-required")
        if role == "event" and namespace != role:
            raise ContractError("event-reference-namespace-mismatch")
        if swidth is None or twidth is None:
            raise ContractError("text-byte-translation-not-supported")
        source_type, target_type = spec.get("source_type", {}), spec.get("target_type", {})
        ss, ts = _type(source_type, swidth), _type(target_type, twidth)
        # A native callback may agree only on part of its input domain. Keep
        # this before sentinels and variable remapping: neither can bypass a
        # literal-only semantic review (e.g. wait-one versus longer waits).
        if "source_literal_range" in spec:
            bounds = spec["source_literal_range"]
            bits = source_type["bits"]
            lo, hi = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if source_type["signed"] else (0, (1 << bits) - 1)
            if (type(bounds) is not list or len(bounds) != 2
                    or any(type(v) is not int for v in bounds)
                    or not lo <= bounds[0] <= bounds[1] <= hi):
                raise ContractError("invalid-source-literal-range")
            if type(value) is not int:
                raise ContractError("source-literal-range-requires-literal")
            if not bounds[0] <= _signed(value, source_type) <= bounds[1]:
                raise ContractError("source-literal-outside-reviewed-range")
        if not isinstance(value, int):
            if isinstance(value, bytes):
                raise ContractError("text-byte-translation-not-supported")
            key = f"{value.kind}:{value.id}"
            m = self.contracts.get("variables", {}).get(key, {})
            if not proof(m) or m.get("namespace") not in ("local", "flag", "system-variable"):
                raise ContractError(f"missing-variable-map:{key}")
            # A changed variable ID does not transform the values stored in it.
            if (m.get("role") != role or m.get("source_type") != source_type
                    or m.get("target_type") != target_type or m.get("value_domain_verified") is not True):
                raise ContractError(f"unproven-runtime-value-domain:{key}:{role}")
            vid, kind = m.get("target_id"), m.get("target_kind")
            if type(vid) is not int or not 0 <= vid <= 65535 or type(kind) is not int or not 1 <= kind <= 255:
                raise ContractError(f"invalid-variable-target:{key}")
            return script.Var(vid, kind)
        if role == "variable-address":
            m = self.contracts.get("variable_addresses", {}).get(address_key, {})
            if (not proof(m) or m.get("value_domain_verified") is not True
                    or m.get("namespace") not in ("local", "flag", "system-variable")):
                raise ContractError(f"missing-variable-destination-map:{address_key}")
            target = m.get("target_id")
            if type(target) is not int:
                raise ContractError("invalid-variable-destination")
            return _encoded(Fraction(target), target_type)
        sentinel = spec.get("sentinels", {}).get(str(value))
        if sentinel is not None:
            if not proof(sentinel):
                raise ContractError("unproven-sentinel")
            raw = sentinel.get("target_raw")
            if type(raw) is not int or not 0 <= raw < 1 << target_type["bits"]:
                raise ContractError("sentinel-target-overflow")
            return raw
        physical = Fraction(_signed(value, source_type)) * ss
        if role != "number":
            if physical.denominator != 1:
                raise ContractError(f"nonintegral-namespace-value:{role}")
            physical = Fraction(self.mapped(namespace, int(physical)))
        return _encoded(physical / ts, target_type)

    def compile_event(self, record):
        eid = record["source_id"]
        report = {k: v for k, v in record.items() if k not in ("event", "ir")}
        report.update(proposed_target=self.allocations.get(eid), status="blocked", issues=[], calls=[],
                      instruction_coverage=[])
        if record.get("error"):
            report["issues"].append(dict(reason="unknown-source-grammar-or-event", detail=record["error"]))
            return report, None
        original, converted = record["event"], []
        index = {id(ins): i for i, ins in enumerate(original.code)}
        for i, ins in enumerate(original.code):
            opkey = f"{ins.cid:04x}"
            contract = self.contracts.get("commands", {}).get(opkey, {})
            coverage = dict(instruction=i, source_opcode=opkey, status="blocked")
            report["instruction_coverage"].append(coverage)
            if not proof(contract) or contract.get("native_equivalence") != "verified":
                coverage["reason"] = "missing-command-native-contract"
                report["issues"].append(dict(instruction=i, opcode=opkey, reason="missing-command-native-contract"))
                converted.append(None)
                continue
            try:
                target_op = int(contract["target_opcode"], 16)
                target = script.Ins(target_op)
                source_layout = layout(ins, self.source.parser)
                if (ins.cid in script.SPECIAL) != (target_op in script.SPECIAL):
                    raise ContractError("incompatible-special-command-layout")
                if ins.cid in script.SPECIAL and ins.cid != target_op:
                    raise ContractError("special-opcode-change-not-supported")
                if target_op in (0x0104, 0x0106):
                    target.args = [0] * len(ins.args)
                elif target_op == 0x0140:
                    target.conds = [script.Cond(0, c.op, 0) for c in ins.conds]
                    target.logic = list(ins.logic)
                elif target_op in (0x1400, 0x1410):
                    target.args = [0] * 4
                elif target_op == 0x6E20:
                    raise ContractError("text-byte-translation-not-supported")
                elif target_op in script.SIGS:
                    target.args = [0] * len(script.SIGS[target_op])
                else:
                    raise ContractError("unknown-receiver-opcode")
                target_layout = layout(target, script)
                if len(source_layout) != len(target_layout):
                    raise ContractError("operand-reordering/rewrite-required")
                specifications = dict(contract.get("operands", {}))
                if ins.cid in (0x0104, 0x0106) and len(ins.args) > 1:
                    if not isinstance(ins.args[0], int):
                        raise ContractError("dynamic-callee-interface-unresolved")
                    interface = self.contracts.get("interfaces", {}).get(str(ins.args[0]), {})
                    if not proof(interface) or len(interface.get("arguments", [])) != len(ins.args) - 1:
                        raise ContractError(f"missing-callee-argument-interface:{ins.args[0]}")
                    for parameter in interface["arguments"]:
                        variable = self.contracts.get("variables", {}).get(parameter.get("callee_variable"), {})
                        if not proof(variable) or variable.get("role") != parameter.get("role") or variable.get("value_domain_verified") is not True:
                            raise ContractError("callee-parameter-value-domain-unresolved")
                    specifications.update({f"arg.{j + 1}": s for j, s in enumerate(interface["arguments"])})
                resolved_specs, used_specs = {}, set()
                for path, _, _ in source_layout:
                    key = path
                    if key not in specifications and path.startswith("condition."):
                        key = "condition.*." + path.rsplit(".", 1)[1]
                    if key not in specifications:
                        raise ContractError("incomplete-operand-contract-coverage")
                    resolved_specs[path] = specifications[key]
                    used_specs.add(key)
                if set(specifications) != used_specs:
                    raise ContractError("incomplete-operand-contract-coverage")
                for (path, value, sw), (tpath, _, tw) in zip(source_layout, target_layout):
                    if path != tpath:
                        raise ContractError("operand-layout-change-not-supported")
                    address = f"{ins.args[0]}:{value}" if ins.cid in (0x1400, 0x1410) and path == "arg.1" else None
                    mapped = self.operand(value, resolved_specs[path], sw, tw, address_key=address)
                    if path.startswith("arg."):
                        target.args[int(path[4:])] = mapped
                    else:
                        _, ci, side = path.split(".")
                        setattr(target.conds[int(ci)], side, mapped)
                if ins.cid in (0x1400, 0x1410):
                    address_map = self.contracts.get("variable_addresses", {}).get(f"{ins.args[0]}:{ins.args[1]}", {})
                    if (resolved_specs["arg.1"].get("role") != "variable-address" or not proof(address_map)
                            or address_map.get("target_raw") != target.args[0] or address_map.get("target_id") != target.args[1]):
                        raise ContractError("variable-destination-bank-contract-mismatch")
                if ins.cid == 0x0140:
                    comparisons, logic = contract.get("comparisons", {}), contract.get("logic", {})
                    for c in target.conds:
                        m = comparisons.get(str(c.op), {})
                        if not proof(m) or m.get("target") not in script.CMP_OPS:
                            raise ContractError("missing-comparison-contract")
                        c.op = m["target"]
                    target.logic = []
                    for op in ins.logic:
                        m = logic.get(str(op), {})
                        if not proof(m) or m.get("target") not in script.LOGIC_OPS:
                            raise ContractError("missing-condition-logic-contract")
                        target.logic.append(m["target"])
                if ins.cid in (0x0100, 0x0104, 0x0106):
                    if not isinstance(ins.args[0], int):
                        raise ContractError("dynamic-event-dispatch-not-supported")
                    if (resolved_specs["arg.0"].get("role") != "event" or target.cid not in (0x0100, 0x0104, 0x0106)
                            or target.args[0] != self.allocations.get(ins.args[0])):
                        raise ContractError("event-call-reference-not-remapped")
                    report["calls"].append(ins.args[0])
                converted.append(target)
                coverage.update(status="compiled-under-supplied-contract", target_opcode=f"{target.cid:04x}")
            except (ValueError, KeyError, TypeError, IndexError, OverflowError) as ex:
                coverage["reason"] = str(ex)
                report["issues"].append(dict(instruction=i, opcode=opkey, reason=str(ex)))
                converted.append(None)
        if report["issues"]:
            return report, None
        try:
            for i, ins in enumerate(original.code):
                if ins.cid == 0x0140:
                    converted[i].target = converted[index[id(ins.target)]] if ins.target is not None else None
            candidate = script.Event(self.allocations[eid], converted)
            raw = candidate.encode()
            parsed = script.parse_event(candidate.id, raw, 0, len(raw))
            if parsed.encode() != raw:
                raise ContractError("receiver-byte-roundtrip-mismatch")
            target_index = {id(ins): i for i, ins in enumerate(parsed.code)}
            branches, pos = [], 0
            for i, ins in enumerate(parsed.code):
                if original.code[i].cid == 0x0140:
                    oldtarget = index[id(original.code[i].target)] if original.code[i].target is not None else len(original.code)
                    newtarget = target_index[id(ins.target)] if ins.target is not None else len(parsed.code)
                    if oldtarget != newtarget:
                        raise ContractError("conditional-target-instruction-changed")
                    branches.append(dict(instruction=i, source_offset=record["ir"][i]["source_offset"],
                                         target_offset=pos, target_instruction=newtarget))
                pos += ins.size()
            report.update(status="locally-verified", emitted_bytes=len(raw), emitted_sha256=sha(raw),
                          branches=branches, receiver_byte_roundtrip=True)
            return report, parsed
        except (ValueError, KeyError, struct.error, OverflowError) as ex:
            report["issues"].append(dict(reason=str(ex)))
            return report, None


def translate_scene(source, receiver, skill_id, contracts=None, *, occupancy=None, event_start=16500000):
    contracts = contracts or {}
    occupancy = occupancy or {}
    modes = {name: source.closure(base + skill_id)
             for name, base in (("normal", 12000000), ("short", 12100000), ("mid-skip", 12200000))}
    ids = sorted({eid for mode in modes.values() for eid in mode["events"]})
    occupied_ids = occupancy.get("event_ids", [])
    if type(occupied_ids) is not list:
        raise ValueError("occupancy.event_ids must be a JSON array of u32 integers")
    proposed = allocate_events(ids, [*receiver.events, *occupied_ids], event_start)
    global_issues = []
    if contracts.get("schema") != CONTRACT_SCHEMA:
        global_issues.append("missing-reviewed-contract-set")
    if contracts.get("source_script_sha256") != source.sha256 or contracts.get("receiver_script_sha256") != receiver.sha256:
        global_issues.append("source-or-receiver-contract-fingerprint-missing/mismatched")
    if (occupancy.get("complete") is not True or not occupancy.get("evidence")
            or occupancy.get("receiver_script_sha256") != receiver.sha256):
        global_issues.append("receiving-original-and-all-mod-event-occupancy-not-proven")
    if any(mode["dynamic_calls"] for mode in modes.values()):
        global_issues.append("dynamic-call-closure-incomplete")
    translator = Translator(source, receiver, contracts, proposed, occupancy)
    reports, candidates = {}, {}
    for eid in ids:
        reports[eid], candidates[eid] = translator.compile_event(source.event(eid))
    ready = {eid for eid in ids if candidates[eid] is not None}
    while True:
        removed = {eid for eid in ready if any(dep not in ready for dep in reports[eid]["calls"])}
        if not removed:
            break
        ready -= removed
    for eid in ids:
        blocked_callees = sorted({dep for dep in reports[eid]["calls"] if dep not in ready})
        if blocked_callees:
            reports[eid]["issues"].append(dict(reason="blocked-callee-closure", source_event_ids=blocked_callees))
        if global_issues:
            reports[eid]["issues"].append(dict(reason="global-preconditions-unresolved", details=global_issues))
        reports[eid]["status"] = "ready-for-offline-emission" if eid in ready and not global_issues else "blocked"
    scene_ready = not global_issues and len(ready) == len(ids)
    bundle = None
    if scene_ready:
        sf = script.ScriptFile()
        sf.events = [candidates[eid] for eid in ids]
        bundle = sf.to_bytes()
        reparsed = script.ScriptFile.from_bytes(bundle, strict=True)
        if reparsed.to_bytes() != bundle:
            raise ValueError("final receiver bundle roundtrip mismatch")
        if set(e.id for e in reparsed.events) & set(receiver.events):
            raise ValueError("final bundle replaces a receiving event")
    opcodes, variables, destinations, untyped, domains = Counter(), {}, {}, [], defaultdict(set)
    ir = []
    for eid in ids:
        record = source.event(eid)
        entry = {k: v for k, v in record.items() if k not in ("event", "ir")}
        entry["instructions"] = record["ir"]
        ir.append(entry)
        for ins in record["ir"] or []:
            opcodes[ins["opcode"]] += 1
            if ins["opcode"] in ("1400", "1410"):
                raw, vid = (operand.get("raw_unsigned") for operand in ins["operands"][:2])
                destinations[f"{raw}:{vid}"] = dict(source_raw_field=raw, source_id=vid, status="requires-reviewed-destination/value-domain")
            for operand in ins["operands"]:
                if operand["kind"] == "variable":
                    key = f"{operand['variable_kind']}:{operand['variable_id']}"
                    variables[key] = dict(variable_kind=operand["variable_kind"], variable_id=operand["variable_id"],
                                          namespace_hint=operand["suggested_namespace"], status="requires-reviewed-value-domain")
                hint = operand.get("suggested_role", "unclassified")
                if operand["kind"] == "literal":
                    domains[hint].add(operand["raw_unsigned"])
                if hint in ("unclassified", "native-operation-contract-required", "encoded-sprite-or-actor-source", "voice-selector-contract-required"):
                    untyped.append(dict(event=eid, instruction=ins["index"], opcode=ins["opcode"], operand=operand["path"], hint=hint))
    report = dict(schema=SCHEMA, skill_id=skill_id, source_script_sha256=source.sha256,
                  receiver_script_sha256=receiver.sha256, status="ready-for-offline-emission" if scene_ready else "blocked",
                  global_issues=global_issues, modes=modes, event_allocations={str(k): v for k, v in proposed.items()},
                  allocation_scope="proposals against supplied original/mod snapshot; no leases or native-capacity assertion",
                  events=[reports[eid] for eid in ids], ir=ir,
                  required_contracts=dict(commands=[dict(opcode=op, occurrences=n, status="reviewed" if (proof(contracts.get("commands", {}).get(op, {})) and contracts["commands"][op].get("native_equivalence") == "verified") else "missing")
                                                    for op, n in sorted(opcodes.items())],
                                          variables=variables, candidate_literal_domains={k: sorted(v) for k, v in domains.items()},
                                          variable_destinations=destinations,
                                          untyped_operands=untyped,
                                          native_operations={op: n for op, n in opcodes.items() if int(op, 16) >> 8 in (0x72, 0x78)}),
                  mode_coverage={name: dict(events=len(mode["events"]),
                      instructions=sum(len(reports[eid]["instruction_coverage"]) for eid in mode["events"]),
                      compiled_instructions=sum(c["status"] == "compiled-under-supplied-contract"
                          for eid in mode["events"] for c in reports[eid]["instruction_coverage"]),
                      blocked_instructions=sum(c["status"] == "blocked"
                          for eid in mode["events"] for c in reports[eid]["instruction_coverage"]),
                      undecoded_events=[eid for eid in mode["events"] if source.event(eid).get("error")],
                      dynamic_calls=mode["dynamic_calls"])
                      for name, mode in modes.items()},
                  summary=dict(events=len(ids), instructions=sum(opcodes.values()), opcode_kinds=len(opcodes),
                               variables=len(variables), ready_events=sum(r["status"] == "ready-for-offline-emission" for r in reports.values()),
                               blocked_events=sum(r["status"] == "blocked" for r in reports.values()),
                               emitted_events=len(ids) if bundle is not None else 0),
                  acceptance=dict(source_structural="checked-for-decoded-events", receiver_structural="checked-for-emitted-events",
                                  gameplay="not-tested", presentation="not-tested", fidelity="partial"),
                  contract_authority="Caller-reviewed evidence pointers; this compiler checks coverage/structure, not the truth of supplied reviews")
    return report, bundle
