"""D4FACEWIRE1: the D4 importer and art preparation read the D4FACETOOL1 extractor output, with one name spelling.

Offline only: writes nothing outside pytest's tmp_path, reads no game file.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from d5lib import d4screenart, paths  # noqa: E402
from d5lib.importers import d4  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_art_env(monkeypatch):
    """No real machine state leaks in: no env, no saved setting, no legacy folder unless a test sets one."""
    monkeypatch.delenv(d4screenart.SCREEN_ART_ENV, raising=False)
    monkeypatch.setattr(paths, "kit_setting", lambda key, default=None: None)
    monkeypatch.setattr(d4screenart, "LEGACY_ART", Path("/nonexistent/forge-art"))


def _art_tree(root: Path, sid: int) -> None:
    face, cutin = d4screenart.art_paths(sid, root)
    face.parent.mkdir(parents=True, exist_ok=True)
    face.write_bytes(b"face")
    cutin.parent.mkdir(parents=True, exist_ok=True)
    cutin.write_bytes(b"cutin")


# ------------------------------------------------------------------ names (acceptance 2)

def test_face_and_cutin_names_share_swf04d_padding():
    # cast ids (< 1000) and class ids (4 digits) are spelled the same way: zero padded to four digits
    assert d4screenart.face_rel(70) == "character_id_00070/face/swf0070.png"
    assert d4screenart.face_rel(10) == "character_id_00010/face/swf0010.png"
    assert d4screenart.face_rel(1220) == "character_id_01220/face/swf1220.png"
    assert d4screenart.face_rel(2190) == "character_id_02190/face/swf2190.png"
    assert d4screenart.cutin_rel(70) == (
        "character_id_00070/cutin/ANM_HI__anm10070/native_frames/p000_t000_b00_r00001.png")
    assert d4screenart.cutin_rel(1220).startswith("character_id_01220/cutin/ANM_HI__anm11220/")


def test_importer_names_are_the_extractor_names():
    """The extractor writes through the same helpers, so a recorded `swf70.png` is never what the importer reads."""
    for sid in (10, 70, 500, 1010, 1220):
        face, cutin = d4screenart.art_paths(sid, Path("/art"))
        assert face == Path("/art") / d4screenart.face_rel(sid)
        assert cutin.name == "p000_t000_b00_r00001.png"
        assert cutin.parent.parent == Path("/art") / d4screenart.cutin_dir_rel(sid)
        assert face.name == f"swf{sid:04d}.png"


def test_prepare_art_tool_uses_the_kit_source_module():
    """tools/d4_prepare_art.py reads the verified source through _d4_source, the importer's own module."""
    import importlib.util
    from d5lib.importers import _d4_source
    spec = importlib.util.spec_from_file_location("d4_prepare_art", ROOT / "tools/d4_prepare_art.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._d4_source is _d4_source


# ------------------------------------------------------------------ resolution (acceptance 1)

def test_env_points_the_importer_at_an_extractor_output(tmp_path, monkeypatch):
    art = tmp_path / "extracted"
    _art_tree(art, 1220)
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(art))
    assert d4screenart.screen_art_dir() == art
    face, cutin = d4.screen_art(1220)
    assert face == art / "character_id_01220/face/swf1220.png"
    assert cutin.is_file()


def test_settings_key_is_used_when_the_env_is_absent(tmp_path, monkeypatch):
    art = tmp_path / "settings-art"
    art.mkdir()
    monkeypatch.setattr(paths, "kit_setting", lambda key, default=None: str(art) if key == "d4_screen_art" else default)
    assert d4screenart.screen_art_dir() == art


def test_default_is_the_sourceprep_source_folder(tmp_path, monkeypatch):
    source = tmp_path / "Source"
    (source / d4screenart.ART_FOLDER).mkdir(parents=True)
    monkeypatch.setattr(d4screenart, "source_root", lambda: source)
    assert d4screenart.screen_art_dir() == source / "d4-screen-art"


def test_legacy_forge_folder_is_never_a_default(tmp_path, monkeypatch):
    """SOURCEPREP4-D4: the source folder is the only default; the October archive must be named explicitly."""
    source = tmp_path / "Source"
    source.mkdir()
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    monkeypatch.setattr(d4screenart, "source_root", lambda: source)
    monkeypatch.setattr(d4screenart, "LEGACY_ART", legacy)
    monkeypatch.delenv(d4screenart.SCREEN_ART_ENV, raising=False)
    assert d4screenart.screen_art_dir() == source / "d4-screen-art"   # not the legacy archive
    (source / d4screenart.ART_FOLDER).mkdir()
    assert d4screenart.screen_art_dir() == source / "d4-screen-art"
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(legacy))       # explicit opt-in still reads it
    assert d4screenart.screen_art_dir() == legacy


def test_missing_art_says_how_to_extract(tmp_path, monkeypatch):
    source = tmp_path / "Source"
    source.mkdir()
    monkeypatch.setattr(d4screenart, "source_root", lambda: source)
    with pytest.raises(FileNotFoundError) as err:
        d4screenart.screen_art_dir(required=True)
    assert "d4_extract_screen_art.py" in str(err.value)
    with pytest.raises(FileNotFoundError) as err:
        d4.screen_art(1220)
    assert "d4_extract_screen_art.py" in str(err.value)


