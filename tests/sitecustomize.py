"""Auto-applied preload for scripts that are not run through pytest.

Put this directory on PYTHONPATH and Python imports it at start-up, which
installs the Unicorn CTR_EL0 shim for offline proof scripts too::

    PYTHONPATH=<checkout>/tests /path/to/venv/bin/python evility/offline_proof.py

pytest runs do not need this: tests/conftest.py does the same thing.  See
Subprojects/Engine-Extensions/SIGILL-REPORT.md.
"""
try:
    import unicorn_darwin_shim
    unicorn_darwin_shim.install()
except Exception:       # never break start-up over a diagnostic shim
    pass
