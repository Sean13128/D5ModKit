"""Test-suite bootstrap.

The only job here is to defuse a Unicorn/Darwin crash that happens before any
test body runs: unicorn 2.1.4 reads CTR_EL0 when its
``sysctlbyname("hw.cachelinesize")`` probe fails, and Darwin raises SIGILL for
that instruction, killing the process inside ``Uc().mem_map()``.  See
tests/unicorn_darwin_shim.py and Subprojects/Engine-Extensions/SIGILL-REPORT.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

pytest_plugins = ('drpg_text_stub',)    # TEXTHASH-DRPG: DRPG data text is hashes; tests resolve them against a stub pool

import unicorn_darwin_shim  # noqa: E402

SHIM_ACTIVE = unicorn_darwin_shim.install()


def pytest_sessionstart(session):
    """Re-take SIGILL: pytest enables faulthandler, which installs its own."""
    global SHIM_ACTIVE
    SHIM_ACTIVE = unicorn_darwin_shim.install(force=True)


import pytest  # noqa: E402

_D4_DIAGNOSTIC = ("/Volumes/Data/Projects/D5/Disgaea Source/Disgaea 4 Complete+ (Steam 1233880)/"
                  "Disgaea 4 Complete+")
_STATE = {"real_resolver": False}


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """``test_d4sourceprep`` tests the prepared-folder resolver itself and never gets the diagnostic fallback."""
    _STATE["real_resolver"] = item.module.__name__.endswith("test_d4sourceprep")


def _install_d4_fallback():
    """The D4 importer reads the verified prepared source folder (SOURCEPREP4-D4).  Tests that predate it and only
    need *a* D4 table set get this machine's own D4 copy through the explicit diagnostic route when no prepared
    folder resolves (module-scoped fixtures included); without that copy they fail as the resolver says."""
    from pathlib import Path
    from d5lib import sourcefolder
    from d5lib.importers import _d4_source
    real = _d4_source._prepared

    def prepared():
        if not _STATE["real_resolver"] and Path(_D4_DIAGNOSTIC).is_dir():
            try:
                present = (sourcefolder.source_dir() / "manifest.json").is_file()
            except Exception:                                     # noqa: BLE001
                present = False
            if not present:
                return _d4_source._explicit(Path(_D4_DIAGNOSTIC))
        return real()
    _d4_source._prepared = prepared


_install_d4_fallback()