def test_explicit_env_that_does_not_exist_is_not_silently_replaced(tmp_path, monkeypatch):
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(tmp_path / "typo"))
    with pytest.raises(FileNotFoundError):
        d4screenart.screen_art_dir(required=True)


# ------------------------------------------------------------------ the class colour-variant run

def test_class_family_is_the_ten_consecutive_face_ids():
    assert d4screenart.family_ids(2090) == list(range(2090, 2100))
    assert d4screenart.family_ids(70) == list(range(70, 80))


def test_ensure_art_hands_the_full_requests_to_the_cache(tmp_path, monkeypatch):
    """The importer does not pre-prune: `ensure` owns both the missing set and the receipt check."""
    art = tmp_path / "extracted"
    _art_tree(art, 2090)
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(art))
    calls = {}

    def fake_ensure(*, game=None, folder=None, face_ids=(), cutin_ids=(), **_kw):
        calls.update(face_ids=list(face_ids), cutin_ids=list(cutin_ids), game=game, folder=folder)
        return list(face_ids)

    monkeypatch.setattr(d4screenart, "ensure", fake_ensure)
    note = d4.ensure_art(d4screenart.family_ids(2090), d4screenart.family_ids(2090), Path("/game"),
                         "colour-variant face and cut-in")
    assert calls["face_ids"] == list(range(2090, 2100))     # the full run, both kinds
    assert calls["cutin_ids"] == list(range(2090, 2100))
    assert calls["folder"] == art and calls["game"] == Path("/game")
    assert "2090" in note


def test_ensure_art_asks_only_for_the_kind_that_is_missing(tmp_path, monkeypatch):
    """A class whose cut-in is missing fills that cut-in alone; no face is rewritten (real cache, fake archive)."""
    import shutil
    game = _d4_archive(tmp_path, d4screenart.family_ids(2090))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    full = tmp_path / "full"
    d4screenart.extract(game, full, ids=d4screenart.family_ids(2090))
    art = tmp_path / "extracted"
    shutil.copytree(full, art)
    (art / d4screenart.cutin_rel(2090)).unlink()
    faces = {n: (art / d4screenart.face_rel(n)).read_bytes() for n in d4screenart.family_ids(2090)}
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(art))
    assert d4.ensure_art(d4screenart.family_ids(2090), [2090], game) is not None
    assert (art / d4screenart.cutin_rel(2090)).is_file()
    for n, data in faces.items():
        assert (art / d4screenart.face_rel(n)).read_bytes() == data   # every face untouched


def test_ensure_art_is_quiet_when_the_run_is_complete(tmp_path, monkeypatch):
    art = tmp_path / "extracted"
    for sid in d4screenart.family_ids(2090):
        _art_tree(art, sid)
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(art))
    calls = []
    monkeypatch.setattr(d4screenart, "ensure",
                        lambda **k: (calls.append(k), [])[1])   # called (receipt check), extracts nothing
    assert d4.ensure_art(d4screenart.family_ids(2090), [2090], Path("/game")) is None
    assert len(calls) == 1


def test_ensure_art_repairs_a_failed_publish_on_the_next_build(tmp_path, monkeypatch):
    """R3: a normal importer retry after a failed manifest publish records the PNGs instead of returning early."""
    import json
    game = _d4_archive(tmp_path, (10, 70))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    art = tmp_path / "extracted"
    d4screenart.extract(game, art, ids=[10])                  # a complete receipt for id 10
    before = (art / "manifest.json").read_text()
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(art))

    real_publish = d4screenart._publish_manifest
    monkeypatch.setattr(d4screenart, "_publish_manifest",
                        lambda folder, doc: (_ for _ in ()).throw(OSError("disk full")))
    note = d4.ensure_art([70], [70], game)
    assert "not extracted" in note and "OSError" in note       # the build is told the art is unrecorded
    assert (art / d4screenart.face_rel(70)).is_file()          # the PNGs were written ...
    assert (art / "manifest.json").read_text() == before       # ... but the live receipt kept its old content

    extracted = []
    real_extract = d4screenart.extract

    def counting_extract(*a, **k):
        extracted.append(k.get("ids"))
        return real_extract(*a, **k)

    monkeypatch.setattr(d4screenart, "_publish_manifest", real_publish)
    monkeypatch.setattr(d4screenart, "extract", counting_extract)
    assert d4.ensure_art([70], [70], game) is None             # nothing new to extract
    assert extracted == []                                    # no file was written a second time
    repaired = json.loads((art / "manifest.json").read_text())
    assert set(repaired["faces"]) == {"10", "70"}
    assert set(repaired["cutins"]) == {"10", "70"}
    assert repaired["missing"] == {"face": [], "cutin": []}


