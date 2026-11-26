# Typed D4 scene translation pilot

`d5lib/d4scripts.py` separates source decoding, semantic contracts and D5 byte
emission. `tools/translate_d4_scene.py` runs it without opening a game or installer.
The current tool is an offline compiler and dependency gate; it is not an accepted
D4 skill implementation.

```sh
python tools/translate_d4_scene.py --d4 '<D4 installation>' --skill 13082 \
  --receiver-script '<private original D5 script snapshot>' \
  --output '<new private result directory>'
```

The default dry-run writes a metadata manifest with all normal, shortened and
mid-skip event closures and a typed intermediate representation. Keep that output
outside the Git repository: it contains game-derived instructions and operands.
The source D4 grammar is the isolated reader from `d4inventory`; D5's parser and
its signatures are not mutated. Source/receiver events must roundtrip structurally
and source duplicate IDs are blockers. Missing or dynamic callees remain explicit.

## Emission gates

Add `--contracts <reviewed.json> --occupied <snapshot.json> --emit` to request a
translated bundle. The tool writes bytecode only when **every event in all three
closures** passes every gate. A blocked child blocks its callers; it never writes
a misleading wrapper that points at unfinished behavior. An unsuccessful emit
request exits 2 after saving the dependency manifest, with no bytecode output.
The final saved bundle is read back through D5's strict reader and re-encoded.
The bundle contains the new events only. A future pack builder must merge them
through the kit's canonical script patch backend.

Required evidence is explicit, and is input for human review. The compiler checks
coverage, types, values, fingerprints and graph closure; it cannot independently
prove the truth of a caller's supplied semantic review. Each reviewed record needs
`status: "verified"`, nonempty `source_evidence` and `target_evidence` lists.

The contract set has schema `d4-scene-contracts/1` and exact source/receiver script
SHA-256 fingerprints. Its `commands` map uses four-digit opcode keys. Every command
requires `target_opcode`, `native_equivalence: "verified"`, and an `operands` map
covering every source operand. A matching number/name never provides that review.
Unknown commands, native operations and unclassified operands block conversion.
Different opcode/layout rewrites beyond a same-arity ordinary command remain
unsupported; strings and dynamic event dispatch explicitly block.

An operand contract has a `role`, `source_type` and `target_type`, plus its review
evidence. Types specify `bits`, boolean `signed`, and positive rational
`scale: [numerator, denominator]`. Physical value is signed-decoded literal times
the source scale. Namespace mapping occurs next, then inverse target scaling.
Target fractions requiring a rounding decision and target overflow are errors.
No integer is silently masked/truncated by the underlying writer. Sentinels may
have separately reviewed explicit target raw encodings.

A review may cover only a bounded literal input domain. Add
`source_literal_range: [minimum, maximum]` to the operand contract to enforce
inclusive bounds on the signed-decoded source integer, before scaling or sentinel
mapping. Bounds must be actual integers inside the declared source type. A
restricted operand rejects every variable expression, even one with a reviewed
variable map: that map does not prove the value stays in the literal review's
domain. For example, `[2, 32767]` can describe a review that excludes wait-one;
it does not itself establish either scheduler or timing equivalence.

```json
{
  "role": "number",
  "source_type": {"bits": 8, "signed": true, "scale": [1, 100]},
  "target_type": {"bits": 16, "signed": true, "scale": [1, 100]},
  "status": "verified",
  "source_evidence": ["<source constructor and consumer evidence>"],
  "target_evidence": ["<receiver constructor and consumer evidence>"]
}
```

This example describes sign extension and equal scaling only. It is not a supplied
native contract for a real command.

Operand paths are `arg.N` for ordinary/call operands and
`condition.N.lhs`/`condition.N.rhs` for comparisons. The latter can use
`condition.*.lhs`/`condition.*.rhs` rules when all terms share a proven type.
Conditional comparison/logic enums have their own reviewed maps in the command's
`comparisons` and `logic` objects. The compiler rebuilds branch targets by
instruction identity and proves the same destination instruction after widening
and remapping. It rejects a relative branch that no longer fits its signed field.

## Namespaces, variables and call interfaces

Namespace roles include event, actor, effect, effect-slot, sound, voice, motion,
sprite, flag, local, system-variable, particle, camera and enum. Scalar `number`
is reserved for proven numerical values. A namespace mapping at
`namespaces.<role>.<source value>` has reviewed `target` and evidence. Resource
roles additionally require `dependency_status: "ready"`; numbering a missing
effect, recording or body does not prepare it for D5.
Enum contracts must name a contextual namespace such as
`namespace: "enum:assignment-operation"`; unrelated mode fields cannot share one
global numeric enum map. Other roles may likewise qualify their namespace when
native selector domains differ. Event-call operands must retain the event role
and map to the proposed imported callee, so a scalar annotation cannot bypass
fresh helper allocation.
Qualified namespaces retain their canonical role root: `effect:bank` still
requires a ready effect resource. Roots must match the operand role; namespace
components use lowercase letters, digits and hyphens, separated by single colons.
Empty components, whitespace and alternate case are rejected.

