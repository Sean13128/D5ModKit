"""patches/exe data validation and owner identity (d5lib.exebytes): needs no game exe, never skips."""
import json
import os
import sys

import pytest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from d5lib import exebytes, exemap  # noqa: E402
from d5lib.modsys import Mod  # noqa: E402

OK = {"va": "0x1401AF645", "orig": "0F84DE010000", "new": "660F1F440000", "what": "steal"}
VAL = {"offset": 2, "size": 4, "setting": "cost", "default": 100}


def mod(tmp_path, folder, patches, name=None, doc=None, settings=None):
    d = tmp_path / folder / "patches" / "exe"
    d.mkdir(parents=True)
    (tmp_path / folder / "mod.json").write_text(json.dumps({"name": name or folder, "settings": settings or {}}))
    (d / "p.json").write_text(json.dumps(doc if doc is not None else {"patches": patches}))
    return Mod(str(tmp_path / folder))


def bad_entries():
    def v(**kw):
        return dict(OK, values=[dict(VAL, **kw)])
    return [
        ("setting list", v(setting=[]), "setting"),
        ("setting empty", v(setting=""), "setting"),
        ("setting number", v(setting=5), "setting"),
        ("offset 1e309", v(offset=1e309), "offset"),
        ("offset float", v(offset=2.5), "offset"),
        ("offset whole float", v(offset=2.0), "offset"),
        ("offset bool", v(offset=True), "offset"),
        ("offset string", v(offset="2"), "offset"),
        ("size float", v(size=4.5), "size"),
        ("size bool", v(size=True), "size"),
        ("default float", v(default=1.5), "default"),
        ("default bool", v(default=True), "default"),
        ("default string", v(default="1"), "default"),
        ("va list", dict(OK, va=[1]), "va"),
        ("va float", dict(OK, va=1.5), "va"),
        ("va bool", dict(OK, va=True), "va"),
        ("va not hex", dict(OK, va="zz"), "va"),
        ("va negative", dict(OK, va=-5), "va"),
        ("orig underscore", dict(OK, orig="0F_84DE010000"), "orig"),
        ("new underscore", dict(OK, new="66_0F1F440000"), "new"),
        ("orig odd hex", dict(OK, orig="0F8"), "orig"),
        ("orig not hex", dict(OK, orig="XY"), "orig"),
        ("orig number", dict(OK, orig=5), "orig"),
        ("orig empty", dict(OK, orig="", new=""), "orig"),
        ("new not hex", dict(OK, new="66GG1F440000"), "new"),
        ("new list", dict(OK, new=["66"]), "new"),
        ("value not object", dict(OK, values=["x"]), "value #0"),
    ]


@pytest.mark.parametrize("label,entry,field", bad_entries(), ids=[b[0] for b in bad_entries()])
def test_bad_entry_is_a_valueerror_naming_file_entry_field(tmp_path, label, entry, field):
    with pytest.raises(ValueError) as cm:
        exebytes.load(mod(tmp_path, "A", [entry]))
    m = str(cm.value)
    assert "p.json #0" in m and field in m, m


@pytest.mark.parametrize("build", [5, [], ["ab"], "xyz", " ", True])
def test_bad_build_is_a_valueerror(tmp_path, build):
    with pytest.raises(ValueError) as cm:
        exebytes.load(mod(tmp_path, "A", None, doc={"build": build, "patches": [OK]}))
    assert "p.json" in str(cm.value) and "build" in str(cm.value)


@pytest.mark.parametrize("doc", [[], 5, "x", None, {"patches": 5}, {"patches": {"a": 1}}])
def test_bad_document_is_a_valueerror(tmp_path, doc):
    with pytest.raises(ValueError):
        exebytes.load(mod(tmp_path, "A", None, doc=doc))


def test_unreadable_json_is_a_valueerror(tmp_path):
    m = mod(tmp_path, "A", [OK])
    (tmp_path / "A" / "patches" / "exe" / "p.json").write_text("{not json")
    with pytest.raises(ValueError) as cm:
        exebytes.load(m)
    assert "p.json" in str(cm.value)


def test_unfit_setting_is_a_valueerror(tmp_path):
    p = dict(OK, new="660F00000000", values=[VAL])
    for bad in (2 ** 40, [], {"x": 1}, float("inf")):
        with pytest.raises(ValueError):
            exebytes.load(mod(tmp_path / str(id(bad)), "A", [p], settings={"cost": bad if bad != float("inf") else 1e309}))


def test_valid_entries_still_load(tmp_path):
    p = dict(OK, va=0x1401AF645, new="660F00000000", values=[VAL])
    (e,) = exebytes.load(mod(tmp_path, "A", [p], settings={"cost": 7}))
    assert e["va"] == 0x1401AF645 and e["new"] == bytes.fromhex("660F07000000")
    (e,) = exebytes.load(mod(tmp_path / "b", "A", [dict(OK, va="1401af645")]))
    assert e["va"] == 0x1401AF645


# ---------------------------------------------------------------------------------------- owner identity
class Ctx:
    def __init__(self, folders):
        self.mod_folders, self.skipped_features, self.logs, self.exe = folders, [], [], b""

    def get(self, f):
        return self.exe

    def put(self, f, data):
        self.exe = data

    def log(self, m):
        self.logs.append(m)