def test_ensure_art_never_writes_into_the_legacy_archive(tmp_path, monkeypatch):
    legacy = tmp_path / "forge"
    _art_tree(legacy, 2090)
    monkeypatch.setattr(d4screenart, "LEGACY_ART", legacy)
    monkeypatch.setattr(d4screenart, "source_root", lambda: tmp_path / "no-source")
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(legacy))
    monkeypatch.setattr(d4screenart, "ensure", lambda *a, **k: pytest.fail("no write into the archive"))
    assert d4.art_dir() == legacy
    assert d4.ensure_art(d4screenart.family_ids(2090), [2090], Path("/game")) is None


def test_ensure_art_resolves_a_symlinked_legacy_archive(tmp_path, monkeypatch):
    """An explicit path that is a symlink to the archive is the archive: never write through it."""
    legacy = tmp_path / "forge"
    _art_tree(legacy, 2090)
    alias = tmp_path / "alias"
    alias.symlink_to(legacy, target_is_directory=True)
    monkeypatch.setattr(d4screenart, "LEGACY_ART", legacy)
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(alias))
    monkeypatch.setattr(d4screenart, "ensure", lambda *a, **k: pytest.fail("no write through a symlink"))
    assert d4.art_dir() == alias
    assert d4.ensure_art(d4screenart.family_ids(2090), [2090], Path("/game")) is None


def _nsac(path, members):
    """A minimal D4 NSAC v2 archive `{name: payload}` (the reader in d4source validates this shape)."""
    import struct
    index = b"\0" * (10 * len(members))
    entries, data = b"", b""
    offset = 28 + len(index)
    for name, payload in members.items():
        raw = name.encode("ascii")
        entries += struct.pack("<HII", len(raw), offset, len(payload)) + raw + b"\0"
        offset += len(payload)
        data += payload
    total = 28 + len(index) + len(entries) + len(data)
    header = struct.pack("<4sHH5I", b"NSAC", 2, len(members), total, 28 + len(index), len(index),
                         len(entries), 0)
    path.write_bytes(header + index + entries + data)


def _fake_image():
    from PIL import Image
    return Image.new("RGBA", (2, 2), (0, 0, 0, 0))


def _d4_archive(tmp_path, ids):
    game = tmp_path / "game" / "DATA"
    game.mkdir(parents=True, exist_ok=True)
    _nsac(game / "WF.dat", {f"swf{n:04d}.nltx": b"face" for n in ids})
    _nsac(game / "ANM_HI.dat", {f"anm1{n:04d}.lzs": b"cutin" for n in ids})
    return game


def test_ensure_fills_missing_kinds_against_the_real_extractor(tmp_path, monkeypatch):
    """Real `extract` manifest writing: filling a missing face must not rewrite an existing cut-in."""
    import json
    game = _d4_archive(tmp_path, (10, 11, 12))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    full = tmp_path / "full"
    d4screenart.extract(game, full, ids=[10, 11, 12])          # the previous, complete extraction
    art = tmp_path / "art"
    import shutil
    shutil.copytree(full, art)
    (art / d4screenart.face_rel(12)).unlink()                  # face 12 missing ...
    (art / d4screenart.cutin_rel(11)).unlink()                 # ... cut-in 11 missing
    keep_face = art / d4screenart.face_rel(11)
    keep_cutin = art / d4screenart.cutin_rel(12)
    keep_face.write_bytes(b"existing-face-11")                 # must not be overwritten
    keep_cutin.write_bytes(b"existing-cutin-12")               # must not be overwritten

    assert d4screenart.ensure([10, 11, 12], game, art) == [11, 12]
    assert keep_face.read_bytes() == b"existing-face-11"
    assert keep_cutin.read_bytes() == b"existing-cutin-12"
    merged = json.loads((art / "manifest.json").read_text())
    assert set(merged["faces"]) == {"10", "11", "12"}
    assert set(merged["cutins"]) == {"10", "11", "12"}
    assert merged["missing"] == {"face": [], "cutin": []}


def test_ensure_parallel_jobs_keep_every_manifest_entry(tmp_path, monkeypatch):
    """import_game defaults to four worker threads; each fills a different id in the same art folder."""
    import json
    import time
    from concurrent.futures import ThreadPoolExecutor
    game = _d4_archive(tmp_path, (10, 11, 12, 13))
    art = tmp_path / "art"
    art.mkdir()

    def slow_face(raw):
        time.sleep(0.02)                                       # widen the read/merge race
        return _fake_image()

    monkeypatch.setattr(d4screenart, "decode_face", slow_face)
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: d4screenart.ensure([n], game, art), (10, 11, 12, 13)))
    merged = json.loads((art / "manifest.json").read_text())
    assert set(merged["faces"]) == {"10", "11", "12", "13"}
    assert set(merged["cutins"]) == {"10", "11", "12", "13"}
    for n in (10, 11, 12, 13):
        assert (art / d4screenart.face_rel(n)).is_file()
        assert (art / d4screenart.cutin_rel(n)).is_file()


