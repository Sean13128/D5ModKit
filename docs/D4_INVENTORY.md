# D4 source inventory

`tools/d4_inventory.py` produces a repeatable metadata catalog from the owner's
Disgaea 4 Complete+ PC installation. It reuses `d4source`, `fafs`, `sound` and an
isolated instance of the existing script parser. It adds no dependency and does
not read saves, extract asset payloads, install content, lease IDs or modify D5.

```sh
python tools/d4_inventory.py --d4 "<D4 installation>" \
  --output "<private research directory>/inventory.json"
```

The output must be a new file outside both the source repository and source game.
Keep it private: names, text and dependency metadata are derived from game files.
The tool streams SHA-256 hashes of source files and archive member ranges; it
retains member offsets, sizes and original names without copying payloads. Files
under `SAVEDATA` are explicitly excluded. Metadata generation requires free space
for the JSON, not another game installation. It can take a few minutes.

## Record and dependency contract

Schema: `d4-content-inventory/1`. `items` includes every selected-language
character, skill, Evility, help, personality and event row, voice-table rows for
available voice languages, all source files, and every member of recognized
NSAC/FAFULLFS/DSARC/PSFS archives across installed localizations. Unrecognized files
are hashed as opaque source files; their internal content is not claimed to be
enumerated. Inner ANM tracks/attachments, effect texture entries and nested member
containers are future extraction work; their enclosing member is accounted for.

Each occurrence has a `uid`, `source` location/hash, `source_id` where applicable,
five separate `status` stages, `fidelity`, and an initially null D5 `target`.
Examples of stable keys within a pinned source snapshot:

- `d4:EN:character:<source ID>:row:<original row index>`
- `d4:EN:event:<source ID>:row:<original row index>`
- `d4:resource:<relative archive>::<member name>:entry:<directory index>`

All row and archive occurrences survive duplicate identifiers. `collisions`
reports ambiguous source IDs/names. No dictionary overwrite silently removes a
row. Character-family records group decimal ID bands and are explicitly
**candidates**. They do not identify native recruitability, class unlock rules or
unique identities. Original kind/gender codes and tier fields remain available.

`edges` contains source UID, target UID(s), relation, confidence, resolution and
available literal/slot evidence. `unresolved` repeats the dependency frontier for
missing, ambiguous and dynamically selected dependencies. One-to-many voice and
personality groups are explicit sets. Associations inferred from numbering are
labeled; body variants, portraits and effects are never accepted as equivalent
solely because filenames resemble each other.

`skill_frontiers` gives every skill occurrence a normal, shortened and mid-skip
wrapper plus literal event closure, resource candidates, undecoded events,
dynamic references and native-opcode counts. Every closure has
`closure_complete: false`: native behavior, dynamic selections and internal asset
dependencies remain outside this static graph. A missing root is distinguishable
from an empty decoded program. Do not reuse D4 helper IDs in D5 without receiving
ID allocation and semantic review.

## Interpretation and fidelity

The isolated script parser applies the twelve D4 command-width corrections
corroborated by the project's native trace. Other commands inherit the existing
D5 grammar provisionally. Events must parse with valid instruction/conditional
boundaries and re-encode byte-identically before static edges are collected.
Unknown programs retain location/hash, a decode error and a blocker. Parsing and
byte roundtrip demonstrate structural consistency, not a verified native command
contract or a translated program.

Weapon-skill codes retain their original slot and threshold. The subtraction
convention that links them to skill rows is inferred; threshold units are not
assumed. Evility parameter bytes remain source values, separate from compiled
eligibility, stacking, rounding and modifier order. Every record begins with
conversion/implementation `not-started` and gameplay/presentation `not-tested`.
Metadata-only items are `partial`; unknown event programs are `blocked`.

The existing research entry points are the project-root
`D4-TO-D5-PORTING-HANDOFF.md` and character bill of materials under `Research/`.
Those documents pin the installed builds, static native contracts and finite
examples behind this inventory. No private reference implementation is copied
into this tool; existing kit code remains under its existing license.

## Progress and receiving IDs

A separate evidence ledger can be supplied with `--progress <ledger.json>`:

```json
{
  "<item uid>": {
    "source_sha256": "<current item source hash>",
    "status": {"conversion": "passed", "implementation": "partial"},
    "fidelity": "partial",
    "evidence": ["<private validation report>"]
  }
}
```

The ledger is read-only input and must match source hashes. A faithful claim
requires passed conversion, implementation, gameplay **and** presentation stages.
Evidence text is a pointer to review, not automatic verification of its contents.
Regenerate to a new output to preserve prior evidence and compare inventories.

Optional `--allocations <plan.json>` validates explicit receiving IDs against
per-resource namespace ranges, duplicate proposals and supplied occupied-ID
snapshots. Its input has `allocations` and `occupied` keys. Each allocation is
`{uid, namespace, target_id, minimum, maximum}`; `occupied` maps namespaces to ID
lists. Body, portrait, event, skill, Evility and other native ID domains must remain
separate. This validates the supplied proposal only: it does not acquire leases,
discover occupied IDs, establish native capacity or prove that a declared range
is supported. Installation must use the kit's canonical lease/restore workflow.

Verification:

```sh
python -m unittest discover -s tests -p test_d4inventory.py -v
```

Synthetic cases cover occurrence retention, ambiguous/missing dependencies,
unknown grammar, dynamic calls, skip frontiers, D4/D5 parser isolation, sparse
weapon slots, source bounds/hashes, save exclusion, allocation collisions and
hash-bound progress. Native play and rendering remain separate acceptance gates.
