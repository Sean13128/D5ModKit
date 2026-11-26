"""D4 face/cut-in pictures keep their white background unless background removal is explicitly opted in."""
import importlib
import os
import unittest

from PIL import Image

from d5lib import sourceimports


def picture():
    img = Image.new('RGB', (32, 32), (255, 255, 255))
    for x in range(8, 24):
        for y in range(8, 24):
            img.putpixel((x, y), (20, 20, 20))
    return img


class ScreenMatte(unittest.TestCase):
    def test_default_is_off(self):
        self.assertIsNone(sourceimports.D4_MATTE)
        self.assertIsNone(sourceimports.FACE_MATTE)

    def test_default_keeps_picture_exactly(self):
        src = picture()
        out = sourceimports.d4_screen_picture(src)
        self.assertEqual(out.mode, 'RGBA')
        self.assertEqual(out.tobytes(), src.convert('RGBA').tobytes())
        self.assertEqual(out.getpixel((0, 0)), (255, 255, 255, 255))

    def test_explicit_matte_needs_the_opt_in(self):
        # an explicit matte is still refused while the opt-in is unset: one picture, one switch
        kept = sourceimports.d4_screen_picture(picture(), sourceimports.D4_MATTE_OPTIONS)
        self.assertEqual(kept.getpixel((0, 0)), (255, 255, 255, 255))
        old = os.environ.get('D5MODKIT_D4_MATTE')
        try:
            os.environ['D5MODKIT_D4_MATTE'] = '1'
            out = sourceimports.d4_screen_picture(picture(), sourceimports.D4_MATTE_OPTIONS)
            self.assertEqual(out.getpixel((0, 0))[3], 0)
            self.assertEqual(out.getpixel((16, 16))[3], 255)
        finally:
            if old is None:
                os.environ.pop('D5MODKIT_D4_MATTE', None)
            else:
                os.environ['D5MODKIT_D4_MATTE'] = old

    def test_environment_opt_in(self):
        old = os.environ.get('D5MODKIT_D4_MATTE')
        try:
            os.environ['D5MODKIT_D4_MATTE'] = '1'
            module = importlib.reload(sourceimports)
            self.assertEqual(module.D4_MATTE, module.D4_MATTE_OPTIONS)
        finally:
            if old is None:
                os.environ.pop('D5MODKIT_D4_MATTE', None)
            else:
                os.environ['D5MODKIT_D4_MATTE'] = old
            importlib.reload(sourceimports)
        self.assertIsNone(sourceimports.D4_MATTE)


if __name__ == '__main__':
    unittest.main()
