"""Baseline gate must fail when the installed pack loses any gameplay content."""
import json

from d5lib.importers._dd2_validation import baseline_preserved


def trees(tmp_path):
    a, b = tmp_path / 'rebuilt', tmp_path / 'installed'
    a.mkdir()
    b.mkdir()
    return a, b


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def test_ignores_only_source_import_and_json_object_order(tmp_path):
    a, b = trees(tmp_path)
    write(a, 'mod.json', {'name': 'DD2', 'source_import': {'source': 'canonical'}})
    write(b, 'mod.json', {'source_import': {'source': 'old'}, 'name': 'DD2'})
    assert baseline_preserved(a, b) == (True, [])


def test_catches_lost_learned_skill_and_evility_order(tmp_path):
    a, b = trees(tmp_path)
    write(a, 'patches/db/char.dat.json', {'added': [{'id': 22210, 'learn1': 5, 'evility1': 2, 'evility2': 1}]})
    write(b, 'patches/db/char.dat.json', {'added': [{'id': 22210, 'learn1': 6, 'evility1': 1, 'evility2': 2}]})
    ok, notes = baseline_preserved(a, b)
    assert not ok and 'evility1' in notes[0]


def test_fails_unknown_metadata_change(tmp_path):
    a, b = trees(tmp_path)
    write(a, 'mod.json', {'name': 'DD2', 'class': 22211})
    write(b, 'mod.json', {'name': 'DD2', 'class': 22210})
    assert not baseline_preserved(a, b)[0]


def test_fails_added_and_missing_files(tmp_path):
    a, b = trees(tmp_path)
    (a / 'new').write_bytes(b'x')
    (b / 'old').write_bytes(b'x')
    assert baseline_preserved(a, b) == (False, ['added file: new', 'missing file: old'])


def test_rejects_changed_corrupt_anm_instead_of_skipping(tmp_path):
    a, b = trees(tmp_path)
    (a / 'anm00001.lzs').write_bytes(b'not an animation')
    (b / 'anm00001.lzs').write_bytes(b'another invalid animation')
    ok, notes = baseline_preserved(a, b)
    assert not ok and 'comparison failed' in notes[0]


def test_ignores_anm_compression_but_preserves_pixels(tmp_path):
    from d5lib import anm
    a, b = trees(tmp_path)
    image = anm.Image8(b'\x09\x01\x01\x01', 2, 2, 1, b'\x00\x01\x02\x03')
    sprite = anm.AnmFile([], [image], [])
    raw = sprite.to_bytes()
    (a / 'anm00001.lzs').write_bytes(anm.lzs_compress(raw))
    (b / 'anm00001.lzs').write_bytes(raw)
    assert baseline_preserved(a, b) == (True, [])
    sprite.textures[0].data = b'\x00\x01\x02\x04'
    (a / 'anm00001.lzs').write_bytes(anm.lzs_compress(sprite.to_bytes()))
    ok, notes = baseline_preserved(a, b)
    assert not ok and 'ANM art, motion or header data differs' in notes[0]


def test_renamed_schema_fields_are_not_a_content_change(tmp_path):
    """SCHEMA1 renamed char.dat unk_0CA -> torture_id; the held spelling must compare equal."""
    a, b = trees(tmp_path)
    write(a, 'patches/db/char.dat.json', {'added': [{'id': 22210, 'torture_id': 3, 'is_unique': 1}]})
    write(b, 'patches/db/char.dat.json', {'added': [{'id': 22210, 'unk_0CA': 3, 'unk_384': 1}]})
    assert baseline_preserved(a, b) == (True, [])
    write(b, 'patches/db/char.dat.json', {'added': [{'id': 22210, 'unk_0CA': 4, 'unk_384': 1}]})
    assert not baseline_preserved(a, b)[0]


def test_added_reviewed_layer_is_expected_but_a_lost_row_still_fails(tmp_path):
    a, b = trees(tmp_path)
    write(a, 'patches/db/char.dat.json', {'added': [{'id': 22210, 'learn1': 5}]})
    write(b, 'patches/db/char.dat.json', {'added': [{'id': 22210, 'learn1': 5}]})
    write(a, 'COREDD2-ABILITIES.json', {'added_evility_ids': [25210]})
    ok, notes = baseline_preserved(a, b, strict=False)
    assert ok and 'expected addition' in notes[0]
    write(b, 'patches/db/Skill.dat.json', {'added': [{'id': 1}]})        # a baseline row the rebuild lost
    assert not baseline_preserved(a, b, strict=False)[0]
    (b / 'patches/db/Skill.dat.json').unlink()
    write(a, 'patches/db/char.dat.json', {'added': [{'id': 22210, 'learn1': 6}]})   # a changed row
    assert not baseline_preserved(a, b)[0]