def test_ensure_merges_the_extractor_manifest(tmp_path, monkeypatch):
    """`d4screenart.ensure` must not shrink a full manifest to the ids it just extracted."""
    art = tmp_path / "extracted"
    art.mkdir()
    full = {"tool": "d5lib.d4screenart", "source": {}, "palettes": [0],
            "faces": {"10": {"file": "character_id_00010/face/swf0010.png", "sha256": "a"}},
            "cutins": {"10": []}, "errors": {}, "missing": {"face": [], "cutin": []}}
    (art / "manifest.json").write_text(__import__("json").dumps(full))
    doc = {"tool": "d5lib.d4screenart", "palettes": [0], "faces": {"11": {"file": "x", "sha256": "b"}},
           "cutins": {}, "errors": {}, "missing": {"face": [11], "cutin": [11]}}
    calls, publishes = [], []

    def fake_extract(*a, **k):
        calls.append((k.get("kinds"), k.get("publish")))
        return doc

    real = d4screenart._publish_manifest
    monkeypatch.setattr(d4screenart, "extract", fake_extract)
    monkeypatch.setattr(d4screenart, "_publish_manifest", lambda f, d: (publishes.append(d), real(f, d))[1])
    _art_tree(art, 10)                       # id 10 present, id 11 absent -> only 11 is extracted
    assert d4screenart.ensure([10, 11], Path("/game"), art) == [11]
    assert calls == [(("face",), False), (("cutin",), False)]   # kinds independent, receipts private
    assert len(publishes) == 1               # ONE merged receipt per cache update
    assert set(publishes[0]["faces"]) == {"10", "11"}
    merged = __import__("json").loads((art / "manifest.json").read_text())
    assert set(merged["faces"]) == {"10", "11"}
    assert merged["missing"]["face"] == []   # face 11 is present now
    assert merged["missing"]["cutin"] == [11]


def test_ensure_publishes_one_merged_receipt_and_repairs_a_failed_publish(tmp_path, monkeypatch):
    """A failed final publish leaves the old receipt and the new PNGs; the retry records the PNGs."""
    import json
    game = _d4_archive(tmp_path, (10, 11))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    art = tmp_path / "art"
    d4screenart.extract(game, art, ids=[10])                  # a complete receipt for id 10
    before = (art / "manifest.json").read_text()

    seen = []
    real = d4screenart._publish_manifest

    def failing(folder, doc):
        seen.append(json.loads(json.dumps(doc)))
        raise OSError("disk full")

    monkeypatch.setattr(d4screenart, "_publish_manifest", failing)
    with pytest.raises(OSError):
        d4screenart.ensure(ids=[10, 11], game=game, folder=art)
    assert len(seen) == 1                                     # one merged publish attempt, never a per-kind subset
    assert set(seen[0]["faces"]) == {"10", "11"} and set(seen[0]["cutins"]) == {"10", "11"}
    assert (art / "manifest.json").read_text() == before      # the live receipt was never a subset
    assert (art / d4screenart.face_rel(11)).is_file()         # ... but the PNGs were written

    monkeypatch.setattr(d4screenart, "_publish_manifest", real)
    assert d4screenart.ensure(ids=[10, 11], game=game, folder=art) == []   # record, do not extract again
    repaired = json.loads((art / "manifest.json").read_text())
    assert set(repaired["faces"]) == {"10", "11"}
    assert set(repaired["cutins"]) == {"10", "11"}
    assert repaired["missing"] == {"face": [], "cutin": []}


def test_ensure_keeps_an_existing_cutin_sibling(tmp_path, monkeypatch):
    """A cut-in with its primary frame missing keeps the sibling frames already in the cache."""
    import json
    import shutil
    game = _d4_archive(tmp_path, (10,))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells",
                        lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image()),
                                                    (0, 0, 0, 2, _fake_image())])
    full = tmp_path / "full"
    d4screenart.extract(game, full, ids=[10])
    art = tmp_path / "art"
    shutil.copytree(full, art)
    primary = art / d4screenart.cutin_rel(10)
    sibling = art / d4screenart.cutin_rel(10, cell=2)
    assert primary.is_file() and sibling.is_file()
    primary.unlink()
    sibling_bytes = sibling.read_bytes()

    assert d4screenart.ensure(cutin_ids=[10], game=game, folder=art) == [10]
    assert sibling.read_bytes() == sibling_bytes              # sibling untouched
    assert primary.is_file()                                  # only the missing frame was written
    rows = json.loads((art / "manifest.json").read_text())["cutins"]["10"]
    assert {row["file"] for row in rows} == {d4screenart.cutin_rel(10), d4screenart.cutin_rel(10, cell=2)}