@pytest.fixture
def stub_apply(monkeypatch):
    """apply() without a game exe: claims like the real one (check + claim), writes nothing"""
    def fake(exe, entries, owner, base=None):
        with exemap.owner(owner):
            for e in entries:
                exemap.claim(e["va"], len(e["orig"]), e["what"])
        return exe + b"."
    monkeypatch.setattr(exebytes, "apply", fake)
    exemap.reset_ledger()
    yield
    exemap.reset_ledger()


def test_same_display_name_different_folders_clash(tmp_path, stub_apply):
    a = mod(tmp_path, "folder_a", [OK], name="Shared Name")
    b = mod(tmp_path, "folder_b", [OK], name="Shared Name")
    ctx = Ctx([a.folder, b.folder])
    exebytes._finalize(ctx)
    (who, why), = ctx.skipped_features
    assert who == "mod Shared Name (folder_b)" and "mod folder_a" in why and "exe patch clash" in why, why
    assert [e["owner"] for e in exemap.LEDGER] == ["mod folder_a"]


def test_failing_second_mod_with_same_name_keeps_first_claims(tmp_path, stub_apply):
    a = mod(tmp_path, "folder_a", [OK], name="Shared Name")
    b = mod(tmp_path, "folder_b", [dict(OK, orig="zz")], name="Shared Name")
    ctx = Ctx([a.folder, b.folder])
    exebytes._finalize(ctx)
    assert [n for n, _ in ctx.skipped_features] == ["mod Shared Name (folder_b)"]
    assert [(e["owner"], e["start"]) for e in exemap.LEDGER] == [("mod folder_a", 0x1401AF645)]


def test_handler_owner_uses_the_folder_id(tmp_path, monkeypatch):
    from d5lib import modsys
    seen = []
    monkeypatch.setattr(modsys, "PATCH_HANDLERS", {"h": (0, lambda ctx, m, p: seen.append(exemap._owner[0]))})
    monkeypatch.setattr(modsys, "load_handlers", lambda log=print: None)
    monkeypatch.setattr(modsys, "ordered_finalizers", lambda: [])
    d = tmp_path / "idfolder"
    (d / "patches" / "h").mkdir(parents=True)
    (d / "patches" / "h" / "x.json").write_text("{}")
    (d / "mod.json").write_text('{"name": "Display Name"}')

    class FS:
        def __init__(self): pass
    try:
        modsys.build(FS(), [Mod(str(d))], log=lambda *_: None)
    except Exception:
        pass            # the build outside a game folder may fail after the handler ran; only the owner matters
    assert seen == ["idfolder:h"]


def test_deeply_nested_json_is_a_valueerror(tmp_path):
    m = mod(tmp_path, "A", [OK])
    (tmp_path / "A" / "patches" / "exe" / "p.json").write_text("[" * 100000 + "]" * 100000)
    with pytest.raises(ValueError) as cm:
        exebytes.load(m)
    assert "p.json" in str(cm.value)


@pytest.mark.parametrize("bad", [True, 7.5, "7", [], None.__class__.__name__])
def test_setting_value_is_strict_int(tmp_path, bad):
    p = dict(OK, new="660F00000000", values=[VAL])
    with pytest.raises(ValueError) as cm:
        exebytes.load(mod(tmp_path, "A", [p], settings={"cost": bad}))
    assert "cost" in str(cm.value) and "p.json #0" in str(cm.value)


def test_skipped_tuple_carries_display_name_and_id(tmp_path, stub_apply):
    ctx = Ctx([mod(tmp_path, "Example_Mod", [dict(OK, orig="zz")], name="Example Mod").folder])
    exebytes._finalize(ctx)
    assert [n for n, _ in ctx.skipped_features] == ["mod Example Mod (Example_Mod)"]


# ---------------------------------------------------------------------------------------- notice before import
def _zip(tmp_path, files):
    import zipfile
    z = tmp_path / "pkg.zip"
    with zipfile.ZipFile(z, "w") as f:
        for name, text in files.items():
            f.writestr(name, text)
    return str(z)


def test_package_notice_counts_the_patches_before_import(tmp_path):
    two = {"patches": [OK, dict(OK, va="0x1401AF700", orig="0F84", new="6690")]}
    z = _zip(tmp_path, {"M/mod.json": "{}", "M/patches/exe/p.json": json.dumps(two)})
    assert exebytes.describe_package(z) == "patches the game's code at 2 sites (8 bytes)"
    assert "Restore vanilla" in exebytes.warning_text("M", exebytes.describe_package(z))


def test_package_without_exe_patches_has_no_notice(tmp_path):
    z = _zip(tmp_path, {"M/mod.json": "{}", "M/patches/db/p.json": "{}"})
    assert exebytes.describe_package(z) == ""


def test_package_with_unreadable_exe_patch_still_gets_a_notice(tmp_path):
    z = _zip(tmp_path, {"M/mod.json": "{}", "M/patches/exe/p.json": "not json"})
    assert "unreadable" in exebytes.describe_package(z)
