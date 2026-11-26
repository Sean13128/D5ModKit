"""Offline feasibility audit of a complete table replacement as a Kit db patch.

This is an audit, not an installer. Inputs must be separately supplied extracted
files; no game, profile or installation paths are written. A PASS proves only
that the Kit's serializer reproduces the target's canonical serialization on
that baseline. It does not establish ownership, compatibility or safety.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from d5lib import database, dbpatch


def audit(name, base_bytes, target_bytes):
    base = database.load_table(name, base_bytes)
    target = database.load_table(name, target_bytes)
    # Patches address existing rows by position. A key shift may edit another
    # mod's row even if the resulting isolated table happens to match.
    key = base.schema.key
    if len(target.rows) < len(base.rows):
        raise ValueError('row deletion/truncation is not composable')
    if key and all(key in row for row in base.rows + target.rows):
        if len({r[key] for r in base.rows}) != len(base.rows):
            raise ValueError("duplicate baseline keys: positional identity ambiguous")
        if len({r[key] for r in target.rows}) != len(target.rows):
            raise ValueError("duplicate target keys: positional identity ambiguous")
        for i, (a, b) in enumerate(zip(base.rows, target.rows)):
            if a[key] != b[key]:
                raise ValueError(f'row key/order changes at index {i}: {a[key]} -> {b[key]}')
    else:
        raise ValueError('no usable row key: positional identity unproven')
    patch = dbpatch.diff_table(base, target)
    applied = database.load_table(name, base_bytes)
    dbpatch.apply_patch(applied, patch, strict=True)
    # Comparing canonical serialized targets also detects lost header, section,
    # padding, string-pool and added-row placement differences.
    if applied.to_bytes() != target.to_bytes():
        raise ValueError('Kit patch does not reproduce canonical target bytes')
    return dict(table=name, baseline_sha256=hashlib.sha256(base_bytes).hexdigest(),
                target_sha256=hashlib.sha256(target_bytes).hexdigest(),
                changed_rows=len(patch.get('rows', {})), added_rows=len(patch.get('added', [])),
                result='representable-in-isolation', patch=patch)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('name')
    p.add_argument('vanilla', type=Path)
    p.add_argument('replacement', type=Path)
    a = p.parse_args()
    try:
        result = audit(a.name, a.vanilla.read_bytes(), a.replacement.read_bytes())
    except (ValueError, KeyError, IndexError, TypeError, OSError) as e:
        print(json.dumps(dict(table=a.name, result='refused', reason=str(e))))
        return 1
    # Only summary goes to stdout: emitted game data requires an explicit future
    # ownership/references policy, not an accidental installable artifact.
    result.pop('patch')
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    sys.exit(main())