def test_ensure_merges_cutin_rows_per_file(tmp_path, monkeypatch):
    """A palette-0 repair keeps the manifest rows of frames written for other palettes."""
    import json
    art = tmp_path / "extracted"
    art.mkdir()
    other = d4screenart.cutin_rel(10, pal=1)
    face = d4screenart.face_rel(10)
    (art / face).parent.mkdir(parents=True)
    (art / face).write_bytes(b"face")
    (art / d4screenart.cutin_rel(10)).parent.mkdir(parents=True)
    (art / d4screenart.cutin_rel(10)).write_bytes(b"cutin")
    old = {"tool": "d5lib.d4screenart", "source": {}, "palettes": [0, 1],
           "faces": {"10": {"file": face, "sha256": "a"}},
           "cutins": {"10": [{"file": other, "size": [2, 2], "sha256": "keep"}]},
           "errors": {}, "missing": {"face": [], "cutin": []}}
    (art / "manifest.json").write_text(json.dumps(old))
    doc = {"tool": "d5lib.d4screenart", "palettes": [0],
           "faces": {}, "cutins": {"10": [{"file": d4screenart.cutin_rel(10), "size": [2, 2], "sha256": "new"}]},
           "errors": {}, "missing": {"face": [], "cutin": []}}

    def fake_extract(*a, **k):
        return doc

    monkeypatch.setattr(d4screenart, "extract", fake_extract)
    (art / d4screenart.cutin_rel(10)).unlink()               # palette-0 frame missing -> cutin is requested
    d4screenart.ensure(cutin_ids=[10], game=Path("/game"), folder=art)
    rows = json.loads((art / "manifest.json").read_text())["cutins"]["10"]
    assert {row["file"]: row["sha256"] for row in rows} == {other: "keep", d4screenart.cutin_rel(10): "new"}


# ------------------------------------------------------------------ the class builder's variant lookup

def test_colour_variants_reads_both_art_layouts(tmp_path):
    """Forge layout: all ten in one character folder.  Extractor layout: one folder per id.  Same result."""
    from d5lib.sourceimports import colour_variants
    forge, extract = tmp_path / "forge", tmp_path / "extract"
    for k in range(10):
        sid = 1220 + k
        (forge / "character_id_01220" / "face").mkdir(parents=True, exist_ok=True)
        (forge / "character_id_01220" / "face" / f"swf{sid}.png").write_bytes(b"f")
        _art_tree(extract, sid)
    assert len(colour_variants(forge / "character_id_01220/face/swf1220.png", 1220)) == 10
    got = colour_variants(extract / "character_id_01220/face/swf1220.png", 1220)
    assert len(got) == 10 and got[3] == str(extract / "character_id_01223/face/swf1223.png")


def test_colour_variants_cutins_follow_the_same_id(tmp_path):
    """A cut-in's folder id is the body id (70) while the id being advanced is anm10070 (+k)."""
    from d5lib.sourceimports import colour_variants
    for k in range(10):
        _art_tree(tmp_path, 70 + k)
    cut = tmp_path / d4screenart.cutin_rel(70)
    got = colour_variants(cut, 10070)
    assert got is not None and got[0] == str(cut) and got[-1] == str(tmp_path / d4screenart.cutin_rel(79))


# ------------------------------------------------------------------ recorded unique commands

def test_recorded_ids_are_read_from_names_with_padding():
    """The extractor names a resource id with the same zero padding for both widths; ids come from the
    file name, not from the recorded folder (180/220 record 54/74)."""
    assert d4screenart.resource_id("--face-path", "/old/forge/character_id_00070/face/swf70.png") == 70
    assert d4screenart.face_rel(70) == "character_id_00070/face/swf0070.png"
    assert d4screenart.resource_id(
        "--cutin-path", "/old/character_id_00050/cutin/ANM_HI__anm10054/native_frames/p000_t000_b00_r00001.png") == 54
    assert d4screenart.cutin_rel(54) == ("character_id_00054/cutin/ANM_HI__anm10054/native_frames/"
                                         "p000_t000_b00_r00001.png")
    assert d4screenart.resource_id("--face-path", "/pack/prepared-5301/face/custom.png") is None


def test_prepared_image_fallback_is_a_recorded_packet_frame():
    """610's recorded cut-in was its own packet's stand frame: the rule data keeps that frame name."""
    from d5lib.importers import _d4_source
    row = _d4_source.command(610)
    assert row.get("cutin_packet_frame") == "1/0000.png"
    assert "cutin_ids" not in row


def test_recorded_art_ids_are_rule_data():
    from d5lib.importers import _d4_source
    assert _d4_source.command(180)["face_ids"] == [54]      # ids come from the file names, not the row
    assert _d4_source.command(180)["cutin_ids"] == [54]
    assert _d4_source.command(70)["face_ids"] == [70]
    assert _d4_source.command(220)["cutin_ids"] == [74]


def test_npc_art_ids_use_the_source_colour_key(monkeypatch):
    """5301's cut-in is colour key 1154 (its face the key rounded to 1150); the on-demand extraction must ask for the key, not the row."""
    from d5lib.importers import d4 as d4imp

    class Files:
        def data(self, lang="EN"):
            class Data:
                chars = {5301: {"color_id": 1154}}
            return Data()

    imp = d4imp.Importer()
    monkeypatch.setattr(d4imp.Importer, "_npc_lease", staticmethod(
        lambda sid: {"npc": True} if int(sid) == 5301 else None))
    monkeypatch.setattr(imp, "source", lambda *a, **k: Files())
    # D4FACE1 (D4-FACE-02): the NPC row's face is the colour key rounded down to tens; its cut-in keeps the key.
    # The old path (--no-d4-face-rule) asks for the key for both.
    assert imp._art_ids(5301) == ([1150], [1154])
    assert imp._art_ids(5301, {"d4_face_rule": False}) == ([1154], [1154])


