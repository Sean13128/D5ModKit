"""The stub cache must belong to the file it describes.

`d5lib.anm.is_stub` gave flaky results: it cached its answer in a module dict
keyed by `id(anm)`, and CPython reuses an object id after the object is collected, so a freed file's
"this animation is a stub" answer could be served for a different file, so two identical runs could draw
different pictures.

The first test reproduces the id reuse deterministically (id() is made to return one value for every
object, which is the limit case of "two objects share an identity"); the second checks the cache is
per file and really is used.
"""
import builtins
import contextlib
import unittest
from unittest import mock

from d5lib import anm


def _file(drawn: bool) -> "anm.AnmFile":
    """A one-block file whose only animation either draws a picture (drawn=True) or draws nothing."""
    block = anm.AnmBlock(1)
    block.animations = [anm.Animation(1, 0)]
    block.cells = [anm.Cell(0, 0, 0, 0, 0, 0, 0, 0, 0), anm.Cell(0, 0, 0, 0, 0, 0, 32, 40, 0)]
    block.nodes = [anm.Node(1, 0x100, 0, 0, 0, 0, 0, 1, -1, -1)]
    block.keys = [anm.Key(0, 0, 1 if drawn else 0, 0, 0, 0)]
    return anm.AnmFile([block], [], [])


class StubCacheTests(unittest.TestCase):
    def test_two_files_that_share_an_object_id_get_their_own_answer(self):
        stub, drawn = _file(False), _file(True)
        self.assertTrue(anm.is_stub(stub, 0, 0))
        real_id = builtins.id
        with mock.patch.object(builtins, "id", lambda _o: 0xDEAD, create=False):
            # under a module cache keyed by id(anm) this returned the stub's answer for a drawn animation
            self.assertTrue(anm.is_stub(stub, 0, 0))
            self.assertFalse(anm.is_stub(drawn, 0, 0))
        del real_id

    def test_the_cache_is_per_file_and_is_used(self):
        stub, drawn = _file(False), _file(True)
        self.assertTrue(anm.is_stub(stub, 0, 0))
        self.assertFalse(anm.is_stub(drawn, 0, 0))
        self.assertEqual(stub._stub_cache, {(0, 0): True})
        self.assertEqual(drawn._stub_cache, {(0, 0): False})
        # a second file must not see the first one's entry; mutating the block is answered from the cache
        stub.blocks[0].keys[0].cell = 1
        self.assertTrue(anm.is_stub(stub, 0, 0))

    def test_there_is_no_module_level_cache_keyed_by_identity(self):
        self.assertFalse(hasattr(anm, "_STUBS") and anm._STUBS)


if __name__ == "__main__":
    unittest.main()