Every variable key is `<source kind>:<source ID>`. Its `variables` record requires
the local/flag/system namespace, target kind/ID, the consumer role and exact source
and target types, and `value_domain_verified: true`. Renaming a local that contains
D4 actor IDs does not turn its stored values into D5 actor IDs. Dynamic resources
need a reviewed producer/value-domain contract; they never become literal zero.
Variable-destination fields in set-variable commands use separate
`variable_addresses.<source raw field>:<source ID>` records, with reviewed target
ID/raw field and verified value-domain behavior.

Calls with arguments require a reviewed `interfaces.<source callee ID>` record.
Each argument specifies its value type/role and `callee_variable`, which must
resolve to the corresponding reviewed variable-domain record. This makes local
storage/argument scaling explicit. The compiler does not apply a global divide
by ten. It also does not infer semantics of local-calculation indices, encoded
actor-source modes or voice-category selectors.

## Event proposals and receiving state

Event IDs are deterministically proposed from `--event-start` (default 16500000),
skipping receiver and supplied occupied IDs. They must fit 24-bit call operands.
These are collision-checked proposals, not canonical kit leases, native capacity
proof or reserved game IDs. Every imported helper receives a fresh proposed ID;
its original D4 ID cannot overwrite D5 helpers.

The occupied snapshot contains `receiver_script_sha256`, an `event_ids` array,
`complete: true` and `evidence`. Completeness means original definitions and all
applicable enabled/disabled mod reservations were actually accounted for. Missing
completeness or fingerprint/evidence blocks output. Snapshot completeness is a
caller-reviewed assertion, not something this compiler discovers automatically.
`event_ids` must be a JSON array of actual integers, excluding booleans, within
the unsigned 32-bit event-table range. Strings, floating values and out-of-range
IDs are rejected before allocation. Occupied table IDs can exceed 24 bits;
newly proposed callable event IDs remain within 24 bits.
Installation must subsequently use the kit's canonical allocation/restore path.

## Acceptance boundary

The source manifest includes every encountered opcode, variable key, candidate
literal domain and unclassified operand, plus native-operation counts and per-
event issues. The private Legit Shield probe currently emits **no real gameplay
programs** because those semantic/resource/native contracts remain unfinished.
The synthetic harness emits and reads back a fully covered test program, including
signed widening and branch relocation. That verifies the compiler mechanism only.
Per-event `instruction_coverage` retains the precise blocked instruction and
reason, including operand-domain rejection. An instruction marked
`compiled-under-supplied-contract` has passed local contract/type checks; its event
can still fail dependency, global or final structural gates. `mode_coverage`
counts those instruction outcomes separately for normal, short and mid-skip,
including undecoded events and dynamic calls. Partial instruction coverage never
enables partial bytecode output or replaces complete scene acceptance.

```sh
python -m unittest discover -s tests -p test_d4scripts.py -v
```

A future successful bytecode build still needs receiving skill registration,
numerical effects/target legality, prepared resources, normal/short/skip cleanup,
and independent gameplay and presentation acceptance. Do not label an emitted
bundle faithful merely because parsing and byte roundtrip passed.

## D4 operand widths and local arithmetic (SPECBULK1, 2026-11-20)

- **Operand widths come from D4's own parsers.** Each registered D4 script command has a vtable whose fifth
  entry parses its operands. Emulating that parser (Unicorn) over a literal-only operand stream and watching
  which bytes it reads gives the widths; the method reproduces the twelve widths already in
  `d4inventory.D4_SIGNATURES` and adds 30 more where D4 differs from D5 or D5 lacks the command
  (`4630` voice is `[u16, u8]`, sound `4600..460c` channels are `u8`, `64a0` has a fourth byte, `6b0x`, `78xx`).
  The wrong `4630` width alone desynchronised 19 special-attack events; all now decode byte-exact.
  `tests/test_specbulk1_d4.py` re-derives every added row from the original `Disgaea4pc.exe`.
- **`1440` op 3 differs.** D4 (0x1401496c0) divides the two operands as floats (`divss`); D5 (0x140184cd0)
  truncates both and uses `idiv`. Ops 0/1/2/4 agree (C06). `choreo.Context(float_divide=True)` traces a D4
  scene with the D4 rule; a division by zero (D4: an infinite float) is kept as 0 by the simulator.
- **`1442`** scales its operands by 1/256 on both engines (constant 0.00390625 in both handlers), while
  `choreo` treats it like `1440` (tenths). Not changed here: the parser's scaling of variable operands for this
  command is unverified. One D4 special (source 10493) is blocked on it.