def test_non_npc_art_ids_follow_the_recording(monkeypatch):
    from d5lib.importers import d4 as d4imp
    imp = d4imp.Importer()
    monkeypatch.setattr(d4imp.Importer, "_npc_lease", staticmethod(lambda sid: None))
    assert imp._art_ids(310) == ([310], [310])
    assert imp._art_ids(180) == ([54], [54])


# ------------------------------------------------------------------ R4 rework regressions

def test_partial_png_write_never_reaches_the_cache(tmp_path, monkeypatch):
    """R4 item 1: a write that leaves a prefix must not leave (or certify) a truncated PNG."""
    import os
    game = _d4_archive(tmp_path, (10,))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    art = tmp_path / "art"
    real_fdopen = os.fdopen

    class ShortWrite:
        def __init__(self, fd):
            self._handle = real_fdopen(fd, "wb")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self._handle.close()

        def write(self, data):
            self._handle.write(data[: len(data) // 2])
            self._handle.flush()
            raise OSError("short write")

    def fake_fdopen(fd, mode="r", *args, **kwargs):
        return ShortWrite(fd) if mode == "wb" else real_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(d4screenart.os, "fdopen", fake_fdopen)
    doc = d4screenart.extract(game, art, ids=[10])
    assert not (art / d4screenart.face_rel(10)).is_file()          # no partial final file
    assert not (art / d4screenart.cutin_rel(10)).is_file()
    assert "swf0010.nltx" in doc["errors"]                          # the member failed, the run did not
    assert list(art.rglob("*.part")) == []                          # the temp files were removed
    assert "10" not in doc["faces"]                                 # and nothing was certified


def test_reconcile_repairs_a_changed_png_instead_of_certifying_it(tmp_path, monkeypatch):
    """R4 item 2: a file replaced after its row was recorded is re-hashed on the next call, not skipped."""
    import hashlib
    import json
    game = _d4_archive(tmp_path, (10,))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    art = tmp_path / "art"
    d4screenart.extract(game, art, ids=[10])
    face = art / d4screenart.face_rel(10)
    old_digest = json.loads((art / "manifest.json").read_text())["faces"]["10"]["sha256"]
    changed = b"regenerated-by-a-run-whose-publish-failed"
    face.write_bytes(changed)
    new_digest = hashlib.sha256(changed).hexdigest()
    assert old_digest != new_digest

    calls = []
    real_extract = d4screenart.extract
    monkeypatch.setattr(d4screenart, "extract",
                        lambda *a, **k: (calls.append(1), real_extract(*a, **k))[1])
    assert d4screenart.ensure(face_ids=[10], cutin_ids=[10], game=game, folder=art) == []
    assert calls == []                                              # nothing re-extracted
    doc = json.loads((art / "manifest.json").read_text())
    assert doc["faces"]["10"]["sha256"] == new_digest               # the row follows the file


def test_failed_first_publish_recovers_source_and_palettes_on_retry(tmp_path, monkeypatch):
    """R4 item 2: a failed first publish must not lose the source sizes or palettes with the receipt."""
    import json
    game = _d4_archive(tmp_path, (10,))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    art = tmp_path / "art"
    real_publish = d4screenart._publish_manifest
    monkeypatch.setattr(d4screenart, "_publish_manifest",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        d4screenart.ensure(ids=[10], game=game, folder=art)
    assert not (art / "manifest.json").exists()                     # the first publish never landed

    monkeypatch.setattr(d4screenart, "_publish_manifest", real_publish)
    extracted = []
    real_extract = d4screenart.extract
    monkeypatch.setattr(d4screenart, "extract",
                        lambda *a, **k: (extracted.append(1), real_extract(*a, **k))[1])
    assert d4screenart.ensure(ids=[10], game=game, folder=art) == []   # recorded, not extracted again
    assert extracted == []
    doc = json.loads((art / "manifest.json").read_text())
    assert doc["source"] == {"WF.dat": (game / "WF.dat").stat().st_size,
                             "ANM_HI.dat": (game / "ANM_HI.dat").stat().st_size}
    assert doc["palettes"] == [0]
    assert set(doc["faces"]) == {"10"} and set(doc["cutins"]) == {"10"}


def test_cli_run_merges_into_a_shared_cache_and_refreshes_on_request(tmp_path, monkeypatch):
    """R4 item 3: the documented extractor run keeps unrelated rows, records what is on disk, and only
    `refresh=True` replaces the requested PNGs."""
    import hashlib
    import json
    game = _d4_archive(tmp_path, (10, 11))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    art = tmp_path / "art"
    d4screenart.extract(game, art, ids=[10])                        # another builder's rows
    row10 = json.loads((art / "manifest.json").read_text())["faces"]["10"]
    full = tmp_path / "full"
    d4screenart.extract(game, full, ids=[11])
    expected = (full / d4screenart.face_rel(11)).read_bytes()

    face11 = art / d4screenart.face_rel(11)
    face11.parent.mkdir(parents=True)
    face11.write_bytes(b"stale-bytes")                              # a substituted PNG
    assert "11" not in json.loads((art / "manifest.json").read_text())["faces"]

    d4screenart.extract_locked(game, art, ids=[11])                 # keep + record, no silent refresh
    doc = json.loads((art / "manifest.json").read_text())
    assert face11.read_bytes() == b"stale-bytes"
    assert doc["faces"]["11"]["sha256"] == hashlib.sha256(b"stale-bytes").hexdigest()
    assert doc["faces"]["10"] == row10                              # unrelated row preserved
    assert set(doc["faces"]) == {"10", "11"}

    d4screenart.extract_locked(game, art, ids=[11], refresh=True)   # the deliberate replacement
    assert face11.read_bytes() == expected
    doc = json.loads((art / "manifest.json").read_text())
    assert doc["faces"]["11"]["sha256"] == hashlib.sha256(expected).hexdigest()
    assert doc["faces"]["10"] == row10                              # still preserved


def test_cli_and_importer_share_the_cache_lock(tmp_path, monkeypatch):
    """R4 item 3: the CLI run and a concurrent importer fill cannot drop each other's receipt rows."""
    import json
    from concurrent.futures import ThreadPoolExecutor
    game = _d4_archive(tmp_path, (10, 11))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    art = tmp_path / "art"
    art.mkdir()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda f: f(), (
            lambda: d4screenart.extract_locked(game, art, ids=[10]),
            lambda: d4screenart.ensure(ids=[11], game=game, folder=art))))
    doc = json.loads((art / "manifest.json").read_text())
    assert set(doc["faces"]) == {"10", "11"}
    assert set(doc["cutins"]) == {"10", "11"}
    assert doc["missing"] == {"face": [], "cutin": []}


def test_legacy_guard_covers_resolved_descendants(tmp_path, monkeypatch):
    """R4 item 4: an explicit descendant of the archive is the archive, through `..` too."""
    legacy = tmp_path / "forge"
    _art_tree(legacy, 70)
    monkeypatch.setattr(d4screenart, "LEGACY_ART", legacy)
    assert d4screenart.is_legacy(legacy)
    assert d4screenart.is_legacy(legacy / "character_id_00070")
    assert d4screenart.is_legacy(legacy / "not-yet" / "..")
    assert not d4screenart.is_legacy(tmp_path / "elsewhere")
    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(legacy / "face-only"))
    monkeypatch.setattr(d4screenart, "ensure", lambda *a, **k: pytest.fail("no write in a descendant"))
    assert d4.ensure_art([70], [70], Path("/game")) is None


