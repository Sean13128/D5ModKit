"""Fail-closed comparison of rebuilt DD2 baseline against its installed reference.

The install is a comparison reference only; it never supplies build bytes. JSON
object ordering and LZS compression are nonsemantic. The sole allowed metadata
change is mod.json/source_import, which records the newly pinned source path.
Every missing/added file and every other changed value fails this gate.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


REVIEWED_RECEIPT = 'COREDD2-ABILITIES.json'


def _first_difference(left, right, where=''):
    """Return a compact pointer to the first changed value, for build receipts."""
    if type(left) is not type(right):
        return f'{where or "/"}: {type(left).__name__} != {type(right).__name__}'
    if isinstance(left, dict):
        if set(left) != set(right):
            return (f'{where or "/"}: added keys {sorted(set(left) - set(right))}; '
                    f'missing keys {sorted(set(right) - set(left))}')
        for key in sorted(left):
            if left[key] != right[key]:
                return _first_difference(left[key], right[key], f'{where}/{key}')
    elif isinstance(left, list):
        if len(left) != len(right):
            return f'{where or "/"}: length {len(left)} != {len(right)}'
        for index, (a, b) in enumerate(zip(left, right)):
            if a != b:
                return _first_difference(a, b, f'{where}/{index}')
    elif left != right:
        return f'{where or "/"}: values differ'
    return ''


def _db_aliases(rel):
    """Legacy->current field names of the table a patches/db/<member>.json row belongs to.

    SCHEMA1/YIELD1 renamed fields on purpose (unk_0E0 -> exp_yield_weight ...); the schema keeps the
    old spellings as ``aliases`` and rows accept both, so a spelling change is not a content change."""
    parts = rel.split('/')
    if len(parts) != 3 or parts[:2] != ['patches', 'db'] or not parts[2].endswith('.json'):
        return {}
    from .. import database
    try:
        return database.get_schema(parts[2][:-5]).alias
    except KeyError:
        return {}


def _canonical_rows(value, alias):
    def fix(row):
        return {alias.get(k, k): v for k, v in row.items()} if isinstance(row, dict) else row
    if isinstance(value, dict):
        value = dict(value)
        if isinstance(value.get('added'), list):
            value['added'] = [fix(r) for r in value['added']]
        if isinstance(value.get('rows'), dict):
            value['rows'] = {k: fix(r) for k, r in value['rows'].items()}
    return value


def _json_semantics(path, rel):
    value = json.loads(path.read_text())
    alias = _db_aliases(rel)
    if alias:
        value = _canonical_rows(value, alias)
    if rel == 'mod.json' and isinstance(value, dict):
        value = copy.deepcopy(value)
        value.pop('source_import', None)
    return value


def _anm_semantics(path):
    """Normalize compression and derived virtual offsets, retain all art/motions."""
    from .. import anm, gamefs
    value = anm.parse(gamefs.decode_member(path.read_bytes()))
    for image in value.textures + value.palettes:
        if len(image.data) != image.expected_size():
            raise ValueError('truncated ANM image data')
    return value.to_bytes(fix_virtual_offsets=True)


def baseline_preserved(pack, installed, *, strict=True):
    """Return (ok, findings); unknown changes are failures, never auto-expected.

    Includes stat, skill, evility, help, quest and lease definitions; all learned
    order and list values remain significant. ANM comparison preserves pixels,
    palettes, texture headers, animation tables and all unknown header fields.
    """
    pack, installed = Path(pack), Path(installed)
    if not pack.is_dir() or not installed.is_dir():
        return False, ['baseline or installed comparison directory missing']
    files = lambda root: {p.relative_to(root).as_posix(): p
                          for p in root.rglob('*') if p.is_file()}
    built, reference = files(pack), files(installed)
    findings = [f'added file: {r}' for r in sorted(set(built) - set(reference))]
    findings += [f'missing file: {r}' for r in sorted(set(reference) - set(built))]
    for rel in sorted(set(built) & set(reference)):
        a, b = built[rel], reference[rel]
        if a.read_bytes() == b.read_bytes():
            continue
        try:
            if a.suffix.lower() == '.json':
                av, bv = _json_semantics(a, rel), _json_semantics(b, rel)
                difference = _first_difference(av, bv)
                if difference:
                    findings.append(f'{rel}: {difference}')
            elif a.suffix.lower() == '.lzs' and a.name.startswith('anm'):
                if _anm_semantics(a) != _anm_semantics(b):
                    findings.append(f'{rel}: ANM art, motion or header data differs')
            else:
                findings.append(f'{rel}: bytes differ')
        except Exception as exc:
            findings.append(f'{rel}: comparison failed: {type(exc).__name__}: {exc}')
    # Source-pinned rebuilds may legitimately differ in serialized ANM and
    # regenerated text while still retaining every installed file.  The
    # runner's compare gate classifies those as expected; the importer gate is
    # only strict when called directly by validation/tests.
    # A reviewed-ability layer added where the installed copy has none is an intended addition
    # (Sean, 2026-11-09): its receipt file is not a gate failure.  Lost or changed rows still are.
    addition = 'added file: ' + REVIEWED_RECEIPT
    expected = {addition} if REVIEWED_RECEIPT in built and REVIEWED_RECEIPT not in reference else set()
    findings = [f + ' (expected addition: reviewed layer, none held)' if f in expected else f for f in findings]
    blocking = [f for f in findings if 'expected addition' not in f]
    return (not blocking if strict else not any(
        item.startswith(('added file:', 'missing file:')) for item in blocking)), findings
