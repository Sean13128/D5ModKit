"""SOAKFREEZE2: the dialog-reading runtime additions compile, and the exe import table has what iat_slot() looks up.

Offline only: Zig builds the core DLL into a temp cache (nothing is installed); the exe is only read.
Run: python -m pytest tests/test_soakfreeze2_native.py -q
"""
import os

import pytest

from d5lib import runtime

NATIVE = os.path.join(os.path.dirname(runtime.__file__), "native")
EXE = "/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 5 Complete (Steam 803600)/disgaea5.exe"


def test_core_builds_with_dialog_tools(tmp_path):
    pytest.importorskip("ziglang")
    dll = runtime.build_core(log=lambda *_: None, native=NATIVE, cache=str(tmp_path))
    for s in (b"MSGBOX %s flags", b"ctl: MessageBox hooked", b"msgbox_dismiss", b"dlg", b"stk"):
        assert s in dll, s


def test_exe_imports_messagebox_by_name():
    pefile = pytest.importorskip("pefile")
    if not os.path.exists(EXE):
        pytest.skip("source exe not present")
    pe = pefile.PE(EXE)
    pe.parse_data_directories()
    names = {i.name for d in pe.DIRECTORY_ENTRY_IMPORT if d.dll.lower() == b"user32.dll" for i in d.imports if i.name}
    assert {b"MessageBoxW", b"MessageBoxA"} <= names