def test_legacy_guard_refuses_a_per_id_symlink_into_the_archive(tmp_path, monkeypatch):
    """R4 item 4: a per-id directory symlink inside a new cache root is still the archive."""
    legacy = tmp_path / "forge"
    _art_tree(legacy, 10)
    (legacy / d4screenart.cutin_rel(10)).unlink()                   # a write is needed
    monkeypatch.setattr(d4screenart, "LEGACY_ART", legacy)
    art = tmp_path / "art"
    art.mkdir()
    (art / "character_id_00010").symlink_to(legacy / "character_id_00010", target_is_directory=True)
    game = _d4_archive(tmp_path, (10,))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    before = {p: p.read_bytes() for p in legacy.rglob("*.png")}
    with pytest.raises(ValueError):
        d4screenart.extract(game, art, ids=[10])
    assert {p: p.read_bytes() for p in legacy.rglob("*.png")} == before
    assert not (legacy / "manifest.json").exists()

    monkeypatch.setenv(d4screenart.SCREEN_ART_ENV, str(art))
    note = d4.ensure_art([10], [10], game)                          # the build is told, never written through
    assert note is not None and "ValueError" in note
    assert {p: p.read_bytes() for p in legacy.rglob("*.png")} == before


def test_colour_variants_keeps_zero_padding_for_low_ids(tmp_path):
    """R4 item 5: `swf0070.png` resolves (the helper documents it, the importer reads it)."""
    from d5lib.sourceimports import colour_variants
    for k in range(10):
        _art_tree(tmp_path, 70 + k)                                 # extractor layout: one folder per id
    path = tmp_path / d4screenart.face_rel(70)
    got = colour_variants(path, 70)
    assert got is not None and len(got) == 10
    assert got[0] == str(path)
    assert got[1] == str(tmp_path / d4screenart.face_rel(71))
    assert Path(got[-1]).name == "swf0079.png"                      # padding preserved, not swf79.png

    forge = tmp_path / "forge" / "character_id_00070" / "face"      # Forge layout: all ten in one folder
    forge.mkdir(parents=True)
    for k in range(10):
        (forge / f"swf{70 + k}.png").write_bytes(b"f")              # the Forge names are unpadded
    assert len(colour_variants(forge / "swf70.png", 70)) == 10


