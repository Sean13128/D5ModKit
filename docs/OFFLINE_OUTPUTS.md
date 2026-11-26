# Offline output paths

The D4 inventory, scene translator, effect converter and pilot/expansion builders
use `d5lib.offlinepaths` before reading source data or creating outputs and caches.
The guard rejects overlap in either direction with explicit repository, game,
state, mods and input-artifact paths. Existing ancestors are compared by filesystem
identity as well as resolved lexical ancestry: case aliases on case-insensitive
volumes and symlinks cannot bypass a protected root. Distinct names on a
case-sensitive filesystem remain distinct; the guard does not lowercase paths.

An adjacent `steamapps/common` pair is recognized without regard to case, including
when a tool has no destination-game argument. Supply explicit game/state/mod/input
paths as usual; the marker is additional protection, not discovery of every game
installation. Only known protected inputs can be checked.

Existing new-output, canonical-parent, no-symlink and exclusive-creation rules
still apply. Build wrappers validate both output and its sibling `.cache` before
copying or assigning a cache. Worker configurations validate output and cache
separately before importing finalizers. Redirected caches must avoid protected
inputs and the output directory itself. Inventory and scene provenance include
the helper's hash; older evidence keeps its original source fingerprints.

Mutually written destinations have a separate conservative portability rule:
`separate_outputs` rejects filesystem overlap **or NFC-normalized/casefolded
component ancestry** (normalizing again after folding).
Thus two future output/cache names differing only in case are refused even on a
case-sensitive volume. This is an explicit write/write policy, not a claim that
those paths have the same filesystem identity. Canonically equivalent composed
and decomposed Unicode destination names are refused by the same portable policy.
It also catches a dangling cache
symlink resolving to a differently cased future output. Protected-input checks
continue to distinguish separate case-sensitive input and output directories.
No probe files are created to determine filesystem case sensitivity.

Direct generic-pilot calls must configure `sprites.CACHE_DIR` to the resolved
per-output sibling cache before calling the API. Direct unique-pilot calls must
also configure `runtime.CACHE` there when finalization is enabled. The APIs
validate these actual globals against protected roots, the write/write separation
policy and the expected cache path before reading inputs. They refuse an unsafe
or mismatched cache with guidance to configure it or use the CLI; they never
silently redirect globals. The build CLIs already configure those paths.
The generic build wrapper also sets this process's Zig global/local cache
environment paths beneath that admitted sibling cache, matching the unique
wrapper. This does not edit user toolchain configuration or establish native
child-process confinement; no compiler run is part of these guard checks.

The guard is a read-only admission check, not a filesystem reservation or a
sandbox against another process replacing a directory after validation. Output
creation remains exclusive where previously required. No installed state or
accepted artifact is rebuilt or changed by this guard-only source update.

Run the focused checks from the repository with its existing Python environment:

```sh
PYTHONDONTWRITEBYTECODE=1 ../Local/python-macos/bin/python \
  -m unittest discover -s tests -p test_offlinepaths.py -v
```

The checks use synthetic files. They cover live-volume repository aliases without
writing into the repository, protected ancestors, new descendants, symlinks,
Steam marker spelling, early CLI/builder/worker refusal, cache redirects and normal
private admission. The distinct-case-directory check skips on a case-insensitive
test volume; it runs on case-sensitive systems. These checks establish offline
path admission only, not game compatibility or gameplay fidelity.
