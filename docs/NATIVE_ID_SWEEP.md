# Native ID query sweep

`tools/native_id_sweep.py` is an optional offline research aid. It reads an x64 PE,
an exported function index and an explicit caller-supplied ID/query specification.
It writes only to a new output directory. It does not execute or change the PE,
open a game, read saves or use the Kit's installation/cache/settings machinery.
Existing research installations of Capstone and pefile are required; the tool
does not install dependencies.

Run `python tools/native_id_sweep.py CONFIG.json NEW_OUTPUT_DIRECTORY`.
The JSON config contains:

- `binary`: immutable input path and `sha256`: required exact fingerprint.
- `index`: exported index with `address`, `name`, `size`, `file` columns. Literal
  backslash-t and ordinary tab separators are accepted.
- `ids`: the explicit numeric ID catalog.
- `targets`: query contracts, each with `address`, argument `register`, `bits`
  and descriptive `role`. Addresses may be hexadecimal strings.
- `typed_offsets`: optional displacement-to-role map for candidate comparisons.

Targets must first be qualified independently. A target name or analyst label
alone does not establish its argument contract or behavior.

The sweep reuses the Kit's existing `exemap.Exe.functions()` range discovery:
original `.pdata` ranges plus padding-based leaf envelopes. Capstone stops a
range at its first decode failure; `decode-frontiers.jsonl` retains that boundary.
Overlapping range outputs are deduplicated by instruction address. The nearest
exported function entry supplies a navigation partition and source-file hash;
it is explicitly **not proof of a recovered function body**, particularly for
shared tails and discontiguous bodies.

Outputs separate four kinds of evidence:

1. `queries.jsonl`: direct call/tail-jump sites to the specified targets. A small
   local constant tracker resolves literal register assignments and register
   copies; every result retains its assignment and surrounding instructions.
   Unknown arguments are preserved explicitly.
2. `typed-comparisons.jsonl`: matching literals compared with values loaded from
   configured field offsets. These are **context candidates**, not proof that
   the base pointer has the intended object type or that an effect activates.
3. `immediates.jsonl`: every matching immediate in the decoded ranges. These
   include incidental numbers; membership in the ID catalog proves no meaning.
4. `decode-frontiers.jsonl`: incomplete ranges, including their range provenance.

The tracker deliberately forgets values at calls, jumps and local branch targets.
It invalidates written registers and retains known subregister bit widths. It
does not solve memory values, stack spills, arithmetic, indirect targets,
cross-function returns or control-flow merges. Missing resolutions are part of
the result, not grounds to guess a value.

`manifest.json` pins the PE, exported index, relevant source exports, config and
output files. For a reproducible research receipt, also pin this tool and the
Kit `exemap.py`, alongside the origin of the supplied ID catalog/contracts.

This is not an exhaustive behavior audit. Supplement it with inline consumers,
data-driven tables, dynamic-ID callers, omitted helpers, undecoded ranges and
actual control-flow/native tests. Similar numeric IDs, names, descriptions or
BSim function matches do not establish cross-engine semantic equivalence.

The synthetic propagation checks are
`python -m unittest tests.test_native_id_sweep`; they skip when optional Capstone
is unavailable. They contain no game bytes or private research fixtures.
