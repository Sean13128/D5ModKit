"""TEXTHASH-DRPG: the DRPG data files hold game text as hashes; tests resolve them against a stub pool.

Loaded by ``tests/conftest.py`` (``pytest_plugins``).  Every ``@text`` answers ``<text 16-hex-digits>`` (equal digests give
equal strings) so tests keep checking structure, ids and our own ``@authored`` wording without any game file.  A test that
wants the real pool calls ``_drpg_text.use(pool)`` itself and restores the stub (``drpg_text_stub.restore()``).
"""
from d5lib.importers import _drpg_text

STUB = _drpg_text.StubPool()


def restore():
    return _drpg_text.use(STUB)


class NamedStub(_drpg_text.StubPool):
    """The stub, except that the given game names resolve to themselves (for a test that reads a name in a sentence)."""

    def __init__(self, *names):
        self._known = {_drpg_text.sha(n): n for n in names}

    def get(self, digest):
        return self._known.get(digest) or super().get(digest)


def names(*known):
    """``with drpg_text_stub.names('Lich Deimos'):`` resolves those names for the block, then restores the stub."""
    import contextlib

    @contextlib.contextmanager
    def block():
        previous = _drpg_text.use(NamedStub(*known))
        try:
            yield
        finally:
            _drpg_text.use(previous)
    return block()


restore()
