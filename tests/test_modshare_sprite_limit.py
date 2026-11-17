"""A sprite group moved on import must stay below 10000 (number + 10000 is its portrait's file name)."""
import unittest

from d5lib import modshare


class SpriteNumberLimit(unittest.TestCase):
    def free(self, taken):
        return modshare._free("sprite", 450, set(taken), None, None)

    def test_first_free_group_from_9000(self):
        self.assertEqual(self.free([]), 9000)
        self.assertEqual(self.free([9000, 9010]), 9020)

    def test_last_group_is_9990(self):
        self.assertEqual(self.free(range(9000, 9990, 10)), 9990)

    def test_refuses_instead_of_going_into_the_portrait_numbers(self):
        with self.assertRaises(RuntimeError) as e:
            self.free(range(9000, 10000, 10))
        self.assertIn("no free sprite numbers", str(e.exception))


if __name__ == "__main__":
    unittest.main()
