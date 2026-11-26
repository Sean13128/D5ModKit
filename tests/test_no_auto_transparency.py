"""No module removes a picture's background on its own (playtest PT1027 S3, owner decision 2026-10-27).

Every source screen picture -- face, cut-in, status portrait -- goes through imgtools.screen_picture, which
keeps the picture exactly as it is unless D5MODKIT_D4_MATTE=1 is set.  A direct remove_white_background call
anywhere else in the kit is how the bad automatic transparency came back, so the rule is enforced here: the
function exists in imgtools and is called from imgtools.screen_picture only.
"""
import os
import re
import unittest

from PIL import Image

from d5lib import imgtools

KIT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ALLOWED = {'imgtools.py'}


def picture():
    img = Image.new('RGB', (32, 32), (255, 255, 255))
    for x in range(8, 24):
        for y in range(8, 24):
            img.putpixel((x, y), (20, 20, 20))
    return img


class NoAutoTransparency(unittest.TestCase):
    def test_screen_picture_keeps_the_picture_by_default(self):
        src = picture()
        out = imgtools.screen_picture(src)
        self.assertEqual(out.mode, 'RGBA')
        self.assertEqual(out.tobytes(), src.convert('RGBA').tobytes())
        self.assertEqual(out.getpixel((0, 0)), (255, 255, 255, 255))

    def test_false_and_none_mean_keep(self):
        src = picture()
        for matte in (None, False):
            out = imgtools.screen_picture(src, matte)
            self.assertEqual(out.getpixel((0, 0)), (255, 255, 255, 255), matte)

    def test_opt_in_removes(self):
        old = os.environ.get('D5MODKIT_D4_MATTE')
        try:
            os.environ['D5MODKIT_D4_MATTE'] = '1'
            out = imgtools.screen_picture(picture(), dict(threshold=246, spread=10, upper=0.25))
            self.assertEqual(out.getpixel((0, 0))[3], 0)
            self.assertEqual(out.getpixel((16, 16))[3], 255)
        finally:
            if old is None:
                os.environ.pop('D5MODKIT_D4_MATTE', None)
            else:
                os.environ['D5MODKIT_D4_MATTE'] = old

    def test_no_module_but_imgtools_calls_remove_white_background(self):
        pattern = re.compile(r'[^.\w]remove_white_background\s*\(')
        offenders = []
        lib = os.path.join(KIT, 'd5lib')
        for name in sorted(os.listdir(lib)):
            if not name.endswith('.py') or name in ALLOWED:
                continue
            with open(os.path.join(lib, name), encoding='utf-8') as f:
                for n, line in enumerate(f, 1):
                    if line.lstrip().startswith('#'):
                        continue
                    if pattern.search(line):
                        offenders.append('%s:%d %s' % (name, n, line.strip()))
        self.assertEqual(offenders, [], 'use imgtools.screen_picture instead of remove_white_background')


if __name__ == '__main__':
    unittest.main()