def test_receipt_lookups_use_posix_separators(tmp_path, monkeypatch):
    """R4 item 7: manifest rows are POSIX; a Windows-style `str()` compare flags every frame unrecorded."""
    import hashlib
    from pathlib import PureWindowsPath
    art = tmp_path / "art"
    _art_tree(art, 10)
    face, cutin = d4screenart.art_paths(10, art)
    doc = {"tool": "d5lib.d4screenart", "source": {}, "palettes": [0], "errors": {},
           "faces": {"10": {"file": d4screenart.face_rel(10),
                            "sha256": hashlib.sha256(face.read_bytes()).hexdigest()}},
           "cutins": {"10": [{"file": d4screenart.cutin_rel(10),
                              "sha256": hashlib.sha256(cutin.read_bytes()).hexdigest()}]},
           "missing": {"face": [], "cutin": []}}

    def windows_relative_to(self, other):
        return PureWindowsPath(*self.parts[len(Path(other).parts):])

    monkeypatch.setattr(Path, "relative_to", windows_relative_to)
    assert d4screenart._file_entry(face, art)["file"] == d4screenart.face_rel(10)
    assert d4screenart._unrecorded(art, doc, [10], [10]) is False
    repaired = d4screenart._reconcile(art, doc, [10], [10])
    assert repaired["faces"] == {} and repaired["cutins"] == {}


# ------------------------------------------------------------------ R5: receipt ownership and archive containment

def test_foreign_receipt_is_left_byte_identical(tmp_path, monkeypatch):
    """R5 item 1: a manifest.json written by another tool is user data, not an empty receipt.

    `_read_manifest()` mapped a foreign document to `{}`, so the merged publish replaced it.  Both the CLI
    path and the importer path must refuse before writing a PNG or the receipt."""
    import json
    game = _d4_archive(tmp_path, (70,))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])
    art = tmp_path / "art"
    art.mkdir()
    foreign = {"tool": "someone-elses-exporter", "note": "keep me", "rows": [1, 2, 3]}
    receipt = art / "manifest.json"
    receipt.write_text(json.dumps(foreign))
    before = receipt.read_bytes()

    with pytest.raises(d4screenart.ForeignReceipt):
        d4screenart.extract_locked(game, art, ids=[70])
    assert receipt.read_bytes() == before                            # untouched
    assert list(art.rglob("*.png")) == []                            # nothing extracted over it

    with pytest.raises(d4screenart.ForeignReceipt):
        d4screenart.ensure(ids=[70], game=game, folder=art)          # the importer's path too
    assert receipt.read_bytes() == before
    assert list(art.rglob("*.png")) == []


def test_cli_leaves_a_plain_text_manifest_untouched(tmp_path, monkeypatch):
    """R5 item 1: the documented CLI run must fail (exit 2), not overwrite a plain-text file."""
    game = _d4_archive(tmp_path, (70,))
    art = tmp_path / "art"
    art.mkdir()
    receipt = art / "manifest.json"
    receipt.write_text("hand-written notes, not JSON\n")
    before = receipt.read_bytes()
    spec = importlib.util.spec_from_file_location("d4_extract_screen_art",
                                                  ROOT / "tools/d4_extract_screen_art.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(sys, "argv", ["d4_extract_screen_art.py", str(game), str(art), "--id", "70"])
    assert mod.main() == 2
    assert receipt.read_bytes() == before
    assert list(art.rglob("*.png")) == []


def test_lock_symlink_into_the_archive_cannot_create_a_file(tmp_path, monkeypatch):
    """R5 item 2a: `open(..., "a+")` on the cache lock created a file through a dangling symlink."""
    legacy = tmp_path / "forge"
    legacy.mkdir()
    monkeypatch.setattr(d4screenart, "LEGACY_ART", legacy)
    art = tmp_path / "art"
    art.mkdir()
    (art / ".manifest.lock").symlink_to(legacy / "planted-lock")     # dangling target inside the archive
    game = _d4_archive(tmp_path, (10,))
    with pytest.raises(ValueError):
        d4screenart.ensure(ids=[10], game=game, folder=art)
    assert not (legacy / "planted-lock").exists()
    assert list(legacy.rglob("*")) == []                             # the archive stayed empty


def test_resolved_parent_guard_blocks_a_face_dir_symlink_into_the_archive(tmp_path, monkeypatch):
    """R5 item 2b: a face dir symlinked into the archive passed the leaf check when the PNG symlinked back out;
    the temp file was staged and the archive's symlink replaced.  The write parent is guarded now."""
    import os
    legacy = tmp_path / "forge"
    face_dir = legacy / "character_id_00010" / "face"
    face_dir.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    target = face_dir / "swf0010.png"
    target.symlink_to(outside)                                       # the leaf resolves back out of the archive
    monkeypatch.setattr(d4screenart, "LEGACY_ART", legacy)
    art = tmp_path / "art"
    (art / "character_id_00010").mkdir(parents=True)
    (art / "character_id_00010" / "face").symlink_to(face_dir, target_is_directory=True)
    game = _d4_archive(tmp_path, (10,))
    monkeypatch.setattr(d4screenart, "decode_face", lambda raw: _fake_image())
    monkeypatch.setattr(d4screenart, "cutin_cells", lambda raw, palettes=(0,): [(0, 0, 0, 1, _fake_image())])

    with pytest.raises(ValueError):
        d4screenart.extract_locked(game, art, ids=[10], refresh=True)
    assert target.is_symlink()                                       # the archive symlink is still a symlink
    assert os.readlink(target) == str(outside)
    assert outside.read_bytes() == b"outside"
    assert not list(legacy.rglob("*.part"))                          # no temp file was staged in the archive
